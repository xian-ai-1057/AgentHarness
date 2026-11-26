"""知識庫治理：文件版本與生效期間、資料分級、題庫回歸評測（核心邏輯）。"""

import asyncio
import datetime
import io
import zipfile

import pytest
import yaml

from harness import classification
from harness import knowledge as knowledge_lib
from harness import knowledge_eval
from harness import project as project_lib
from harness.web import knowledge_eval as eval_web
from tests import conftest
from tests.test_knowledge_bases import write

D = datetime.date


def versioned(tmp_path):
    """人資規章：2025 年版被 2026 年版取代，另有一份還沒生效的草案。"""
    folder = tmp_path / "kb"
    write(folder / "leave-2025.md", "特休規定：滿一年七天。")
    write(folder / "leave-2026.md", "特休規定：滿一年十天。")
    write(
        folder / "draft.md",
        "---\nversion: 草案\neffective: 2027-01-01\n---\n"
        "特休規定：滿一年十二天。",
    )
    write(folder / "old.md", "加班：舊的辦法。")
    (folder / knowledge_lib.DOCUMENTS_FILE).write_text(
        yaml.safe_dump(
            {
                "leave-2026.md": {
                    "version": "2026 年版",
                    "effective": "2026-01-01",
                    "supersedes": ["leave-2025.md"],
                },
                "leave-2025.md": {"version": "2025 年版"},
                "old.md": {"expires": "2026-06-01"},
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    return knowledge_lib.Knowledge(folder)


def sources(hits):
    return sorted(hit.chunk.source for hit in hits)


class TestDocumentVersions:
    async def test_only_documents_in_force_are_found(self, tmp_path):
        kb = versioned(tmp_path)

        today = await kb.search("特休規定", as_of=D(2026, 11, 26))
        last_year = await kb.search("特休規定", as_of=D(2025, 6, 1))
        future = await kb.search("特休規定", as_of=D(2027, 2, 1))
        everything = await kb.search("特休規定", all_versions=True)
        overtime_before = await kb.search("加班", as_of=D(2026, 5, 31))
        overtime_after = await kb.search("加班", as_of=D(2026, 6, 1))

        assert sources(today) == ["leave-2026.md"]
        assert sources(last_year) == ["leave-2025.md"]
        # 草案生效後也不會取代 2026 年版（沒有寫 supersedes），兩份都在。
        assert sources(future) == ["draft.md", "leave-2026.md"]
        assert len(everything) == 3
        assert sources(overtime_before) == ["old.md"]
        assert overtime_after == []

    async def test_status_and_superseded_by(self, tmp_path):
        kb = versioned(tmp_path)
        await kb.chunks()
        day = D(2026, 11, 26)

        assert kb.document_status("leave-2026.md", day) == "active"
        assert kb.document_status("leave-2025.md", day) == "superseded"
        assert kb.document_status("draft.md", day) == "pending"
        assert kb.document_status("old.md", day) == "expired"
        assert kb.superseded_by("leave-2025.md", day) == ["leave-2026.md"]
        # frontmatter 的版本資訊也讀得到，documents.yaml 不算文件。
        assert kb.document_infos()["draft.md"].version == "草案"
        assert knowledge_lib.DOCUMENTS_FILE not in kb.files()

    async def test_results_show_the_version(self, tmp_path):
        kb = versioned(tmp_path)
        hits = await kb.search("特休規定", as_of=D(2026, 11, 26))

        text = knowledge_lib.format_hits(hits)
        dated = knowledge_lib.format_hits(hits, as_of=D(2025, 1, 1))

        assert (
            "[1] 來源：leave-2026.md\n版本：2026 年版，2026-01-01 起生效\n"
            in text
        )
        assert dated.endswith("（查詢 2025-01-01 當時有效的文件）")

    async def test_save_document_info_rewrites_the_file(self, tmp_path):
        kb = versioned(tmp_path)
        await kb.chunks()

        kb.save_document_info(
            "old.md",
            knowledge_lib.DocumentInfo(version="v2", effective=D(2026, 1, 1)),
        )
        kb.save_document_info("leave-2025.md", knowledge_lib.DocumentInfo())
        saved = yaml.safe_load(
            (kb.path / knowledge_lib.DOCUMENTS_FILE).read_text("utf-8")
        )

        assert saved["old.md"] == {"version": "v2", "effective": "2026-01-01"}
        assert "leave-2025.md" not in saved
        assert kb.document_status("old.md", D(2026, 11, 26)) == "active"

    def test_bad_info_is_rejected(self):
        with pytest.raises(ValueError, match="失效日必須晚於生效日"):
            knowledge_lib.parse_document_info(
                {"effective": "2026-02-01", "expires": "2026-01-01"}
            )
        with pytest.raises(ValueError, match="YYYY-MM-DD"):
            knowledge_lib.parse_document_info({"effective": "明年"})
        with pytest.raises(ValueError, match="不認得的欄位"):
            knowledge_lib.parse_document_info({"owner": "人資"})

    async def test_tool_takes_as_of(self, tmp_path, context):
        kb = versioned(tmp_path)
        tool = knowledge_lib.search_tool(
            [knowledge_lib.KnowledgeBase("hr", "人資規章", kb)]
        )

        found = await tool.func(context, "特休規定", "2025-03-01")

        assert "leave-2025.md" in found and "leave-2026.md" not in found
        assert "as_of" in tool.parameters["properties"]


def policy():
    return classification.load_policy(
        {
            "defaultClearance": "internal",
            "models": {"local-gemma": "confidential"},
            "routeTo": "local-gemma",
            "toolsets": {"assets": "confidential"},
        }
    )


class TestClassification:
    def test_policy_levels_and_clearance(self):
        rules = policy()

        assert [level.name for level in rules.levels] == [
            "公開",
            "內部",
            "機密",
        ]
        assert rules.clearance("cloud-model") == rules.rank("internal")
        assert rules.allows("local-gemma", rules.rank("confidential"))
        assert not rules.allows("cloud-model", rules.rank("confidential"))
        assert rules.pick(rules.rank("confidential")) == "local-gemma"
        assert classification.load_policy(None) is None
        with pytest.raises(ValueError, match="不在 levels 裡"):
            classification.load_policy({"routeTo": "x", "models": {"a": "top"}})

    async def test_model_is_switched_when_data_is_classified(self):
        model = conftest.FakeModel(
            [conftest.text_response("一"), conftest.text_response("二")]
        )
        tracker = classification.Tracker(policy())
        routes = []
        routed = classification.routed_model_fn(
            model, tracker, on_route=lambda a, b: routes.append((a, b))
        )

        async for _ in routed("cloud-model", [], [], {}):
            pass
        tracker.note("confidential", "知識庫「人資」")
        async for _ in routed("cloud-model", [], [], {}):
            pass

        assert [r["model"] for r in model.requests] == [
            "cloud-model",
            "local-gemma",
        ]
        assert routes == [("cloud-model", "local-gemma")]
        assert tracker.model == "local-gemma" and tracker.routed

    async def test_stops_when_no_model_can_handle_it(self):
        rules = classification.load_policy(
            {"defaultClearance": "public", "models": {}}
        )
        tracker = classification.Tracker(rules, level="internal")
        model = conftest.FakeModel([conftest.text_response("不該呼叫")])
        routed = classification.routed_model_fn(model, tracker)

        with pytest.raises(
            classification.ClassificationError, match="沒有送出"
        ):
            routed("cloud-model", [], [], {})
        assert model.requests == []

    async def test_knowledge_search_notes_the_level(self, tmp_path, context):
        write(tmp_path / "kb" / "pay.md", "薪資：每月五號發放。")
        base = knowledge_lib.KnowledgeBase(
            "hr",
            "人資規章",
            knowledge_lib.Knowledge(tmp_path / "kb"),
            classification="confidential",
        )
        tool = knowledge_lib.search_tool([base])
        tracker = classification.Tracker(policy())

        async def run(query):
            classification.set_tracker(tracker)
            return await tool.func(context, query)

        await asyncio.create_task(run("沒有這個字詞的查詢zzz"))
        nothing = tracker.level
        await asyncio.create_task(run("薪資"))

        assert nothing is None
        assert tracker.level == "confidential"
        assert tracker.sources == ["知識庫「人資規章」"]

    async def test_classified_tool_notes_after_running(self, add_tool):
        tracker = classification.Tracker(policy())
        wrapped = classification.classified_tool(
            add_tool, "confidential", "工具組「assets」"
        )

        async def run():
            classification.set_tracker(tracker)
            return await wrapped.func(1, 2)

        assert await asyncio.create_task(run()) == 3
        assert tracker.level == "confidential"

    def test_knowledge_base_level_must_exist(self, tmp_path):
        write(tmp_path / "knowledge" / "a.md", "內容")
        config = {
            "knowledge": {"classification": "secret"},
            "dataClassification": {},
        }
        with pytest.raises(ValueError, match="不在等級裡"):
            project_lib.load_knowledge_bases(tmp_path, config)
        config["knowledge"]["classification"] = "confidential"
        bases = project_lib.load_knowledge_bases(tmp_path, config)
        assert bases["default"].classification == "confidential"
        with pytest.raises(ValueError, match="沒有 dataClassification"):
            project_lib.load_knowledge_bases(
                tmp_path, {"knowledge": {"classification": "confidential"}}
            )


def leave_base(tmp_path):
    folder = tmp_path / "eval-kb"
    write(
        folder / "hr" / "leave.md", "# 特休\n\n特休：滿半年三天，滿一年七天。"
    )
    write(folder / "it" / "vpn.md", "# VPN\n\nVPN 申請要找資訊處。")
    return knowledge_lib.KnowledgeBase(
        "hr", "人資", knowledge_lib.Knowledge(folder)
    )


class TestEvaluation:
    async def test_retrieval_checks_sources_and_keywords(self, tmp_path):
        base = leave_base(tmp_path)
        questions = [
            knowledge_eval.Question(
                "q1", "特休怎麼算", ["hr/leave.md › 特休"], ["七天"]
            ),
            knowledge_eval.Question("q2", "VPN 要找誰", ["leave.md"]),
            knowledge_eval.Question("q3", "特休天數", [], ["十天"]),
        ]

        report = await knowledge_eval.run([base], questions, top_k=1)
        results = {item["id"]: item for item in report["results"]}

        assert results["q1"]["passed"] and results["q1"]["rank"] == 1
        assert not results["q2"]["passed"]
        assert results["q2"]["reasons"] == ["前 1 筆沒有應該找到的文件"]
        assert results["q3"]["missing_keywords"] == ["十天"]
        assert report["summary"]["passed"] == 1
        assert report["summary"]["hitRate"] == 0.5
        assert report["summary"]["mrr"] == 0.5

    async def test_regressions_against_the_previous_run(self, tmp_path):
        base = leave_base(tmp_path)
        question = knowledge_eval.Question("q1", "特休怎麼算", ["leave.md"])
        first = await knowledge_eval.run([base], [question])
        (tmp_path / "eval-kb" / "hr" / "leave.md").unlink()

        second = await knowledge_eval.run(
            [base], [question], previous=first["results"]
        )

        assert first["summary"]["passed"] == 1
        assert second["regressions"] == ["q1"] and second["fixed"] == []

    async def test_answer_check_with_a_model(self, tmp_path):
        base = leave_base(tmp_path)
        model = conftest.FakeModel(
            [
                conftest.text_response("滿一年七天 [1]。"),
                conftest.text_response('{"pass": false, "reason": "天數不同"}'),
            ]
        )
        question = knowledge_eval.Question(
            "q1", "特休怎麼算", ["leave.md"], ["七天"], "滿一年十天"
        )

        result = await knowledge_eval.check_question(
            [base], question, answer_model="m", model_fn=model
        )

        assert result.answer == "滿一年七天 [1]。"
        assert result.judge == "天數不同"
        assert result.reasons == ["和參考答案不一致：天數不同"]
        assert "搜尋結果" in model.requests[0]["messages"][1]["content"]

    def test_checked_question(self):
        item = knowledge_eval.checked_question(
            {
                "question": " 特休？ ",
                "sources": "a.md, b.md",
                "keywords": "三天",
            }
        )
        assert item == {
            "question": "特休？",
            "sources": ["a.md", "b.md"],
            "keywords": ["三天"],
            "answer": "",
        }
        with pytest.raises(ValueError, match="至少填寫"):
            knowledge_eval.checked_question({"question": "只有問題"})


def xlsx(rows):
    """最小的 Excel 檔：只寫有值的儲存格（空格不寫，模擬 Excel 的行為）。"""
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    cells = []
    for r, row in enumerate(rows, start=1):
        parts = []
        for c, value in enumerate(row):
            if value:
                ref = f"{chr(65 + c)}{r}"
                parts.append(
                    f'<c r="{ref}" t="inlineStr"><is><t>{value}</t></is></c>'
                )
        cells.append(f'<row r="{r}">{"".join(parts)}</row>')
    sheet = (
        f'<worksheet xmlns="{ns}"><sheetData>{"".join(cells)}'
        "</sheetData></worksheet>"
    )
    workbook = (
        f'<workbook xmlns="{ns}"><sheets><sheet name="題庫" sheetId="1"/>'
        "</sheets></workbook>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/worksheets/sheet1.xml", sheet)
    return buffer.getvalue()


class TestImport:
    def test_csv_and_excel(self):
        csv_items = eval_web.parse_import(
            "題庫.csv",
            "問題,應該找到的文件,關鍵字\n特休?,leave.md,七天\n".encode(),
        )
        excel_items = eval_web.parse_import(
            "題庫.xlsx",
            xlsx(
                [
                    ["問題", "文件", "關鍵字", "參考答案"],
                    ["特休?", "", "", "七天"],
                ]
            ),
        )

        assert csv_items[0]["sources"] == ["leave.md"]
        assert excel_items[0]["answer"] == "七天"
        assert excel_items[0]["sources"] == []
        with pytest.raises(eval_web.EvalError, match="第 2 列"):
            eval_web.parse_import("x.csv", "問題\n只有問題\n".encode())
        with pytest.raises(eval_web.EvalError, match="問題"):
            eval_web.parse_import("x.csv", b"a,b\n1,2\n")

    def test_export_round_trip(self, tmp_path):
        store = eval_web.EvalStore(tmp_path / "harness.db")
        store.add(
            "hr",
            [
                {
                    "question": "特休?",
                    "sources": ["a.md", "b.md"],
                    "keywords": ["七天"],
                    "answer": "",
                }
            ],
        )

        text = eval_web.export_csv(store.questions("hr"))
        again = eval_web.parse_import("x.csv", text.encode("utf-8"))

        assert again[0]["sources"] == ["a.md", "b.md"]
        assert again[0]["keywords"] == ["七天"]


class TestToday:
    def test_uses_tz_and_falls_back_on_unknown_zone(self, monkeypatch):
        monkeypatch.setenv("TZ", "Asia/Taipei")
        taipei = knowledge_lib.today()
        monkeypatch.setenv("TZ", "No/Such_Zone")
        fallback = knowledge_lib.today()

        assert isinstance(taipei, datetime.date)
        assert isinstance(fallback, datetime.date)
