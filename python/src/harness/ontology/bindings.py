"""綁定：把檔案、知識庫或 Python 處理函式的資料變成物件與關係。

完全照定義檔的對應規則轉換，不經過 LLM。每個綁定有一個簽章（來源內容
與對應規則的雜湊），沒變就不重新載入；變了就把這個綁定的物件與關係
整批換掉，其他綁定不受影響。
"""

import csv
import dataclasses
import datetime
import hashlib
import importlib.util
import io
import json
import os
import pathlib
import re
import sys
from collections.abc import Callable
from typing import Any

import yaml

from harness import regulation
from harness.ontology import schema as schema_lib
from harness.ontology import store as store_lib

_SPLIT = re.compile(r"\s*[,，、;；\n]\s*")
_PAGE_SUFFIX = re.compile(r"\s*[（(]\s*第\s*\d+\s*頁\s*[）)]\s*$")
_MENTION = re.compile(
    r"第\s*([0-9一二三四五六七八九十百零〇]+)\s*(條|點)"
    r"(?:\s*之\s*([0-9一二三四五六七八九十百零〇]+))?"
)
_TEXT_LIMIT = 4000
# 這個程式啟動後只載入一次（Python 綁定沒有 watch 時）。
_PROCESS = f"process-{id(object())}"


@dataclasses.dataclass
class Loaded:
    """一個綁定讀出來的結果。"""

    records: list[store_lib.Record]
    links: list[store_lib.Link]
    warnings: list[str]


@dataclasses.dataclass
class BindingContext:
    """傳給 Python 綁定處理函式的環境。

    Attributes:
        root: 專案根目錄。
        binding: 這個綁定的設定。
        schema: 整份定義。
        warn: 回報資料問題（會列在 pyharness ontology check）。
    """

    root: pathlib.Path
    binding: schema_lib.Binding
    schema: schema_lib.Schema
    warn: Callable[[str], None]


def signature(
    root: pathlib.Path,
    directory: pathlib.Path,
    binding: schema_lib.Binding,
    extra: str = "",
) -> str:
    """綁定的簽章：對應規則加上來源內容的雜湊。"""
    digest = hashlib.sha256(repr(binding).encode())
    digest.update(extra.encode())
    if binding.source == "file":
        path = resolve(root, binding.file or "")
        digest.update(path.read_bytes() if path.is_file() else b"<missing>")
    elif binding.source == "python":
        handler = directory / (binding.run or "").partition(":")[0]
        if handler.is_file():
            digest.update(handler.read_bytes())
        if not binding.watch:
            digest.update(_PROCESS.encode())
        for item in binding.watch:
            path = resolve(root, item)
            if path.is_file():
                stat = path.stat()
                digest.update(
                    f"{item}:{stat.st_size}:{stat.st_mtime_ns}".encode()
                )
            else:
                digest.update(f"{item}:<missing>".encode())
    return digest.hexdigest()


def resolve(root: pathlib.Path, value: str) -> pathlib.Path:
    """綁定裡的路徑：絕對路徑照用，相對路徑以專案根目錄為準。

    可以寫 ${環境變數}，例如 ${ASSET_EXPORT}。
    """
    expanded = re.sub(
        r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}",
        lambda m: os.environ.get(m.group(1), ""),
        value,
    )
    path = pathlib.Path(expanded).expanduser()
    return path if path.is_absolute() else root / path


def load_file(
    root: pathlib.Path,
    binding: schema_lib.Binding,
    schema: schema_lib.Schema,
) -> Loaded:
    """讀 JSON、YAML 或 CSV 檔案。"""
    path = resolve(root, binding.file or "")
    warnings: list[str] = []
    if not path.is_file():
        return Loaded([], [], [f"找不到檔案 {binding.file}"])
    raw = path.read_bytes()
    suffix = path.suffix.lower()
    try:
        if suffix == ".csv":
            text = raw.decode("utf-8-sig")
            rows: Any = list(csv.DictReader(io.StringIO(text)))
        elif suffix in (".yaml", ".yml"):
            rows = yaml.safe_load(raw.decode("utf-8")) or []
        else:
            rows = json.loads(raw.decode("utf-8-sig"))
    except (ValueError, yaml.YAMLError, UnicodeDecodeError) as error:
        return Loaded([], [], [f"讀不了 {binding.file}：{error}"])
    items = _records_at(rows, binding.records)
    if items is None:
        return Loaded(
            [], [], [f"{binding.file} 裡找不到清單 {binding.records!r}"]
        )
    source = {"binding": binding.name, "file": binding.file}
    return convert(items, binding, schema, source, warnings)


def load_python(
    root: pathlib.Path,
    binding: schema_lib.Binding,
    schema: schema_lib.Schema,
) -> Loaded:
    """呼叫 Python 處理函式，把回傳的紀錄轉成物件。

    處理函式收到 BindingContext，回傳紀錄的清單。綁定有 properties 時
    紀錄是原始資料，照對應規則轉換；沒有時紀錄要整理成：
        {"type": 型別（可省略，用綁定的）, "id": …, "label": …,
         "properties": {…}, "links": {關係: [識別碼…]},
         "validFrom": …, "validTo": …, "source": {…}, "docs": [{…}]}
    """
    warnings: list[str] = []
    func = resolve_handler(binding.run or "", schema.directory)
    context = BindingContext(root, binding, schema, warnings.append)
    items = list(func(context) or [])
    source = {"binding": binding.name, "run": binding.run}
    if binding.properties is not None:
        return convert(items, binding, schema, source, warnings)
    records: list[store_lib.Record] = []
    links: list[store_lib.Link] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            warnings.append(f"第 {index + 1} 筆不是對照表，略過")
            continue
        type_name = str(item.get("type") or binding.type or "")
        type_ = schema.types.get(type_name)
        if type_ is None:
            warnings.append(f"第 {index + 1} 筆的型別 {type_name!r} 不存在")
            continue
        identifier = _text(item.get("id"))
        if not identifier:
            warnings.append(f"第 {index + 1} 筆（{type_name}）沒有 id，略過")
            continue
        props = dict(item.get("properties") or {})
        here = f"{type_.label} {identifier}"
        _check_props(type_, props, here, warnings)
        record = store_lib.Record(
            type=type_name,
            id=identifier,
            label=_text(item.get("label")) or display(type_, identifier, props),
            props=props,
            valid_from=to_date(item.get("validFrom")),
            valid_to=to_date(item.get("validTo")),
            source={**source, **dict(item.get("source") or {})},
            docs=list(item.get("docs") or []),
        )
        records.append(record)
        for rel, targets in (item.get("links") or {}).items():
            links += _links(
                schema, record, str(rel), split_ids(targets), warnings
            )
    return Loaded(records, links, warnings)


def load_chunks(
    binding: schema_lib.Binding,
    schema: schema_lib.Schema,
    chunks: list[Any],
) -> Loaded:
    """知識庫的片段：同一份文件同一條（點）合成一個物件。

    物件的屬性：doc（文件代碼）、file（檔案）、article（條號，例如
    「第五條」）、chapter（章節）、pages（頁碼）、text（條文內容）。
    docs 記著每一片的出處，search_documents 用它限定搜尋範圍。
    """
    warnings: list[str] = []
    type_ = schema.types[binding.type or ""]
    pattern = re.compile(binding.doc_id) if binding.doc_id else None
    grouped: dict[str, dict[str, Any]] = {}
    for chunk in chunks:
        doc = _doc_code(chunk.source, pattern)
        chapter, article = _split_location(chunk.location)
        identifier = f"{doc}:{article}" if article else doc
        item = grouped.setdefault(
            identifier,
            {
                "doc": doc,
                "file": chunk.source,
                "article": article,
                "chapter": chapter,
                "pages": [],
                "texts": [],
                "docs": [],
            },
        )
        page = regulation._PAGE.search(chunk.location)
        if page and page.group(1) not in item["pages"]:
            item["pages"].append(page.group(1))
        item["texts"].append(chunk.text)
        item["docs"].append(
            {
                "base": binding.base or "",
                "source": chunk.source,
                "location": chunk.location,
            }
        )
    records = []
    for identifier, item in grouped.items():
        text = "\n".join(item.pop("texts"))
        docs = item.pop("docs")
        props = {
            key: value
            for key, value in {**item, "text": text[:_TEXT_LIMIT]}.items()
            if key in type_.properties
        }
        title = _doc_title(item["file"], item["doc"])
        label = f"{title} {item['article']}".strip()
        records.append(
            store_lib.Record(
                type=type_.name,
                id=identifier,
                label=display(type_, identifier, props)
                if type_.display
                else label,
                props=props,
                source={
                    "binding": binding.name,
                    "base": binding.base,
                    "file": item["file"],
                },
                docs=docs,
            )
        )
        item["text"] = text
    links = []
    if binding.references:
        links = _references(binding, grouped)
    if binding.document:
        target = schema.relations[binding.document].target
        for identifier, item in grouped.items():
            if item["doc"]:
                links.append(
                    store_lib.Link(
                        rel=binding.document,
                        from_type=type_.name,
                        from_id=identifier,
                        to_type=target,
                        to_id=item["doc"],
                        source={"binding": binding.name, "rule": "文件代碼"},
                    )
                )
    return Loaded(records, links, warnings)


def convert(
    items: list[Any],
    binding: schema_lib.Binding,
    schema: schema_lib.Schema,
    source: dict[str, Any],
    warnings: list[str],
) -> Loaded:
    """照綁定的對應規則把原始紀錄轉成物件與關係。"""
    type_ = schema.types[binding.type or ""]
    records: list[store_lib.Record] = []
    links: list[store_lib.Link] = []
    seen: set[tuple[str, str]] = set()
    for index, row in enumerate(items):
        if not isinstance(row, dict):
            warnings.append(f"第 {index + 1} 筆不是對照表，略過")
            continue
        identifier = _text(field(row, binding.id))
        if not identifier:
            warnings.append(f"第 {index + 1} 筆沒有 {binding.id}，略過")
            continue
        if binding.properties is None:
            props = {
                key: value
                for key, value in row.items()
                if key in type_.properties
            }
        else:
            props = {
                prop: value
                for prop, spec in binding.properties.items()
                if (value := field(row, spec)) not in (None, "")
            }
        valid_from = to_date(field(row, binding.valid_from))
        key = (identifier, valid_from)
        if key in seen:
            warnings.append(f"{type_.label} {identifier} 重複，用最後一筆")
        seen.add(key)
        here = f"{type_.label} {identifier}"
        _check_props(type_, props, here, warnings)
        label = _text(field(row, binding.label)) if binding.label else ""
        record = store_lib.Record(
            type=type_.name,
            id=identifier,
            label=label or display(type_, identifier, props),
            props=props,
            valid_from=valid_from,
            valid_to=to_date(field(row, binding.valid_to)),
            source={**source, "row": index + 1},
        )
        records.append(record)
        for rel, spec in binding.links.items():
            links += _links(
                schema, record, rel, split_ids(field(row, spec)), warnings
            )
    return Loaded(records, links, warnings)


def field(row: dict[str, Any], spec: str | None) -> Any:
    """依欄位規則取值：「a.b」是巢狀欄位，含 {} 的是樣板，= 開頭是固定值。"""
    if spec is None:
        return None
    if spec.startswith("="):
        return spec[1:]
    if "{" in spec:
        return re.sub(
            r"\{([^{}]+)\}",
            lambda m: _text(_dig(row, m.group(1).strip())),
            spec,
        )
    return _dig(row, spec)


def display(
    type_: schema_lib.ObjectType, identifier: str, props: dict[str, Any]
) -> str:
    """顯示名稱：用型別的 display 樣板，沒有時用識別碼。"""
    if not type_.display:
        return identifier
    values = {"id": identifier, **props}
    text = field(values, type_.display)
    return _text(text).strip() or identifier


def split_ids(value: Any) -> list[str]:
    """欄位裡的識別碼：清單，或用逗號、頓號、分號分開的文字。"""
    if value is None or value == "":
        return []
    if isinstance(value, (list, tuple, set)):
        found = []
        for item in value:
            found += split_ids(item)
        return found
    if isinstance(value, dict):
        return [str(key) for key in value]
    return [part for part in _SPLIT.split(str(value)) if part]


def to_date(value: Any) -> str:
    """轉成 YYYY-MM-DD；看不懂或空的時是空字串。"""
    if value is None or value == "":
        return ""
    if isinstance(value, datetime.datetime):
        return value.date().isoformat()
    if isinstance(value, datetime.date):
        return value.isoformat()
    text = str(value).strip()
    match = re.match(r"^(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})", text)
    if not match:
        return ""
    year, month, day = (int(part) for part in match.groups())
    try:
        return datetime.date(year, month, day).isoformat()
    except ValueError:
        return ""


def resolve_handler(spec: str, directory: pathlib.Path) -> Any:
    """「檔名.py:函式」→ 函式。

    檔案從 ontology/ 資料夾載入，改過會重新載入。
    """
    file_name, _, func_name = spec.partition(":")
    path = (directory / file_name).resolve()
    digest = hashlib.sha1(str(path).encode()).hexdigest()[:12]
    module_name = f"_harness_ontology_{digest}"
    module = sys.modules.get(module_name)
    mtime = path.stat().st_mtime_ns
    if module is None or getattr(module, "__harness_mtime__", None) != mtime:
        # 讓處理函式可以 import 同一個資料夾裡的其他檔案與專案的套件。
        for folder in (str(directory), str(directory.parent)):
            if folder not in sys.path:
                sys.path.insert(0, folder)
        loader_spec = importlib.util.spec_from_file_location(module_name, path)
        assert loader_spec is not None and loader_spec.loader is not None
        module = importlib.util.module_from_spec(loader_spec)
        sys.modules[module_name] = module
        loader_spec.loader.exec_module(module)
        module.__harness_mtime__ = mtime  # type: ignore[attr-defined]
    func = getattr(module, func_name, None)
    if not callable(func):
        raise schema_lib.SchemaError(
            f"ontology/{file_name} 裡沒有函式 {func_name}"
        )
    return func


def _records_at(data: Any, path: str) -> list[Any] | None:
    found = _dig(data, path) if path else data
    if isinstance(found, list):
        return found
    if isinstance(found, dict):
        # {識別碼: 紀錄} 的對照表：識別碼放進 _key。
        return [
            {"_key": key, **value} if isinstance(value, dict) else value
            for key, value in found.items()
        ]
    return None


def _dig(data: Any, path: str) -> Any:
    current = data
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit():
            index = int(part)
            current = current[index] if index < len(current) else None
        else:
            return None
        if current is None:
            return None
    return current


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, (list, tuple)):
        return "、".join(_text(item) for item in value)
    return str(value).strip()


def _check_props(
    type_: schema_lib.ObjectType,
    props: dict[str, Any],
    here: str,
    warnings: list[str],
) -> None:
    for prop in type_.properties.values():
        if prop.name in props:
            props[prop.name] = _coerce(prop, props[prop.name], here, warnings)
        value = props.get(prop.name)
        if prop.required and value in (None, "", [], {}):
            warnings.append(f"{here} 缺少必填屬性 {prop.label}")
        if prop.enum and value not in (None, ""):
            values = value if isinstance(value, list) else [value]
            bad = [item for item in values if item not in prop.enum]
            if bad:
                warnings.append(f"{here} 的 {prop.label} 不在允許的值裡：{bad}")
    unknown = [key for key in props if key not in type_.properties]
    for key in unknown:
        props.pop(key)
        warnings.append(f"{here} 有定義裡沒有的屬性 {key}，略過")


def _coerce(
    prop: schema_lib.Property, value: Any, here: str, warnings: list[str]
) -> Any:
    """CSV 等來源的文字轉成屬性的型別；轉不了時保留原值並列為警告。"""
    if not isinstance(value, str) and not isinstance(
        value, (datetime.date, datetime.datetime)
    ):
        return value
    text = value.strip() if isinstance(value, str) else value
    try:
        if prop.type == "integer":
            return int(text)
        if prop.type == "number":
            number = float(text)
            return int(number) if number.is_integer() else number
        if prop.type == "boolean":
            lowered = str(text).lower()
            if lowered in ("true", "yes", "y", "1", "是"):
                return True
            if lowered in ("false", "no", "n", "0", "否"):
                return False
            raise ValueError(text)
        if prop.type == "date":
            day = to_date(text)
            if not day:
                raise ValueError(text)
            return day
    except (TypeError, ValueError):
        warnings.append(f"{here} 的 {prop.label} 不是{prop.type}：{value!r}")
        return value
    if isinstance(value, (datetime.date, datetime.datetime)):
        return to_date(value)
    return value


def _links(
    schema: schema_lib.Schema,
    record: store_lib.Record,
    rel: str,
    targets: list[str],
    warnings: list[str],
) -> list[store_lib.Link]:
    step = schema.step(rel)
    if step is None:
        warnings.append(f"{record.type} {record.id}：關係 {rel} 不存在")
        return []
    relation, reverse = step
    mine = relation.target if reverse else relation.source
    other = relation.source if reverse else relation.target
    if mine != record.type:
        warnings.append(
            f"{record.type} {record.id}：關係 {rel} 的起點必須是 {mine}"
        )
        return []
    found = []
    for target in dict.fromkeys(targets):
        ends = (other, target, record.type, record.id)
        if not reverse:
            ends = (record.type, record.id, other, target)
        found.append(
            store_lib.Link(
                rel=relation.name,
                from_type=ends[0],
                from_id=ends[1],
                to_type=ends[2],
                to_id=ends[3],
                valid_from=record.valid_from,
                valid_to=record.valid_to,
                source=record.source,
            )
        )
    return found


def _doc_code(source: str, pattern: re.Pattern[str] | None) -> str:
    name = pathlib.PurePosixPath(source).name
    if pattern is not None:
        match = pattern.search(name)
        if match:
            return match.group(1) if match.groups() else match.group(0)
    return pathlib.PurePosixPath(name).stem


def _doc_title(source: str, doc: str) -> str:
    """檔名去掉文件代碼，例如 OUT-01_委外管理辦法.md → 委外管理辦法。"""
    stem = pathlib.PurePosixPath(source).stem
    if stem.startswith(doc):
        stem = stem[len(doc) :].lstrip(" _-－–")
    return stem or doc


def _split_location(location: str) -> tuple[str, str]:
    """「第二章 › 第五條（第 3 頁）」→ ("第二章", "第五條")。"""
    cleaned = _PAGE_SUFFIX.sub("", location).strip()
    if regulation._PAGE.fullmatch(cleaned.replace(" ", "")) or re.fullmatch(
        r"第\s*\d+\s*頁", cleaned
    ):
        return "", ""
    parts = [part.strip() for part in cleaned.split("›")]
    article = parts[-1] if parts else ""
    chapter = " › ".join(parts[:-1])
    return chapter, article


def _references(
    binding: schema_lib.Binding, grouped: dict[str, dict[str, Any]]
) -> list[store_lib.Link]:
    """條文裡提到「第 N 條」「第 N 點」時，連到同一份文件的那一條。"""
    by_number: dict[tuple[str, str, int, int], str] = {}
    for identifier, item in grouped.items():
        match = _MENTION.match(item["article"] or "")
        if match:
            by_number[_number_key(item["doc"], match)] = identifier
    links = []
    for identifier, item in grouped.items():
        targets = []
        for match in _MENTION.finditer(item.get("text", "")):
            found = by_number.get(_number_key(item["doc"], match))
            if found and found != identifier and found not in targets:
                targets.append(found)
        for target in targets:
            links.append(
                store_lib.Link(
                    rel=binding.references or "",
                    from_type=binding.type or "",
                    from_id=identifier,
                    to_type=binding.type or "",
                    to_id=target,
                    source={"binding": binding.name, "rule": "第 N 條"},
                )
            )
    return links


def _number_key(doc: str, match: re.Match[str]) -> tuple[str, str, int, int]:
    sub = match.group(3)
    return (
        doc,
        match.group(2),
        regulation.numeral(match.group(1)),
        regulation.numeral(sub) if sub else 0,
    )
