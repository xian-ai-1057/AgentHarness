"""資料版本：更新時自動升級資料庫、先拍快照，出問題時一行還原。

網頁版的資料都在專案資料夾裡（docker 部署時是 volume），換映像檔不會
清掉。這個模組讓「更新」只要換上新版、重新啟動：

    1. 每次啟動網頁版時呼叫 prepare。
    2. 偵測到程式換了版本（或資料庫有新的升級步驟要做）時，先把資料庫
       與設定檔快照到 .harness/backups/<時間>/，只留最近幾份。
    3. 依序執行還沒做過的資料庫升級步驟（MIGRATIONS），做完的版本記在
       資料庫的 PRAGMA user_version。
    4. 資料庫是比這版程式更新的版本建立的（例如換回舊的映像檔）時拒絕
       啟動，提示用 `pyharness data restore` 還原升級前的快照，不會讓
       舊程式寫壞新格式的資料。

快照的內容（都很小，不含對話與上傳的檔案）：

    資料庫   .harness/harness.db（帳號、群組、自建 agent、知識庫設定、
             稽核紀錄…）與 .harness/ontology.db，用 SQLite 的 backup
             API 複製，服務執行中也是一致的內容
    設定檔   harness.yaml、AGENTS.md、agents/、skills/、tools/、
             ontology/、.harness/ 底下的 JSON 設定、金鑰（secrets/）、
             每個人的記憶與權限、個人 skill

對話紀錄（JSONL，只會往後附加）、上傳與產生的檔案、知識庫文件不會被
升級改寫，所以不放進快照；向量索引可以重建，也不放。搬機器或整個
volume 損壞要靠 volume 備份（見文件「快速部署」的「備份與還原」）。

升級步驟的寫法（新增欄位、資料表時）：在 MIGRATIONS 最後加一項，
版本號加一，不要改已經發布的項目；同時更新模組自己的 CREATE TABLE，
讓新建的資料庫一開始就是最新的樣子（新建時不執行升級步驟）。步驟要能
重複執行（加欄位用 add_column）。盡量只做「新增」（加欄位、加資料
表），舊版程式讀得懂，換回舊版時才不必還原。之後改用 PostgreSQL
時，同一份版本號與步驟清單照樣適用，只換執行的地方。
"""

import dataclasses
import datetime
import hashlib
import importlib.metadata
import json
import os
import pathlib
import re
import shutil
import sqlite3
import time
from collections.abc import Callable

from harness import project as project_lib
from harness.ontology import service as ontology_service
from harness.web import accounts as accounts_lib
from harness.web import audit as audit_lib
from harness.web import groups as groups_lib
from harness.web import knowledge_admin
from harness.web import knowledge_eval
from harness.web import personal_knowledge
from harness.web import user_agents as user_agents_lib

BACKUP_DIR = project_lib.DATA_DIR / "backups"
STATE_FILE = project_lib.DATA_DIR / "data-version.json"
# 自動快照保留的份數（手動拍的快照不算在內，也不會被自動刪掉）。
KEEP_AUTOMATIC = 3
# 快照裡的資料庫（相對於專案根目錄）。
DATABASES = (accounts_lib.DB_FILE, ontology_service.DB_FILE)
# 快照裡的設定檔：檔案或資料夾（相對於專案根目錄，可以用 * 萬用字元）。
CONFIG_PATHS = (
    project_lib.CONFIG_FILE,
    "AGENTS.md",
    "agents",
    "skills",
    "tools",
    "ontology",
    f"{project_lib.DATA_DIR.as_posix()}/*.json",
    f"{project_lib.DATA_DIR.as_posix()}/secrets",
    f"{project_lib.DATA_DIR.as_posix()}/personal-skills",
    f"{accounts_lib.USERS_DIR.as_posix()}/*.json",
    f"{accounts_lib.USERS_DIR.as_posix()}/*/*.json",
)
# 設定檔超過這個大小就不放進快照（避免誤放大檔案把磁碟塞滿）。
MAX_CONFIG_FILE_BYTES = 10 * 1024 * 1024
_MANIFEST = "manifest.json"
_DB_DIR = "db"
_FILES_DIR = "files"
_NAME = re.compile(r"^[0-9]{8}-[0-9]{6}(-[a-z0-9-]+)?$")


class DataError(RuntimeError):
    """資料版本或快照的問題，訊息會直接顯示給管理者。"""


@dataclasses.dataclass(frozen=True)
class Migration:
    """一個資料庫升級步驟。

    Attributes:
        version: 做完這一步之後的版本號，從 1 開始依序加一。
        summary: 給管理者看的說明。
        apply: 在同一個交易裡執行的升級，參數是 harness.db 的連線。
    """

    version: int
    summary: str
    apply: Callable[[sqlite3.Connection], None]


def _baseline(db: sqlite3.Connection) -> None:
    """第 1 版：之前沒有版本號的資料庫，資料表照原樣保留。

    資料表本身由各模組建立（CREATE TABLE IF NOT EXISTS，見 open_stores），
    這一步只是開始記錄版本號。
    """
    del db


MIGRATIONS: tuple[Migration, ...] = (
    Migration(1, "開始記錄資料庫版本（資料表照原樣保留）", _baseline),
)
SCHEMA_VERSION = MIGRATIONS[-1].version


@dataclasses.dataclass(frozen=True)
class Snapshot:
    """一份快照。

    Attributes:
        name: 資料夾名稱（時間加上原因），還原時用它指定。
        path: 快照資料夾。
        created_at: 建立時間（秒）。
        reason: 為什麼拍這份快照。
        app_version: 拍快照時的程式版本。
        schema_version: 拍快照時的資料庫版本。
        automatic: 是不是啟動時自動拍的（只有自動快照會被輪替刪除）。
        size: 快照占用的位元組數。
    """

    name: str
    path: pathlib.Path
    created_at: float
    reason: str
    app_version: str
    schema_version: int
    automatic: bool
    size: int


@dataclasses.dataclass(frozen=True)
class Report:
    """prepare 做了什麼，給啟動訊息使用。

    Attributes:
        snapshot: 這次拍的快照；沒有拍時為 None。
        applied: 這次執行的升級步驟。
        previous_app: 上次啟動時的程式版本（第一次記錄時為空字串）。
        app_version: 目前的程式版本。
    """

    snapshot: Snapshot | None
    applied: tuple[Migration, ...]
    previous_app: str
    app_version: str

    def messages(self) -> list[str]:
        """啟動時印出的說明；什麼都沒做時是空的。"""
        lines = []
        if self.snapshot is not None:
            lines.append(
                f"已自動備份資料庫與設定：{self.snapshot.path}"
                f"（{self.snapshot.reason}）"
            )
        lines.extend(
            f"資料庫升級到第 {step.version} 版：{step.summary}"
            for step in self.applied
        )
        return lines


def app_version() -> str:
    """目前程式的版本：套件版本號加上程式碼的指紋。

    版本號不一定每次更新都會改，所以再加上所有 .py 檔內容的雜湊，任何
    程式的改動都算是換了版本。
    """
    try:
        version = importlib.metadata.version("agent-harness")
    except importlib.metadata.PackageNotFoundError:
        version = "0"
    package = pathlib.Path(__file__).resolve().parent.parent
    digest = hashlib.sha256()
    for path in sorted(package.rglob("*.py")):
        digest.update(path.relative_to(package).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return f"{version}+{digest.hexdigest()[:12]}"


def schema_version(root: str | pathlib.Path) -> int:
    """資料庫目前的版本；還沒有資料庫時為 0。"""
    path = pathlib.Path(root) / accounts_lib.DB_FILE
    if not path.exists():
        return 0
    db = sqlite3.connect(path, timeout=10)
    try:
        return int(db.execute("PRAGMA user_version").fetchone()[0])
    finally:
        db.close()


def open_stores(root: pathlib.Path) -> None:
    """讓每個模組建立自己的資料表（已經有的不會動）。

    升級步驟可能要修改這些資料表，所以要先確定它們都在。
    """
    path = root / accounts_lib.DB_FILE
    accounts_lib.AccountStore(path)
    groups_lib.GroupStore(path)
    user_agents_lib.UserAgentStore(path)
    knowledge_admin.MaintainerStore(path)
    knowledge_eval.EvalStore(path)
    personal_knowledge.PersonalKnowledgeStore(root)
    audit_lib.AuditLog(path)


def prepare(
    root: str | pathlib.Path,
    *,
    keep: int = KEEP_AUTOMATIC,
    version: str | None = None,
) -> Report:
    """啟動網頁版之前呼叫：必要時先快照，再升級資料庫。

    Args:
        root: 專案根目錄。
        keep: 自動快照保留的份數。
        version: 目前的程式版本，預設用 app_version()；測試時可以指定。

    Returns:
        這次做了什麼。

    Raises:
        DataError: 資料庫是比這版程式更新的版本建立的。
    """
    root = pathlib.Path(root).resolve()
    version = version or app_version()
    current = schema_version(root)
    if current > SCHEMA_VERSION:
        raise DataError(
            f"資料庫是較新的程式建立的（資料第 {current} 版，這版程式只認得到"
            f"第 {SCHEMA_VERSION} 版），為了不弄壞資料，不會啟動。請換回"
            "新版的映像檔；一定要用這一版時，先用 `pyharness data list` "
            "找出升級前的快照，再用 `pyharness data restore <名稱>` 還原"
        )
    state = _read_state(root)
    previous = state.get("app", "")
    has_data = (root / accounts_lib.DB_FILE).exists()
    snapshot = None
    if has_data and (previous != version or current < SCHEMA_VERSION):
        reason = (
            f"升級前（{previous} → {version}）"
            if previous
            else "第一次記錄版本"
        )
        snapshot = create_snapshot(root, reason=reason, automatic=True)
        prune(root, keep)
    open_stores(root)
    if has_data:
        applied = _migrate(root / accounts_lib.DB_FILE, current)
    else:
        # 新建的資料庫：各模組建立的資料表已經是最新的樣子。
        _set_version(root / accounts_lib.DB_FILE, SCHEMA_VERSION)
        applied = ()
    _write_state(root, version)
    return Report(
        snapshot=snapshot,
        applied=applied,
        previous_app=previous,
        app_version=version,
    )


def _migrate(path: pathlib.Path, current: int) -> tuple[Migration, ...]:
    """執行版本號大於 current 的升級步驟，每一步一個交易。"""
    pending = tuple(step for step in MIGRATIONS if step.version > current)
    if not pending:
        return ()
    db = sqlite3.connect(path, timeout=10, isolation_level=None)
    try:
        for step in pending:
            db.execute("BEGIN IMMEDIATE")
            try:
                step.apply(db)
                # PRAGMA 不能用參數；版本號是程式裡的整數。
                db.execute(f"PRAGMA user_version = {int(step.version)}")
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise
    finally:
        db.close()
    return pending


def _set_version(path: pathlib.Path, version: int) -> None:
    db = sqlite3.connect(path, timeout=10)
    try:
        db.execute(f"PRAGMA user_version = {int(version)}")
    finally:
        db.close()


def add_column(
    db: sqlite3.Connection, table: str, column: str, definition: str
) -> None:
    """升級步驟用：資料表還沒有這個欄位時才加上。

    舊資料庫裡原本沒有的資料表，會由模組直接建立成最新的樣子（已經有
    這個欄位），所以升級步驟要能重複執行，加欄位一律用這個函式。

    Args:
        db: 升級步驟拿到的連線。
        table: 資料表名稱（程式裡寫死的名稱，不能來自使用者輸入）。
        column: 欄位名稱。
        definition: 欄位型別與預設值，例如 "TEXT NOT NULL DEFAULT ''"。
    """
    columns = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def create_snapshot(
    root: str | pathlib.Path,
    *,
    reason: str = "手動備份",
    automatic: bool = False,
) -> Snapshot:
    """把資料庫與設定檔複製到 .harness/backups/<名稱>/。

    Args:
        root: 專案根目錄。
        reason: 記在快照裡的原因。
        automatic: 是不是自動拍的（只有自動快照會被 prune 刪掉）。

    Returns:
        新的快照。
    """
    root = pathlib.Path(root).resolve()
    backups = root / BACKUP_DIR
    backups.mkdir(parents=True, exist_ok=True)
    os.chmod(backups, 0o700)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    label = "auto" if automatic else "manual"
    name = f"{stamp}-{label}"
    counter = 1
    while (backups / name).exists():
        counter += 1
        name = f"{stamp}-{label}-{counter}"
    work = backups / f".{name}.partial"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir()
    databases = []
    for relative in DATABASES:
        source = root / relative
        if not source.exists():
            continue
        target = work / _DB_DIR / relative.name
        target.parent.mkdir(parents=True, exist_ok=True)
        _copy_database(source, target)
        databases.append(relative.as_posix())
    files = []
    for relative in _config_files(root):
        target = work / _FILES_DIR / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / relative, target)
        files.append(relative)
    manifest = {
        "createdAt": time.time(),
        "reason": reason,
        "automatic": automatic,
        "appVersion": _read_state(root).get("app") or app_version(),
        "schemaVersion": schema_version(root),
        "databases": databases,
        "files": files,
    }
    (work / _MANIFEST).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), "utf-8"
    )
    # 全部寫完才改名，中途失敗不會留下看起來完整的快照。
    work.rename(backups / name)
    return _load_snapshot(backups / name)


def _copy_database(source: pathlib.Path, target: pathlib.Path) -> None:
    """用 SQLite 的 backup API 複製：服務執行中也是一致的內容。"""
    src = sqlite3.connect(source, timeout=10)
    try:
        dst = sqlite3.connect(target)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def _config_files(root: pathlib.Path) -> list[str]:
    """要放進快照的設定檔（相對路徑，排序過、不重複）。"""
    found: set[str] = set()
    for pattern in CONFIG_PATHS:
        for path in root.glob(pattern):
            candidates = path.rglob("*") if path.is_dir() else [path]
            for item in candidates:
                if item.is_symlink() or not item.is_file():
                    continue
                if item.stat().st_size > MAX_CONFIG_FILE_BYTES:
                    continue
                relative = item.relative_to(root)
                if relative.parts[:2] == BACKUP_DIR.parts:
                    continue
                found.add(relative.as_posix())
    return sorted(found)


def list_snapshots(root: str | pathlib.Path) -> list[Snapshot]:
    """所有完整的快照，新的在前。"""
    backups = pathlib.Path(root).resolve() / BACKUP_DIR
    if not backups.is_dir():
        return []
    snapshots = []
    for path in backups.iterdir():
        if not path.is_dir() or not _NAME.match(path.name):
            continue
        try:
            snapshots.append(_load_snapshot(path))
        except (OSError, ValueError):
            continue
    return sorted(
        snapshots, key=lambda item: (item.created_at, item.name), reverse=True
    )


def _load_snapshot(path: pathlib.Path) -> Snapshot:
    data = json.loads((path / _MANIFEST).read_text("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("快照說明格式不對")
    size = sum(
        item.stat().st_size for item in path.rglob("*") if item.is_file()
    )
    return Snapshot(
        name=path.name,
        path=path,
        created_at=float(data.get("createdAt") or 0),
        reason=str(data.get("reason") or ""),
        app_version=str(data.get("appVersion") or ""),
        schema_version=int(data.get("schemaVersion") or 0),
        automatic=bool(data.get("automatic")),
        size=size,
    )


def prune(root: str | pathlib.Path, keep: int = KEEP_AUTOMATIC) -> list[str]:
    """只留最近 keep 份自動快照，回傳刪掉的名稱。手動快照不會刪。"""
    automatic = [item for item in list_snapshots(root) if item.automatic]
    removed = []
    for item in automatic[max(keep, 1) :]:
        shutil.rmtree(item.path, ignore_errors=True)
        removed.append(item.name)
    return removed


def restore(root: str | pathlib.Path, name: str) -> Snapshot:
    """把資料庫與設定檔換回快照的內容。

    還原前會先把現在的狀態拍一份手動快照，還原錯了也可以再換回來。
    快照之後才新增的設定檔（例如新的 agent）不會被刪掉。請先停止網頁版
    再還原。

    Args:
        root: 專案根目錄。
        name: 快照名稱（list_snapshots 的 name）。

    Returns:
        還原前拍的快照。

    Raises:
        DataError: 找不到這份快照。
    """
    root = pathlib.Path(root).resolve()
    if not _NAME.match(name):
        raise DataError(f"快照名稱不對：{name}")
    source = root / BACKUP_DIR / name
    try:
        manifest = json.loads((source / _MANIFEST).read_text("utf-8"))
    except (OSError, ValueError) as error:
        raise DataError(
            f"找不到快照 {name}，可用 `pyharness data list` 查看"
        ) from error
    before = create_snapshot(root, reason=f"還原 {name} 之前")
    for relative in manifest.get("databases") or []:
        path = pathlib.PurePosixPath(relative)
        stored = source / _DB_DIR / path.name
        if stored.exists():
            _restore_database(stored, root / path)
    for relative in manifest.get("files") or []:
        stored = source / _FILES_DIR / relative
        target = (root / relative).resolve()
        if not stored.is_file() or not target.is_relative_to(root):
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(stored, target)
    _write_state(root, str(manifest.get("appVersion") or ""))
    return before


def _restore_database(stored: pathlib.Path, target: pathlib.Path) -> None:
    """用 backup API 把快照寫回資料庫（WAL 也一併處理）。"""
    target.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(stored)
    try:
        dst = sqlite3.connect(target, timeout=10)
        try:
            src.backup(dst)
            dst.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            dst.close()
    finally:
        src.close()


def _read_state(root: pathlib.Path) -> dict:
    try:
        data = json.loads((root / STATE_FILE).read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_state(root: pathlib.Path, version: str) -> None:
    path = root / STATE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "app": version,
        "schema": schema_version(root),
        "updatedAt": time.time(),
    }
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), "utf-8"
    )
    temporary.replace(path)
