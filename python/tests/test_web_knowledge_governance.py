"""網頁版的知識庫治理：文件版本、題庫評測與資料分級。"""

import asyncio
import json

import aiohttp
import yaml

from harness import llm
from harness.web import server as server_lib
from tests import conftest
from tests import test_knowledge_bases as kb_tests
from tests import test_web_accounts
from tests.test_web_accounts import password_of

site = test_web_accounts.site
fast_hash = test_web_accounts.fast_hash

BASES = kb_tests.BASES
KNOWLEDGE_AGENT = kb_tests.KNOWLEDGE_AGENT


def workspace_of(s):
    return s.client.server.app[server_lib._WORKSPACE]  # noqa: SLF001


async def wait_eval(person, base_id):
    async with asyncio.timeout(5):
        while True:
            _, found = await person.api("GET", f"/knowledge/{base_id}/eval")
            if not found["running"] and found["runs"]:
                return found
            await asyncio.sleep(0.02)


class TestDocumentInfo:
    async def test_maintainer_sets_version_and_old_one_is_hidden(self, site):
        s = await site(extra=BASES, prepare=kb_tests.add_documents)
        boss = await s.login("boss", password_of("boss"))
        alice = await s.login("alice", password_of("alice"))
        kb_tests.write(s.root / "knowledge" / "hr" / "leave-old.md", "特休舊制")

        status, saved = await boss.api(
            "PUT",
            "/knowledge/hr/documents/info?path=leave.md",
            {
                "version": "2026 年版",
                "effective": "2020-01-01",
                "supersedes": ["leave-old.md"],
            },
        )
        _, docs = await boss.api("GET", "/knowledge/hr/documents")
        _, found = await boss.api(
            "POST", "/knowledge/hr/search", {"query": "特休"}
        )
        _, history = await boss.api(
            "POST",
            "/knowledge/hr/search",
            {"query": "特休", "allVersions": True},
        )
        refused, _ = await alice.api(
            "PUT", "/knowledge/hr/documents/info?path=leave.md", {}
        )
        bad, error = await boss.api(
            "PUT",
            "/knowledge/hr/documents/info?path=leave.md",
            {"supersedes": ["leave.md"]},
        )

        by_path = {item["path"]: item for item in docs["documents"]}
        assert status == 200 and saved["status"] == "active"
        assert by_path["leave-old.md"]["status"] == "superseded"
        assert by_path["leave-old.md"]["supersededBy"] == ["leave.md"]
        assert by_path["leave.md"]["version"]["version"] == "2026 年版"
        assert [hit["source"] for hit in found["hits"]] == ["leave.md"]
        assert found["hits"][0]["version"].startswith("2026 年版")
        assert len(history["hits"]) == 2
        assert refused == 403
        assert bad == 400 and "取代自己" in error["error"]
        written = yaml.safe_load(
            (s.root / "knowledge" / "hr" / "documents.yaml").read_text()
        )
        assert written["leave.md"]["supersedes"] == ["leave-old.md"]


class TestEvaluation:
    async def test_questions_run_and_auto_rerun_after_upload(self, site):
        s = await site(extra=BASES, prepare=kb_tests.add_documents)
        workspace_of(s).evals._delay = 0  # noqa: SLF001
        boss = await s.login("boss", password_of("boss"))
        alice = await s.login("alice", password_of("alice"))

        added, question = await boss.api(
            "POST",
            "/knowledge/hr/eval/questions",
            {
                "question": "特休怎麼算",
                "sources": "leave.md",
                "keywords": "半年",
            },
        )
        started, run = await boss.api("POST", "/knowledge/hr/eval/run", {})
        first = await wait_eval(boss, "hr")
        _, detail = await boss.api(
            "GET", f"/knowledge/hr/eval/runs/{run['id']}"
        )
        forbidden, _ = await alice.api("GET", "/knowledge/hr/eval")

        # 刪掉文件後自動再評測一次，那一題退步。
        await boss.api("DELETE", "/knowledge/hr/documents?path=leave.md")
        async with asyncio.timeout(5):
            while True:
                _, found = await boss.api("GET", "/knowledge/hr/eval")
                if len(found["runs"]) == 2 and not found["running"]:
                    break
                await asyncio.sleep(0.02)
        _, listed = await boss.api("GET", "/knowledge")

        assert added == 201 and question["sources"] == ["leave.md"]
        assert started == 201
        assert first["runs"][0]["summary"]["passed"] == 1
        assert detail["results"][0]["rank"] == 1
        assert detail["settings"]["searchMode"] == "bm25"
        assert forbidden == 403
        latest = found["runs"][0]
        assert latest["trigger"] == "刪除文件"
        assert latest["startedBy"] == "自動"
        assert latest["regressions"] == [question["id"]]
        hr = next(item for item in listed["bases"] if item["id"] == "hr")
        assert hr["evaluation"]["questions"] == 1
        assert hr["evaluation"]["latest"]["regressions"] == 1

    async def test_import_and_export(self, site):
        s = await site(extra=BASES, prepare=kb_tests.add_documents)
        boss = await s.login("boss", password_of("boss"))
        form = aiohttp.FormData()
        form.add_field(
            "file",
            "問題,應該找到的文件,關鍵字\n特休?,leave.md,三天\nVPN?,vpn.md,\n",
            filename="題庫.csv",
        )

        response = await s.client.post(
            "/api/knowledge/hr/eval/import?replace=1",
            data=form,
            headers={**boss.headers, "X-Harness-Upload": "1"},
        )
        imported = await response.json()
        exported = await s.client.get(
            "/api/knowledge/hr/eval/export", headers=boss.headers
        )
        text = await exported.text()

        assert response.status == 201 and imported == {"added": 2}
        assert "特休?" in text and "vpn.md" in text
        assert exported.headers["Content-Type"].startswith("text/csv")


CLASSIFIED = (
    BASES
    + """
dataClassification:
  defaultClearance: internal
  models:
    local-gemma: confidential
  routeTo: local-gemma
"""
)


class TestClassification:
    async def test_confidential_knowledge_switches_to_the_local_model(
        self, site
    ):
        s = await site(
            agent=KNOWLEDGE_AGENT,
            extra=CLASSIFIED,
            prepare=kb_tests.add_documents,
            script=[
                *kb_tests.search_script(),
                conftest.text_response("第二輪"),
            ],
        )
        boss = await s.login("boss", password_of("boss"))
        _, settings = await boss.api("GET", "/admin/classification")
        settings["knowledgeBases"] = {"hr": "confidential"}
        saved, after = await boss.api("PUT", "/admin/classification", settings)

        _, created = await boss.api(
            "POST",
            "/sessions",
            {"text": "特休", "options": {"knowledge": ["hr"]}},
        )
        detail = await boss.wait_idle(created["id"])
        await boss.api(
            "POST", f"/sessions/{created['id']}/messages", {"text": "再說一次"}
        )
        again = await boss.wait_idle(created["id"])

        default = llm.default_model()
        models = [request["model"] for request in s.model.requests]
        assert saved == 200
        assert after["knowledgeBases"] == {"hr": "confidential"}
        assert models == [default, "local-gemma", "local-gemma"]
        info = detail["summary"]["classification"]
        assert info["name"] == "機密" and info["model"] == "local-gemma"
        assert info["sources"] == ["知識庫「人資規章」"]
        assert again["summary"]["classification"]["level"] == "confidential"
        meta = next((s.root / ".harness").rglob(f"{created['id']}.meta.json"))
        assert json.loads(meta.read_text())["classification"]["model"] == (
            "local-gemma"
        )
        config = yaml.safe_load((s.root / "harness.yaml").read_text())
        assert config["knowledgeBases"]["hr"]["classification"] == (
            "confidential"
        )

    async def test_disabling_removes_levels_and_members_cannot_edit(self, site):
        s = await site(extra=CLASSIFIED, prepare=kb_tests.add_documents)
        boss = await s.login("boss", password_of("boss"))
        alice = await s.login("alice", password_of("alice"))
        _, settings = await boss.api("GET", "/admin/classification")
        await boss.api(
            "PUT",
            "/admin/classification",
            {**settings, "knowledgeBases": {"it": "confidential"}},
        )

        off, _ = await boss.api(
            "PUT", "/admin/classification", {**settings, "enabled": False}
        )
        bad, error = await boss.api(
            "PUT",
            "/admin/classification",
            {**settings, "routeTo": "x", "models": {"x": "top-secret"}},
        )
        refused, _ = await alice.api("GET", "/admin/classification")

        config = yaml.safe_load((s.root / "harness.yaml").read_text())
        assert off == 200
        assert "dataClassification" not in config
        assert "classification" not in config["knowledgeBases"]["it"]
        assert bad == 400 and "top-secret" in error["error"]
        assert refused == 403
