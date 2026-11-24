"""Ontology：在 agent 與資料之間的語意層（Python 版）。

專案有 ontology/ 資料夾（或 harness.yaml 有 ontology 區塊）時載入。定義檔
見 schema 模組，綁定見 bindings 模組，查詢與權限見 service 模組，給 agent
的五個工具見 tools 模組。

harness.yaml：
    ontology:
      path: ontology               定義檔資料夾（預設 ontology）
      maxClassification: internal  agent 沒設定時能讀的最高等級（預設不限）
      levels:                      自訂機密等級（由低到高）
        - {id: public, label: 公開}
        - {id: internal, label: 內部使用}

agent 的 frontmatter：
    ontology: true                       全部模組
    ontology: [contracts]                這些模組（含它們引用的模組）
    ontology:
      modules: [contracts]
      maxClassification: internal        這個 agent 能讀的最高等級

設定了 ontology 的 agent 會自動拿到 ontology toolset 的五個工具，指示後面
接上這些模組的型別、關係、動作與詞彙。其他 agent 也可以在 tools 列出
ontology，但不會有定義摘要（工具會說明怎麼查型別）。
"""

import pathlib
from typing import Any

from harness import knowledge as knowledge_lib
from harness.ontology.bindings import BindingContext
from harness.ontology.schema import REPORT_ACTION
from harness.ontology.schema import Schema
from harness.ontology.schema import SchemaError
from harness.ontology.schema import load_schema
from harness.ontology.service import ActionContext
from harness.ontology.service import ActionEvent
from harness.ontology.service import MetricContext
from harness.ontology.service import Ontology
from harness.ontology.service import Scope
from harness.ontology.service import View
from harness.ontology.service import Viewer
from harness.ontology.service import current_viewer
from harness.ontology.service import set_viewer
from harness.ontology.store import Record
from harness.ontology.tools import TOOL_NAMES
from harness.ontology.tools import TOOLSET
from harness.ontology.tools import make_tools

DEFAULT_DIR = "ontology"

__all__ = [
    "DEFAULT_DIR",
    "REPORT_ACTION",
    "TOOLSET",
    "TOOL_NAMES",
    "ActionContext",
    "ActionEvent",
    "BindingContext",
    "MetricContext",
    "Ontology",
    "Record",
    "Schema",
    "SchemaError",
    "Scope",
    "View",
    "Viewer",
    "agent_scope",
    "current_viewer",
    "from_config",
    "load_schema",
    "make_tools",
    "set_viewer",
]


def from_config(
    root: pathlib.Path,
    config: dict[str, Any],
    knowledge_bases: dict[str, knowledge_lib.KnowledgeBase],
) -> Ontology | None:
    """依 harness.yaml 載入專案的 ontology。

    Args:
        root: 專案根目錄。
        config: harness.yaml 的內容。
        knowledge_bases: 專案的知識庫。

    Returns:
        Ontology；沒有 ontology/ 資料夾也沒有設定，或設定為 false 時為
        None。

    Raises:
        SchemaError: 定義檔有錯，或 ontology 設定的寫法不對。
    """
    setting = config.get("ontology")
    if setting is False:
        return None
    if setting is None or setting is True:
        setting = {}
    if not isinstance(setting, dict):
        raise SchemaError(
            "harness.yaml 的 ontology 必須是 true、false 或對照表"
        )
    directory = root / str(setting.get("path") or DEFAULT_DIR)
    if not directory.is_dir():
        if config.get("ontology") is None:
            return None
        raise SchemaError(f"找不到 ontology 定義檔資料夾：{directory}")
    schema = load_schema(directory, setting.get("levels"), set(knowledge_bases))
    max_level = setting.get("maxClassification")
    if max_level is not None and str(max_level) not in schema.levels:
        raise SchemaError(
            f"ontology.maxClassification 的等級 {max_level} 不存在，"
            f"可用的有：{list(schema.levels)}"
        )
    return Ontology(
        root,
        schema,
        knowledge_bases,
        None if max_level is None else str(max_level),
    )


def agent_scope(
    agent_name: str, setting: Any, ontology: Ontology | None
) -> Scope | None:
    """解析 agent frontmatter 的 ontology 欄位。

    Returns:
        範圍；沒寫或寫 false 時為 None。

    Raises:
        ValueError: 寫法不對、專案沒有 ontology，或引用不存在的模組與等級。
    """
    if not setting:
        return None
    if ontology is None:
        raise ValueError(
            f"agent {agent_name} 設定了 ontology，但專案沒有 ontology/ 資料夾"
        )
    schema = ontology.schema
    max_level = ontology.default_max_level
    if setting is True:
        return Scope(None, max_level)
    if isinstance(setting, list):
        setting = {"modules": setting}
    if not isinstance(setting, dict):
        raise ValueError(
            f"agent {agent_name} 的 ontology 必須是 true、模組清單或 "
            "{modules: [...], maxClassification: ...}"
        )
    modules = setting.get("modules")
    if modules is not None:
        if not isinstance(modules, list) or not modules:
            raise ValueError(
                f"agent {agent_name} 的 ontology.modules 必須是清單"
            )
        modules = tuple(str(item) for item in modules)
        unknown = [m for m in modules if m not in schema.modules]
        if unknown:
            raise ValueError(
                f"agent {agent_name} 引用不存在的 ontology 模組：{unknown}，"
                f"可用的有：{list(schema.modules)}"
            )
    if setting.get("maxClassification") is not None:
        max_level = str(setting["maxClassification"])
        if max_level not in schema.levels:
            raise ValueError(
                f"agent {agent_name} 的 maxClassification {max_level} 不存在，"
                f"可用的有：{list(schema.levels)}"
            )
    return Scope(modules, max_level)
