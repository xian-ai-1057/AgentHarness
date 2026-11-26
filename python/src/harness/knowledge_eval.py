"""知識庫的題庫回歸評測：改了文件或模型之後，自動檢查答得對不對。

每個知識庫可以有一份題庫，每一題寫下：

- question：使用者會問的問題；
- sources：應該找到的文件（路徑或路徑樣式，例如 hr/leave.md、hr/*.pdf；
  可以加上位置，例如「leave.md › 特休」），任一份出現在前 topK 筆就算找到；
- keywords：找到的片段（或回答）裡應該出現的字詞，全部出現才算通過；
- answer：參考答案（選填），用模型評分回答時才用到。

評測分兩層：

1. 檢索（每次都做，不需要模型）：用知識庫目前的設定搜尋，看應該找到的
   文件有沒有出現、排第幾名，片段裡有沒有關鍵字。算出通過率、命中率
   （hit@k）與 MRR（第一個正確結果名次的倒數平均）。
2. 回答（選擇性，需要模型）：把搜尋結果交給模型回答，檢查回答有沒有
   關鍵字、有沒有引用 [n]；有參考答案時再請模型判斷回答和參考答案是否
   一致。

和上一次的結果比較，列出「退步」（上次通過、這次沒過）與「改善」的題目，
文件或檢索設定改動後馬上知道有沒有改壞。
"""

import dataclasses
import fnmatch
import json
import re
import time
from collections.abc import Sequence
from typing import Any

from harness import datatypes
from harness import knowledge as knowledge_lib
from harness import llm

# 題目的欄位上限，避免匯入奇怪的檔案。
QUESTION_LIMIT = 1000
ANSWER_LIMIT = 4000
LIST_LIMIT = 20
ITEM_LIMIT = 200

_ANSWER_SYSTEM = """你是知識庫問答的評測對象。只根據下面的搜尋結果回答問題，\
在句子後面用 [編號] 註明出處；搜尋結果裡沒有答案時，直接說知識庫裡沒有\
相關資料，不要自己編造。用繁體中文回答，簡潔即可。"""

_JUDGE_SYSTEM = """你是嚴格的評分員。比較「回答」和「參考答案」的重點是否\
一致：數字、期限、條件、對象要相同；回答多出不衝突的補充沒關係，但遺漏\
參考答案的關鍵重點或說法矛盾就不通過。只回覆一行 JSON：\
{"pass": true 或 false, "reason": "一句話說明"}"""


@dataclasses.dataclass
class Question:
    """題庫裡的一題。

    Attributes:
        id: 識別碼。
        question: 問題。
        sources: 應該找到的文件（路徑或路徑樣式，可以加「› 位置」）。
        keywords: 應該出現的字詞。
        answer: 參考答案，空字串表示沒有。
    """

    id: str
    question: str
    sources: list[str] = dataclasses.field(default_factory=list)
    keywords: list[str] = dataclasses.field(default_factory=list)
    answer: str = ""

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


def checked_question(data: Any) -> dict[str, Any]:
    """檢查網頁送來（或匯入）的一題，回傳整理過的欄位。

    Raises:
        ValueError: 欄位不對（訊息會直接顯示給使用者）。
    """
    if not isinstance(data, dict):
        raise ValueError("題目必須是物件")
    question = str(data.get("question") or "").strip()
    if not question:
        raise ValueError("請輸入問題")
    if len(question) > QUESTION_LIMIT:
        raise ValueError(f"問題最多 {QUESTION_LIMIT} 個字")
    answer = str(data.get("answer") or "").strip()
    if len(answer) > ANSWER_LIMIT:
        raise ValueError(f"參考答案最多 {ANSWER_LIMIT} 個字")
    sources = _text_list(data.get("sources"), "應該找到的文件")
    keywords = _text_list(data.get("keywords"), "關鍵字")
    if not sources and not keywords and not answer:
        raise ValueError("請至少填寫應該找到的文件、關鍵字或參考答案其中一項")
    return {
        "question": question,
        "sources": sources,
        "keywords": keywords,
        "answer": answer,
    }


def _text_list(value: Any, label: str) -> list[str]:
    """清單或以換行、逗號、頓號分開的文字。"""
    if value is None or value == "":
        return []
    if isinstance(value, str):
        items = re.split(r"[\n,，、;；]+", value)
    elif isinstance(value, list):
        items = [str(item) for item in value]
    else:
        raise ValueError(f"{label}必須是清單或文字")
    cleaned = []
    for item in items:
        item = item.strip()
        if item and item not in cleaned:
            cleaned.append(item[:ITEM_LIMIT])
    if len(cleaned) > LIST_LIMIT:
        raise ValueError(f"{label}最多 {LIST_LIMIT} 項")
    return cleaned


@dataclasses.dataclass
class QuestionResult:
    """一題的評測結果。

    Attributes:
        id: 題目識別碼。
        question: 問題（記下當時的文字，題目之後改了也看得懂）。
        passed: 是否通過。
        rank: 第一個應該找到的文件排第幾名（從 1 開始）；沒找到時為 None。
        missing_keywords: 沒有出現的關鍵字。
        hits: 搜尋到的出處（依名次）。
        answer: 模型的回答（有評測回答時）。
        judge: 模型評分的說明（有參考答案時）。
        reasons: 沒通過的原因。
        error: 執行出錯時的訊息。
        expects_source: 這題有沒有寫應該找到的文件（算命中率用）。
    """

    id: str
    question: str
    passed: bool
    rank: int | None = None
    missing_keywords: list[str] = dataclasses.field(default_factory=list)
    hits: list[str] = dataclasses.field(default_factory=list)
    answer: str | None = None
    judge: str | None = None
    reasons: list[str] = dataclasses.field(default_factory=list)
    error: str | None = None
    expects_source: bool = False

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


def source_matches(expected: str, hit: knowledge_lib.Hit) -> bool:
    """應該找到的文件（可以加「› 位置」）和一筆結果對不對得上。

    路徑可以是完整的相對路徑、只有檔名，或 fnmatch 樣式（hr/*.pdf）；
    有寫位置時，結果的位置要包含這段文字。
    """
    path, _, location = expected.partition("›")
    path = path.strip()
    location = location.strip()
    source = hit.chunk.source
    name = source.rsplit("/", 1)[-1]
    matched = (
        source == path
        or name == path
        or fnmatch.fnmatchcase(source, path)
        or fnmatch.fnmatchcase(name, path)
    )
    if not matched:
        return False
    return not location or location in hit.chunk.location


def _normalize(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def missing_keywords(keywords: Sequence[str], text: str) -> list[str]:
    """沒有出現在 text 裡的關鍵字（忽略空白與大小寫）。"""
    plain = _normalize(text)
    return [word for word in keywords if _normalize(word) not in plain]


async def check_question(
    bases: Sequence[knowledge_lib.KnowledgeBase],
    question: Question,
    top_k: int = 5,
    answer_model: str | None = None,
    model_fn: llm.ModelFn | None = None,
) -> QuestionResult:
    """評測一題。

    Args:
        bases: 要搜尋的知識庫（通常是一個）。
        question: 題目。
        top_k: 看前幾筆結果。
        answer_model: 評測回答用的模型；None 表示只評測檢索。
        model_fn: 模型函式，預設透過 litellm 呼叫；測試時可換成假的。
    """
    result = QuestionResult(
        question.id,
        question.question,
        passed=False,
        expects_source=bool(question.sources),
    )
    try:
        hits = await knowledge_lib.search_bases(
            bases, question.question, top_k=top_k
        )
    except Exception as error:  # noqa: BLE001 - 搜尋失敗記在這一題
        result.error = f"搜尋失敗：{error}"
        result.reasons.append(result.error)
        return result
    result.hits = [hit.citation for hit in hits]
    if question.sources:
        for rank, hit in enumerate(hits, start=1):
            if any(source_matches(item, hit) for item in question.sources):
                result.rank = rank
                break
        if result.rank is None:
            result.reasons.append(f"前 {top_k} 筆沒有應該找到的文件")
    retrieved = "\n".join(hit.chunk.text for hit in hits)
    if question.keywords and answer_model is None:
        result.missing_keywords = missing_keywords(question.keywords, retrieved)
        if result.missing_keywords:
            result.reasons.append(
                "找到的片段沒有：" + "、".join(result.missing_keywords)
            )
    if answer_model is not None:
        await _check_answer(
            result, question, hits, answer_model, model_fn or llm.complete
        )
    result.passed = not result.reasons
    return result


async def _check_answer(
    result: QuestionResult,
    question: Question,
    hits: list[knowledge_lib.Hit],
    model: str,
    model_fn: llm.ModelFn,
) -> None:
    """請模型根據搜尋結果回答，檢查關鍵字、引用，並和參考答案比對。"""
    context = knowledge_lib.format_hits(hits)
    try:
        answer = await _ask(
            model_fn,
            model,
            _ANSWER_SYSTEM,
            f"搜尋結果：\n\n{context}\n\n問題：{question.question}",
        )
    except Exception as error:  # noqa: BLE001 - 模型出錯記在這一題
        result.error = f"模型回答失敗：{llm.explain_error(error) or error}"
        result.reasons.append(result.error)
        return
    result.answer = answer
    if question.keywords:
        result.missing_keywords = missing_keywords(question.keywords, answer)
        if result.missing_keywords:
            result.reasons.append(
                "回答沒有提到：" + "、".join(result.missing_keywords)
            )
    if hits and not re.search(r"\[\d+", answer):
        result.reasons.append("回答沒有引用出處 [n]")
    if not question.answer:
        return
    try:
        verdict = await _ask(
            model_fn,
            model,
            _JUDGE_SYSTEM,
            f"問題：{question.question}\n\n參考答案：{question.answer}\n\n"
            f"回答：{answer}",
        )
    except Exception as error:  # noqa: BLE001
        result.error = f"模型評分失敗：{llm.explain_error(error) or error}"
        result.reasons.append(result.error)
        return
    passed, reason = _parse_verdict(verdict)
    result.judge = reason
    if not passed:
        result.reasons.append(f"和參考答案不一致：{reason}")


def _parse_verdict(text: str) -> tuple[bool, str]:
    """讀出評分模型回的 {"pass", "reason"}；讀不出來時當作不通過。"""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict) and isinstance(data.get("pass"), bool):
            return data["pass"], str(data.get("reason") or "").strip()
    return False, f"評分結果讀不出來：{text.strip()[:200]}"


async def _ask(
    model_fn: llm.ModelFn, model: str, system: str, user: str
) -> str:
    """呼叫一次模型（不用工具），回傳文字。"""
    messages: list[datatypes.Message] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    response = None
    async for item in model_fn(model, messages, [], {}):
        if isinstance(item, datatypes.ModelResponse):
            response = item
    if response is None:
        raise RuntimeError("模型沒有回覆")
    return str(response.message.get("content") or "").strip()


def summarize(results: Sequence[QuestionResult], top_k: int) -> dict[str, Any]:
    """整體結果：題數、通過數、通過率、命中率與 MRR。"""
    total = len(results)
    passed = sum(1 for item in results if item.passed)
    ranked = [item for item in results if item.rank is not None]
    with_sources = [item for item in results if item.expects_source]
    hit_rate = len(ranked) / len(with_sources) if with_sources else None
    mrr = (
        sum(1 / item.rank for item in ranked if item.rank) / len(with_sources)
        if with_sources
        else None
    )
    return {
        "total": total,
        "passed": passed,
        "passRate": passed / total if total else None,
        "hitRate": hit_rate,
        "mrr": mrr,
        "topK": top_k,
        "errors": sum(1 for item in results if item.error),
    }


def compare(
    previous: Sequence[dict[str, Any]] | None,
    current: Sequence[QuestionResult],
) -> dict[str, list[str]]:
    """和上一次比較：退步（上次通過、這次沒過）與改善的題目識別碼。"""
    if not previous:
        return {"regressions": [], "fixed": []}
    before = {item["id"]: bool(item.get("passed")) for item in previous}
    regressions = [
        item.id for item in current if before.get(item.id) and not item.passed
    ]
    fixed = [
        item.id
        for item in current
        if item.id in before and not before[item.id] and item.passed
    ]
    return {"regressions": regressions, "fixed": fixed}


async def run(
    bases: Sequence[knowledge_lib.KnowledgeBase],
    questions: Sequence[Question],
    top_k: int = 5,
    answer_model: str | None = None,
    model_fn: llm.ModelFn | None = None,
    previous: Sequence[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """評測整份題庫（一題一題依序，避免同時打太多模型請求）。

    Returns:
        {"summary", "results", "regressions", "fixed", "seconds"}。
    """
    started = time.monotonic()
    results = []
    for question in questions:
        results.append(
            await check_question(bases, question, top_k, answer_model, model_fn)
        )
    return {
        "summary": summarize(results, top_k),
        "results": [item.to_dict() for item in results],
        **compare(previous, results),
        "seconds": round(time.monotonic() - started, 2),
    }
