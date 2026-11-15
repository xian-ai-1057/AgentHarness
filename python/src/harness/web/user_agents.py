"""使用者自己建立的 agent（自建 Agent）。

做法參考 ChatGPT 的 GPTs、Claude 的 Projects 與 MaiAgent 的建立 Agent：

    - 每個人可以建立自己的 agent：名稱、說明、指示、開場建議、預設模型，
      以及要用哪些工具組、知識庫與技能。
    - 只能挑自己能用的東西：工具組與知識庫要是所屬群組開放的，模型要在
      模型選單裡（模型中台允許的）。存檔時檢查一次，每一輪執行時
      workspace 再依「使用的人」的群組套用一次限制（見 workspace.py），
      所以管理者收回工具後，自建的 agent 也跟著不能用。
    - 只有建立的人看得到、用得到、改得到（目前沒有分享功能）。

資料存在帳號資料庫（.harness/harness.db）：

    user_agents     自建的 agent

agent 在對話裡的名稱是 KEY_PREFIX 加上識別碼（例如 user:3f9a…），
不會和 agents/ 底下的 agent 撞名。
"""

import dataclasses
import json
import pathlib
import sqlite3
import time
import uuid
from typing import Any

from harness.web import accounts as accounts_lib

KEY_PREFIX = "user:"
NAME_LIMIT = 40
DESCRIPTION_LIMIT = 200
INSTRUCTIONS_LIMIT = 8000
STARTER_LIMIT = 100
STARTERS_MAX = 4
# 一個人最多建立幾個 agent，避免把資料庫塞爆。
PER_USER_LIMIT = 100
# 腳本要在沙盒裡執行的 skills（處理 Office 檔與 PDF）；沒有勾「執行 Python」
# （sandbox 工具組）時用不了，建立表單不會預設勾選。
SANDBOX_SKILLS = frozenset({"xlsx", "docx", "pptx", "pdf"})
SANDBOX_TOOLSET = "sandbox"
_LIST_LIMIT = 200

_SCHEMA = """
CREATE TABLE IF NOT EXISTS user_agents (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    instructions TEXT NOT NULL DEFAULT '',
    starters TEXT NOT NULL DEFAULT '[]',
    model TEXT,
    toolsets TEXT NOT NULL DEFAULT '[]',
    knowledge_bases TEXT NOT NULL DEFAULT '[]',
    skills TEXT NOT NULL DEFAULT '[]',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS user_agents_owner ON user_agents (owner_id);
"""

# 可以修改的欄位（API 用 camelCase）→ 資料表欄位。
_LIST_FIELDS = {
    "starters": "starters",
    "toolsets": "toolsets",
    "knowledgeBases": "knowledge_bases",
    "skills": "skills",
}


class UserAgentError(Exception):
    """操作失敗，訊息會直接顯示給使用者。

    Attributes:
        status: HTTP 狀態碼。
    """

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


@dataclasses.dataclass(frozen=True)
class UserAgent:
    """一個自建的 agent。

    Attributes:
        id: 識別碼（12 個十六進位字元）。
        owner_id: 建立的人。
        name: 顯示名稱。
        description: 一句話說明用途。
        instructions: 指示（角色指令），會成為 system prompt 的開頭。
        starters: 開場建議，新對話頁顯示成可以點的按鈕。
        model: 預設模型；None 表示跟著專案的預設模型。
        toolsets: 可以使用的工具組名稱。
        knowledge_bases: 可以搜尋的知識庫識別碼。
        skills: 可以載入的技能名稱。
        created_at: 建立時間（秒）。
        updated_at: 最後修改時間（秒）。
    """

    id: str
    owner_id: str
    name: str
    description: str = ""
    instructions: str = ""
    starters: tuple[str, ...] = ()
    model: str | None = None
    toolsets: tuple[str, ...] = ()
    knowledge_bases: tuple[str, ...] = ()
    skills: tuple[str, ...] = ()
    created_at: float = 0.0
    updated_at: float = 0.0

    @property
    def key(self) -> str:
        """在對話裡代表這個 agent 的名稱。"""
        return KEY_PREFIX + self.id

    def info(self) -> dict[str, Any]:
        """完整的設定（UserAgentInfo，見 src/web/protocol.ts）；只給擁有者。"""
        return {
            "id": self.id,
            "key": self.key,
            "name": self.name,
            "description": self.description,
            "instructions": self.instructions,
            "starters": list(self.starters),
            "model": self.model,
            "toolsets": list(self.toolsets),
            "knowledgeBases": list(self.knowledge_bases),
            "skills": list(self.skills),
            "createdAt": self.created_at * 1000,
            "updatedAt": self.updated_at * 1000,
        }


def is_key(name: str | None) -> bool:
    """這個 agent 名稱是不是自建的 agent。"""
    return bool(name) and name.startswith(KEY_PREFIX)


def id_of(key: str) -> str:
    """從對話裡的名稱取出識別碼。"""
    return key[len(KEY_PREFIX) :]


class UserAgentStore:
    """自建 agent 的資料庫，和帳號共用 .harness/harness.db。

    每次操作都開一個新的連線，和其他資料表的做法一樣。
    """

    def __init__(self, path: str | pathlib.Path, clock=time.time) -> None:
        self.path = pathlib.Path(path)
        self._clock = clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=10)
        try:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(_SCHEMA)
            db.commit()
        finally:
            db.close()

    @classmethod
    def for_project(cls, root: str | pathlib.Path) -> "UserAgentStore":
        """專案的自建 agent 資料庫（和帳號同一個檔案）。"""
        return cls(pathlib.Path(root) / accounts_lib.DB_FILE)

    def get(self, agent_id: str) -> UserAgent | None:
        """依識別碼找 agent，找不到時為 None。"""
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM user_agents WHERE id = ?", (agent_id,)
            ).fetchone()
        return _agent(row) if row else None

    def list_all(self) -> list[UserAgent]:
        """所有自建的 agent，最近修改的排前面。"""
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM user_agents ORDER BY updated_at DESC"
            ).fetchall()
        return [_agent(row) for row in rows]

    def owned_by(self, owner_id: str) -> list[UserAgent]:
        """一個人建立的 agent，最近修改的排前面。"""
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM user_agents WHERE owner_id = ? "
                "ORDER BY updated_at DESC",
                (owner_id,),
            ).fetchall()
        return [_agent(row) for row in rows]

    def create(self, owner_id: str, values: dict[str, Any]) -> UserAgent:
        """建立 agent。values 的格式見 checked_values；資源是否能用由
        呼叫的人（workspace）先檢查。

        Raises:
            UserAgentError: 欄位不對，或已經建立太多 agent。
        """
        fields = checked_values(values, creating=True)
        now = self._clock()
        agent_id = uuid.uuid4().hex[:12]
        with self._connect() as db:
            count = db.execute(
                "SELECT COUNT(*) FROM user_agents WHERE owner_id = ?",
                (owner_id,),
            ).fetchone()[0]
            if count >= PER_USER_LIMIT:
                raise UserAgentError(
                    f"每個人最多建立 {PER_USER_LIMIT} 個 Agent"
                )
            columns = ["id", "owner_id", *fields, "created_at", "updated_at"]
            db.execute(
                f"INSERT INTO user_agents ({', '.join(columns)}) "
                f"VALUES ({', '.join('?' for _ in columns)})",
                (agent_id, owner_id, *fields.values(), now, now),
            )
        found = self.get(agent_id)
        assert found is not None
        return found

    def update(self, agent_id: str, values: dict[str, Any]) -> UserAgent:
        """修改有給的欄位。

        Raises:
            UserAgentError: 找不到 agent，或欄位不對。
        """
        self.require(agent_id)
        fields = checked_values(values, creating=False)
        if fields:
            sets = ", ".join(f"{column} = ?" for column in fields)
            with self._connect() as db:
                db.execute(
                    f"UPDATE user_agents SET {sets}, updated_at = ? "
                    "WHERE id = ?",
                    (*fields.values(), self._clock(), agent_id),
                )
        return self.require(agent_id)

    def delete(self, agent_id: str) -> UserAgent:
        """刪除 agent，回傳刪掉的那一個。

        Raises:
            UserAgentError: 找不到 agent。
        """
        agent = self.require(agent_id)
        with self._connect() as db:
            db.execute("DELETE FROM user_agents WHERE id = ?", (agent_id,))
        return agent

    def require(self, agent_id: str) -> UserAgent:
        """依識別碼找 agent。

        Raises:
            UserAgentError: 找不到（404）。
        """
        agent = self.get(agent_id)
        if agent is None:
            raise UserAgentError("找不到這個 Agent", 404)
        return agent

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        return accounts_lib._Transaction(db)


def checked_values(values: Any, *, creating: bool) -> dict[str, Any]:
    """檢查 API 送來的欄位，回傳要寫進資料表的值（以欄位名稱為鍵）。

    只檢查格式；資源能不能用由 workspace 依建立者的群組檢查。

    Raises:
        UserAgentError: 格式不對。
    """
    if not isinstance(values, dict):
        raise UserAgentError("內容必須是物件")
    fields: dict[str, Any] = {}
    if creating or "name" in values:
        fields["name"] = _checked_text(
            values.get("name"), "名稱", NAME_LIMIT, required=True
        )
    if "description" in values:
        fields["description"] = _checked_text(
            values["description"], "說明", DESCRIPTION_LIMIT
        )
    if "instructions" in values:
        fields["instructions"] = _checked_text(
            values["instructions"], "指示", INSTRUCTIONS_LIMIT, multiline=True
        )
    if "model" in values:
        model = values["model"]
        if model is not None and not isinstance(model, str):
            raise UserAgentError("model 必須是字串或 null")
        fields["model"] = (model or "").strip() or None
    for api_name, column in _LIST_FIELDS.items():
        if api_name not in values:
            continue
        items = _checked_list(values[api_name], api_name)
        if api_name == "starters":
            if len(items) > STARTERS_MAX:
                raise UserAgentError(f"開場建議最多 {STARTERS_MAX} 個")
            for item in items:
                if len(item) > STARTER_LIMIT:
                    raise UserAgentError(
                        f"每個開場建議最多 {STARTER_LIMIT} 個字"
                    )
        fields[column] = json.dumps(items, ensure_ascii=False)
    return fields


def _agent(row: sqlite3.Row) -> UserAgent:
    return UserAgent(
        id=row["id"],
        owner_id=row["owner_id"],
        name=row["name"],
        description=row["description"] or "",
        instructions=row["instructions"] or "",
        starters=_decode(row["starters"]),
        model=row["model"],
        toolsets=_decode(row["toolsets"]),
        knowledge_bases=_decode(row["knowledge_bases"]),
        skills=_decode(row["skills"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _decode(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    try:
        items = json.loads(value)
    except ValueError:
        return ()
    return tuple(item for item in items if isinstance(item, str))


def _checked_list(value: Any, what: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(
        isinstance(item, str) for item in value
    ):
        raise UserAgentError(f"{what} 必須是字串清單")
    if len(value) > _LIST_LIMIT:
        raise UserAgentError(f"{what} 最多 {_LIST_LIMIT} 項")
    # 去掉空白與重複，保留順序。
    return list(dict.fromkeys(item.strip() for item in value if item.strip()))


def _checked_text(
    value: Any,
    what: str,
    limit: int,
    *,
    required: bool = False,
    multiline: bool = False,
) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise UserAgentError(f"{what}必須是文字")
    value = value.strip()
    if not multiline:
        value = " ".join(value.split())
    if required and not value:
        raise UserAgentError(f"請輸入{what}")
    if len(value) > limit:
        raise UserAgentError(f"{what}最多 {limit} 個字")
    return value
