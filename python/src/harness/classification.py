"""資料分級：機密的資料只交給核可的模型（例如地端模型）處理。

管理者在 harness.yaml 的 dataClassification 區塊定義等級（由低到高），
並指定：

- 每個模型可以處理的最高等級（沒列出的模型用 defaultClearance）；
- 資料來源的等級：知識庫（knowledgeBases.<id>.classification）、工具組
  （toolsets）、所有個人知識庫（personalKnowledge）；
- 對話碰到超過目前模型等級的資料時，自動改用哪個模型（routeTo）。

執行時用 Tracker 記錄「這段對話碰過的最高等級」：知識庫有結果、分級的
工具執行完時呼叫 note()。每次呼叫模型前（routed_model_fn），如果目前的
模型不能處理這個等級，就改用 routeTo（或其他可以處理的模型）；一個都
沒有時停下來，資料絕不送給不能處理它的模型。等級只升不降：資料已經在
對話紀錄裡，之後每一輪都要繼續用可以處理它的模型。

harness.yaml 範例：
    dataClassification:
      levels:                    # 由低到高
        - {id: public, name: 公開}
        - {id: internal, name: 內部}
        - {id: confidential, name: 機密}
      defaultClearance: internal   # 沒列在 models 的模型最高能處理到哪一級
      models:
        gemma-4-31b: confidential  # 地端模型可以處理機密資料
      routeTo: gemma-4-31b          # 超過時自動改用的模型
      personalKnowledge: internal   # 個人知識庫的等級
      toolsets:
        asset_platform: confidential
    knowledgeBases:
      hr:
        classification: confidential
"""

import contextvars
import dataclasses
from collections.abc import AsyncIterator
from collections.abc import Callable
from collections.abc import Sequence
from typing import Any

from harness import datatypes
from harness import llm
from harness import tools as tools_lib

CONFIG_KEY = "dataClassification"
DEFAULT_LEVELS = (
    ("public", "公開"),
    ("internal", "內部"),
    ("confidential", "機密"),
)
_FIELDS = {
    "levels",
    "defaultClearance",
    "models",
    "routeTo",
    "personalKnowledge",
    "toolsets",
}


class ClassificationError(Exception):
    """對話裡的資料等級沒有模型可以處理，停下這一輪。"""


@dataclasses.dataclass(frozen=True)
class Level:
    """一個資料等級。

    Attributes:
        id: 識別碼（寫在設定裡的值）。
        name: 顯示名稱，例如「機密」。
    """

    id: str
    name: str


@dataclasses.dataclass
class Policy:
    """資料分級的設定（harness.yaml 的 dataClassification 區塊）。

    Attributes:
        levels: 等級，由低到高。
        models: 每個模型可以處理的最高等級（等級識別碼）。
        default_clearance: 沒列在 models 的模型最高能處理的等級；None
            表示最高等級（不限制）。
        route_to: 資料超過目前模型的等級時改用的模型；None 表示從
            候選模型裡挑第一個可以處理的。
        personal_knowledge: 個人知識庫的等級；None 表示沒有分級。
        toolsets: 工具組的等級，以工具組名稱為鍵。
    """

    levels: tuple[Level, ...]
    models: dict[str, str] = dataclasses.field(default_factory=dict)
    default_clearance: str | None = None
    route_to: str | None = None
    personal_knowledge: str | None = None
    toolsets: dict[str, str] = dataclasses.field(default_factory=dict)

    def rank(self, level: str | None) -> int:
        """等級的高低（0 是最低）；None 或不認得的等級是 -1（沒有分級）。"""
        for index, item in enumerate(self.levels):
            if item.id == level:
                return index
        return -1

    def name(self, level: str | None) -> str:
        """等級的顯示名稱。"""
        for item in self.levels:
            if item.id == level:
                return item.name
        return level or ""

    def clearance(self, model: str) -> int:
        """模型可以處理的最高等級（rank）。"""
        level = self.models.get(model)
        if level is None:
            level = self.default_clearance
        if level is None:
            return len(self.levels) - 1
        return self.rank(level)

    def allows(self, model: str, rank: int) -> bool:
        """模型能不能處理這個等級（rank）的資料。"""
        return rank < 0 or self.clearance(model) >= rank

    def pick(self, rank: int, candidates: Sequence[str] = ()) -> str | None:
        """可以處理這個等級的模型：先看 routeTo，再依序看 candidates。"""
        for model in (self.route_to, *candidates):
            if model and self.allows(model, rank):
                return model
        return None

    def to_dict(self) -> dict[str, Any]:
        """寫回 harness.yaml 的格式。"""
        found: dict[str, Any] = {
            "levels": [
                {"id": item.id, "name": item.name} for item in self.levels
            ]
        }
        if self.default_clearance:
            found["defaultClearance"] = self.default_clearance
        if self.models:
            found["models"] = dict(self.models)
        if self.route_to:
            found["routeTo"] = self.route_to
        if self.personal_knowledge:
            found["personalKnowledge"] = self.personal_knowledge
        if self.toolsets:
            found["toolsets"] = dict(self.toolsets)
        return found


def load_policy(config: Any) -> Policy | None:
    """依 harness.yaml 的 dataClassification 區塊建立設定。

    Args:
        config: 區塊的內容；None 或 False 表示不使用資料分級。

    Raises:
        ValueError: 設定有誤（訊息會顯示給管理者）。
    """
    if config is None or config is False:
        return None
    if config is True:
        config = {}
    if not isinstance(config, dict):
        raise ValueError(f"{CONFIG_KEY} 必須是設定區塊")
    unknown = sorted(set(map(str, config)) - _FIELDS)
    if unknown:
        raise ValueError(
            f"{CONFIG_KEY} 有不認得的設定：{unknown}，"
            f"可用的有：{sorted(_FIELDS)}"
        )
    raw = config.get("levels")
    if raw is None:
        levels = tuple(Level(i, n) for i, n in DEFAULT_LEVELS)
    else:
        levels = tuple(_parse_level(item) for item in _as_list(raw, "levels"))
    ids = [item.id for item in levels]
    if len(levels) < 2:
        raise ValueError(f"{CONFIG_KEY}.levels 至少要有兩個等級")
    if len(set(ids)) != len(ids):
        raise ValueError(f"{CONFIG_KEY}.levels 的識別碼重複了")

    def level(value: Any, where: str) -> str | None:
        if value is None or value == "":
            return None
        value = str(value)
        if value not in ids:
            raise ValueError(
                f"{CONFIG_KEY}.{where} 的等級 {value} 不在 levels 裡"
                f"（可用的有：{'、'.join(ids)}）"
            )
        return value

    def mapping(key: str) -> dict[str, str]:
        value = config.get(key) or {}
        if not isinstance(value, dict):
            raise ValueError(f"{CONFIG_KEY}.{key} 必須是「名稱: 等級」")
        found = {}
        for name, item in value.items():
            checked = level(item, f"{key}.{name}")
            if checked is not None:
                found[str(name)] = checked
        return found

    route = config.get("routeTo")
    return Policy(
        levels=levels,
        models=mapping("models"),
        default_clearance=level(
            config.get("defaultClearance"), "defaultClearance"
        ),
        route_to=str(route) if route else None,
        personal_knowledge=level(
            config.get("personalKnowledge"), "personalKnowledge"
        ),
        toolsets=mapping("toolsets"),
    )


def check_level(policy: Policy | None, value: Any, where: str) -> str | None:
    """檢查資料來源設定的等級（例如知識庫的 classification）。

    Raises:
        ValueError: 沒有啟用資料分級卻設定了等級，或等級不存在。
    """
    if value is None or value == "":
        return None
    if policy is None:
        raise ValueError(
            f"{where} 設定了 classification，但 harness.yaml 沒有 "
            f"{CONFIG_KEY} 區塊"
        )
    value = str(value)
    if policy.rank(value) < 0:
        ids = "、".join(item.id for item in policy.levels)
        raise ValueError(
            f"{where} 的 classification {value} 不在等級裡（{ids}）"
        )
    return value


def _as_list(value: Any, key: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{CONFIG_KEY}.{key} 必須是清單")
    return value


def _parse_level(item: Any) -> Level:
    if isinstance(item, str):
        return Level(item, item)
    if isinstance(item, dict) and item.get("id"):
        return Level(str(item["id"]), str(item.get("name") or item["id"]))
    raise ValueError(f"{CONFIG_KEY}.levels 的每一項必須有 id（和 name）")


@dataclasses.dataclass
class Tracker:
    """一段對話碰過的資料等級，以及實際使用的模型。

    Attributes:
        policy: 資料分級的設定。
        level: 碰過的最高等級（識別碼）；None 表示沒有碰過分級的資料。
        sources: 碰過的分級資料來自哪裡（例如「知識庫「人資規章」」）。
        model: 最近一次實際呼叫的模型（可能是改用的模型）。
        routed: 最近一次呼叫有沒有改用模型。
    """

    policy: Policy
    level: str | None = None
    sources: list[str] = dataclasses.field(default_factory=list)
    model: str | None = None
    routed: bool = False

    @property
    def rank(self) -> int:
        return self.policy.rank(self.level)

    def note(self, level: str | None, source: str = "") -> None:
        """記下碰到這個等級的資料（比目前低的不影響）。"""
        if level is None or self.policy.rank(level) < 0:
            return
        if self.policy.rank(level) > self.rank:
            self.level = level
        if source and source not in self.sources:
            self.sources.append(source)


_TRACKER: contextvars.ContextVar[Tracker | None] = contextvars.ContextVar(
    "harness_classification", default=None
)


def current() -> Tracker | None:
    """這一輪的 Tracker；沒有啟用資料分級時為 None。"""
    return _TRACKER.get()


def set_tracker(tracker: Tracker | None) -> None:
    """設定這一輪的 Tracker（同一個 asyncio task 與它開出的 task 共用）。

    Tracker 是同一個物件，subagent 與平行執行的工具記下的等級都會反映
    回來。
    """
    _TRACKER.set(tracker)


def note(level: str | None, source: str = "") -> None:
    """記下這一輪碰到某個等級的資料；沒有 Tracker 時不做事。"""
    tracker = _TRACKER.get()
    if tracker is not None:
        tracker.note(level, source)


def classified_tool(
    item: tools_lib.Tool, level: str, source: str
) -> tools_lib.Tool:
    """包一層：工具執行成功後記下它的資料等級。"""
    original = item.func

    async def run(*args: Any, **kwargs: Any) -> Any:
        result = original(*args, **kwargs)
        if hasattr(result, "__await__"):
            result = await result
        note(level, source)
        return result

    return dataclasses.replace(item, func=run)


def routed_model_fn(
    model_fn: llm.ModelFn,
    tracker: Tracker,
    candidates: Callable[[], Sequence[str]] = tuple,
    on_route: Callable[[str, str], None] | None = None,
    subject: str = "這段對話",
) -> llm.ModelFn:
    """包一層模型函式：呼叫前檢查目前的模型能不能處理碰過的資料。

    Args:
        model_fn: 原本的模型函式。
        tracker: 這段對話的 Tracker。
        candidates: 改用模型時依序考慮的模型（routeTo 優先）。
        on_route: 改用模型時呼叫（原本的模型, 改用的模型），例如通知
            瀏覽器。
        subject: 錯誤訊息的主詞，例如「這段對話」「這次評測」。

    Returns:
        新的模型函式；沒有模型可以處理時丟出 ClassificationError。
    """

    def call(
        model: str,
        messages: list[datatypes.Message],
        tools: list[dict[str, Any]],
        params: dict[str, Any],
    ) -> AsyncIterator[Any]:
        policy = tracker.policy
        rank = tracker.rank
        chosen = model
        if not policy.allows(model, rank):
            chosen = policy.pick(rank, list(candidates()))
            if chosen is None:
                raise ClassificationError(
                    f"{subject}用到「{policy.name(tracker.level)}」等級的資料"
                    f"（{'、'.join(tracker.sources) or '分級資料'}），但沒有"
                    "可以處理這個等級的模型，已經停止，資料沒有送出。請管理者"
                    "在管理平台的「資料分級」指定可以處理的模型（例如地端模型）。"
                )
        tracker.routed = chosen != model
        tracker.model = chosen
        if tracker.routed and on_route is not None:
            on_route(model, chosen)
        return model_fn(chosen, messages, tools, params)

    return call
