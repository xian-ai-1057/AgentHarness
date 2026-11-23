"""語意層：agent 透過它查物件、走關係、搜文件、查指標、執行動作。

權限、機密等級、生效期間與出處都跟著物件走：

- **群組**：型別與動作可以設定 groups，只有這些群組（識別碼或名稱）的
  成員看得到、能執行。管理者與本機模式不受限制。網頁版每一輪對話開始
  時用 set_viewer 設定這一輪是誰。
- **機密等級**：型別與屬性都有等級。agent 可以設定 maxClassification，
  超過的型別看不到、超過的屬性值會遮起來（標示原因），避免機密資料送
  到不該收的模型。
- **時間**：查詢預設取今天有效的版本，也可以指定日期（as_of）。
- **出處**：每個物件都附上它來自哪個綁定、哪個檔案的第幾筆或哪份文件。

寫入只有一條路：run_action。每次執行都要使用者核准、填寫理由，並寫進
只能新增的動作紀錄。
"""

import asyncio
import contextvars
import dataclasses
import datetime
import inspect
import json
import pathlib
import re
import secrets
from collections.abc import Callable
from typing import Any

from harness import datatypes
from harness import knowledge as knowledge_lib
from harness import tools as tools_lib
from harness.ontology import bindings as bindings_lib
from harness.ontology import schema as schema_lib
from harness.ontology import store as store_lib

DB_FILE = pathlib.Path(".harness") / "ontology.db"
REDACTED = "（{level}，這個助手不能讀取）"
_LIST_LIMIT = 20
_PATH_LIMIT = 4
_CHAIN_LIMIT = 50
_VALUE_LIMIT = 300
_SUMMARY_PROPS = 3
_MIN_REASON = 2


@dataclasses.dataclass(frozen=True)
class Viewer:
    """這一輪是誰在查詢。

    Attributes:
        user: 帳號名稱（記在動作紀錄）。
        groups: 所屬群組的識別碼與名稱。
        admin: 管理者（或本機模式）：不受群組限制。
        knowledge_bases: 可以搜尋的知識庫識別碼；None 表示不限制。
        labels: 知識庫裡可以搜尋的標籤；None 表示不限制。
        actor: 呼叫端自己的使用者物件（網頁版寫稽核紀錄用）。
    """

    user: str = ""
    groups: frozenset[str] = frozenset()
    admin: bool = True
    knowledge_bases: frozenset[str] | None = None
    labels: frozenset[str] | None = None
    actor: Any = None


LOCAL_VIEWER = Viewer()
_VIEWER: contextvars.ContextVar[Viewer | None] = contextvars.ContextVar(
    "harness_ontology_viewer", default=None
)


def set_viewer(viewer: Viewer | None) -> None:
    """設定目前這個 asyncio task（與它開出的 task）是誰在查詢。

    網頁版每一輪對話是自己的 task，在開始時設定；沒有設定時當成本機
    使用者（不受群組限制）。
    """
    _VIEWER.set(viewer)


def current_viewer() -> Viewer:
    """目前的查詢者；沒有設定時是 LOCAL_VIEWER。"""
    return _VIEWER.get() or LOCAL_VIEWER


@dataclasses.dataclass(frozen=True)
class Scope:
    """一個 agent 能用的範圍（agent 的 ontology 設定）。

    Attributes:
        modules: 能用的模組（含它們引用的模組）；None 表示全部。
        max_level: 能讀的最高機密等級；None 表示不限。
    """

    modules: tuple[str, ...] | None = None
    max_level: str | None = None


@dataclasses.dataclass(frozen=True)
class ActionEvent:
    """執行過的一個動作（傳給 Ontology.on_action，例如寫稽核紀錄）。"""

    seq: int
    action: str
    label: str
    target: str
    params: dict[str, Any]
    reason: str
    status: str
    result: str
    viewer: Viewer
    agent: str
    session: str


class View:
    """套用了權限與分級的讀取介面，給處理函式用。

    處理函式（指標、動作、綁定）拿到的資料和 agent 看到的一樣：看不到的
    型別不會出現，超過等級的屬性已經遮起來。
    """

    def __init__(
        self, ontology: "Ontology", viewer: Viewer, scope: Scope, as_of: str
    ) -> None:
        self.ontology = ontology
        self.viewer = viewer
        self.scope = scope
        self.as_of = as_of

    @property
    def schema(self) -> schema_lib.Schema:
        return self.ontology.schema

    def objects(self, type_: str) -> list[store_lib.Record]:
        """這個型別在 as_of 那天有效的物件。"""
        if not self.ontology.type_visible(type_, self.viewer, self.scope):
            return []
        found = self.ontology.store.objects([type_], self.as_of)
        return [self.ontology.redact(item, self.scope) for item in found]

    def get(self, type_: str, identifier: str) -> store_lib.Record | None:
        """一個物件；找不到或看不到時為 None。"""
        if not self.ontology.type_visible(type_, self.viewer, self.scope):
            return None
        found = self.ontology.store.objects([type_], self.as_of, [identifier])
        return self.ontology.redact(found[-1], self.scope) if found else None

    def related(
        self, type_: str, identifier: str, relation: str
    ) -> list[store_lib.Record]:
        """經過一個關係（可以寫 inverse 或 ~關係）連到的物件。"""
        step = self.schema.step(relation)
        if step is None:
            raise tools_lib.ToolError(f"沒有 {relation} 這個關係")
        relation_def, reverse = step
        links = self.ontology.store.links_of(
            type_, [identifier], [relation_def.name], reverse, self.as_of
        )
        other = relation_def.source if reverse else relation_def.target
        ids = [link.from_id if reverse else link.to_id for link in links]
        return [
            item for item in self.objects_by_ids(other, ids) if item is not None
        ]

    def objects_by_ids(
        self, type_: str, ids: list[str]
    ) -> list[store_lib.Record | None]:
        if not self.ontology.type_visible(type_, self.viewer, self.scope):
            return []
        found = {
            item.id: item
            for item in self.ontology.store.objects([type_], self.as_of, ids)
        }
        return [
            self.ontology.redact(found[i], self.scope) if i in found else None
            for i in ids
        ]


@dataclasses.dataclass
class MetricContext:
    """傳給指標處理函式的環境。"""

    view: View
    metric: schema_lib.Metric
    run: datatypes.RunContext | None


@dataclasses.dataclass
class ActionContext:
    """傳給動作處理函式的環境。

    Attributes:
        view: 套用權限的讀取介面。
        action: 動作的定義。
        target: 指定的物件；動作沒有 target 時為 None。
        reason: 使用者核准時看到的理由。
        run: 這次執行的 RunContext（工作資料夾在 run.workdir）。
        viewer: 誰核准執行。
    """

    view: View
    action: schema_lib.Action
    target: store_lib.Record | None
    reason: str
    run: datatypes.RunContext | None
    viewer: Viewer
    _ontology: "Ontology" = dataclasses.field(repr=False, default=None)  # type: ignore[assignment]

    def record(
        self,
        type_: str,
        identifier: str,
        properties: dict[str, Any],
        links: dict[str, list[str] | str] | None = None,
        label: str = "",
    ) -> store_lib.Record:
        """在 ontology 裡記下一個物件（例如送出的審查申請）。

        記在「action:動作名稱」底下，重新載入綁定時不會被清掉。
        """
        return self._ontology._record_from_action(
            self, type_, identifier, properties, links or {}, label
        )


class Ontology:
    """一個專案的 ontology：定義、資料與五個查詢方法。

    Attributes:
        root: 專案根目錄。
        schema: 定義。
        store: 資料。
        knowledge_bases: 專案的知識庫（search_documents 與知識庫綁定用）。
        default_max_level: agent 沒有設定 maxClassification 時的上限。
        scopes: 每個 agent 的範圍，以 agent 名稱為鍵；沒有的用預設。
        on_action: 每次執行動作後呼叫（例如網頁版寫稽核紀錄）。
    """

    def __init__(
        self,
        root: pathlib.Path,
        schema: schema_lib.Schema,
        knowledge_bases: dict[str, knowledge_lib.KnowledgeBase] | None = None,
        default_max_level: str | None = None,
        db_path: pathlib.Path | None = None,
    ) -> None:
        self.root = root
        self.schema = schema
        self.store = store_lib.Store(db_path or root / DB_FILE)
        self.knowledge_bases = knowledge_bases or {}
        self.default_max_level = default_max_level
        self.scopes: dict[str, Scope] = {}
        self.on_action: Callable[[ActionEvent], None] | None = None
        self._lock: asyncio.Lock | None = None
        self._lock_loop: Any = None

    # ── 同步綁定 ──

    async def sync(self, force: bool = False) -> list[store_lib.BindingState]:
        """有變動的綁定重新載入；回傳每個綁定目前的狀態。"""
        loop = asyncio.get_running_loop()
        if self._lock is None or self._lock_loop is not loop:
            self._lock = asyncio.Lock()
            self._lock_loop = loop
        async with self._lock:
            states = []
            for binding in self.schema.bindings:
                states.append(await self._sync_one(binding, force))
            self.store.drop_bindings({b.name for b in self.schema.bindings})
            return states

    async def _sync_one(
        self, binding: schema_lib.Binding, force: bool
    ) -> store_lib.BindingState:
        chunks: list[Any] = []
        extra = repr(self.schema.types.get(binding.type or ""))
        if binding.source == "knowledge":
            base = self.knowledge_bases.get(binding.base or "")
            if base is None:
                return self.store.replace_binding(
                    binding.name, "", [], [], [f"找不到知識庫 {binding.base}"]
                )
            chunks = await base.knowledge.chunks()
            extra += "".join(
                f"{c.source}\0{c.location}\0{len(c.text)}\n" for c in chunks
            )
        signature = bindings_lib.signature(
            self.root, self.schema.directory, binding, extra
        )
        state = self.store.binding_state(binding.name)
        if state is not None and state.signature == signature and not force:
            return state
        try:
            if binding.source == "file":
                loaded = bindings_lib.load_file(self.root, binding, self.schema)
            elif binding.source == "knowledge":
                loaded = bindings_lib.load_chunks(binding, self.schema, chunks)
            else:
                loaded = await asyncio.to_thread(
                    bindings_lib.load_python, self.root, binding, self.schema
                )
        # 綁定是專案自己的資料與程式：讀不了時記下原因，其他綁定照常。
        except Exception as error:  # noqa: BLE001
            message = f"載入失敗：{type(error).__name__}: {error}"
            return self.store.replace_binding(
                binding.name, "", [], [], [message]
            )
        return self.store.replace_binding(
            binding.name,
            signature,
            loaded.records,
            loaded.links,
            loaded.warnings,
        )

    # ── 權限與分級 ──

    def scope_for(self, agent_name: str) -> Scope:
        """這個 agent 的範圍；沒有設定時是全部模組、預設等級上限。"""
        found = self.scopes.get(agent_name)
        if found is None:
            return Scope(None, self.default_max_level)
        return found

    def type_visible(
        self, type_name: str, viewer: Viewer, scope: Scope
    ) -> bool:
        """這個型別這位查詢者、這個 agent 看不看得到。"""
        type_ = self.schema.types.get(type_name)
        if type_ is None:
            return False
        if type_name not in self.schema.module_types(scope.modules):
            return False
        if not self._groups_allow(type_.groups, viewer):
            return False
        return self._level_ok(type_.classification, scope)

    def redact(
        self, record: store_lib.Record, scope: Scope
    ) -> store_lib.Record:
        """把超過等級的屬性值換成說明。"""
        if scope.max_level is None:
            return record
        type_ = self.schema.types[record.type]
        props = {}
        for key, value in record.props.items():
            level = self.schema.property_level(type_, key)
            if self._level_ok(level.id, scope):
                props[key] = value
            else:
                props[key] = REDACTED.format(level=level.label)
        return dataclasses.replace(record, props=props)

    def _level_ok(self, level: str, scope: Scope) -> bool:
        if scope.max_level is None:
            return True
        return (
            self.schema.level(level).rank
            <= self.schema.level(scope.max_level).rank
        )

    @staticmethod
    def _groups_allow(groups: tuple[str, ...] | None, viewer: Viewer) -> bool:
        if groups is None or viewer.admin:
            return True
        return bool(set(groups) & viewer.groups)

    def _visible_types(self, viewer: Viewer, scope: Scope) -> list[str]:
        return [
            name
            for name in self.schema.types
            if self.type_visible(name, viewer, scope)
        ]

    # ── 給 agent 看的定義摘要 ──

    def describe(self, scope: Scope | None = None) -> str:
        """模組的型別、關係、動作、指標與詞彙，放進 agent 的指示。"""
        scope = scope or Scope(None, self.default_max_level)
        modules = self.schema.expand(
            scope.modules or tuple(self.schema.modules)
        )
        types = [
            t
            for t in self.schema.types.values()
            if t.module in modules and self._level_ok(t.classification, scope)
        ]
        names = {t.name for t in types}
        lines = [
            "## 業務物件（ontology）",
            "",
            "查業務資料一律用 ontology 工具：find_entity 找物件、get_related "
            "走關係、search_documents 搜這些物件對應的文件段落、get_metric "
            "查治理過的指標；要寫入或送出時用 run_action（使用者核准、一定要"
            "填理由）。不要自己從檔案或文件裡推算這些資料；工具回傳的出處"
            "與資料日期要一併告訴使用者。",
        ]
        for name in sorted(modules):
            module = self.schema.modules[name]
            lines += ["", f"### 模組 {module.label}（{module.name}）"]
            if module.description:
                lines.append(module.description)
            for type_ in [t for t in types if t.module == name]:
                props = "、".join(
                    f"{p.name}（{p.label}）" for p in type_.properties.values()
                )
                head = f"- 型別 {type_.name}（{type_.label}）"
                if type_.key:
                    head += f"，識別碼是{type_.key}"
                if type_.description:
                    head += f"：{type_.description}"
                lines.append(head)
                if props:
                    lines.append(f"  屬性：{props}")
            for relation in self.schema.relations.values():
                if relation.module != name:
                    continue
                if relation.source not in names or relation.target not in names:
                    continue
                inverse = relation.inverse or f"~{relation.name}"
                lines.append(
                    f"- 關係 {relation.name}：{relation.source} "
                    f"{relation.label} {relation.target}（反向：{inverse}）"
                )
            for action in self.schema.actions.values():
                if action.module == name:
                    lines.append(f"- 動作 {action.name}：{action.label}")
            for metric in self.schema.metrics.values():
                if metric.module == name:
                    lines.append(f"- 指標 {metric.name}：{metric.label}")
        terms = [t for t in self.schema.glossary if t.module in modules]
        if terms:
            lines += ["", "### 詞彙表"]
            for term in terms:
                alias = (
                    f"（又稱 {'、'.join(term.aliases)}）"
                    if term.aliases
                    else ""
                )
                lines.append(f"- {term.term}{alias}：{term.definition}")
        return "\n".join(lines)

    # ── 五個查詢方法 ──

    async def find_entity(
        self,
        context: datatypes.RunContext | None,
        entity_type: str | None = None,
        query: str = "",
        where: dict[str, Any] | None = None,
        as_of: str | None = None,
        limit: int = 10,
    ) -> str:
        """找物件；只找到一個時顯示完整內容。"""
        await self.sync()
        viewer, scope, day = self._env(context, as_of)
        visible = self._visible_types(viewer, scope)
        if entity_type:
            name = self._type_name(entity_type)
            if name is None or name not in visible:
                return self._unknown_type(entity_type, visible)
            types = [name]
        else:
            types = visible
        if not types:
            return "這個助手沒有可以查詢的物件型別。"
        if not query.strip() and not where and not entity_type:
            return self._overview(types)
        records = self.store.objects(types, day)
        matched = _match(records, self._expand_query(query), where or {})
        if not matched:
            return (
                f"沒有找到符合的物件（{day} 有效的資料）。"
                "可以換個關鍵字，或不指定型別再找一次。"
            )
        if len(matched) == 1:
            return self._detail(
                self.redact(matched[0], scope), viewer, scope, day
            )
        shown = matched[: max(1, min(limit, 50))]
        lines = [f"找到 {len(matched)} 筆（{day} 有效的資料）："]
        for record in shown:
            lines.append(self._summary(self.redact(record, scope)))
        if len(matched) > len(shown):
            lines.append(
                f"…還有 {len(matched) - len(shown)} 筆，請把條件縮小。"
            )
        lines.append("要看完整內容，請用 find_entity 指定型別與識別碼。")
        return "\n".join(lines)

    async def get_related(
        self,
        context: datatypes.RunContext | None,
        entity_type: str,
        entity_id: str,
        path: list[str] | None = None,
        as_of: str | None = None,
    ) -> str:
        """從一個物件沿著關係走。沒有 path 時列出所有直接的關係。"""
        await self.sync()
        viewer, scope, day = self._env(context, as_of)
        visible = self._visible_types(viewer, scope)
        name = self._type_name(entity_type)
        if name is None or name not in visible:
            return self._unknown_type(entity_type, visible)
        start = self.store.objects([name], day, [entity_id])
        if not start:
            return (
                f"找不到 {self.schema.types[name].label} {entity_id}（{day}）。"
            )
        head = self._name(start[-1])
        if not path:
            return self._neighbors(start[-1], head, viewer, scope, day)
        if len(path) > _PATH_LIMIT:
            raise tools_lib.ToolError(f"path 最多 {_PATH_LIMIT} 步")
        chains: list[list[store_lib.Record]] = [[start[-1]]]
        hidden = 0
        for step_name in path:
            step = self.schema.step(step_name)
            if step is None:
                raise tools_lib.ToolError(
                    f"沒有 {step_name} 這個關係，可用的有："
                    + "、".join(self._relation_names())
                )
            relation, reverse = step
            next_chains = []
            for chain in chains:
                last = chain[-1]
                expected = relation.target if reverse else relation.source
                if last.type != expected:
                    raise tools_lib.ToolError(
                        f"{step_name} 要從 {expected} 出發，"
                        f"這一步是 {last.type}"
                    )
                other = relation.source if reverse else relation.target
                links = self.store.links_of(
                    last.type, [last.id], [relation.name], reverse, day
                )
                ids = [x.from_id if reverse else x.to_id for x in links]
                if not self.type_visible(other, viewer, scope):
                    hidden += len(ids)
                    continue
                found = {r.id: r for r in self.store.objects([other], day, ids)}
                for identifier in ids:
                    target = found.get(identifier) or store_lib.Record(
                        other,
                        identifier,
                        label=identifier,
                        source={"missing": True},
                    )
                    next_chains.append([*chain, target])
            chains = next_chains[:_CHAIN_LIMIT]
        steps = " → ".join(path)
        if not chains:
            note = f"（另有 {hidden} 筆因權限或分級沒有顯示）" if hidden else ""
            return f"{head} 沿著 {steps} 沒有找到任何物件{note}。"
        lines = [f"{head} 沿著 {steps}（{day} 有效的資料）："]
        for chain in chains:
            parts = [self._name(item) for item in chain[1:]]
            last = self.redact(chain[-1], scope)
            lines.append(f"- {' → '.join(parts)}{self._brief(last)}")
        if hidden:
            lines.append(f"另有 {hidden} 筆因權限或分級沒有顯示。")
        return "\n".join(lines)

    async def search_documents(
        self,
        context: datatypes.RunContext | None,
        query: str,
        entity_type: str | None = None,
        entity_id: str | None = None,
        path: list[str] | None = None,
        top_k: int = 5,
    ) -> str:
        """搜尋文件段落；指定物件時只搜尋那個物件（與關係）對應的段落。"""
        await self.sync()
        viewer, scope, day = self._env(context, None)
        modules = self.schema.expand(
            scope.modules or tuple(self.schema.modules)
        )
        base_ids = [
            base
            for name in sorted(modules)
            for base in self.schema.modules[name].documents
        ]
        bases = [
            self.knowledge_bases[b]
            for b in dict.fromkeys(base_ids)
            if b in self.knowledge_bases
            and (viewer.knowledge_bases is None or b in viewer.knowledge_bases)
        ]
        refs: set[tuple[str, str, str]] | None = None
        if entity_type and entity_id:
            records = self._documents_scope(
                entity_type, entity_id, path, viewer, scope, day
            )
            refs = {
                (d.get("base", ""), d.get("source", ""), d.get("location", ""))
                for r in records
                for d in r.docs
            }
            if not refs:
                return (
                    "這個物件（與它的關係）沒有對應的文件段落。"
                    "可以不指定物件再搜尋一次。"
                )
            ref_bases = {base for base, _, _ in refs}
            bases = [b for b in bases if b.id in ref_bases] or [
                self.knowledge_bases[b]
                for b in ref_bases
                if b in self.knowledge_bases
                and (
                    viewer.knowledge_bases is None
                    or b in viewer.knowledge_bases
                )
            ]
        if not bases:
            return "這個助手沒有可以搜尋的文件（模組沒有設定 documents）。"
        where = None
        if refs is not None:
            chosen = refs

            def where(base: knowledge_lib.KnowledgeBase, chunk: Any) -> bool:
                return (base.id, chunk.source, chunk.location) in chosen or (
                    base.id,
                    chunk.source,
                    "",
                ) in chosen

        labels = None if viewer.labels is None else sorted(viewer.labels)
        hits = await knowledge_lib.search_bases(
            bases,
            query,
            top_k=max(1, min(top_k, 20)),
            labels=labels,
            context=context,
            where=where,
        )
        for hit, base in _hit_bases(hits, bases):
            hit.base = base.name or base.id
        if context is None:
            return knowledge_lib.format_hits(hits)
        start = knowledge_lib._next_number(context, hits)
        return knowledge_lib.format_hits(hits, start=start)

    async def get_metric(
        self,
        context: datatypes.RunContext | None,
        metric: str,
        params: dict[str, Any] | None = None,
        as_of: str | None = None,
    ) -> str:
        """計算一個治理過的指標。"""
        await self.sync()
        viewer, scope, day = self._env(context, as_of)
        definition = self.schema.metrics.get(metric)
        modules = self.schema.expand(
            scope.modules or tuple(self.schema.modules)
        )
        if definition is None or definition.module not in modules:
            available = [
                f"{m.name}（{m.label}）"
                for m in self.schema.metrics.values()
                if m.module in modules
            ]
            return f"沒有 {metric} 這個指標。可用的有：" + (
                "、".join(available) or "（沒有）"
            )
        values = _check_params(definition.params, params or {})
        heading = f"{definition.label}（{day}）"
        if definition.count is not None:
            if not self.type_visible(definition.count, viewer, scope):
                return f"這個助手不能查詢「{definition.label}」用到的資料。"
            records = self.store.objects([definition.count], day)
            records = _match(_latest(records), [], definition.where)
            unit = definition.unit
            if definition.group_by is None:
                body = f"{len(records)}{unit}"
            else:
                counts: dict[str, int] = {}
                for record in records:
                    value = record.props.get(definition.group_by)
                    keys = value if isinstance(value, list) else [value]
                    for key in keys:
                        label = "（未填）" if key in (None, "") else str(key)
                        counts[label] = counts.get(label, 0) + 1
                ordered = sorted(counts.items(), key=lambda x: -x[1])
                body = "、".join(f"{k} {v}{unit}" for k, v in ordered)
                body += f"；合計 {len(records)}{unit}"
        else:
            view = View(self, viewer, scope, day)
            func = bindings_lib.resolve_handler(
                definition.run or "", self.schema.directory
            )
            value = await _call(
                func, MetricContext(view, definition, context), values
            )
            body = _format_value(value)
        lines = [f"{heading}：{body}"]
        if definition.description:
            lines.append(f"定義：{definition.description}")
        return "\n".join(lines)

    def check_action(
        self,
        context: datatypes.RunContext | None,
        action: str,
        params: dict[str, Any] | None,
        reason: str,
        target_id: str | None = None,
    ) -> str | None:
        """核准前先檢查：動作存在、可以執行、參數與理由都對。

        Returns:
            None 表示沒問題，否則是給模型的錯誤說明。
        """
        try:
            self._prepare(context, action, params, reason, target_id)
        except tools_lib.ToolError as error:
            return str(error)
        return None

    def describe_call(self, arguments: dict[str, Any]) -> dict[str, Any] | None:
        """run_action 的參數換成給人看的內容（核准卡片用）。"""
        action = self.schema.actions.get(str(arguments.get("action") or ""))
        if action is None:
            return None
        params = arguments.get("params") or {}
        labeled = []
        if isinstance(params, dict):
            for key, value in params.items():
                found = action.params.get(key)
                labeled.append(
                    {
                        "name": key,
                        "label": (found.description if found else "") or key,
                        "value": value,
                    }
                )
        target = None
        if action.target and arguments.get("target_id"):
            type_ = self.schema.types[action.target]
            target = f"{type_.label} {arguments['target_id']}"
        return {
            "name": action.name,
            "label": action.label,
            "effects": action.effects,
            "target": target,
            "reason": str(arguments.get("reason") or ""),
            "params": labeled,
        }

    async def run_action(
        self,
        context: datatypes.RunContext | None,
        action: str,
        params: dict[str, Any] | None,
        reason: str,
        target_id: str | None = None,
    ) -> str:
        """執行動作（核准之後），寫進動作紀錄。"""
        await self.sync()
        viewer = current_viewer()
        agent = context.agent_name if context else ""
        session = context.session_id if context else ""
        try:
            definition, values, target, scope, day = self._prepare(
                context, action, params, reason, target_id
            )
        except tools_lib.ToolError as error:
            self._log(
                viewer,
                agent,
                session,
                action,
                target_id or "",
                params or {},
                reason,
                "rejected",
                str(error),
                action,
            )
            raise
        view = View(self, viewer, scope, day)
        ctx = ActionContext(
            view, definition, target, reason.strip(), context, viewer, self
        )
        try:
            if definition.name == schema_lib.REPORT_ACTION:
                seq = self.store.add_candidate(
                    actor=viewer.user,
                    module=str(values.get("module") or ""),
                    concept=str(values["concept"]),
                    description=str(values.get("description") or ""),
                    example=str(values.get("example") or ""),
                    reason=reason.strip(),
                )
                result: Any = (
                    f"已記進候選清單（第 {seq} 筆），等定義檔的負責人審查。"
                )
            elif definition.create is not None:
                identifier = str(values.pop("id", "") or "") or _new_id(
                    definition.name
                )
                links = {}
                if target is not None:
                    rel = self._relation_between(definition.create, target.type)
                    if rel is not None:
                        links[rel] = [target.id]
                record = ctx.record(
                    definition.create, identifier, values, links
                )
                result = f"已建立 {self._name(record)}。"
            else:
                func = bindings_lib.resolve_handler(
                    definition.run or "", self.schema.directory
                )
                result = await _call(func, ctx, values)
        except Exception as error:
            message = (
                str(error)
                if isinstance(error, tools_lib.ToolError)
                else f"{type(error).__name__}: {error}"
            )
            self._log(
                viewer,
                agent,
                session,
                definition.name,
                target.id if target else "",
                values,
                reason,
                "failed",
                message,
                definition.label,
            )
            raise
        text = _format_value(result)
        seq = self._log(
            viewer,
            agent,
            session,
            definition.name,
            target.id if target else "",
            values,
            reason,
            "done",
            text,
            definition.label,
        )
        return f"{text}\n（動作紀錄第 {seq} 筆）"

    # ── 內部 ──

    def _prepare(
        self,
        context: datatypes.RunContext | None,
        action: str,
        params: dict[str, Any] | None,
        reason: str,
        target_id: str | None,
    ) -> tuple[
        schema_lib.Action,
        dict[str, Any],
        store_lib.Record | None,
        Scope,
        str,
    ]:
        viewer, scope, day = self._env(context, None)
        definition = self.schema.actions.get(action)
        modules = self.schema.expand(
            scope.modules or tuple(self.schema.modules)
        )
        allowed = [
            a
            for a in self.schema.actions.values()
            if (not a.module or a.module in modules)
            and self._groups_allow(a.groups, viewer)
        ]
        if definition is None or definition not in allowed:
            names = "、".join(f"{a.name}（{a.label}）" for a in allowed)
            raise tools_lib.ToolError(
                f"沒有 {action} 這個動作，或這個助手不能執行。可用的有：{names}"
            )
        if len(reason.strip()) < _MIN_REASON:
            raise tools_lib.ToolError(
                "一定要填 reason：為什麼要執行這個動作（使用者核准時會看到）"
            )
        target = None
        if definition.target is not None:
            if not target_id:
                type_ = self.schema.types[definition.target]
                raise tools_lib.ToolError(
                    f"這個動作要指定一個{type_.label}：請給 target_id"
                )
            if not self.type_visible(definition.target, viewer, scope):
                raise tools_lib.ToolError("這個助手不能讀取這個動作的對象")
            found = self.store.objects([definition.target], day, [target_id])
            if not found:
                type_ = self.schema.types[definition.target]
                raise tools_lib.ToolError(
                    f"找不到{type_.label} {target_id}，請先用 find_entity 確認"
                )
            target = self.redact(found[-1], scope)
        if definition.create is not None and not self._groups_allow(
            self.schema.types[definition.create].groups, viewer
        ):
            raise tools_lib.ToolError("你沒有權限建立這種物件")
        values = _check_params(definition.params, params or {})
        return definition, values, target, scope, day

    def _record_from_action(
        self,
        ctx: ActionContext,
        type_name: str,
        identifier: str,
        properties: dict[str, Any],
        links: dict[str, list[str] | str],
        label: str,
    ) -> store_lib.Record:
        type_ = self.schema.types.get(type_name)
        if type_ is None:
            raise tools_lib.ToolError(f"沒有 {type_name} 這個型別")
        unknown = [k for k in properties if k not in type_.properties]
        if unknown:
            raise tools_lib.ToolError(f"{type_.label} 沒有這些屬性：{unknown}")
        binding = f"action:{ctx.action.name}"
        today = _today()
        record = store_lib.Record(
            type=type_name,
            id=identifier,
            label=label or bindings_lib.display(type_, identifier, properties),
            props=dict(properties),
            valid_from="",
            source={
                "binding": binding,
                "action": ctx.action.name,
                "actor": ctx.viewer.user,
                "reason": ctx.reason,
                "date": today,
            },
            binding=binding,
        )
        warnings: list[str] = []
        made: list[store_lib.Link] = []
        for rel, targets in links.items():
            made += bindings_lib._links(
                self.schema,
                record,
                rel,
                bindings_lib.split_ids(targets),
                warnings,
            )
        if warnings:
            raise tools_lib.ToolError("；".join(warnings))
        self.store.upsert(record, made)
        return record

    def _relation_between(self, source: str, target: str) -> str | None:
        for relation in self.schema.relations.values():
            if relation.source == source and relation.target == target:
                return relation.name
            if relation.source == target and relation.target == source:
                return f"~{relation.name}"
        return None

    def _log(
        self,
        viewer: Viewer,
        agent: str,
        session: str,
        action: str,
        target: str,
        params: dict[str, Any],
        reason: str,
        status: str,
        result: str,
        label: str,
    ) -> int:
        seq = self.store.log_action(
            actor=viewer.user,
            agent=agent,
            session=session,
            action=action,
            target=target,
            params=params,
            reason=reason.strip(),
            status=status,
            result=result,
        )
        if self.on_action is not None:
            self.on_action(
                ActionEvent(
                    seq,
                    action,
                    label,
                    target,
                    params,
                    reason.strip(),
                    status,
                    result,
                    viewer,
                    agent,
                    session,
                )
            )
        return seq

    def _env(
        self, context: datatypes.RunContext | None, as_of: str | None
    ) -> tuple[Viewer, Scope, str]:
        scope = self.scope_for(context.agent_name if context else "")
        day = _today()
        if as_of:
            day = bindings_lib.to_date(as_of)
            if not day:
                raise tools_lib.ToolError("as_of 要寫成 YYYY-MM-DD")
        return current_viewer(), scope, day

    def _type_name(self, value: str) -> str | None:
        if value in self.schema.types:
            return value
        for type_ in self.schema.types.values():
            if value == type_.label:
                return type_.name
        return None

    def _unknown_type(self, value: str, visible: list[str]) -> str:
        names = "、".join(
            f"{n}（{self.schema.types[n].label}）" for n in visible
        )
        names = names or "（沒有）"
        return f"沒有 {value} 這個型別，或這個助手不能查詢。可用的有：{names}"

    def _relation_names(self) -> list[str]:
        names = []
        for relation in self.schema.relations.values():
            names.append(relation.name)
            names.append(relation.inverse or f"~{relation.name}")
        return names

    def _overview(self, types: list[str]) -> str:
        lines = ["可以查詢的物件型別："]
        for name in types:
            type_ = self.schema.types[name]
            count = self.store.count(name)
            lines.append(f"- {name}（{type_.label}）：{count} 筆")
        lines.append("用 entity_type 與 query 找物件。")
        return "\n".join(lines)

    def _expand_query(self, query: str) -> list[str]:
        words = [w for w in re.split(r"\s+", query.strip()) if w]
        expanded = []
        for word in words:
            options = [word]
            for term in self.schema.glossary:
                if word in term.aliases:
                    options.append(term.term)
            expanded.append("|".join(options))
        return expanded

    def _name(self, record: store_lib.Record) -> str:
        type_ = self.schema.types.get(record.type)
        label = type_.label if type_ else record.type
        name = (
            record.label if record.label and record.label != record.id else ""
        )
        missing = (
            "（沒有這個物件的資料）" if record.source.get("missing") else ""
        )
        return f"{label} {record.id}{(' ' + name) if name else ''}{missing}"

    def _summary(self, record: store_lib.Record) -> str:
        return f"- {self._name(record)}{self._brief(record)}"

    def _brief(self, record: store_lib.Record) -> str:
        type_ = self.schema.types.get(record.type)
        if type_ is None or record.source.get("missing"):
            return ""
        parts = []
        for prop in type_.properties.values():
            value = record.props.get(prop.name)
            if value in (None, "", [], {}):
                continue
            text = _short(value)
            if len(text) > 40 or text == record.label:
                continue
            parts.append(f"{prop.label}：{text}")
            if len(parts) >= _SUMMARY_PROPS:
                break
        return f"（{'；'.join(parts)}）" if parts else ""

    def _detail(
        self,
        record: store_lib.Record,
        viewer: Viewer,
        scope: Scope,
        day: str,
    ) -> str:
        type_ = self.schema.types[record.type]
        level = self.schema.level(type_.classification)
        lines = [f"【{type_.label}】{record.id} {record.label}".rstrip()]
        meta = [f"分級：{level.label}", f"有效期間：{_period(record)}"]
        meta.append(f"出處：{self._source_text(record)}")
        lines.append("｜".join(meta))
        for prop in type_.properties.values():
            value = record.props.get(prop.name)
            if value in (None, "", [], {}):
                continue
            lines.append(
                f"- {prop.label}（{prop.name}）：{_short(value, _VALUE_LIMIT)}"
            )
        counts = self._relation_counts(record, viewer, scope, day)
        if counts:
            lines.append(
                "關係："
                + "、".join(f"{label} {n} 筆" for label, n in counts)
                + "（用 get_related 查看）"
            )
        if record.docs:
            lines.append(
                f"對應的文件段落 {len(record.docs)} 段"
                "（用 search_documents 指定這個物件搜尋）"
            )
        return "\n".join(lines)

    def _source_text(self, record: store_lib.Record) -> str:
        source = record.source
        if source.get("action"):
            return (
                f"動作「{source['action']}」由 {source.get('actor') or '本機'} "
                f"於 {source.get('date')} 建立"
            )
        state = self.store.binding_state(source.get("binding", ""))
        loaded = ""
        if state is not None:
            when = datetime.datetime.fromtimestamp(state.loaded_at)
            loaded = f"，{when:%Y-%m-%d %H:%M} 載入"
        where = source.get("file") or source.get("run") or ""
        row = f" 第 {source['row']} 筆" if source.get("row") else ""
        base = f"知識庫 {source['base']} / " if source.get("base") else ""
        return f"{base}{where}{row}{loaded}".strip() or "（未記錄）"

    def _relation_counts(
        self,
        record: store_lib.Record,
        viewer: Viewer,
        scope: Scope,
        day: str,
    ) -> list[tuple[str, int]]:
        counts = []
        for reverse in (False, True):
            links = self.store.links_of(
                record.type, [record.id], None, reverse, day
            )
            grouped: dict[str, int] = {}
            for link in links:
                relation = self.schema.relations.get(link.rel)
                if relation is None:
                    continue
                other = relation.source if reverse else relation.target
                if not self.type_visible(other, viewer, scope):
                    continue
                key = self._step_label(relation, reverse)
                grouped[key] = grouped.get(key, 0) + 1
            counts += list(grouped.items())
        return counts

    def _step_label(self, relation: schema_lib.Relation, reverse: bool) -> str:
        if not reverse:
            return f"{relation.label}（{relation.name}）"
        name = relation.inverse or f"~{relation.name}"
        label = relation.inverse_label or f"被{relation.label}"
        return f"{label}（{name}）"

    def _neighbors(
        self,
        record: store_lib.Record,
        head: str,
        viewer: Viewer,
        scope: Scope,
        day: str,
    ) -> str:
        lines = [f"{head} 的關係（{day} 有效的資料）："]
        hidden = 0
        shown = 0
        for reverse in (False, True):
            links = self.store.links_of(
                record.type, [record.id], None, reverse, day
            )
            grouped: dict[str, list[store_lib.Link]] = {}
            for link in links:
                grouped.setdefault(link.rel, []).append(link)
            for rel, items in grouped.items():
                relation = self.schema.relations.get(rel)
                if relation is None:
                    continue
                other = relation.source if reverse else relation.target
                if not self.type_visible(other, viewer, scope):
                    hidden += len(items)
                    continue
                ids = [x.from_id if reverse else x.to_id for x in items]
                found = {r.id: r for r in self.store.objects([other], day, ids)}
                lines.append(f"{self._step_label(relation, reverse)}：")
                for identifier in ids[:_LIST_LIMIT]:
                    target = found.get(identifier)
                    if target is None:
                        target = store_lib.Record(
                            other,
                            identifier,
                            label=identifier,
                            source={"missing": True},
                        )
                    else:
                        target = self.redact(target, scope)
                    lines.append(self._summary(target))
                    shown += 1
                if len(ids) > _LIST_LIMIT:
                    lines.append(f"…還有 {len(ids) - _LIST_LIMIT} 筆")
        if shown == 0:
            lines.append("（沒有任何關係）")
        if hidden:
            lines.append(f"另有 {hidden} 筆因權限或分級沒有顯示。")
        return "\n".join(lines)

    def _documents_scope(
        self,
        entity_type: str,
        entity_id: str,
        path: list[str] | None,
        viewer: Viewer,
        scope: Scope,
        day: str,
    ) -> list[store_lib.Record]:
        name = self._type_name(entity_type)
        if name is None or not self.type_visible(name, viewer, scope):
            raise tools_lib.ToolError(
                f"沒有 {entity_type} 這個型別，或不能查詢"
            )
        start = self.store.objects([name], day, [entity_id])
        if not start:
            raise tools_lib.ToolError(f"找不到 {entity_type} {entity_id}")
        collected = list(start)
        frontier = list(start)
        steps = path or [None]
        for step_name in steps:
            nxt: list[store_lib.Record] = []
            for record in frontier:
                if step_name is None:
                    pairs = [(False, None), (True, None)]
                else:
                    step = self.schema.step(step_name)
                    if step is None:
                        raise tools_lib.ToolError(f"沒有 {step_name} 這個關係")
                    pairs = [(step[1], step[0].name)]
                for reverse, rel in pairs:
                    links = self.store.links_of(
                        record.type,
                        [record.id],
                        None if rel is None else [rel],
                        reverse,
                        day,
                    )
                    by_type: dict[str, list[str]] = {}
                    for link in links:
                        other = link.from_type if reverse else link.to_type
                        other_id = link.from_id if reverse else link.to_id
                        by_type.setdefault(other, []).append(other_id)
                    for other, ids in by_type.items():
                        if self.type_visible(other, viewer, scope):
                            nxt += self.store.objects([other], day, ids)
            collected += nxt
            frontier = nxt
        return collected


def _today() -> str:
    return datetime.date.today().isoformat()


def _period(record: store_lib.Record) -> str:
    if not record.valid_from and not record.valid_to:
        return "不限"
    if not record.valid_to:
        return f"{record.valid_from} 起"
    if not record.valid_from:
        return f"到 {record.valid_to} 前"
    return f"{record.valid_from} 起到 {record.valid_to} 前"


def _short(value: Any, limit: int = 80) -> str:
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, (dict, list)):
        if isinstance(value, list) and all(
            not isinstance(item, (dict, list)) for item in value
        ):
            text = "、".join(str(item) for item in value)
        else:
            text = json.dumps(value, ensure_ascii=False, default=str)
    else:
        text = str(value)
    text = text.replace("\n", " ")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _latest(records: list[store_lib.Record]) -> list[store_lib.Record]:
    """同一個物件有好幾個版本同時有效時，只留最新的。"""
    found: dict[tuple[str, str], store_lib.Record] = {}
    for record in records:
        found[(record.type, record.id)] = record
    return list(found.values())


def _match(
    records: list[store_lib.Record],
    words: list[str],
    where: dict[str, Any],
) -> list[store_lib.Record]:
    """關鍵字（每個字都要出現，| 分開的是同義詞）加上屬性條件。"""
    records = _latest(records)
    exact = []
    others = []
    for record in records:
        if not _where_ok(record, where):
            continue
        if not words:
            others.append(record)
            continue
        if len(words) == 1 and words[0].split("|")[0] in (
            record.id,
            record.label,
        ):
            exact.append(record)
            continue
        haystack = " ".join(
            [
                record.id,
                record.label,
                *(_short(v, 10_000) for v in record.props.values()),
            ]
        ).lower()
        if all(
            any(option.lower() in haystack for option in word.split("|"))
            for word in words
        ):
            others.append(record)
    return exact or others


def _where_ok(record: store_lib.Record, where: dict[str, Any]) -> bool:
    for key, expected in where.items():
        value = record.props.get(key)
        values = value if isinstance(value, list) else [value]
        wanted = expected if isinstance(expected, list) else [expected]
        if not any(str(v) == str(w) for v in values for w in wanted):
            return False
    return True


def _check_params(
    defined: dict[str, schema_lib.Param], given: dict[str, Any]
) -> dict[str, Any]:
    """依定義檢查參數，回傳整理過的值。"""
    if not isinstance(given, dict):
        raise tools_lib.ToolError("params 必須是 {參數: 值} 的物件")
    unknown = [key for key in given if key not in defined]
    if unknown:
        names = "、".join(defined) or "（沒有參數）"
        raise tools_lib.ToolError(f"沒有這些參數：{unknown}。可用的有：{names}")
    values: dict[str, Any] = {}
    problems = []
    for name, param in defined.items():
        value = given.get(name)
        if value is None or value == "":
            if param.required:
                problems.append(f"{name} 必填")
            continue
        checked, problem = _check_value(param, value)
        if problem:
            problems.append(f"{name} {problem}")
        else:
            values[name] = checked
    if problems:
        raise tools_lib.ToolError("參數不對：" + "；".join(problems))
    return values


def _check_value(param: schema_lib.Param, value: Any) -> tuple[Any, str]:
    kind = param.type
    if kind == "integer":
        if isinstance(value, bool):
            return value, "必須是整數"
        if isinstance(value, str) and re.fullmatch(r"-?\d+", value.strip()):
            value = int(value)
        if not isinstance(value, int):
            return value, "必須是整數"
    elif kind == "number":
        if isinstance(value, str):
            try:
                value = float(value)
            except ValueError:
                return value, "必須是數字"
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return value, "必須是數字"
    elif kind == "boolean":
        if not isinstance(value, bool):
            return value, "必須是 true 或 false"
    elif kind == "date":
        day = bindings_lib.to_date(value)
        if not day:
            return value, "必須是日期（YYYY-MM-DD）"
        value = day
    elif kind == "array":
        if not isinstance(value, list):
            return value, "必須是清單"
    elif kind == "object":
        if not isinstance(value, dict):
            return value, "必須是物件"
    elif not isinstance(value, str):
        value = str(value)
    if param.enum and value not in param.enum:
        return value, f"必須是 {list(param.enum)} 其中之一"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if param.minimum is not None and value < param.minimum:
            return value, f"不能小於 {param.minimum}"
        if param.maximum is not None and value > param.maximum:
            return value, f"不能大於 {param.maximum}"
    if param.pattern and isinstance(value, str):
        if not re.fullmatch(param.pattern, value):
            return value, f"格式不對（{param.pattern}）"
    return value, ""


async def _call(func: Any, ctx: Any, values: dict[str, Any]) -> Any:
    if inspect.iscoroutinefunction(func):
        return await func(ctx, **values)
    # 處理函式可能讀檔、算分，放到執行緒裡跑。ContextVar 要帶過去。
    run = contextvars.copy_context().run
    return await asyncio.to_thread(run, func, ctx, **values)


def _format_value(value: Any) -> str:
    if value is None:
        return "完成"
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def _new_id(action: str) -> str:
    stamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    return f"{action}-{stamp}-{secrets.token_hex(2)}"


def _hit_bases(
    hits: list[knowledge_lib.Hit], bases: list[knowledge_lib.KnowledgeBase]
) -> list[tuple[knowledge_lib.Hit, knowledge_lib.KnowledgeBase]]:
    """每筆結果來自哪個知識庫（只搜一個時 search_bases 不會標名稱）。"""
    if len(bases) != 1:
        return []
    return [(hit, bases[0]) for hit in hits]
