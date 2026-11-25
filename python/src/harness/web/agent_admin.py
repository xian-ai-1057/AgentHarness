"""管理平台的「Agent」頁：新增與修改公司的 agent（專案的 agents/*.md）。

成員自建的 agent 在 user_agents（只有建立的人能用）；這裡是管理者提供給
大家的 agent，存成 Markdown 檔，開頭的 YAML 是設定、內文是指示（見
harness.project）。網頁上能改的欄位：

    description   一句話說明（新對話頁與 Agent 頁顯示）
    instructions  指示（檔案的內文）
    tools         工具組或工具名稱；None 表示沒寫（可以用專案所有的工具）
    skills        skill 名稱；None 表示沒寫（可以用專案所有的公司 skill）
    knowledge     預設搜尋的知識庫；原本寫了 labels、topK 的會保留

其他設定（model、subagents、handoffs、ontology、modelParams…）原樣保留，
只能改檔案。存檔會重寫開頭的設定，裡面的註解會消失。模型在管理平台的
「模型」頁設定，掛載的 MCP 伺服器在「MCP 工具」頁決定給哪些 agent。
"""

import pathlib
import re
from typing import Any

import yaml

from harness import project as project_lib

NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,39}$")
DESCRIPTION_LIMIT = 300
INSTRUCTIONS_LIMIT = 100_000
LIST_LIMIT = 200
# 網頁上可以改的設定；其他的原樣保留。
EDITABLE = ("description", "tools", "skills", "knowledge")


class AgentAdminError(Exception):
    """內容不對或找不到，訊息會直接顯示給使用者。

    Attributes:
        status: HTTP 狀態碼。
    """

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def agent_files(root: pathlib.Path) -> dict[str, pathlib.Path]:
    """agents/ 裡每個 agent 的檔案，以 agent 名稱為鍵。"""
    found: dict[str, pathlib.Path] = {}
    for path in sorted((root / "agents").glob("*.md")):
        try:
            meta, _ = read(path)
        except AgentAdminError:
            continue
        found[str(meta.get("name") or path.stem)] = path
    return found


def read(path: pathlib.Path) -> tuple[dict[str, Any], str]:
    """讀出 agent 檔的設定與內文。

    Raises:
        AgentAdminError: 讀不到或格式不對。
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise AgentAdminError("找不到這個 agent", 404) from error
    try:
        meta, body = project_lib.parse_frontmatter(text)
    except yaml.YAMLError as error:
        raise AgentAdminError(f"{path.name} 的開頭設定格式不對") from error
    if not isinstance(meta, dict):
        raise AgentAdminError(f"{path.name} 的開頭設定格式不對")
    return meta, body


def render(meta: dict[str, Any], body: str) -> str:
    """組成 agent 檔的內容。"""
    head = yaml.safe_dump(
        meta, allow_unicode=True, sort_keys=False, width=1000
    ).strip()
    return f"---\n{head}\n---\n{body.strip()}\n"


def knowledge_bases(value: Any, all_bases: list[str]) -> list[str]:
    """agent 設定的 knowledge 換成知識庫識別碼清單（給表單勾選）。"""
    if not value:
        return []
    fallback = (
        [project_lib.DEFAULT_KNOWLEDGE_ID]
        if project_lib.DEFAULT_KNOWLEDGE_ID in all_bases
        else list(all_bases)
    )
    if value is True:
        return fallback
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, dict):
        bases = value.get("bases")
        return fallback if bases is None else [str(item) for item in bases]
    return []


def detail(name: str, path: pathlib.Path, all_bases: list[str]) -> dict:
    """一個 agent 檔的內容（編輯頁用）。"""
    meta, body = read(path)
    knowledge = meta.get("knowledge")
    others = sorted(key for key in meta if key not in (*EDITABLE, "name"))
    return {
        "name": name,
        "file": f"agents/{path.name}",
        "description": str(meta.get("description") or ""),
        "instructions": body,
        "tools": _names(meta["tools"]) if "tools" in meta else None,
        "skills": _names(meta["skills"]) if "skills" in meta else None,
        "knowledge": knowledge_bases(knowledge, all_bases),
        "knowledgeFilter": bool(
            isinstance(knowledge, dict)
            and (knowledge.get("labels") is not None or knowledge.get("topK"))
        ),
        "otherSettings": others,
    }


def _names(value: Any) -> list[str]:
    return [str(item) for item in value or []]


def apply_changes(meta: dict[str, Any], body: str, changes: Any) -> tuple:
    """把表單的改動套到設定與內文上，回傳 (新的設定, 新的內文)。

    Raises:
        AgentAdminError: 欄位格式不對。
    """
    if not isinstance(changes, dict):
        raise AgentAdminError("內容必須是物件")
    meta = dict(meta)
    if "description" in changes:
        description = changes["description"]
        if not isinstance(description, str):
            raise AgentAdminError("說明必須是文字")
        description = " ".join(description.split())
        if len(description) > DESCRIPTION_LIMIT:
            raise AgentAdminError(f"說明最多 {DESCRIPTION_LIMIT} 個字")
        if description:
            meta["description"] = description
        else:
            meta.pop("description", None)
    if "instructions" in changes:
        instructions = changes["instructions"]
        if not isinstance(instructions, str) or not instructions.strip():
            raise AgentAdminError("請填寫指示")
        if len(instructions) > INSTRUCTIONS_LIMIT:
            raise AgentAdminError(f"指示最多 {INSTRUCTIONS_LIMIT} 個字")
        body = instructions.strip()
    for key, what in (("tools", "工具"), ("skills", "skills")):
        if key not in changes:
            continue
        value = changes[key]
        if value is None:
            meta.pop(key, None)
        else:
            meta[key] = _checked_list(value, what)
    if "knowledge" in changes:
        bases = _checked_list(changes["knowledge"] or [], "知識庫")
        current = meta.get("knowledge")
        if not bases:
            meta.pop("knowledge", None)
        elif isinstance(current, dict):
            # 保留原本的標籤過濾與 topK，只換知識庫。
            meta["knowledge"] = {**current, "bases": bases}
        else:
            meta["knowledge"] = bases
    return meta, body


def _checked_list(value: Any, what: str) -> list[str]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) for item in value
    ):
        raise AgentAdminError(f"{what}必須是字串清單")
    if len(value) > LIST_LIMIT:
        raise AgentAdminError(f"{what}最多 {LIST_LIMIT} 項")
    return list(dict.fromkeys(item.strip() for item in value if item.strip()))


def check_name(name: Any) -> str:
    if not isinstance(name, str) or not NAME.match(name.strip()):
        raise AgentAdminError(
            "名稱用英文字母開頭，只能有英文、數字、底線與連字號，最多 40 "
            "個字元，例如 hr-helper"
        )
    return name.strip()
