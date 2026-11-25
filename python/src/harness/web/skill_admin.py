"""網頁上新增、修改、刪除 skill（管理平台的公司 skill 與成員的個人 skill）。

一個 skill 就是一個資料夾（見 harness.skills）：SKILL.md 加上參考檔案。
這裡只管資料夾裡的檔案，誰能改、改完怎麼重新載入由 workspace 決定：

    公司 skill   專案的 skills/<名稱>/，只有管理者能改。和內建 skill 同名
                 時取代內建的（「修改」內建 skill 就是複製一份成公司版本，
                 刪掉公司版本即還原）。內建 skill 不能刪，但可以在
                 harness.yaml 的 web.disabledSkills 關掉。
    個人 skill   .harness/personal-skills/<使用者識別碼>/<名稱>/，只有建立
                 的人看得到、用得到，不能分享（和個人知識庫、自建 agent
                 一樣）。不能帶專屬工具（SKILL.md 的 tools），只能用
                 agent 本來就有的工具。

也可以上傳整個 skill 資料夾的 zip（例如從 Anthropic 或社群下載的
skill）：只解開 SKILL.md 所在的那一層，不接受捷徑、絕對路徑與 ..，
大小與檔案數有上限（避免壓縮炸彈）。
"""

import contextlib
import dataclasses
import io
import pathlib
import re
import shutil
import stat
import uuid
import zipfile
from collections.abc import Iterator
from typing import Any

import yaml

from harness import project as project_lib
from harness import skills as skills_lib

# 和 Anthropic 的 skill 規格一樣：小寫英文、數字與連字號，最多 64 個字元。
NAME = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")
DESCRIPTION_LIMIT = 1024
INSTRUCTIONS_LIMIT = 100_000
PERSONAL_DIR = project_lib.DATA_DIR / "personal-skills"
# 寫入時的暫存與備份資料夾（以點開頭，載入 skill 時不會讀到）。
_WORK_DIR = ".work"
_IGNORED = ("__MACOSX/", ".DS_Store")


class SkillError(Exception):
    """skill 的內容不對或找不到，訊息會直接顯示給使用者。

    Attributes:
        status: HTTP 狀態碼。
    """

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


@dataclasses.dataclass(frozen=True)
class Limits:
    """一個 skill 資料夾的上限。

    Attributes:
        max_skills: 最多幾個 skill；None 表示不限。
        max_zip_bytes: 上傳的 zip 檔最大幾個位元組。
        max_files: 一個 skill 最多幾個檔案。
        max_total_bytes: 一個 skill 解開後最多幾個位元組。
        allow_tools: SKILL.md 能不能寫 tools（skill 的專屬工具）。
    """

    max_skills: int | None = None
    max_zip_bytes: int = 30_000_000
    max_files: int = 1000
    max_total_bytes: int = 100_000_000
    allow_tools: bool = True

    def info(self) -> dict[str, Any]:
        return {
            "maxSkills": self.max_skills,
            "maxZipBytes": self.max_zip_bytes,
            "maxFiles": self.max_files,
            "descriptionLimit": DESCRIPTION_LIMIT,
            "instructionsLimit": INSTRUCTIONS_LIMIT,
        }


COMPANY_LIMITS = Limits()
PERSONAL_LIMITS = Limits(
    max_skills=50,
    max_zip_bytes=5_000_000,
    max_files=100,
    max_total_bytes=10_000_000,
    allow_tools=False,
)


def check_name(name: Any) -> str:
    """檢查 skill 名稱。

    Raises:
        SkillError: 名稱不符合規則。
    """
    if not isinstance(name, str) or not NAME.match(name.strip()):
        raise SkillError(
            "名稱只能用小寫英文、數字與連字號（-），開頭和結尾不能是"
            "連字號，最多 64 個字元，例如 meeting-notes"
        )
    return name.strip()


def check_description(description: Any) -> str:
    if not isinstance(description, str) or not description.strip():
        raise SkillError(
            "請填寫說明：agent 靠這段說明判斷什麼時候要載入這個 skill"
        )
    description = " ".join(description.split())
    if len(description) > DESCRIPTION_LIMIT:
        raise SkillError(f"說明最多 {DESCRIPTION_LIMIT} 個字")
    return description


def check_instructions(instructions: Any) -> str:
    if not isinstance(instructions, str) or not instructions.strip():
        raise SkillError("請填寫指示：載入 skill 後 agent 要照著做的內容")
    instructions = instructions.strip()
    if len(instructions) > INSTRUCTIONS_LIMIT:
        raise SkillError(f"指示最多 {INSTRUCTIONS_LIMIT} 個字")
    return instructions


def render(meta: dict[str, Any], body: str) -> str:
    """組成 SKILL.md 的內容。"""
    head = yaml.safe_dump(
        meta, allow_unicode=True, sort_keys=False, width=1000
    ).strip()
    return f"---\n{head}\n---\n{body.strip()}\n"


def read_source(folder: pathlib.Path) -> tuple[dict[str, Any], str]:
    """讀出 skill 資料夾裡 SKILL.md 的設定與內文。

    Raises:
        SkillError: 沒有 SKILL.md，或格式不對。
    """
    path = folder / skills_lib.SKILL_FILE
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise SkillError("找不到這個 skill", 404) from error
    try:
        meta, body = project_lib.parse_frontmatter(text)
    except yaml.YAMLError as error:
        raise SkillError(f"SKILL.md 的開頭設定格式不對：{error}") from error
    if not isinstance(meta, dict):
        raise SkillError("SKILL.md 的開頭設定必須是「名稱: 值」的對應")
    return meta, body


def resource_files(folder: pathlib.Path) -> list[str]:
    """skill 資料夾裡的其他檔案（不含 SKILL.md 與隱藏檔）。"""
    return skills_lib.Skill(
        name="", description="", instructions="", root=folder
    ).resource_files()


class SkillFolder:
    """一個存放 skill 的資料夾（每個子資料夾是一個 skill）。

    寫入時先寫到暫存資料夾再換上；舊的版本先移到備份，呼叫端用
    change() 包住寫入與重新載入，重新載入失敗時還原。
    """

    def __init__(self, directory: pathlib.Path, limits: Limits) -> None:
        self.directory = directory
        self.limits = limits

    def names(self) -> list[str]:
        """有 SKILL.md 的子資料夾名稱。"""
        if not self.directory.is_dir():
            return []
        return sorted(
            path.parent.name
            for path in self.directory.glob(f"*/{skills_lib.SKILL_FILE}")
            if not path.parent.name.startswith(".")
        )

    def path(self, name: str) -> pathlib.Path:
        return self.directory / check_name(name)

    def exists(self, name: str) -> bool:
        return (self.path(name) / skills_lib.SKILL_FILE).is_file()

    def detail(self, name: str) -> dict[str, Any]:
        """SKILL.md 的內容與參考檔案清單（編輯頁用）。"""
        folder = self.path(name)
        meta, body = read_source(folder)
        return source_detail(name, meta, body, folder)

    @contextlib.contextmanager
    def change(self, name: str) -> Iterator[pathlib.Path]:
        """改一個 skill：先把現在的版本搬到備份，區塊裡出錯時還原。

        Yields:
            skill 的資料夾（可能還不存在）。
        """
        target = self.path(name)
        work = self.directory / _WORK_DIR
        work.mkdir(parents=True, exist_ok=True)
        backup = work / f"backup-{uuid.uuid4().hex}"
        had = target.exists()
        if had:
            shutil.copytree(target, backup, symlinks=True)
        try:
            yield target
        except BaseException:
            if target.exists():
                shutil.rmtree(target)
            if had:
                backup.rename(target)
            raise
        finally:
            if backup.exists():
                shutil.rmtree(backup)

    def write(
        self,
        name: str,
        description: str,
        instructions: str,
        meta: dict[str, Any] | None = None,
    ) -> None:
        """寫入 SKILL.md（保留 meta 裡其他的設定，例如 license、requires）。"""
        meta = dict(meta or {})
        meta.pop("name", None)
        meta.pop("description", None)
        if meta.get("tools") and not self.limits.allow_tools:
            raise SkillError("個人 skill 不能帶專屬工具（tools）")
        ordered = {"name": name, "description": description, **meta}
        folder = self.path(name)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / skills_lib.SKILL_FILE).write_text(
            render(ordered, instructions), encoding="utf-8"
        )

    def check_room(self, name: str) -> None:
        """新增時檢查數量上限。"""
        limit = self.limits.max_skills
        if limit is not None and not self.exists(name):
            if len(self.names()) >= limit:
                raise SkillError(f"最多 {limit} 個 skill，請先刪掉用不到的")

    def delete(self, name: str) -> None:
        folder = self.path(name)
        if not (folder / skills_lib.SKILL_FILE).is_file():
            raise SkillError("找不到這個 skill", 404)
        shutil.rmtree(folder)

    def copy_from(self, name: str, source: pathlib.Path) -> None:
        """把整個 skill 資料夾（例如內建的）複製過來，不跟著捷徑。"""
        target = self.path(name)
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(
            source,
            target,
            symlinks=False,
            ignore=shutil.ignore_patterns("__pycache__", ".*"),
        )

    def unpack(self, data: bytes, fallback_name: str = "") -> str:
        """檢查上傳的 zip，回傳 skill 名稱；還沒寫入（見 extract）。

        Raises:
            SkillError: 不是 zip、太大、有不安全的路徑，或 SKILL.md 不對。
        """
        _, name, _ = self._inspect(data, fallback_name)
        return name

    def extract(self, data: bytes, fallback_name: str = "") -> str:
        """把 zip 裡的 skill 解開到資料夾（取代同名的），回傳名稱。

        呼叫端要先用 change() 包住，重新載入失敗時才能還原。
        """
        members, name, prefix = self._inspect(data, fallback_name)
        target = self.path(name)
        work = self.directory / _WORK_DIR
        work.mkdir(parents=True, exist_ok=True)
        staging = work / f"upload-{uuid.uuid4().hex}"
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                for info in members:
                    relative = info.filename[len(prefix) :]
                    destination = staging.joinpath(*relative.split("/"))
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with (
                        archive.open(info) as source,
                        destination.open("wb") as output,
                    ):
                        shutil.copyfileobj(source, output)
            if target.exists():
                shutil.rmtree(target)
            staging.rename(target)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
        return name

    def _inspect(
        self, data: bytes, fallback_name: str
    ) -> tuple[list[zipfile.ZipInfo], str, str]:
        limits = self.limits
        if len(data) > limits.max_zip_bytes:
            raise SkillError(
                f"zip 檔最大 {limits.max_zip_bytes // 1_000_000} MB"
            )
        try:
            archive = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile as error:
            raise SkillError("不是 zip 檔") from error
        with archive:
            infos = [
                info
                for info in archive.infolist()
                if not info.is_dir()
                and not any(part in info.filename for part in _IGNORED)
            ]
            markers = [
                info
                for info in infos
                if info.filename.rsplit("/", 1)[-1] == skills_lib.SKILL_FILE
            ]
            if not markers:
                raise SkillError("zip 裡找不到 SKILL.md")
            # 有好幾個時用最上層的那一個（其他可能是範例）。
            marker = min(markers, key=lambda info: info.filename.count("/"))
            prefix = marker.filename[: -len(skills_lib.SKILL_FILE)]
            members = [
                info for info in infos if info.filename.startswith(prefix)
            ]
            for info in members:
                _check_member(info)
            if len(members) > limits.max_files:
                raise SkillError(f"一個 skill 最多 {limits.max_files} 個檔案")
            total = sum(info.file_size for info in members)
            if total > limits.max_total_bytes:
                raise SkillError(
                    f"解開後超過 {limits.max_total_bytes // 1_000_000} MB"
                )
            try:
                text = archive.read(marker).decode("utf-8")
            except UnicodeDecodeError as error:
                raise SkillError("SKILL.md 必須是 UTF-8 文字檔") from error
        try:
            meta, body = project_lib.parse_frontmatter(text)
        except yaml.YAMLError as error:
            raise SkillError(f"SKILL.md 的開頭設定格式不對：{error}") from error
        if not isinstance(meta, dict):
            raise SkillError("SKILL.md 的開頭設定必須是「名稱: 值」的對應")
        folder_name = prefix.rstrip("/").rsplit("/", 1)[-1]
        raw = meta.get("name") or folder_name or fallback_name
        name = check_name(str(raw))
        check_description(str(meta.get("description") or ""))
        if not body.strip():
            raise SkillError("SKILL.md 沒有指示內容")
        if meta.get("tools") and not limits.allow_tools:
            raise SkillError("個人 skill 不能帶專屬工具（SKILL.md 的 tools）")
        return members, name, prefix


def _check_member(info: zipfile.ZipInfo) -> None:
    """zip 裡的一個檔案：不能是捷徑、絕對路徑或往上層的路徑。"""
    name = info.filename
    mode = info.external_attr >> 16
    if stat.S_ISLNK(mode):
        raise SkillError(f"zip 裡不能有捷徑（symlink）：{name}")
    parts = name.split("/")
    if (
        name.startswith("/")
        or "\\" in name
        or ":" in parts[0]
        or any(part in ("", "..", ".") for part in parts)
    ):
        raise SkillError(f"zip 裡有不安全的路徑：{name}")


def source_detail(
    name: str, meta: dict[str, Any], body: str, folder: pathlib.Path
) -> dict[str, Any]:
    """SkillDetail（見 src/web/protocol.ts）的檔案部分。"""
    return {
        "name": name,
        "description": str(meta.get("description") or ""),
        "instructions": body,
        "requires": [str(item) for item in meta.get("requires") or []],
        "tools": [str(item) for item in meta.get("tools") or []],
        "files": resource_files(folder),
    }


def personal_folder(root: pathlib.Path, user_id: str) -> SkillFolder:
    """一個人的個人 skill 資料夾。"""
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", user_id):
        raise SkillError("使用者識別碼不對", 404)
    return SkillFolder(root / PERSONAL_DIR / user_id, PERSONAL_LIMITS)


def load_personal(folder: SkillFolder) -> dict[str, skills_lib.Skill]:
    """讀出個人 skill；格式壞掉的略過（不影響其他 skill 與對話）。"""
    loaded: dict[str, skills_lib.Skill] = {}
    for name in folder.names():
        path = folder.directory / name
        try:
            meta, body = read_source(path)
        except SkillError:
            continue
        description = str(meta.get("description") or "").strip()
        if not description or not body.strip():
            continue
        loaded[name] = skills_lib.Skill(
            name=name,
            description=description,
            instructions=body,
            root=path,
            requires=[str(item) for item in meta.get("requires") or []],
        )
    return loaded
