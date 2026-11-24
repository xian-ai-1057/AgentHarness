"""Ontology 的資料：物件、關係、綁定的狀態、動作紀錄與候選概念。

存在專案的 .harness/ontology.db（SQLite）。物件與關係都可以從綁定的
資料重建；動作紀錄與候選概念只能新增（資料表上有觸發器擋住修改與
刪除），是 AI 寫入的稽核依據。

時間：每個物件與關係都有生效日（valid_from）與失效日（valid_to），
空字串表示不限。查詢時給一個日期（as_of），只取那天有效的資料：
valid_from <= as_of < valid_to。
"""

import contextlib
import dataclasses
import json
import pathlib
import sqlite3
import time
from collections.abc import Iterable
from collections.abc import Iterator
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS objects (
    type TEXT NOT NULL,
    id TEXT NOT NULL,
    valid_from TEXT NOT NULL DEFAULT '',
    valid_to TEXT NOT NULL DEFAULT '',
    label TEXT NOT NULL DEFAULT '',
    props TEXT NOT NULL DEFAULT '{}',
    source TEXT NOT NULL DEFAULT '{}',
    docs TEXT NOT NULL DEFAULT '[]',
    binding TEXT NOT NULL,
    PRIMARY KEY (type, id, valid_from)
);
CREATE INDEX IF NOT EXISTS objects_binding ON objects (binding);
CREATE TABLE IF NOT EXISTS links (
    rel TEXT NOT NULL,
    from_type TEXT NOT NULL,
    from_id TEXT NOT NULL,
    to_type TEXT NOT NULL,
    to_id TEXT NOT NULL,
    valid_from TEXT NOT NULL DEFAULT '',
    valid_to TEXT NOT NULL DEFAULT '',
    binding TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS links_from ON links (from_type, from_id);
CREATE INDEX IF NOT EXISTS links_to ON links (to_type, to_id);
CREATE INDEX IF NOT EXISTS links_binding ON links (binding);
CREATE TABLE IF NOT EXISTS bindings (
    name TEXT PRIMARY KEY,
    signature TEXT NOT NULL,
    loaded_at REAL NOT NULL,
    objects INTEGER NOT NULL,
    links INTEGER NOT NULL,
    warnings TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS action_log (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    at REAL NOT NULL,
    actor TEXT NOT NULL DEFAULT '',
    agent TEXT NOT NULL DEFAULT '',
    session TEXT NOT NULL DEFAULT '',
    action TEXT NOT NULL,
    target TEXT NOT NULL DEFAULT '',
    params TEXT NOT NULL DEFAULT '{}',
    reason TEXT NOT NULL,
    status TEXT NOT NULL,
    result TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS candidates (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    at REAL NOT NULL,
    actor TEXT NOT NULL DEFAULT '',
    module TEXT NOT NULL DEFAULT '',
    concept TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    example TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT ''
);
CREATE TRIGGER IF NOT EXISTS action_log_no_update
BEFORE UPDATE ON action_log
BEGIN SELECT RAISE(ABORT, 'action_log 只能新增，不能修改'); END;
CREATE TRIGGER IF NOT EXISTS action_log_no_delete
BEFORE DELETE ON action_log
BEGIN SELECT RAISE(ABORT, 'action_log 只能新增，不能刪除'); END;
CREATE TRIGGER IF NOT EXISTS candidates_no_update
BEFORE UPDATE ON candidates
BEGIN SELECT RAISE(ABORT, 'candidates 只能新增，不能修改'); END;
CREATE TRIGGER IF NOT EXISTS candidates_no_delete
BEFORE DELETE ON candidates
BEGIN SELECT RAISE(ABORT, 'candidates 只能新增，不能刪除'); END;
"""
# 結果太長時截斷，避免動作紀錄塞進整份檔案。
_RESULT_LIMIT = 2000


@dataclasses.dataclass
class Record:
    """一個物件（某段有效期間的版本）。

    Attributes:
        type: 型別。
        id: 識別碼。
        label: 顯示名稱。
        props: 屬性。
        valid_from: 生效日（YYYY-MM-DD），空字串表示不限。
        valid_to: 失效日，空字串表示不限。
        source: 出處，例如 {"binding", "file", "row"}。
        docs: 對應的文件段落：[{"base", "source", "location"}]。
        binding: 來自哪個綁定（動作建立的是「action:動作名稱」）。
    """

    type: str
    id: str
    label: str = ""
    props: dict[str, Any] = dataclasses.field(default_factory=dict)
    valid_from: str = ""
    valid_to: str = ""
    source: dict[str, Any] = dataclasses.field(default_factory=dict)
    docs: list[dict[str, str]] = dataclasses.field(default_factory=list)
    binding: str = ""


@dataclasses.dataclass
class Link:
    """一條關係：from 經過 rel 連到 to。"""

    rel: str
    from_type: str
    from_id: str
    to_type: str
    to_id: str
    valid_from: str = ""
    valid_to: str = ""
    binding: str = ""
    source: dict[str, Any] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass(frozen=True)
class BindingState:
    """一個綁定最近一次載入的結果。"""

    name: str
    signature: str
    loaded_at: float
    objects: int
    links: int
    warnings: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class ActionEntry:
    """動作紀錄的一筆。"""

    seq: int
    at: float
    actor: str
    agent: str
    session: str
    action: str
    target: str
    params: dict[str, Any]
    reason: str
    status: str
    result: str


class Store:
    """ontology.db 的讀寫。每個操作各自開關連線，可以跨執行緒使用。"""

    def __init__(self, path: pathlib.Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(_SCHEMA)

    # ── 綁定 ──

    def binding_state(self, name: str) -> BindingState | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM bindings WHERE name = ?", (name,)
            ).fetchone()
        if row is None:
            return None
        return BindingState(
            row["name"],
            row["signature"],
            row["loaded_at"],
            row["objects"],
            row["links"],
            tuple(json.loads(row["warnings"])),
        )

    def binding_states(self) -> list[BindingState]:
        with self._connect() as db:
            names = [r[0] for r in db.execute("SELECT name FROM bindings")]
        return [s for name in names if (s := self.binding_state(name))]

    def replace_binding(
        self,
        name: str,
        signature: str,
        records: Iterable[Record],
        links: Iterable[Link],
        warnings: list[str],
    ) -> BindingState:
        """把一個綁定的物件與關係整批換成新的（同一個交易）。"""
        records = list(records)
        links = list(links)
        now = time.time()
        with self._connect() as db:
            db.execute("BEGIN")
            db.execute("DELETE FROM objects WHERE binding = ?", (name,))
            db.execute("DELETE FROM links WHERE binding = ?", (name,))
            db.executemany(
                "INSERT OR REPLACE INTO objects VALUES (?,?,?,?,?,?,?,?,?)",
                [_object_row(item, name) for item in records],
            )
            db.executemany(
                "INSERT INTO links VALUES (?,?,?,?,?,?,?,?,?)",
                [_link_row(item, name) for item in links],
            )
            db.execute(
                "INSERT OR REPLACE INTO bindings VALUES (?,?,?,?,?,?)",
                (
                    name,
                    signature,
                    now,
                    len(records),
                    len(links),
                    json.dumps(warnings, ensure_ascii=False),
                ),
            )
            db.execute("COMMIT")
        return BindingState(
            name, signature, now, len(records), len(links), tuple(warnings)
        )

    def drop_bindings(self, keep: set[str]) -> None:
        """拿掉定義檔裡已經沒有的綁定（動作建立的物件保留）。"""
        with self._connect() as db:
            names = [r[0] for r in db.execute("SELECT name FROM bindings")]
            for name in names:
                if name in keep:
                    continue
                db.execute("DELETE FROM objects WHERE binding = ?", (name,))
                db.execute("DELETE FROM links WHERE binding = ?", (name,))
                db.execute("DELETE FROM bindings WHERE name = ?", (name,))

    # ── 物件與關係 ──

    def upsert(self, record: Record, links: Iterable[Link] = ()) -> None:
        """新增或取代一個物件（動作建立的物件用）。"""
        with self._connect() as db:
            db.execute("BEGIN")
            db.execute(
                "INSERT OR REPLACE INTO objects VALUES (?,?,?,?,?,?,?,?,?)",
                _object_row(record, record.binding),
            )
            db.execute(
                "DELETE FROM links WHERE binding = ? AND from_type = ? "
                "AND from_id = ?",
                (record.binding, record.type, record.id),
            )
            db.executemany(
                "INSERT INTO links VALUES (?,?,?,?,?,?,?,?,?)",
                [_link_row(item, record.binding) for item in links],
            )
            db.execute("COMMIT")

    def objects(
        self,
        types: Iterable[str],
        as_of: str | None,
        ids: Iterable[str] | None = None,
    ) -> list[Record]:
        """這些型別在 as_of 那天有效的物件；as_of 為 None 時取所有版本。"""
        types = list(types)
        if not types:
            return []
        sql = f"SELECT * FROM objects WHERE type IN ({_marks(types)})"
        args: list[Any] = list(types)
        if ids is not None:
            ids = list(ids)
            if not ids:
                return []
            sql += f" AND id IN ({_marks(ids)})"
            args += ids
        if as_of is not None:
            sql += _valid_clause()
            args += [as_of, as_of]
        sql += " ORDER BY type, id, valid_from"
        with self._connect() as db:
            return [_record(row) for row in db.execute(sql, args)]

    def links_of(
        self,
        type_: str,
        ids: Iterable[str],
        rels: Iterable[str] | None,
        reverse: bool,
        as_of: str | None,
    ) -> list[Link]:
        """從（reverse 時是連到）這些物件出發的關係。"""
        ids = list(ids)
        if not ids:
            return []
        side = "to" if reverse else "from"
        sql = (
            f"SELECT * FROM links WHERE {side}_type = ? "
            f"AND {side}_id IN ({_marks(ids)})"
        )
        args: list[Any] = [type_, *ids]
        if rels is not None:
            rels = list(rels)
            sql += f" AND rel IN ({_marks(rels)})"
            args += rels
        if as_of is not None:
            sql += _valid_clause()
            args += [as_of, as_of]
        with self._connect() as db:
            return [_link(row) for row in db.execute(sql, args)]

    def dangling_links(self) -> list[tuple[str, str, str, list[str]]]:
        """連到不存在物件的關係：[(綁定, 關係, 對象型別, [對象識別碼…])]。

        只看物件存不存在，不看有效期間；動作建立的物件也算存在。
        """
        sql = (
            "SELECT l.binding, l.rel, l.to_type, l.to_id FROM links l "
            "WHERE NOT EXISTS (SELECT 1 FROM objects o "
            "WHERE o.type = l.to_type AND o.id = l.to_id) "
            "ORDER BY l.binding, l.rel, l.to_id"
        )
        grouped: dict[tuple[str, str, str], list[str]] = {}
        with self._connect() as db:
            for binding, rel, to_type, to_id in db.execute(sql):
                ids = grouped.setdefault((binding, rel, to_type), [])
                if to_id not in ids:
                    ids.append(to_id)
        return [(b, r, t, ids) for (b, r, t), ids in grouped.items()]

    def count(self, type_: str) -> int:
        with self._connect() as db:
            return db.execute(
                "SELECT COUNT(DISTINCT id) FROM objects WHERE type = ?",
                (type_,),
            ).fetchone()[0]

    # ── 動作紀錄與候選概念 ──

    def log_action(
        self,
        *,
        actor: str,
        agent: str,
        session: str,
        action: str,
        target: str,
        params: dict[str, Any],
        reason: str,
        status: str,
        result: str,
    ) -> int:
        with self._connect() as db:
            cursor = db.execute(
                "INSERT INTO action_log (at, actor, agent, session, action, "
                "target, params, reason, status, result) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    time.time(),
                    actor,
                    agent,
                    session,
                    action,
                    target,
                    json.dumps(params, ensure_ascii=False, default=str),
                    reason,
                    status,
                    result[:_RESULT_LIMIT],
                ),
            )
            return int(cursor.lastrowid or 0)

    def actions(self, limit: int = 50) -> list[ActionEntry]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM action_log ORDER BY seq DESC LIMIT ?", (limit,)
            ).fetchall()
        return [
            ActionEntry(
                row["seq"],
                row["at"],
                row["actor"],
                row["agent"],
                row["session"],
                row["action"],
                row["target"],
                json.loads(row["params"]),
                row["reason"],
                row["status"],
                row["result"],
            )
            for row in rows
        ]

    def add_candidate(
        self,
        *,
        actor: str,
        module: str,
        concept: str,
        description: str,
        example: str,
        reason: str,
    ) -> int:
        with self._connect() as db:
            cursor = db.execute(
                "INSERT INTO candidates (at, actor, module, concept, "
                "description, example, reason) VALUES (?,?,?,?,?,?,?)",
                (
                    time.time(),
                    actor,
                    module,
                    concept,
                    description,
                    example,
                    reason,
                ),
            )
            return int(cursor.lastrowid or 0)

    def candidates(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM candidates ORDER BY seq DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]

    @contextlib.contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            yield db
        finally:
            db.close()


def _marks(values: list[Any]) -> str:
    return ",".join("?" * len(values))


def _valid_clause() -> str:
    return (
        " AND (valid_from = '' OR valid_from <= ?)"
        " AND (valid_to = '' OR valid_to > ?)"
    )


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _object_row(item: Record, binding: str) -> tuple[Any, ...]:
    return (
        item.type,
        item.id,
        item.valid_from,
        item.valid_to,
        item.label,
        _dump(item.props),
        _dump(item.source),
        _dump(item.docs),
        binding,
    )


def _link_row(item: Link, binding: str) -> tuple[Any, ...]:
    return (
        item.rel,
        item.from_type,
        item.from_id,
        item.to_type,
        item.to_id,
        item.valid_from,
        item.valid_to,
        binding,
        _dump(item.source),
    )


def _record(row: sqlite3.Row) -> Record:
    return Record(
        type=row["type"],
        id=row["id"],
        label=row["label"],
        props=json.loads(row["props"]),
        valid_from=row["valid_from"],
        valid_to=row["valid_to"],
        source=json.loads(row["source"]),
        docs=json.loads(row["docs"]),
        binding=row["binding"],
    )


def _link(row: sqlite3.Row) -> Link:
    return Link(
        rel=row["rel"],
        from_type=row["from_type"],
        from_id=row["from_id"],
        to_type=row["to_type"],
        to_id=row["to_id"],
        valid_from=row["valid_from"],
        valid_to=row["valid_to"],
        binding=row["binding"],
        source=json.loads(row["source"]),
    )
