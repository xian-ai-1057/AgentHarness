"""管理平台 → 資料分級：讀寫 harness.yaml 的 dataClassification 區塊，以及
每個知識庫的 classification。

規則與執行時的行為見 harness.classification。這裡只負責把網頁送來的設定
檢查過、寫回 harness.yaml：先組出新的設定，用 project.load_knowledge_bases
試載入一次（等級不存在之類的錯誤在這裡就擋下），才真的寫檔。
"""

from typing import Any

from harness import classification as classification_lib
from harness import project as project_lib
from harness.web import config as config_lib
from harness.web import knowledge_admin

_ID_LIMIT = 40
_NAME_LIMIT = 20
_LEVEL_LIMIT = 8


class ClassificationAdminError(Exception):
    """設定不對，訊息會直接顯示給管理者。"""


def describe(project: project_lib.Project) -> dict[str, Any]:
    """管理平台顯示用的設定：目前的等級、模型對應與資料來源的等級。"""
    policy = project.classification
    return {
        "enabled": policy is not None,
        "levels": [
            {"id": item.id, "name": item.name}
            for item in (
                policy.levels
                if policy is not None
                else (
                    classification_lib.Level(i, n)
                    for i, n in classification_lib.DEFAULT_LEVELS
                )
            )
        ],
        "defaultClearance": policy.default_clearance if policy else None,
        "models": dict(policy.models) if policy else {},
        "routeTo": policy.route_to if policy else None,
        "personalKnowledge": policy.personal_knowledge if policy else None,
        "toolsets": dict(policy.toolsets) if policy else {},
        "knowledgeBases": {
            base.id: base.classification
            for base in project.knowledge_bases.values()
            if base.classification
        },
    }


def save(project: project_lib.Project, body: Any) -> None:
    """把管理平台送來的設定寫回 harness.yaml。

    body 的格式和 describe 回傳的相同；enabled 為 false 時拿掉整個
    dataClassification 區塊，也拿掉每個知識庫的 classification。

    Raises:
        ClassificationAdminError: 設定不對或檔案不能自動修改。
    """
    if not isinstance(body, dict):
        raise ClassificationAdminError("設定必須是物件")
    root = project.root
    enabled = body.get("enabled") is True
    block: dict[str, Any] | None = None
    if enabled:
        block = _checked_block(body)
    try:
        policy = classification_lib.load_policy(block)
    except ValueError as error:
        raise ClassificationAdminError(str(error)) from error
    levels = body.get("knowledgeBases") if enabled else {}
    if levels is None:
        levels = {}
    if not isinstance(levels, dict):
        raise ClassificationAdminError("knowledgeBases 必須是「識別碼: 等級」")
    for base_id in levels:
        if base_id not in project.knowledge_bases:
            raise ClassificationAdminError(f"找不到知識庫：{base_id}")

    default_spec, specs = knowledge_admin.config_blocks(root)

    def apply(spec: dict[str, Any], base_id: str) -> dict[str, Any]:
        spec = dict(spec)
        level = levels.get(base_id)
        if level:
            spec["classification"] = str(level)
        else:
            spec.pop("classification", None)
        return spec

    builtin = project_lib.DEFAULT_KNOWLEDGE_ID
    new_default = None
    if builtin in project.knowledge_bases:
        new_default = apply(default_spec, builtin)
    new_specs = {
        base_id: apply(spec, base_id) for base_id, spec in specs.items()
    }
    config = config_lib.read_config(root)
    if block is None:
        config.pop(classification_lib.CONFIG_KEY, None)
    else:
        config[classification_lib.CONFIG_KEY] = block
    if new_default is not None:
        config["knowledge"] = new_default
    if new_specs:
        config[project_lib.KNOWLEDGE_BASES_KEY] = new_specs
    try:
        project_lib.load_knowledge_bases(root, config)
    except ValueError as error:
        raise ClassificationAdminError(str(error)) from error

    try:
        # 先拿掉知識庫上的等級（關閉時），再改分級區塊；開啟時相反，
        # 每一步寫完的檔案都載入得了。
        if block is None:
            _write_bases(root, new_default, new_specs, default_spec)
            config_lib.save_block(root, classification_lib.CONFIG_KEY, None)
        else:
            config_lib.save_block(root, classification_lib.CONFIG_KEY, block)
            _write_bases(root, new_default, new_specs, default_spec)
    except (ValueError, knowledge_admin.KnowledgeAdminError) as error:
        raise ClassificationAdminError(str(error)) from error
    project.classification = policy


def _write_bases(root, new_default, new_specs, old_default) -> None:
    changed_default = new_default is not None and new_default != old_default
    knowledge_admin.write_config(
        root, new_default if changed_default else None, new_specs
    )


def _checked_block(body: dict[str, Any]) -> dict[str, Any]:
    """網頁送來的設定 → harness.yaml 的 dataClassification 區塊。"""
    raw = body.get("levels")
    if not isinstance(raw, list):
        raise ClassificationAdminError("請設定資料等級")
    if not 2 <= len(raw) <= _LEVEL_LIMIT:
        raise ClassificationAdminError(f"資料等級要有 2 到 {_LEVEL_LIMIT} 個")
    levels = []
    for item in raw:
        if not isinstance(item, dict):
            raise ClassificationAdminError("每個等級要有識別碼與名稱")
        level_id = str(item.get("id") or "").strip()
        name = str(item.get("name") or "").strip()
        if not level_id or not project_lib.KNOWLEDGE_ID_PATTERN.match(level_id):
            raise ClassificationAdminError(
                "等級識別碼只能用小寫英文、數字、- 與 _，例如 confidential"
            )
        if len(level_id) > _ID_LIMIT:
            raise ClassificationAdminError(f"等級識別碼最多 {_ID_LIMIT} 字")
        if not name or len(name) > _NAME_LIMIT:
            raise ClassificationAdminError(
                f"請輸入等級名稱（最多 {_NAME_LIMIT} 字）"
            )
        levels.append({"id": level_id, "name": name})
    block: dict[str, Any] = {"levels": levels}
    for key in ("defaultClearance", "routeTo", "personalKnowledge"):
        value = body.get(key)
        if value is not None and not isinstance(value, str):
            raise ClassificationAdminError(f"{key} 必須是文字")
        if value and value.strip():
            block[key] = value.strip()
    for key in ("models", "toolsets"):
        value = body.get(key) or {}
        if not isinstance(value, dict):
            raise ClassificationAdminError(f"{key} 必須是「名稱: 等級」")
        cleaned = {
            str(name): str(level)
            for name, level in value.items()
            if str(name).strip() and level
        }
        if cleaned:
            block[key] = cleaned
    return block
