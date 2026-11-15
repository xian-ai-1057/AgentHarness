"""個人知識庫：使用者自己建立、自己上傳文件的知識庫。

和公司知識庫（harness.yaml 的 knowledge 與 knowledgeBases，由管理者用
群組開放）分開管理：

- 名稱、說明與擁有者存在帳號資料庫 .harness/harness.db 的
  personal_knowledge，不寫進 harness.yaml。
- 文件放在 .harness/personal-knowledge/<識別碼>/，索引放在
  .harness/knowledge/personal/<識別碼>/。agent 的工作資料夾看不到這裡，
  只能透過 search_knowledge 搜尋。
- 只有擁有者看得到、搜尋得到，不經過存取群組，也不能分享（使用者
  2026-11-15 決定：要給別人用的資料請管理者建成公司知識庫）。管理者
  可以在 harness.yaml 的 personalKnowledge 區塊關掉整個功能，並調整
  數量與容量上限。
- 檢索設定（檢索方式、embedding 模型、reranker、門檻等）沿用 harness.yaml 的
  knowledge 區塊，只有切片方式（依段落或依條文）由擁有者選。
"""

import dataclasses
import pathlib
import secrets
import shutil
import sqlite3
import time
from collections.abc import AsyncIterator
from typing import Any

from harness import knowledge as knowledge_lib
from harness import project as project_lib
from harness.web import accounts as accounts_lib
from harness.web import config as config_lib
from harness.web import knowledge_admin

CONFIG_KEY = "personalKnowledge"
FILES_DIR = project_lib.DATA_DIR / "personal-knowledge"
CACHE_DIR = project_lib.KNOWLEDGE_CACHE_DIR / "personal"
# 個人知識庫的識別碼都以這個開頭，不會和 harness.yaml 裡的撞到（見
# knowledge_admin.checked_id）。
ID_PREFIX = knowledge_admin.PERSONAL_PREFIX
_MB = 1024 * 1024

# harness.yaml 的 personalKnowledge 沒寫時的值。
DEFAULT_LIMITS = {
    "enabled": True,
    "maxBases": 10,
    "maxDocuments": 50,
    "maxFileMB": 20,
    "maxTotalMB": 200,
}
_RETRIEVAL_KEYS = (
    "searchMode",
    "embeddingModel",
    "chunkSize",
    "reranker",
    "rerankCandidates",
    "minSimilarity",
    "minRerankScore",
)
_NAME_LIMIT = 40
_DESCRIPTION_LIMIT = 300

_SCHEMA = """
CREATE TABLE IF NOT EXISTS personal_knowledge (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    chunking TEXT NOT NULL DEFAULT 'paragraph',
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS personal_knowledge_owner
    ON personal_knowledge (owner_id);
"""


class PersonalKnowledgeError(Exception):
    """個人知識庫的操作失敗，訊息會直接顯示給使用者。

    Attributes:
        status: HTTP 狀態碼。
    """

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


@dataclasses.dataclass(frozen=True)
class Limits:
    """harness.yaml 的 personalKnowledge 區塊。

    Attributes:
        enabled: 使用者能不能建立個人知識庫（關掉後已經建立的也搜尋不到）。
        max_bases: 每個人最多幾個知識庫。
        max_documents: 每個知識庫最多幾份文件。
        max_file_bytes: 單一檔案的大小上限。
        max_total_bytes: 每個人所有個人知識庫加起來的容量。
    """

    enabled: bool = True
    max_bases: int = DEFAULT_LIMITS["maxBases"]
    max_documents: int = DEFAULT_LIMITS["maxDocuments"]
    max_file_bytes: int = DEFAULT_LIMITS["maxFileMB"] * _MB
    max_total_bytes: int = DEFAULT_LIMITS["maxTotalMB"] * _MB

    def info(self) -> dict[str, Any]:
        """PersonalKnowledgeLimits（見 src/web/protocol.ts）。"""
        return {
            "enabled": self.enabled,
            "maxBases": self.max_bases,
            "maxDocuments": self.max_documents,
            "maxFileBytes": self.max_file_bytes,
            "maxTotalBytes": self.max_total_bytes,
        }


def read_limits(config: dict[str, Any]) -> Limits:
    """從 harness.yaml 的內容讀出 personalKnowledge 的設定。

    寫成 personalKnowledge: false 時關掉整個功能；格式不對的值沿用預設。
    """
    block = config.get(CONFIG_KEY)
    if block is False:
        return Limits(enabled=False)
    if not isinstance(block, dict):
        return Limits()

    def flag(key: str) -> bool:
        value = block.get(key, DEFAULT_LIMITS[key])
        return value if isinstance(value, bool) else bool(DEFAULT_LIMITS[key])

    def number(key: str) -> int:
        value = block.get(key, DEFAULT_LIMITS[key])
        if isinstance(value, bool) or not isinstance(value, int | float):
            value = DEFAULT_LIMITS[key]
        return max(1, int(value))

    return Limits(
        enabled=flag("enabled"),
        max_bases=number("maxBases"),
        max_documents=number("maxDocuments"),
        max_file_bytes=number("maxFileMB") * _MB,
        max_total_bytes=number("maxTotalMB") * _MB,
    )


@dataclasses.dataclass(frozen=True)
class PersonalBase:
    """一個個人知識庫的資料（不含文件）。

    Attributes:
        id: 識別碼，以 my- 開頭。
        owner_id: 擁有者的帳號識別碼。
        name: 名稱。
        description: 說明，agent 也會看到。
        chunking: 切片方式（paragraph 或 regulation）。
        created_at: 建立時間（秒）。
    """

    id: str
    owner_id: str
    name: str
    description: str = ""
    chunking: str = "paragraph"
    created_at: float = 0.0


class PersonalKnowledgeStore:
    """所有人的個人知識庫：資料在帳號資料庫，文件在 .harness 底下。"""

    def __init__(self, root: str | pathlib.Path) -> None:
        self.root = pathlib.Path(root)
        self.path = self.root / accounts_lib.DB_FILE
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=10)
        try:
            db.executescript(_SCHEMA)
            db.commit()
        finally:
            db.close()
        # 識別碼 → (建立時的設定, KnowledgeBase)；設定沒變時重複使用，
        # 索引才不必每一輪重新讀取。
        self._loaded: dict[str, tuple[tuple[Any, ...], Any]] = {}

    # --- 設定 -------------------------------------------------------------

    def limits(self) -> Limits:
        """目前的上限（每次讀 harness.yaml，改了不必重新啟動）。"""
        return read_limits(_read_config(self.root))

    # --- 查詢 -------------------------------------------------------------

    def get(self, base_id: str) -> PersonalBase | None:
        """依識別碼找知識庫，找不到時為 None。"""
        found = self._select("WHERE id = ?", (base_id,))
        return found[0] if found else None

    def owned_by(self, user_id: str) -> list[PersonalBase]:
        """這個人建立的知識庫，依建立時間排序。"""
        return self._select("WHERE owner_id = ?", (user_id,))

    def all(self) -> list[PersonalBase]:
        """所有人的個人知識庫。"""
        return self._select("", ())

    # --- 修改 -------------------------------------------------------------

    def create(
        self,
        owner_id: str,
        name: Any,
        description: Any = "",
        chunking: Any = "paragraph",
    ) -> PersonalBase:
        """建立個人知識庫與它的資料夾。

        Raises:
            PersonalKnowledgeError: 功能關閉、超過數量上限，或欄位不對。
        """
        limits = self.limits()
        if not limits.enabled:
            raise PersonalKnowledgeError("管理者沒有開放個人知識庫", 403)
        if len(self.owned_by(owner_id)) >= limits.max_bases:
            raise PersonalKnowledgeError(
                f"每個人最多 {limits.max_bases} 個知識庫，請先刪除不用的"
            )
        base = PersonalBase(
            id=ID_PREFIX + secrets.token_hex(5),
            owner_id=owner_id,
            name=_checked_name(name),
            description=_checked_description(description),
            chunking=_checked_chunking(chunking),
            created_at=time.time(),
        )
        self.files_path(base.id).mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute(
                "INSERT INTO personal_knowledge VALUES (?, ?, ?, ?, ?, ?)",
                (
                    base.id,
                    base.owner_id,
                    base.name,
                    base.description,
                    base.chunking,
                    base.created_at,
                ),
            )
        return base

    def update(self, base_id: str, changes: dict[str, Any]) -> PersonalBase:
        """修改名稱、說明或切片方式。

        Args:
            base_id: 知識庫識別碼。
            changes: name、description、chunking 其中幾個。

        Raises:
            PersonalKnowledgeError: 找不到，或欄位不對。
        """
        self._require(base_id)
        unknown = sorted(set(changes) - {"name", "description", "chunking"})
        if unknown:
            raise PersonalKnowledgeError(f"不認得的欄位：{'、'.join(unknown)}")
        values = {}
        if "name" in changes:
            values["name"] = _checked_name(changes["name"])
        if "description" in changes:
            values["description"] = _checked_description(changes["description"])
        if "chunking" in changes:
            values["chunking"] = _checked_chunking(changes["chunking"])
        with self._connect() as db:
            for key, value in values.items():
                db.execute(
                    f"UPDATE personal_knowledge SET {key} = ? WHERE id = ?",
                    (value, base_id),
                )
        return self._require(base_id)

    def delete(self, base_id: str) -> PersonalBase:
        """刪除知識庫、它的文件與索引，回傳被刪除的知識庫。

        Raises:
            PersonalKnowledgeError: 找不到。
        """
        base = self._require(base_id)
        with self._connect() as db:
            db.execute(
                "DELETE FROM personal_knowledge WHERE id = ?", (base_id,)
            )
        self._loaded.pop(base_id, None)
        shutil.rmtree(self.files_path(base_id), ignore_errors=True)
        shutil.rmtree(self.root / CACHE_DIR / base_id, ignore_errors=True)
        return base

    # --- 文件 -------------------------------------------------------------

    def files_path(self, base_id: str) -> pathlib.Path:
        """知識庫的文件資料夾。"""
        return self.root / FILES_DIR / base_id

    def used_bytes(self, owner_id: str) -> int:
        """這個人所有個人知識庫的文件加起來的大小。"""
        total = 0
        for base in self.owned_by(owner_id):
            folder = self.files_path(base.id)
            if not folder.is_dir():
                continue
            for path in folder.rglob("*"):
                if path.is_file() and not path.is_symlink():
                    total += path.stat().st_size
        return total

    async def save_document(
        self,
        base_id: str,
        filename: str,
        chunks: AsyncIterator[bytes],
        *,
        max_upload_bytes: int,
        replace: str | None = None,
    ) -> dict[str, Any]:
        """把上傳的檔案存進個人知識庫，檢查文件數與容量。

        Args:
            base_id: 知識庫識別碼。
            filename: 瀏覽器送來的檔名。
            chunks: 檔案內容。
            max_upload_bytes: 網頁版的上傳上限（和個人上限取比較小的）。
            replace: 要換掉的文件；None 表示新增。

        Returns:
            {"path": 相對路徑, "size": 位元組數}。

        Raises:
            PersonalKnowledgeError: 超過文件數、單檔或總容量上限，或檔案
                不能存。
        """
        base = self._require(base_id)
        limits = self.limits()
        loaded = self.knowledge_base(base)
        files = loaded.knowledge.files()
        if replace is None and len(files) >= limits.max_documents:
            raise PersonalKnowledgeError(
                f"每個知識庫最多 {limits.max_documents} 份文件", 413
            )
        replaced = 0
        if replace is not None and replace in files:
            replaced = (self.files_path(base_id) / replace).stat().st_size
        remaining = (
            limits.max_total_bytes - self.used_bytes(base.owner_id) + replaced
        )
        per_file = min(limits.max_file_bytes, max_upload_bytes)
        if remaining <= 0:
            raise PersonalKnowledgeError(_quota_message(limits), 413)
        try:
            return await knowledge_admin.save_document(
                loaded,
                filename,
                chunks,
                max_bytes=min(per_file, remaining),
                replace=replace,
            )
        except knowledge_admin.KnowledgeAdminError as error:
            if error.status == 413 and remaining < per_file:
                raise PersonalKnowledgeError(
                    _quota_message(limits), 413
                ) from error
            raise PersonalKnowledgeError(str(error), error.status) from error

    def delete_document(self, base_id: str, path: str) -> None:
        """刪除個人知識庫裡的一份文件。

        Raises:
            PersonalKnowledgeError: 找不到這份文件。
        """
        loaded = self.knowledge_base(self._require(base_id))
        try:
            knowledge_admin.delete_document(loaded, path)
        except knowledge_admin.KnowledgeAdminError as error:
            raise PersonalKnowledgeError(str(error), error.status) from error

    # --- 搜尋 -------------------------------------------------------------

    def knowledge_base(self, base: PersonalBase) -> knowledge_lib.KnowledgeBase:
        """個人知識庫對應的 KnowledgeBase（搜尋、列出文件用）。

        檢索設定沿用 harness.yaml 的 knowledge 區塊；設定沒變時重複使用
        同一個物件，索引不必重新讀取。
        """
        shared = _read_config(self.root).get("knowledge")
        retrieval = shared if isinstance(shared, dict) else {}
        settings = tuple(retrieval.get(key) for key in _RETRIEVAL_KEYS)
        signature = (base.name, base.description, base.chunking, settings)
        cached = self._loaded.get(base.id)
        if cached is not None and cached[0] == signature:
            return cached[1]
        folder = self.files_path(base.id)
        folder.mkdir(parents=True, exist_ok=True)
        made = knowledge_lib.KnowledgeBase(
            id=base.id,
            name=base.name,
            description=base.description,
            knowledge=knowledge_lib.Knowledge(
                folder,
                **project_lib.retrieval_options(retrieval, "knowledge"),
                chunking=base.chunking,
                cache_dir=self.root / CACHE_DIR / base.id,
            ),
        )
        self._loaded[base.id] = (signature, made)
        return made

    # --- 內部 -------------------------------------------------------------

    def _require(self, base_id: str) -> PersonalBase:
        base = self.get(base_id)
        if base is None:
            raise PersonalKnowledgeError(f"找不到知識庫：{base_id}", 404)
        return base

    def _select(
        self, where: str, params: tuple[Any, ...]
    ) -> list[PersonalBase]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT id, owner_id, name, description, chunking, created_at "
                f"FROM personal_knowledge {where} ORDER BY created_at, id",
                params,
            ).fetchall()
        return [
            PersonalBase(
                id=row[0],
                owner_id=row[1],
                name=row[2],
                description=row[3],
                chunking=row[4],
                created_at=row[5],
            )
            for row in rows
        ]

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        return accounts_lib._Transaction(db)


def _read_config(root: pathlib.Path) -> dict[str, Any]:
    try:
        return config_lib.read_config(root)
    except (OSError, ValueError):
        return {}


def _quota_message(limits: Limits) -> str:
    return (
        f"個人知識庫的空間已經用完（每人 {limits.max_total_bytes // _MB} MB），"
        "請先刪除不用的文件"
    )


def _checked_name(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PersonalKnowledgeError("請輸入知識庫名稱")
    value = value.strip()
    if len(value) > _NAME_LIMIT:
        raise PersonalKnowledgeError(f"名稱最多 {_NAME_LIMIT} 個字")
    return value


def _checked_description(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise PersonalKnowledgeError("說明必須是文字")
    value = value.strip()
    if len(value) > _DESCRIPTION_LIMIT:
        raise PersonalKnowledgeError(f"說明最多 {_DESCRIPTION_LIMIT} 個字")
    return value


def _checked_chunking(value: Any) -> str:
    if value is None or value == "":
        return "paragraph"
    if value not in knowledge_lib.CHUNKING_MODES:
        choices = "、".join(knowledge_lib.CHUNKING_MODES)
        raise PersonalKnowledgeError(f"chunking 必須是 {choices} 其中之一")
    return value
