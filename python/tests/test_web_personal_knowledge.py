"""個人知識庫：使用者自己建立、只有自己能用的知識庫。"""

import io

import aiohttp
import pypdf

from tests import conftest
from tests import test_knowledge_bases as kb_tests
from tests import test_web_accounts
from tests.test_web_accounts import password_of

site = test_web_accounts.site
fast_hash = test_web_accounts.fast_hash

BASES = kb_tests.BASES
KNOWLEDGE_AGENT = kb_tests.KNOWLEDGE_AGENT


async def upload(s, person, base_id, name, data, query=""):
    form = aiohttp.FormData()
    form.add_field("file", data, filename=name)
    response = await s.client.post(
        f"/api/my/knowledge/{base_id}/documents{query}",
        data=form,
        headers={**person.headers, "X-Harness-Upload": "1"},
    )
    return response.status, await response.json()


async def create(person, name="我的筆記", **extra):
    return await person.api("POST", "/my/knowledge", {"name": name, **extra})


class TestPersonalKnowledge:
    async def test_owner_creates_uploads_and_searches_in_chat(self, site):
        s = await site(
            agent=KNOWLEDGE_AGENT,
            extra=BASES,
            prepare=kb_tests.add_documents,
            script=kb_tests.search_script(),
        )
        alice = await s.login("alice", password_of("alice"))

        status, created = await create(
            alice, "專案筆記", description="會議紀錄", chunking="regulation"
        )
        base_id = created["id"]
        uploaded, saved = await upload(
            s, alice, base_id, "會議 紀錄.md", "特休專案：下週一上線。"
        )
        _, docs = await alice.api("GET", f"/my/knowledge/{base_id}/documents")
        _, listed = await alice.api("GET", "/my/knowledge")
        _, project = await alice.api("GET", "/project")
        found = await kb_tests.run_search(s, alice, {"knowledge": [base_id]})

        assert status == 201 and base_id.startswith("my-")
        assert created["chunking"] == "regulation"
        assert uploaded == 201 and saved["files"][0]["path"] == "會議_紀錄.md"
        assert docs["documents"][0]["chunks"] == 1
        assert [b["name"] for b in listed["mine"]] == ["專案筆記"]
        assert listed["mine"][0]["documents"] == 1
        assert listed["usedBytes"] == len("特休專案：下週一上線。".encode())
        assert [b["id"] for b in listed["company"]] == ["default", "hr", "it"]
        assert listed["company"][0]["documents"] == 1
        assert listed["company"][0]["manage"] is False
        assert project["features"]["personalKnowledge"] is True
        assert project["knowledgeBases"][-1] == {
            "id": base_id,
            "name": "專案筆記",
            "description": "會議紀錄",
            "personal": True,
        }
        assert "來源：會議_紀錄.md" in found
        assert (
            s.root
            / ".harness"
            / "personal-knowledge"
            / base_id
            / "會議_紀錄.md"
        ).exists()

    async def test_only_the_owner_can_see_or_use_it(self, site):
        s = await site(
            agent=KNOWLEDGE_AGENT,
            prepare=kb_tests.add_documents,
            script=[conftest.text_response("好")],
        )
        alice = await s.login("alice", password_of("alice"))
        bob = await s.login("bob", password_of("bob"))
        boss = await s.login("boss", password_of("boss"))
        _, created = await create(alice)
        base_id = created["id"]
        await upload(s, alice, base_id, "a.md", "特休祕密")

        _, bob_list = await bob.api("GET", "/my/knowledge")
        _, bob_project = await bob.api("GET", "/project")
        docs, _ = await bob.api("GET", f"/my/knowledge/{base_id}/documents")
        renamed, _ = await bob.api(
            "PATCH", f"/my/knowledge/{base_id}", {"name": "x"}
        )
        removed, _ = await bob.api("DELETE", f"/my/knowledge/{base_id}")
        uploaded, _ = await upload(s, bob, base_id, "b.md", "x")
        boss_docs, _ = await boss.api(
            "GET", f"/my/knowledge/{base_id}/documents"
        )
        chat, error = await bob.api(
            "POST",
            "/sessions",
            {"text": "x", "options": {"knowledge": [base_id]}},
        )
        source = await s.client.get(
            "/api/knowledge/source?base=我的筆記&path=a.md",
            headers=bob.headers,
        )
        own_source = await s.client.get(
            "/api/knowledge/source?base=我的筆記&path=a.md",
            headers=alice.headers,
        )

        assert bob_list["mine"] == []
        assert base_id not in [b["id"] for b in bob_project["knowledgeBases"]]
        assert docs == renamed == removed == uploaded == boss_docs == 404
        assert chat == 400 and base_id in error["error"]
        assert source.status == 404
        assert own_source.status == 200
        assert await own_source.text() == "特休祕密"

    async def test_groups_do_not_hide_own_bases(self, site):
        s = await site(
            agent=KNOWLEDGE_AGENT,
            extra=BASES,
            prepare=kb_tests.add_documents,
            script=kb_tests.search_script(),
        )
        boss = await s.login("boss", password_of("boss"))
        alice = await s.login("alice", password_of("alice"))
        await boss.api(
            "PATCH", "/admin/groups/everyone", {"knowledgeBases": ["hr"]}
        )
        _, created = await create(alice)
        await upload(s, alice, created["id"], "a.md", "特休自己的資料")

        _, listed = await alice.api("GET", "/my/knowledge")
        found = await kb_tests.run_search(
            s, alice, {"knowledge": ["hr", created["id"]]}
        )

        assert [b["id"] for b in listed["company"]] == ["hr"]
        assert "人資規章 / leave.md" in found
        assert "我的筆記 / a.md" in found

    async def test_explains_documents_without_text(self, site):
        s = await site(script=[conftest.text_response("好")])
        alice = await s.login("alice", password_of("alice"))
        _, created = await create(alice)
        base_id = created["id"]
        writer = pypdf.PdfWriter()
        writer.add_blank_page(width=200, height=200)
        scanned = io.BytesIO()
        writer.write(scanned)
        await upload(s, alice, base_id, "掃描.pdf", scanned.getvalue())
        await upload(s, alice, base_id, "空白.md", "   ")
        await upload(s, alice, base_id, "有字.md", "內容")

        _, docs = await alice.api("GET", f"/my/knowledge/{base_id}/documents")

        notes = {item["path"]: item.get("note") for item in docs["documents"]}
        assert "掃描檔" in notes["掃描.pdf"]
        assert "沒有讀到文字" in notes["空白.md"]
        assert notes["有字.md"] is None

    async def test_rename_and_delete(self, site):
        s = await site(script=[conftest.text_response("好")])
        alice = await s.login("alice", password_of("alice"))
        _, created = await create(alice)
        base_id = created["id"]
        await upload(s, alice, base_id, "a.md", "內容")
        folder = s.root / ".harness" / "personal-knowledge" / base_id

        renamed, info = await alice.api(
            "PATCH",
            f"/my/knowledge/{base_id}",
            {"name": "新名稱", "description": "說明"},
        )
        bad, error = await alice.api(
            "PATCH", f"/my/knowledge/{base_id}", {"sharedWith": ["x"]}
        )
        removed_doc, _ = await alice.api(
            "DELETE", f"/my/knowledge/{base_id}/documents?path=a.md"
        )
        deleted, _ = await alice.api("DELETE", f"/my/knowledge/{base_id}")
        _, listed = await alice.api("GET", "/my/knowledge")
        _, made = await alice.api(
            "POST", "/sessions", {"text": "嗨", "options": {"knowledge": []}}
        )

        assert renamed == 200 and info["name"] == "新名稱"
        assert bad == 400 and "sharedWith" in error["error"]
        assert removed_doc == 200 and deleted == 200
        assert listed["mine"] == [] and not folder.exists()

    async def test_limits(self, site):
        extra = (
            "personalKnowledge:\n"
            "  maxBases: 1\n"
            "  maxDocuments: 2\n"
            "  maxFileMB: 1\n"
            "  maxTotalMB: 1\n"
        )
        s = await site(extra=extra)
        alice = await s.login("alice", password_of("alice"))
        _, created = await create(alice)
        base_id = created["id"]

        second, error = await create(alice, "第二個")
        first, _ = await upload(s, alice, base_id, "a.md", "a" * 600_000)
        quota, quota_error = await upload(
            s, alice, base_id, "b.md", "b" * 600_000
        )
        small, _ = await upload(s, alice, base_id, "c.md", "c")
        count, count_error = await upload(s, alice, base_id, "d.md", "d")
        replaced, _ = await upload(
            s, alice, base_id, "e.md", "e" * 500_000, "?replace=a.md"
        )
        _, listed = await alice.api("GET", "/my/knowledge")

        assert second == 400 and "最多 1 個" in error["error"]
        assert first == 201
        assert quota == 413 and "空間已經用完" in quota_error["error"]
        assert small == 201
        assert count == 413 and "最多 2 份" in count_error["error"]
        assert replaced == 201
        assert listed["limits"]["maxDocuments"] == 2
        assert listed["limits"]["maxTotalBytes"] == 1024 * 1024

    async def test_admin_can_turn_it_off(self, site):
        s = await site(
            extra="personalKnowledge: false\n",
            script=[conftest.text_response("好")],
        )
        alice = await s.login("alice", password_of("alice"))

        status, error = await create(alice)
        _, project = await alice.api("GET", "/project")
        _, listed = await alice.api("GET", "/my/knowledge")

        assert status == 403 and "沒有開放" in error["error"]
        assert project["features"]["personalKnowledge"] is False
        assert listed["limits"]["enabled"] is False

    async def test_company_ids_cannot_use_the_personal_prefix(self, site):
        s = await site()
        boss = await s.login("boss", password_of("boss"))

        status, error = await boss.api(
            "POST", "/knowledge", {"id": "my-notes", "name": "x"}
        )

        assert status == 400 and "my-" in error["error"]

    async def test_actions_are_audited(self, site):
        s = await site()
        boss = await s.login("boss", password_of("boss"))
        alice = await s.login("alice", password_of("alice"))
        _, created = await create(alice)
        await upload(s, alice, created["id"], "a.md", "x")
        await alice.api("DELETE", f"/my/knowledge/{created['id']}")

        _, page = await boss.api("GET", "/admin/audit?category=knowledge")

        assert [entry["action"] for entry in page["entries"]] == [
            "knowledge.personal_delete",
            "knowledge.personal_upload",
            "knowledge.personal_create",
        ]


class TestUserAgents:
    """自建 agent 可以選自己的個人知識庫：兩者都只有建立者能用。"""

    async def test_own_agent_can_search_own_base(self, site):
        s = await site(
            agent=KNOWLEDGE_AGENT,
            prepare=kb_tests.add_documents,
            script=kb_tests.search_script(),
        )
        alice = await s.login("alice", password_of("alice"))
        _, created = await create(alice, "專案筆記")
        base_id = created["id"]
        await upload(s, alice, base_id, "a.md", "特休自己的筆記")

        status, agent = await alice.api(
            "POST", "/agents", {"name": "筆記助手", "knowledgeBases": [base_id]}
        )
        _, summary = await alice.api(
            "POST", "/sessions", {"text": "特休", "agent": agent["key"]}
        )
        await alice.wait_idle(summary["id"])

        assert status == 201 and agent["knowledgeBases"] == [base_id]
        found = s.model.requests[-1]["messages"][-1]["content"]
        assert "特休自己的筆記" in found

    async def test_others_cannot_pick_it_and_names_stay_hidden(self, site):
        s = await site(
            agent=KNOWLEDGE_AGENT,
            extra=BASES,
            prepare=kb_tests.add_documents,
        )
        boss = await s.login("boss", password_of("boss"))
        alice = await s.login("alice", password_of("alice"))
        bob = await s.login("bob", password_of("bob"))
        _, created = await create(alice, "祕密筆記")
        await boss.api(
            "PATCH", "/admin/groups/everyone", {"knowledgeBases": ["it"]}
        )

        other, other_error = await bob.api(
            "POST",
            "/agents",
            {"name": "x", "knowledgeBases": [created["id"]]},
        )
        company, company_error = await bob.api(
            "POST", "/agents", {"name": "x", "knowledgeBases": ["hr"]}
        )

        assert other == 400 and created["id"] in other_error["error"]
        assert "祕密筆記" not in other_error["error"]
        assert company == 400 and "人資規章" in company_error["error"]

    async def test_deleted_or_disabled_bases_are_skipped(self, site):
        s = await site(
            agent=KNOWLEDGE_AGENT,
            prepare=kb_tests.add_documents,
            script=[conftest.text_response("好")],
        )
        alice = await s.login("alice", password_of("alice"))
        _, created = await create(alice)
        await upload(s, alice, created["id"], "a.md", "內容")
        _, agent = await alice.api(
            "POST",
            "/agents",
            {"name": "a", "knowledgeBases": [created["id"]]},
        )
        await alice.api("DELETE", f"/my/knowledge/{created['id']}")

        _, summary = await alice.api(
            "POST", "/sessions", {"text": "嗨", "agent": agent["key"]}
        )
        await alice.wait_idle(summary["id"])

        names = [
            tool["function"]["name"]
            for tool in s.model.requests[0].get("tools") or []
        ]
        assert "search_knowledge" not in names
