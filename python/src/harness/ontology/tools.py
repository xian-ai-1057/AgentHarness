"""ontology toolset：給 agent 的五個語意工具。

    find_entity       查物件
    get_related       走關係
    search_documents  搜物件對應的文件段落
    get_metric        查治理過的指標
    run_action        執行動作（唯一的寫入路徑；每次都要核准、填理由）

五個工具都是同一組物件，用 RunContext.agent_name 找出這個 agent 的範圍
（能用的模組、機密等級上限），用 current_viewer() 套用群組權限。
"""

from typing import Any

from harness import datatypes
from harness import tools as tools_lib
from harness.ontology import service as service_lib

TOOLSET = "ontology"
TOOL_NAMES = (
    "find_entity",
    "get_related",
    "search_documents",
    "get_metric",
    "run_action",
)


def make_tools(ontology: service_lib.Ontology) -> list[tools_lib.Tool]:
    """建立綁定這個 ontology 的五個工具。

    Args:
        ontology: 專案的 ontology。

    Returns:
        依 TOOL_NAMES 順序的工具。
    """

    async def find_entity(
        context: datatypes.RunContext,
        entity_type: str | None = None,
        query: str = "",
        where: dict[str, Any] | None = None,
        as_of: str | None = None,
        limit: int = 10,
    ) -> str:
        """查業務物件（例如某個提案、某位人員、某條內規）。

        回答業務資料的問題前先用這個工具找到物件，不要從文件或記憶裡
        推算。只找到一筆時會顯示完整內容（屬性、分級、有效期間、出處、
        有哪些關係）；好幾筆時列出摘要，再指定識別碼查看。什麼都不給時
        列出可以查詢的型別。

        Args:
            entity_type: 型別識別碼或名稱，例如 proposal 或「提案」；不確定
                時省略，會在所有型別裡找。
            query: 識別碼或關鍵字，空白分開的每個字都要出現。
            where: 屬性條件，例如 {"risk_level": "高"}；值可以是清單（任一）。
            as_of: 查哪一天有效的資料（YYYY-MM-DD），預設今天。
            limit: 最多列出幾筆。
        """
        return await ontology.find_entity(
            context, entity_type, query, where, as_of, limit
        )

    async def get_related(
        context: datatypes.RunContext,
        entity_type: str,
        entity_id: str,
        path: list[str] | None = None,
        as_of: str | None = None,
    ) -> str:
        """從一個物件沿著關係找到其他物件。

        沒給 path 時列出它所有直接的關係；給 path 時一步一步走，例如
        ["uses_model", "provided_by"] 是「這個提案用的模型 → 模型的
        供應商」。反方向可以寫關係的 inverse 名稱，或在前面加 ~。

        Args:
            entity_type: 起點的型別識別碼或名稱。
            entity_id: 起點的識別碼。
            path: 要走的關係（最多 4 步）。
            as_of: 查哪一天有效的資料（YYYY-MM-DD），預設今天。
        """
        return await ontology.get_related(
            context, entity_type, entity_id, path, as_of
        )

    async def search_documents(
        context: datatypes.RunContext,
        query: str,
        entity_type: str | None = None,
        entity_id: str | None = None,
        path: list[str] | None = None,
        top_k: int = 5,
    ) -> str:
        """搜尋文件段落（條文、規章），取得原文與出處。

        指定物件時只搜尋那個物件與它直接關係的物件對應的段落，例如
        某個關卡要求的內規條文；給 path 時改成只沿著這些關係找。回答時
        在句子後面寫結果的編號註明出處，例如「應經核准 [3]」。同一輪的
        編號會接續，直接寫原本的編號。找不到時直接說沒有，不要編造。

        Args:
            query: 要找的內容，寫成完整的問題或關鍵字。
            entity_type: 限定範圍的物件型別。
            entity_id: 限定範圍的物件識別碼。
            path: 從那個物件走哪些關係去找段落，例如 ["requires"]。
            top_k: 最多回傳幾筆。
        """
        return await ontology.search_documents(
            context, query, entity_type, entity_id, path, top_k
        )

    async def get_metric(
        context: datatypes.RunContext,
        metric: str,
        params: dict[str, Any] | None = None,
        as_of: str | None = None,
    ) -> str:
        """查一個治理過的指標（件數、比例、清單），定義大家都一樣。

        要數量或統計時用這個工具，不要自己用 find_entity 的結果去數。

        Args:
            metric: 指標識別碼。
            params: 指標的參數。
            as_of: 以哪一天的資料計算（YYYY-MM-DD），預設今天。
        """
        return await ontology.get_metric(context, metric, params, as_of)

    async def run_action(
        context: datatypes.RunContext,
        action: str,
        reason: str,
        params: dict[str, Any] | None = None,
        target_id: str | None = None,
    ) -> str:
        """執行一個定義好的動作（建立草稿、送出申請…），這是唯一的寫入方式。

        每一次都會請使用者核准，核准卡片上會顯示動作、對象、參數與理由。
        動作清單與參數見系統指示裡的 ontology 說明；使用者提到的概念在
        定義裡找不到時，可以用 report_missing_concept 回報。

        Args:
            action: 動作識別碼。
            reason: 為什麼要執行（寫給核准的人看，一定要填）。
            params: 動作的參數。
            target_id: 動作的對象（動作有指定對象型別時必填）。
        """
        return await ontology.run_action(
            context, action, params, reason, target_id
        )

    async def precheck(
        arguments: dict[str, Any], context: datatypes.RunContext
    ) -> str | None:
        await ontology.sync()
        params = arguments.get("params")
        return ontology.check_action(
            context,
            str(arguments.get("action") or ""),
            params
            if isinstance(params, dict)
            else ({} if params is None else params),
            str(arguments.get("reason") or ""),
            arguments.get("target_id"),
        )

    made = [
        tools_lib.tool(find_entity),
        tools_lib.tool(get_related),
        tools_lib.tool(search_documents),
        tools_lib.tool(get_metric),
        tools_lib.tool(run_action, needs_approval=True),
    ]
    made[-1].force_approval = True
    made[-1].precheck = precheck
    _describe_actions(ontology, made[-1])
    return made


def _describe_actions(
    ontology: service_lib.Ontology, item: tools_lib.Tool
) -> None:
    """把動作清單附在 run_action 的說明裡（給沒有 schema 摘要的 agent）。"""
    lines = []
    for action in ontology.schema.actions.values():
        params = "、".join(
            f"{p.name}{'（必填）' if p.required else ''}"
            for p in action.params.values()
        )
        target = ""
        if action.target:
            target = f"；對象：{ontology.schema.types[action.target].label}"
        lines.append(
            f"- {action.name}：{action.label}{target}"
            + (f"；參數：{params}" if params else "")
        )
    item.description += "\n\n可以執行的動作：\n" + "\n".join(lines)
