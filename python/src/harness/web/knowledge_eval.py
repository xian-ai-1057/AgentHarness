"""網頁版的知識庫評測：題庫與評測紀錄（存在 .harness/harness.db），以及
在背景執行評測。

- 題庫：每個知識庫一份，管理者與該知識庫的維護者可以新增、修改、刪除，
  也可以從 CSV 或 Excel 匯入、匯出成 CSV。
- 評測：手動執行（可以選擇用模型評測回答），或在文件、版本資訊、檢索
  設定改動後自動執行（只評測檢索，不花模型費用）。自動執行會等幾秒，
  連續上傳好幾份文件時只跑一次。
- 紀錄：每個知識庫保留最近 RUN_LIMIT 次，和上一次同類型的評測比較，
  列出退步與改善的題目。

評測本身的邏輯在 harness.knowledge_eval。
"""

import asyncio
import contextlib
import csv
import io
import json
import logging
import pathlib
import sqlite3
import time
import uuid
from collections.abc import Callable
from typing import Any

from harness import knowledge as knowledge_lib
from harness import knowledge_eval as eval_lib
from harness import llm
from harness.web import accounts as accounts_lib

_LOG = logging.getLogger(__name__)

# 每個知識庫最多幾題、保留幾次紀錄。
QUESTION_LIMIT = 500
RUN_LIMIT = 30
# 文件改動後等幾秒才自動評測（期間再改動就重新計時）。
AUTO_DELAY = 5.0
TOP_K_LIMIT = 20
# 匯入的檔案大小上限。
IMPORT_LIMIT = 5 * 1024 * 1024
MODES = ("retrieval", "answer")

# 匯入時認得的欄位名稱（第一列）。
_COLUMNS = {
    "question": ("question", "問題", "題目"),
    "sources": ("sources", "source", "應該找到的文件", "文件", "出處"),
    "keywords": ("keywords", "關鍵字", "應包含"),
    "answer": ("answer", "參考答案", "答案"),
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS knowledge_eval_questions (
    id TEXT PRIMARY KEY,
    base_id TEXT NOT NULL,
    position INTEGER NOT NULL,
    data TEXT NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS knowledge_eval_questions_base
    ON knowledge_eval_questions (base_id, position);
CREATE TABLE IF NOT EXISTS knowledge_eval_runs (
    id TEXT PRIMARY KEY,
    base_id TEXT NOT NULL,
    mode TEXT NOT NULL,
    status TEXT NOT NULL,
    trigger TEXT NOT NULL,
    started_by TEXT NOT NULL,
    started_at REAL NOT NULL,
    finished_at REAL,
    settings TEXT NOT NULL,
    report TEXT,
    error TEXT
);
CREATE INDEX IF NOT EXISTS knowledge_eval_runs_base
    ON knowledge_eval_runs (base_id, started_at);
"""


class EvalError(Exception):
    """評測相關的操作失敗，訊息會直接顯示給使用者。

    Attributes:
        status: HTTP 狀態碼。
    """

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


class EvalStore:
    """題庫與評測紀錄，和帳號共用 .harness/harness.db。"""

    def __init__(self, path: str | pathlib.Path) -> None:
        self.path = pathlib.Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=10)
        try:
            db.executescript(_SCHEMA)
            # 伺服器在評測途中停掉時，留下的「執行中」改成中斷。
            db.execute(
                "UPDATE knowledge_eval_runs SET status = 'error', "
                "error = '伺服器重新啟動，評測中斷' WHERE status = 'running'"
            )
            db.commit()
        finally:
            db.close()

    @classmethod
    def for_project(cls, root: str | pathlib.Path) -> "EvalStore":
        return cls(pathlib.Path(root) / accounts_lib.DB_FILE)

    # --- 題庫 -------------------------------------------------------------

    def questions(self, base_id: str) -> list[eval_lib.Question]:
        """知識庫的題庫，依加入的順序。"""
        with self._connect() as db:
            rows = db.execute(
                "SELECT id, data FROM knowledge_eval_questions "
                "WHERE base_id = ? ORDER BY position, updated_at",
                (base_id,),
            ).fetchall()
        return [_question(row[0], row[1]) for row in rows]

    def count(self, base_id: str) -> int:
        with self._connect() as db:
            return db.execute(
                "SELECT COUNT(*) FROM knowledge_eval_questions "
                "WHERE base_id = ?",
                (base_id,),
            ).fetchone()[0]

    def add(self, base_id: str, items: list[dict[str, Any]]) -> list[str]:
        """加入題目（已經用 checked_question 檢查過），回傳識別碼。

        Raises:
            EvalError: 超過題數上限。
        """
        if self.count(base_id) + len(items) > QUESTION_LIMIT:
            raise EvalError(f"每個知識庫最多 {QUESTION_LIMIT} 題")
        ids = []
        now = time.time()
        with self._connect() as db:
            start = db.execute(
                "SELECT COALESCE(MAX(position), 0) FROM "
                "knowledge_eval_questions WHERE base_id = ?",
                (base_id,),
            ).fetchone()[0]
            for offset, item in enumerate(items, start=1):
                question_id = uuid.uuid4().hex[:12]
                db.execute(
                    "INSERT INTO knowledge_eval_questions "
                    "(id, base_id, position, data, updated_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        question_id,
                        base_id,
                        start + offset,
                        json.dumps(item, ensure_ascii=False),
                        now,
                    ),
                )
                ids.append(question_id)
        return ids

    def update(self, base_id: str, question_id: str, item: dict[str, Any]):
        """修改一題。

        Raises:
            EvalError: 找不到這一題。
        """
        with self._connect() as db:
            changed = db.execute(
                "UPDATE knowledge_eval_questions SET data = ?, updated_at = ? "
                "WHERE id = ? AND base_id = ?",
                (
                    json.dumps(item, ensure_ascii=False),
                    time.time(),
                    question_id,
                    base_id,
                ),
            ).rowcount
        if not changed:
            raise EvalError("找不到這一題", 404)

    def delete(self, base_id: str, question_id: str) -> None:
        with self._connect() as db:
            changed = db.execute(
                "DELETE FROM knowledge_eval_questions "
                "WHERE id = ? AND base_id = ?",
                (question_id, base_id),
            ).rowcount
        if not changed:
            raise EvalError("找不到這一題", 404)

    def clear(self, base_id: str) -> None:
        """清掉知識庫的所有題目（匯入時取代原本的題庫）。"""
        with self._connect() as db:
            db.execute(
                "DELETE FROM knowledge_eval_questions WHERE base_id = ?",
                (base_id,),
            )

    def forget_base(self, base_id: str) -> None:
        """知識庫拿掉時，題庫與紀錄一起刪除。"""
        with self._connect() as db:
            db.execute(
                "DELETE FROM knowledge_eval_questions WHERE base_id = ?",
                (base_id,),
            )
            db.execute(
                "DELETE FROM knowledge_eval_runs WHERE base_id = ?", (base_id,)
            )

    # --- 評測紀錄 ---------------------------------------------------------

    def start_run(
        self,
        base_id: str,
        mode: str,
        trigger: str,
        started_by: str,
        settings: dict[str, Any],
    ) -> str:
        run_id = uuid.uuid4().hex[:12]
        with self._connect() as db:
            db.execute(
                "INSERT INTO knowledge_eval_runs (id, base_id, mode, status, "
                "trigger, started_by, started_at, settings) "
                "VALUES (?, ?, ?, 'running', ?, ?, ?, ?)",
                (
                    run_id,
                    base_id,
                    mode,
                    trigger,
                    started_by,
                    time.time(),
                    json.dumps(settings, ensure_ascii=False),
                ),
            )
        return run_id

    def finish_run(
        self,
        run_id: str,
        report: dict[str, Any] | None,
        error: str | None = None,
    ) -> None:
        with self._connect() as db:
            db.execute(
                "UPDATE knowledge_eval_runs SET status = ?, finished_at = ?, "
                "report = ?, error = ? WHERE id = ?",
                (
                    "error" if error else "done",
                    time.time(),
                    None
                    if report is None
                    else json.dumps(report, ensure_ascii=False),
                    error,
                    run_id,
                ),
            )
            base_id = db.execute(
                "SELECT base_id FROM knowledge_eval_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
            if base_id is not None:
                db.execute(
                    "DELETE FROM knowledge_eval_runs WHERE base_id = ? AND id "
                    "NOT IN (SELECT id FROM knowledge_eval_runs WHERE "
                    "base_id = ? ORDER BY started_at DESC LIMIT ?)",
                    (base_id[0], base_id[0], RUN_LIMIT),
                )

    def runs(self, base_id: str) -> list[dict[str, Any]]:
        """最近的評測（新的在前），只有摘要。"""
        with self._connect() as db:
            rows = db.execute(
                f"SELECT {_RUN_COLUMNS} FROM knowledge_eval_runs "
                "WHERE base_id = ? ORDER BY started_at DESC",
                (base_id,),
            ).fetchall()
        return [_run(row, full=False) for row in rows]

    def run(self, base_id: str, run_id: str) -> dict[str, Any]:
        """一次評測的完整結果。

        Raises:
            EvalError: 找不到。
        """
        with self._connect() as db:
            row = db.execute(
                f"SELECT {_RUN_COLUMNS} FROM knowledge_eval_runs "
                "WHERE id = ? AND base_id = ?",
                (run_id, base_id),
            ).fetchone()
        if row is None:
            raise EvalError("找不到這次評測", 404)
        return _run(row, full=True)

    def latest(self, base_id: str, mode: str | None = None) -> dict | None:
        """最近一次完成的評測（完整結果）；mode 指定時只找同類型的。"""
        query = (
            f"SELECT {_RUN_COLUMNS} FROM knowledge_eval_runs "
            "WHERE base_id = ? AND status = 'done'"
        )
        params: list[Any] = [base_id]
        if mode is not None:
            query += " AND mode = ?"
            params.append(mode)
        with self._connect() as db:
            row = db.execute(
                query + " ORDER BY started_at DESC LIMIT 1", params
            ).fetchone()
        return None if row is None else _run(row, full=True)

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        return accounts_lib._Transaction(db)


_RUN_COLUMNS = (
    "id, base_id, mode, status, trigger, started_by, started_at, "
    "finished_at, settings, report, error"
)


def _question(question_id: str, data: str) -> eval_lib.Question:
    item = json.loads(data)
    return eval_lib.Question(
        id=question_id,
        question=item.get("question", ""),
        sources=list(item.get("sources") or []),
        keywords=list(item.get("keywords") or []),
        answer=item.get("answer") or "",
    )


def _run(row: tuple[Any, ...], full: bool) -> dict[str, Any]:
    (
        run_id,
        _base_id,
        mode,
        status,
        trigger,
        started_by,
        started_at,
        finished_at,
        settings,
        report,
        error,
    ) = row
    parsed = json.loads(report) if report else None
    found: dict[str, Any] = {
        "id": run_id,
        "mode": mode,
        "status": status,
        "trigger": trigger,
        "startedBy": started_by,
        "startedAt": started_at,
        "finishedAt": finished_at,
        "settings": json.loads(settings),
        "summary": parsed["summary"] if parsed else None,
        "regressions": parsed["regressions"] if parsed else [],
        "fixed": parsed["fixed"] if parsed else [],
        "error": error,
    }
    if full:
        found["results"] = parsed["results"] if parsed else []
    return found


def snapshot(base: knowledge_lib.KnowledgeBase) -> dict[str, Any]:
    """評測當時的檢索設定，事後看得出是哪個設定的結果。"""
    knowledge = base.knowledge
    return {
        "searchMode": knowledge.search_mode,
        "embeddingModel": knowledge.embedding_model,
        "reranker": knowledge.reranker,
        "chunking": knowledge.chunking,
        "chunkSize": knowledge.chunk_size,
        "minSimilarity": knowledge.min_similarity,
        "minRerankScore": knowledge.min_rerank_score,
        "documents": len(knowledge.files()),
    }


def parse_import(filename: str, data: bytes) -> list[dict[str, Any]]:
    """讀出匯入的題庫（CSV 或 Excel），第一列是欄位名稱。

    欄位：問題（必填）、應該找到的文件、關鍵字、參考答案；文件與關鍵字
    有好幾個時用換行、逗號或頓號分開。

    Raises:
        EvalError: 格式不對、沒有問題欄，或某一題不合格（指出第幾列）。
    """
    if len(data) > IMPORT_LIMIT:
        raise EvalError(f"檔案超過 {IMPORT_LIMIT // (1024 * 1024)} MB")
    suffix = pathlib.PurePath(filename).suffix.lower()
    if suffix == ".xlsx":
        rows = _xlsx_rows(data)
    elif suffix in (".csv", ".txt"):
        text = data.decode("utf-8-sig", errors="replace")
        rows = list(csv.reader(io.StringIO(text)))
    else:
        raise EvalError("只能匯入 CSV 或 Excel（.xlsx）檔")
    rows = [row for row in rows if any(cell.strip() for cell in row)]
    if len(rows) < 2:
        raise EvalError("檔案裡沒有題目：第一列是欄位名稱，第二列開始是題目")
    header = [cell.strip().lower() for cell in rows[0]]
    columns: dict[str, int] = {}
    for key, names in _COLUMNS.items():
        for index, cell in enumerate(header):
            if cell in names:
                columns[key] = index
                break
    if "question" not in columns:
        raise EvalError("找不到「問題」欄（第一列要有 問題 或 question）")
    items = []
    for number, row in enumerate(rows[1:], start=2):
        values = {
            key: row[index] if index < len(row) else ""
            for key, index in columns.items()
        }
        try:
            items.append(eval_lib.checked_question(values))
        except ValueError as error:
            raise EvalError(f"第 {number} 列：{error}") from error
    return items


def _xlsx_rows(data: bytes) -> list[list[str]]:
    """Excel 第一個工作表的每一列，依儲存格位置（A、B、C…）對齊欄位。"""
    import re
    import zipfile

    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            shared: list[str] = []
            if "xl/sharedStrings.xml" in archive.namelist():
                strings = knowledge_lib._office_xml(
                    archive, "xl/sharedStrings.xml"
                )
                shared = [
                    "".join(
                        item.text or ""
                        for item in entry.iter(f"{knowledge_lib._S}t")
                    )
                    for entry in strings.iter(f"{knowledge_lib._S}si")
                ]
            sheets = knowledge_lib._xlsx_sheets(archive)
            if not sheets:
                return []
            sheet = knowledge_lib._office_xml(archive, sheets[0][1])
    except (zipfile.BadZipFile, ValueError, KeyError) as error:
        raise EvalError(f"讀不出這個 Excel 檔：{error}") from error
    except Exception as error:  # noqa: BLE001 - XML 壞掉
        raise EvalError(f"讀不出這個 Excel 檔：{error}") from error
    rows = []
    for row in sheet.iter(f"{knowledge_lib._S}row"):
        values: dict[int, str] = {}
        for position, cell in enumerate(row):
            ref = re.match(r"[A-Z]+", cell.get("r", ""))
            column = _column_index(ref.group(0)) if ref else position
            values[column] = knowledge_lib._xlsx_cell(cell, shared)
        if values:
            rows.append([values.get(i, "") for i in range(max(values) + 1)])
        if len(rows) > QUESTION_LIMIT + 1:
            break
    return rows


def _column_index(letters: str) -> int:
    """Excel 的欄名轉成從 0 開始的位置（A → 0、AA → 26）。"""
    number = 0
    for letter in letters:
        number = number * 26 + ord(letter) - ord("A") + 1
    return number - 1


def export_csv(questions: list[eval_lib.Question]) -> str:
    """匯出題庫成 CSV（Excel 打得開，含 BOM）。"""
    out = io.StringIO()
    out.write("﻿")
    writer = csv.writer(out)
    writer.writerow(["問題", "應該找到的文件", "關鍵字", "參考答案"])
    for item in questions:
        writer.writerow(
            [
                item.question,
                "\n".join(item.sources),
                "、".join(item.keywords),
                item.answer,
            ]
        )
    return out.getvalue()


class EvalRunner:
    """在背景執行評測；每個知識庫同時只跑一次。

    Args:
        store: 題庫與紀錄。
        get_base: 依識別碼取得目前的知識庫（設定可能剛改過）。
        model_fn_for: 評測回答時用的模型函式（依知識庫，套用資料分級）。
        on_finish: 評測結束後呼叫（知識庫識別碼, 紀錄），例如寫稽核紀錄。
        delay: 自動評測的等待秒數。
    """

    def __init__(
        self,
        store: EvalStore,
        get_base: Callable[[str], knowledge_lib.KnowledgeBase | None],
        model_fn_for: Callable[[knowledge_lib.KnowledgeBase], llm.ModelFn],
        on_finish: Callable[[str, dict[str, Any]], None] | None = None,
        delay: float = AUTO_DELAY,
    ) -> None:
        self.store = store
        self._get_base = get_base
        self._model_fn_for = model_fn_for
        self._on_finish = on_finish
        self._delay = delay
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._running: dict[str, str] = {}
        self._timers: dict[str, asyncio.TimerHandle] = {}
        # 執行中又有改動時，結束後再跑一次（記下觸發原因）。
        self._again: dict[str, str] = {}

    def running(self, base_id: str) -> str | None:
        """執行中的評測識別碼。"""
        return self._running.get(base_id)

    def schedule(self, base_id: str, trigger: str) -> None:
        """文件或設定改動後自動評測（只評測檢索）；沒有題庫時不做事。"""
        if self.store.count(base_id) == 0:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if base_id in self._running:
            self._again[base_id] = trigger
            return
        timer = self._timers.pop(base_id, None)
        if timer is not None:
            timer.cancel()
        self._timers[base_id] = loop.call_later(
            self._delay, self._fire, base_id, trigger
        )

    def _fire(self, base_id: str, trigger: str) -> None:
        self._timers.pop(base_id, None)
        with contextlib.suppress(EvalError):
            self.start(base_id, trigger, "自動")

    def start(
        self,
        base_id: str,
        trigger: str,
        started_by: str,
        answer_model: str | None = None,
        top_k: int = 5,
        caller: llm.Caller | None = None,
    ) -> str:
        """開始評測，回傳紀錄的識別碼。

        Raises:
            EvalError: 找不到知識庫、沒有題庫，或已經在評測。
        """
        base = self._get_base(base_id)
        if base is None:
            raise EvalError(f"找不到知識庫：{base_id}", 404)
        if base_id in self._running:
            raise EvalError("這個知識庫正在評測，請等它結束", 409)
        questions = self.store.questions(base_id)
        if not questions:
            raise EvalError("還沒有題目，請先新增或匯入題庫")
        if isinstance(top_k, bool) or not isinstance(top_k, int):
            raise EvalError("topK 必須是整數")
        top_k = max(1, min(top_k, TOP_K_LIMIT))
        mode = "answer" if answer_model else "retrieval"
        settings = {**snapshot(base), "topK": top_k}
        if answer_model:
            settings["answerModel"] = answer_model
        run_id = self.store.start_run(
            base_id, mode, trigger, started_by, settings
        )
        self._running[base_id] = run_id
        self._tasks[base_id] = asyncio.get_running_loop().create_task(
            self._execute(
                base, run_id, mode, questions, top_k, answer_model, caller
            )
        )
        return run_id

    async def _execute(
        self,
        base: knowledge_lib.KnowledgeBase,
        run_id: str,
        mode: str,
        questions: list[eval_lib.Question],
        top_k: int,
        answer_model: str | None,
        caller: llm.Caller | None,
    ) -> None:
        report = None
        error = None
        try:
            llm.set_caller(caller)
            previous = self.store.latest(base.id, mode)
            report = await eval_lib.run(
                [base],
                questions,
                top_k=top_k,
                answer_model=answer_model,
                model_fn=self._model_fn_for(base) if answer_model else None,
                previous=previous["results"] if previous else None,
            )
        except asyncio.CancelledError:
            error = "評測被中斷"
            raise
        except Exception as failure:  # noqa: BLE001 - 記在紀錄裡
            _LOG.warning("知識庫 %s 評測失敗：%s", base.id, failure)
            error = str(failure) or failure.__class__.__name__
        finally:
            self.store.finish_run(run_id, report, error)
            self._running.pop(base.id, None)
            self._tasks.pop(base.id, None)
        if self._on_finish is not None:
            with contextlib.suppress(Exception):
                self._on_finish(base.id, self.store.run(base.id, run_id))
        again = self._again.pop(base.id, None)
        if again is not None:
            self.schedule(base.id, again)

    async def close(self) -> None:
        """停掉計時與執行中的評測（伺服器關閉時）。"""
        for timer in self._timers.values():
            timer.cancel()
        self._timers.clear()
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
