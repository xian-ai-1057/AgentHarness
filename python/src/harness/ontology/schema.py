"""Ontology 的定義檔（schema 即程式碼）。

專案的 ontology/ 資料夾裡一個 YAML 檔是一個模組，定義業務物件的型別、
彼此的關係、可以執行的動作、治理過的指標、詞彙表，以及資料從哪裡來
（綁定）。定義檔跟著 Git 管理，改動要經過審查才生效。

    module: contracts            模組識別碼（英數字與底線）
    label: 合約管理
    description: …
    imports: [core]              引用其他模組的型別（關係可以連過去）
    documents: [policies]        search_documents 搜尋的知識庫
    types:                       物件型別
      vendor:
        label: 供應商
        display: "{name}"        顯示名稱的樣板
        classification: internal 機密等級（見 LEVELS）
        groups: [procurement]    只有這些群組看得到（省略是所有人）
        properties:
          name: {label: 名稱, required: true}
          rating: {label: 評等, enum: [A, B, C]}
          bank_account: {label: 匯款帳號, classification: confidential}
    relations:
      supplies: {label: 提供, from: vendor, to: system,
                 inverse: supplied_by, inverseLabel: 供應商}
    actions: …                   見 Action
    metrics: …                   見 Metric
    glossary: [{term, definition, aliases, owner}]
    bindings: …                  見 Binding

載入時會檢查所有引用（型別、關係、知識庫、處理函式）都存在，錯誤一次
列出來，方便在審查定義檔時修正。
"""

import dataclasses
import pathlib
import re
from typing import Any

import yaml

IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
# 機密等級（由低到高）。harness.yaml 的 ontology.levels 可以換成自己的。
LEVELS = (
    ("public", "公開"),
    ("internal", "內部使用"),
    ("confidential", "機密"),
    ("restricted", "極機密"),
)
DEFAULT_LEVEL = "internal"
PARAM_TYPES = (
    "string",
    "integer",
    "number",
    "boolean",
    "date",
    "array",
    "object",
)
# 每個 ontology 都有的動作：回報 schema 沒涵蓋的概念（進候選清單）。
REPORT_ACTION = "report_missing_concept"


class SchemaError(ValueError):
    """定義檔有錯。訊息列出所有找到的問題。"""


@dataclasses.dataclass(frozen=True)
class Level:
    """一個機密等級。"""

    id: str
    label: str
    rank: int


@dataclasses.dataclass(frozen=True)
class Property:
    """物件型別的一個屬性。

    Attributes:
        name: 屬性識別碼。
        label: 給人看的名稱。
        description: 說明。
        type: string、integer、number、boolean、date、array 或 object。
        required: 綁定的資料缺少這個屬性時列為警告。
        enum: 允許的值；資料不在裡面時列為警告。
        classification: 這個屬性自己的機密等級；None 表示跟著型別。
    """

    name: str
    label: str = ""
    description: str = ""
    type: str = "string"
    required: bool = False
    enum: tuple[Any, ...] = ()
    classification: str | None = None


@dataclasses.dataclass(frozen=True)
class ObjectType:
    """一種業務物件。

    Attributes:
        name: 型別識別碼，在所有模組裡不能重複。
        module: 所屬模組。
        label: 給人看的名稱，例如「供應商」。
        description: 說明，會放進給 agent 的 schema 摘要。
        display: 顯示名稱的樣板，例如 "{name}"；空的時用識別碼。
        key: 識別碼的意義，例如「統一編號」。
        classification: 機密等級。
        groups: 看得到的群組（識別碼或名稱）；None 表示所有人。
        properties: 屬性，以識別碼為鍵。
    """

    name: str
    module: str
    label: str
    description: str = ""
    display: str = ""
    key: str = ""
    classification: str = DEFAULT_LEVEL
    groups: tuple[str, ...] | None = None
    properties: dict[str, Property] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass(frozen=True)
class Relation:
    """兩種物件之間的關係，例如「供應商 提供 系統」。

    Attributes:
        name: 關係識別碼（從 source 往 target 的方向）。
        module: 所屬模組。
        label: 給人看的名稱。
        source: 起點型別。
        target: 終點型別。
        inverse: 反方向的識別碼；None 時用「~name」反向走。
        inverse_label: 反方向給人看的名稱。
        description: 說明。
    """

    name: str
    module: str
    label: str
    source: str
    target: str
    inverse: str | None = None
    inverse_label: str = ""
    description: str = ""


@dataclasses.dataclass(frozen=True)
class Param:
    """動作或指標的一個參數。"""

    name: str
    type: str = "string"
    description: str = ""
    required: bool = False
    enum: tuple[Any, ...] = ()
    minimum: float | None = None
    maximum: float | None = None
    pattern: str | None = None


@dataclasses.dataclass(frozen=True)
class Action:
    """AI 唯一的寫入路徑：一個定義好的動作。

    每次執行都要經過使用者核准、填寫理由，並寫進動作紀錄。

        renew_contract:
          label: 申請續約
          description: …
          target: contract          要指定一個物件（執行時要給 id）
          params:
            months: {type: integer, required: true, minimum: 1}
          run: actions.py:renew     處理函式（ontology/ 底下的檔案:函式）
          check: actions.py:can_renew 核准前的檢查（可省略）：回傳錯誤說明
                                    或 None，有錯時不會請使用者核准
          create: renewal_request   或：建立一個這種型別的物件
          effects: 產生續約申請單    副作用說明，會寫在工具說明裡
          groups: [procurement]     只有這些群組能執行

    Attributes:
        name: 動作識別碼。
        module: 所屬模組。
        label: 給人看的名稱。
        description: 說明。
        target: 要指定的物件型別；None 表示不針對單一物件。
        params: 參數，以識別碼為鍵。
        run: 處理函式（"檔名.py:函式"）；和 create 擇一。
        check: 核准前的檢查函式（"檔名.py:函式"）；None 表示只檢查參數。
        create: 建立的物件型別；參數直接當成屬性。
        effects: 副作用說明。
        groups: 能執行的群組；None 表示看得到 target 型別的人都能執行。
    """

    name: str
    module: str
    label: str
    description: str = ""
    target: str | None = None
    params: dict[str, Param] = dataclasses.field(default_factory=dict)
    run: str | None = None
    create: str | None = None
    effects: str = ""
    groups: tuple[str, ...] | None = None
    check: str | None = None


@dataclasses.dataclass(frozen=True)
class Metric:
    """治理過的計算：大家用同一個定義，不讓模型自己數。

        contracts_by_status:
          label: 各狀態合約數
          count: contract            數某一型別的物件
          where: {status: 生效中}     只數符合的
          groupBy: status            依屬性分組
        expiring:
          label: 即將到期的合約
          run: metrics.py:expiring   或：用處理函式計算
          params: {days: {type: integer}}

    Attributes:
        name: 指標識別碼。
        module: 所屬模組。
        label: 給人看的名稱。
        description: 說明（計算方式）。
        count: 要數的型別。
        where: 條件：屬性 → 值。
        group_by: 分組的屬性。
        run: 處理函式。
        params: 參數。
        unit: 單位，例如「件」。
    """

    name: str
    module: str
    label: str
    description: str = ""
    count: str | None = None
    where: dict[str, Any] = dataclasses.field(default_factory=dict)
    group_by: str | None = None
    run: str | None = None
    params: dict[str, Param] = dataclasses.field(default_factory=dict)
    unit: str = ""


@dataclasses.dataclass(frozen=True)
class Term:
    """詞彙表的一個用語。"""

    term: str
    definition: str
    module: str
    aliases: tuple[str, ...] = ()
    owner: str = ""


@dataclasses.dataclass(frozen=True)
class Binding:
    """把真實資料對到物件（不經過 LLM）。

    三種來源：

        - name: vendors              檔案：JSON、YAML 或 CSV
          type: vendor
          file: data/vendors.csv     相對於專案根目錄
          records: items             JSON/YAML 裡清單的位置（用 . 分隔）
          id: vendor_id              識別碼的欄位，或樣板 "{unit}-{no}"
          label: name                顯示名稱的欄位（可省略，用型別的 display）
          properties: {name: 名稱, rating: 評等.等級}
          links: {supplies: 系統代碼}  欄位裡是對方的識別碼（可以是清單，
                                      或用逗號、頓號分開）；~關係 表示反向
          validFrom: 生效日
          validTo: 失效日             失效日當天起不再有效
        - name: articles             知識庫：每一條條文變成一個物件
          from: knowledge
          base: policies
          type: policy_article
          docId: "^([A-Za-z0-9-]+)_" 從檔名取出文件代碼的規則（可省略）
          references: refers_to      條文裡提到「第 N 條」時連到同文件的
                                      那一條（可省略）
          document: in_document      每一條連到文件代碼相同的物件（可省略；
                                      關係的對象型別要有那份文件）
        - name: platform             Python：處理函式回傳整理好的紀錄
          run: loaders.py:load
          watch: [data/export.json]  這些檔案改了才重新載入

    Attributes:
        name: 綁定名稱，在所有模組裡不能重複。
        module: 所屬模組。
        type: 物件型別；Python 綁定的紀錄可以自己帶 type。
        source: file、knowledge 或 python。
        file: 檔案路徑。
        records: 清單在檔案裡的位置。
        id: 識別碼欄位或樣板。
        label: 顯示名稱欄位或樣板。
        properties: 屬性 → 欄位或樣板；None 時整筆紀錄照欄位名稱對應。
        links: 關係 → 欄位。
        valid_from: 生效日欄位。
        valid_to: 失效日欄位。
        base: 知識庫識別碼。
        doc_id: 從檔名取出文件代碼的規則。
        references: 條文互相引用的關係。
        document: 條文連到所屬文件的關係（對方的識別碼就是文件代碼）。
        run: 處理函式。
        watch: 處理函式讀的檔案。
    """

    name: str
    module: str
    type: str | None
    source: str
    file: str | None = None
    records: str = ""
    id: str = "id"
    label: str | None = None
    properties: dict[str, str] | None = None
    links: dict[str, str] = dataclasses.field(default_factory=dict)
    valid_from: str | None = None
    valid_to: str | None = None
    base: str | None = None
    doc_id: str | None = None
    references: str | None = None
    run: str | None = None
    watch: tuple[str, ...] = ()
    document: str | None = None


@dataclasses.dataclass(frozen=True)
class Module:
    """一個 YAML 定義檔。"""

    name: str
    label: str
    description: str = ""
    imports: tuple[str, ...] = ()
    documents: tuple[str, ...] = ()
    path: pathlib.Path | None = None


@dataclasses.dataclass
class Schema:
    """所有模組合起來的定義。

    Attributes:
        modules: 模組，以識別碼為鍵。
        types: 物件型別。
        relations: 關係（正方向的識別碼為鍵）。
        actions: 動作（含內建的 report_missing_concept）。
        metrics: 指標。
        glossary: 詞彙表。
        bindings: 綁定，依定義的順序。
        levels: 機密等級，由低到高。
        directory: 定義檔所在的資料夾（處理函式從這裡找）。
    """

    modules: dict[str, Module]
    types: dict[str, ObjectType]
    relations: dict[str, Relation]
    actions: dict[str, Action]
    metrics: dict[str, Metric]
    glossary: list[Term]
    bindings: list[Binding]
    levels: dict[str, Level]
    directory: pathlib.Path

    def level(self, name: str | None) -> Level:
        """機密等級；不認識的名稱當成最高等級（寧可多擋）。"""
        if name in self.levels:
            return self.levels[name]
        return max(self.levels.values(), key=lambda item: item.rank)

    def property_level(self, type_: ObjectType, prop: str) -> Level:
        """一個屬性的機密等級：屬性自己的與型別的取高者。"""
        found = type_.properties.get(prop)
        own = found.classification if found else None
        base = self.level(type_.classification)
        if own is None:
            return base
        mine = self.level(own)
        return mine if mine.rank > base.rank else base

    def step(self, name: str) -> tuple[Relation, bool] | None:
        """關係路徑的一步：回傳 (關係, 是否反向)。

        可以寫關係識別碼、它的 inverse 識別碼，或「~識別碼」反向走。
        """
        reverse = name.startswith("~")
        key = name[1:] if reverse else name
        if key in self.relations:
            return self.relations[key], reverse
        for relation in self.relations.values():
            if relation.inverse == key and not reverse:
                return relation, True
        return None

    def module_types(self, modules: tuple[str, ...] | None) -> set[str]:
        """這些模組（含它們引用的模組）裡的型別；None 表示全部。"""
        if modules is None:
            return set(self.types)
        names = self.expand(modules)
        return {t.name for t in self.types.values() if t.module in names}

    def expand(self, modules: tuple[str, ...]) -> set[str]:
        """模組加上它們（遞迴）引用的模組。"""
        seen: set[str] = set()
        pending = list(modules)
        while pending:
            name = pending.pop()
            if name in seen or name not in self.modules:
                continue
            seen.add(name)
            pending.extend(self.modules[name].imports)
        return seen


def load_schema(
    directory: pathlib.Path,
    levels: Any = None,
    knowledge_bases: set[str] | None = None,
) -> Schema:
    """讀取資料夾裡所有的 *.yaml / *.yml 定義檔。

    Args:
        directory: ontology/ 資料夾。
        levels: harness.yaml 的 ontology.levels：[{id, label}, …]（由低到
            高），None 用預設的 LEVELS。
        knowledge_bases: 專案有的知識庫識別碼，用來檢查 documents 與
            知識庫綁定；None 表示不檢查。

    Returns:
        合起來的定義。

    Raises:
        SchemaError: 定義有錯（列出所有問題）。
    """
    errors: list[str] = []
    schema = Schema(
        modules={},
        types={},
        relations={},
        actions={},
        metrics={},
        glossary=[],
        bindings=[],
        levels=_levels(levels, errors),
        directory=directory,
    )
    files = sorted([*directory.glob("*.yaml"), *directory.glob("*.yml")])
    for path in files:
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as error:
            errors.append(f"{path.name}：YAML 格式錯誤：{error}")
            continue
        if not isinstance(data, dict):
            errors.append(f"{path.name}：最外層必須是對照表")
            continue
        _read_module(schema, path, data, errors)
    if not schema.modules and not errors:
        errors.append(f"{directory} 裡沒有任何定義檔（*.yaml）")
    _add_report_action(schema)
    _check(schema, knowledge_bases, errors)
    if errors:
        raise SchemaError(
            "ontology 定義有錯：\n" + "\n".join(f"- {e}" for e in errors)
        )
    return schema


def _levels(value: Any, errors: list[str]) -> dict[str, Level]:
    if value is None:
        pairs = list(LEVELS)
    elif isinstance(value, list) and value:
        pairs = []
        for item in value:
            if isinstance(item, dict) and item.get("id"):
                pairs.append((str(item["id"]), str(item.get("label") or "")))
            elif isinstance(item, str):
                pairs.append((item, item))
            else:
                errors.append("ontology.levels 每一項要有 id")
        if not pairs:
            pairs = list(LEVELS)
    else:
        errors.append("ontology.levels 必須是清單")
        pairs = list(LEVELS)
    return {
        name: Level(name, label or name, rank)
        for rank, (name, label) in enumerate(pairs)
    }


def _read_module(
    schema: Schema,
    path: pathlib.Path,
    data: dict[str, Any],
    errors: list[str],
) -> None:
    where = path.name
    name = str(data.get("module") or path.stem)
    if not IDENTIFIER.match(name):
        errors.append(f"{where}：模組識別碼 {name!r} 只能用小寫英數字與底線")
        return
    if name in schema.modules:
        errors.append(f"{where}：模組 {name} 重複定義")
        return
    schema.modules[name] = Module(
        name=name,
        label=str(data.get("label") or name),
        description=str(data.get("description") or "").strip(),
        imports=_strings(data.get("imports"), f"{where} imports", errors),
        documents=_strings(data.get("documents"), f"{where} documents", errors),
        path=path,
    )
    for type_name, spec in _mapping(data, "types", where, errors):
        _read_type(
            schema, name, type_name, spec, f"{where} types.{type_name}", errors
        )
    for rel_name, spec in _mapping(data, "relations", where, errors):
        _read_relation(schema, name, rel_name, spec, where, errors)
    for act_name, spec in _mapping(data, "actions", where, errors):
        _read_action(schema, name, act_name, spec, where, errors)
    for met_name, spec in _mapping(data, "metrics", where, errors):
        _read_metric(schema, name, met_name, spec, where, errors)
    for index, item in enumerate(data.get("glossary") or []):
        if not isinstance(item, dict) or not item.get("term"):
            errors.append(f"{where} glossary[{index}]：要有 term")
            continue
        schema.glossary.append(
            Term(
                term=str(item["term"]),
                definition=str(item.get("definition") or "").strip(),
                module=name,
                aliases=_strings(item.get("aliases"), "aliases", errors),
                owner=str(item.get("owner") or ""),
            )
        )
    for index, item in enumerate(data.get("bindings") or []):
        _read_binding(schema, name, index, item, where, errors)


def _read_type(
    schema: Schema,
    module: str,
    name: str,
    spec: dict[str, Any],
    where: str,
    errors: list[str],
) -> None:
    if not _identifier(name, where, errors):
        return
    if name in schema.types:
        errors.append(f"{where}：型別 {name} 已經在其他地方定義")
        return
    props = {}
    for prop_name, prop in _mapping(spec, "properties", where, errors):
        if not _identifier(prop_name, f"{where}.{prop_name}", errors):
            continue
        kind = str(prop.get("type") or "string")
        if kind not in PARAM_TYPES:
            errors.append(f"{where}.{prop_name}：type 必須是 {PARAM_TYPES}")
        props[prop_name] = Property(
            name=prop_name,
            label=str(prop.get("label") or prop_name),
            description=str(prop.get("description") or "").strip(),
            type=kind,
            required=bool(prop.get("required")),
            enum=tuple(prop.get("enum") or ()),
            classification=_optional_str(prop.get("classification")),
        )
    schema.types[name] = ObjectType(
        name=name,
        module=module,
        label=str(spec.get("label") or name),
        description=str(spec.get("description") or "").strip(),
        display=str(spec.get("display") or ""),
        key=str(spec.get("key") or ""),
        classification=str(spec.get("classification") or DEFAULT_LEVEL),
        groups=_groups(spec.get("groups"), where, errors),
        properties=props,
    )


def _read_relation(
    schema: Schema,
    module: str,
    name: str,
    spec: dict[str, Any],
    where: str,
    errors: list[str],
) -> None:
    here = f"{where} relations.{name}"
    if not _identifier(name, here, errors):
        return
    if name in schema.relations:
        errors.append(f"{here}：關係 {name} 已經在其他地方定義")
        return
    if not spec.get("from") or not spec.get("to"):
        errors.append(f"{here}：要有 from 與 to")
        return
    inverse = _optional_str(spec.get("inverse"))
    if inverse is not None and not _identifier(
        inverse, f"{here}.inverse", errors
    ):
        inverse = None
    schema.relations[name] = Relation(
        name=name,
        module=module,
        label=str(spec.get("label") or name),
        source=str(spec["from"]),
        target=str(spec["to"]),
        inverse=inverse,
        inverse_label=str(spec.get("inverseLabel") or ""),
        description=str(spec.get("description") or "").strip(),
    )


def _read_params(
    spec: dict[str, Any], where: str, errors: list[str]
) -> dict[str, Param]:
    params = {}
    for name, item in _mapping(spec, "params", where, errors):
        if not _identifier(name, f"{where}.params.{name}", errors):
            continue
        kind = str(item.get("type") or "string")
        if kind not in PARAM_TYPES:
            errors.append(f"{where}.params.{name}：type 必須是 {PARAM_TYPES}")
        pattern = _optional_str(item.get("pattern"))
        if pattern is not None:
            try:
                re.compile(pattern)
            except re.error as error:
                errors.append(f"{where}.params.{name}：pattern 錯誤：{error}")
                pattern = None
        params[name] = Param(
            name=name,
            type=kind,
            description=str(item.get("description") or "").strip(),
            required=bool(item.get("required")),
            enum=tuple(item.get("enum") or ()),
            minimum=item.get("minimum"),
            maximum=item.get("maximum"),
            pattern=pattern,
        )
    return params


def _read_action(
    schema: Schema,
    module: str,
    name: str,
    spec: dict[str, Any],
    where: str,
    errors: list[str],
) -> None:
    here = f"{where} actions.{name}"
    if not _identifier(name, here, errors):
        return
    if name in schema.actions or name == REPORT_ACTION:
        errors.append(f"{here}：動作 {name} 已經定義過（或是內建的動作）")
        return
    run = _optional_str(spec.get("run"))
    create = _optional_str(spec.get("create"))
    if (run is None) == (create is None):
        errors.append(f"{here}：run（處理函式）與 create（建立物件）要擇一")
    schema.actions[name] = Action(
        name=name,
        module=module,
        label=str(spec.get("label") or name),
        description=str(spec.get("description") or "").strip(),
        target=_optional_str(spec.get("target")),
        params=_read_params(spec, here, errors),
        run=run,
        create=create,
        effects=str(spec.get("effects") or "").strip(),
        groups=_groups(spec.get("groups"), here, errors),
        check=_optional_str(spec.get("check")),
    )


def _read_metric(
    schema: Schema,
    module: str,
    name: str,
    spec: dict[str, Any],
    where: str,
    errors: list[str],
) -> None:
    here = f"{where} metrics.{name}"
    if not _identifier(name, here, errors):
        return
    if name in schema.metrics:
        errors.append(f"{here}：指標 {name} 已經定義過")
        return
    count = _optional_str(spec.get("count"))
    run = _optional_str(spec.get("run"))
    if (count is None) == (run is None):
        errors.append(f"{here}：count（數物件）與 run（處理函式）要擇一")
    where_spec = spec.get("where") or {}
    if not isinstance(where_spec, dict):
        errors.append(f"{here}.where：必須是 屬性: 值 的對照表")
        where_spec = {}
    schema.metrics[name] = Metric(
        name=name,
        module=module,
        label=str(spec.get("label") or name),
        description=str(spec.get("description") or "").strip(),
        count=count,
        where=dict(where_spec),
        group_by=_optional_str(spec.get("groupBy")),
        run=run,
        params=_read_params(spec, here, errors),
        unit=str(spec.get("unit") or ""),
    )


def _read_binding(
    schema: Schema,
    module: str,
    index: int,
    item: Any,
    where: str,
    errors: list[str],
) -> None:
    here = f"{where} bindings[{index}]"
    if not isinstance(item, dict):
        errors.append(f"{here}：必須是對照表")
        return
    name = str(item.get("name") or f"{module}_{index}")
    if any(b.name == name for b in schema.bindings):
        errors.append(f"{here}：綁定名稱 {name} 重複")
        return
    if item.get("from") == "knowledge":
        source = "knowledge"
    elif item.get("run"):
        source = "python"
    elif item.get("file"):
        source = "file"
    else:
        errors.append(f"{here}：要有 file、run 或 from: knowledge")
        return
    type_name = _optional_str(item.get("type"))
    if type_name is None and source != "python":
        errors.append(f"{here}：要有 type")
    properties = item.get("properties")
    if properties is not None and not isinstance(properties, dict):
        errors.append(f"{here}.properties：必須是 屬性: 欄位 的對照表")
        properties = None
    links = item.get("links") or {}
    if not isinstance(links, dict):
        errors.append(f"{here}.links：必須是 關係: 欄位 的對照表")
        links = {}
    doc_id = _optional_str(item.get("docId"))
    if doc_id is not None:
        try:
            re.compile(doc_id)
        except re.error as error:
            errors.append(f"{here}.docId：規則錯誤：{error}")
            doc_id = None
    schema.bindings.append(
        Binding(
            name=name,
            module=module,
            type=type_name,
            source=source,
            file=_optional_str(item.get("file")),
            records=str(item.get("records") or ""),
            id=str(item.get("id") or "id"),
            label=_optional_str(item.get("label")),
            properties=None
            if properties is None
            else {str(k): str(v) for k, v in properties.items()},
            links={str(k): str(v) for k, v in links.items()},
            valid_from=_optional_str(item.get("validFrom")),
            valid_to=_optional_str(item.get("validTo")),
            base=_optional_str(item.get("base")),
            doc_id=doc_id,
            references=_optional_str(item.get("references")),
            run=_optional_str(item.get("run")),
            watch=_strings(item.get("watch"), f"{here}.watch", errors),
            document=_optional_str(item.get("document")),
        )
    )


def _add_report_action(schema: Schema) -> None:
    schema.actions[REPORT_ACTION] = Action(
        name=REPORT_ACTION,
        module="",
        label="回報 schema 沒涵蓋的概念",
        description=(
            "使用者提到的業務概念、屬性或關係在定義裡找不到時，記進候選"
            "清單給定義檔的負責人審查；不會改動任何資料。"
        ),
        params={
            "concept": Param("concept", required=True, description="概念名稱"),
            "description": Param(
                "description", required=True, description="它是什麼、為什麼需要"
            ),
            "example": Param("example", description="對話裡的例子"),
            "module": Param("module", description="應該放在哪個模組"),
        },
        effects="寫進候選清單",
    )


def _check(schema: Schema, bases: set[str] | None, errors: list[str]) -> None:
    """檢查所有引用都存在。"""
    for module in schema.modules.values():
        for name in module.imports:
            if name not in schema.modules:
                errors.append(f"模組 {module.name} 引用不存在的模組 {name}")
        if bases is not None:
            for base in module.documents:
                if base not in bases:
                    errors.append(
                        f"模組 {module.name} 的 documents 引用不存在的知識庫 "
                        f"{base}，可用的有：{sorted(bases)}"
                    )
    for type_ in schema.types.values():
        _check_level(schema, type_.classification, f"型別 {type_.name}", errors)
        for prop in type_.properties.values():
            if prop.classification is not None:
                _check_level(
                    schema,
                    prop.classification,
                    f"屬性 {type_.name}.{prop.name}",
                    errors,
                )
    inverses: set[str] = set()
    for relation in schema.relations.values():
        for end in (relation.source, relation.target):
            if end not in schema.types:
                errors.append(f"關係 {relation.name} 引用不存在的型別 {end}")
        if relation.inverse:
            if relation.inverse in schema.relations or relation.inverse in (
                inverses
            ):
                errors.append(
                    f"關係 {relation.name} 的 inverse {relation.inverse} 重複"
                )
            inverses.add(relation.inverse)
    for action in schema.actions.values():
        for name in (action.target, action.create):
            if name is not None and name not in schema.types:
                errors.append(f"動作 {action.name} 引用不存在的型別 {name}")
        if action.create is not None and action.create in schema.types:
            props = schema.types[action.create].properties
            extra = [p for p in action.params if p not in props and p != "id"]
            if extra:
                errors.append(
                    f"動作 {action.name} 的參數 {extra} 不是 "
                    f"{action.create} 的屬性"
                )
        for spec in (action.run, action.check):
            if spec is not None:
                _check_handler(schema, spec, f"動作 {action.name}", errors)
    for metric in schema.metrics.values():
        if metric.count is not None:
            type_ = schema.types.get(metric.count)
            if type_ is None:
                errors.append(
                    f"指標 {metric.name} 引用不存在的型別 {metric.count}"
                )
            else:
                for prop in [*metric.where, metric.group_by]:
                    if prop is not None and prop not in type_.properties:
                        errors.append(
                            f"指標 {metric.name} 引用 {type_.name} 沒有的屬性 "
                            f"{prop}"
                        )
        if metric.run is not None:
            _check_handler(schema, metric.run, f"指標 {metric.name}", errors)
    for binding in schema.bindings:
        here = f"綁定 {binding.name}"
        if binding.type is not None and binding.type not in schema.types:
            errors.append(f"{here} 引用不存在的型別 {binding.type}")
        for name in binding.links:
            if schema.step(name) is None:
                errors.append(f"{here} 引用不存在的關係 {name}")
        if binding.references is not None and (
            binding.references not in schema.relations
        ):
            errors.append(f"{here} 引用不存在的關係 {binding.references}")
        if binding.document is not None:
            relation = schema.relations.get(binding.document)
            if relation is None:
                errors.append(f"{here} 引用不存在的關係 {binding.document}")
            elif relation.source != binding.type:
                errors.append(
                    f"{here} 的 document 關係 {binding.document} "
                    f"要從 {binding.type} 出發"
                )
        if binding.source == "knowledge":
            if not binding.base:
                errors.append(f"{here} 要有 base（知識庫識別碼）")
            elif bases is not None and binding.base not in bases:
                errors.append(
                    f"{here} 引用不存在的知識庫 {binding.base}，"
                    f"可用的有：{sorted(bases)}"
                )
        if binding.run is not None:
            _check_handler(schema, binding.run, here, errors)


def _check_level(
    schema: Schema, name: str, where: str, errors: list[str]
) -> None:
    if name not in schema.levels:
        errors.append(
            f"{where} 的機密等級 {name} 不存在，可用的有：{list(schema.levels)}"
        )


def _check_handler(
    schema: Schema, spec: str, where: str, errors: list[str]
) -> None:
    file_name, _, func = spec.partition(":")
    if not file_name.endswith(".py") or not func:
        errors.append(f"{where} 的處理函式要寫成「檔名.py:函式名稱」：{spec}")
        return
    path = (schema.directory / file_name).resolve()
    if schema.directory.resolve() not in path.parents or not path.is_file():
        errors.append(f"{where} 的處理函式檔案不存在：ontology/{file_name}")


def _mapping(
    data: dict[str, Any], key: str, where: str, errors: list[str]
) -> list[tuple[str, dict[str, Any]]]:
    value = data.get(key) or {}
    if not isinstance(value, dict):
        errors.append(f"{where}：{key} 必須是對照表")
        return []
    items = []
    for name, spec in value.items():
        if spec is None:
            spec = {}
        if not isinstance(spec, dict):
            errors.append(f"{where} {key}.{name}：必須是對照表")
            continue
        items.append((str(name), spec))
    return items


def _identifier(name: str, where: str, errors: list[str]) -> bool:
    if IDENTIFIER.match(name):
        return True
    errors.append(f"{where}：識別碼 {name!r} 只能用小寫英數字與底線")
    return False


def _strings(value: Any, where: str, errors: list[str]) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if not isinstance(value, list):
        errors.append(f"{where}：必須是清單")
        return ()
    return tuple(str(item) for item in value)


def _groups(
    value: Any, where: str, errors: list[str]
) -> tuple[str, ...] | None:
    if value is None:
        return None
    return _strings(value, f"{where}.groups", errors)


def _optional_str(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return str(value)
