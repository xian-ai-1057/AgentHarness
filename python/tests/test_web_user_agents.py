"""自建 Agent：每個人建立自己的 agent，只能挑自己能用的工具組、知識庫與技能。"""

import pathlib

import pytest

from harness.web import user_agents as user_agents_lib
from tests import conftest
from tests import test_web
from tests import test_web_accounts
from tests.test_web_accounts import password_of
from tests.test_web_groups import KNOWLEDGE_AGENT

site = test_web_accounts.site
start = test_web.start
fast_hash = test_web_accounts.fast_hash

LAWYER = {
    "name": "合約小幫手",
    "description": "檢查合約條款",
    "instructions": "你只回答合約相關的問題。\n用條列回覆。",
    "starters": ["幫我看這份合約有沒有風險", "  "],
    "toolsets": ["files"],
}


def add_documents(root: pathlib.Path) -> None:
    folder = root / "knowledge"
    folder.mkdir()
    (folder / "rules.md").write_text("請假要提前三天申請。", "utf-8")


def tool_names(request) -> list[str]:
    return [tool["function"]["name"] for tool in request.get("tools") or []]


class TestUserAgentStore:
    def test_create_update_delete(self, tmp_path):
        store = user_agents_lib.UserAgentStore.for_project(tmp_path)

        created = store.create("u1", LAWYER)
        updated = store.update(created.id, {"name": " 新 名稱 ", "model": ""})
        owned = store.owned_by("u1")
        deleted = store.delete(created.id)

        assert created.key == f"user:{created.id}"
        assert created.starters == ("幫我看這份合約有沒有風險",)
        assert created.instructions == LAWYER["instructions"]
        assert updated.name == "新 名稱" and updated.model is None
        assert [item.id for item in owned] == [created.id]
        assert deleted.id == created.id
        assert store.get(created.id) is None

    @pytest.mark.parametrize(
        "values",
        [
            {},
            {"name": "  "},
            {"name": "x" * 41},
            {"name": "a", "starters": ["1", "2", "3", "4", "5"]},
            {"name": "a", "toolsets": "files"},
            {"name": "a", "model": 3},
        ],
    )
    def test_bad_values_are_refused(self, tmp_path, values):
        store = user_agents_lib.UserAgentStore.for_project(tmp_path)

        with pytest.raises(user_agents_lib.UserAgentError):
            store.create("u1", values)


class TestApi:
    async def test_only_owner_sees_and_changes_own_agents(self, site):
        s = await site()
        alice = await s.login("alice", password_of("alice"))
        bob = await s.login("bob", password_of("bob"))
        boss = await s.login("boss", password_of("boss"))

        status, created = await alice.api("POST", "/agents", LAWYER)
        _, alice_list = await alice.api("GET", "/agents")
        _, bob_list = await bob.api("GET", "/agents")
        _, alice_project = await alice.api("GET", "/project")
        _, bob_project = await bob.api("GET", "/project")
        bob_patch, _ = await bob.api(
            "PATCH", f"/agents/{created['id']}", {"name": "偷改"}
        )
        boss_delete, _ = await boss.api("DELETE", f"/agents/{created['id']}")
        bob_use, _ = await bob.api(
            "POST", "/sessions", {"text": "嗨", "agent": created["key"]}
        )

        assert status == 201
        assert [item["id"] for item in alice_list["agents"]] == [created["id"]]
        assert bob_list["agents"] == []
        mine = [a for a in alice_project["agents"] if a.get("custom")]
        assert mine[0]["name"] == created["key"]
        assert mine[0]["label"] == "合約小幫手"
        assert mine[0]["custom"]["starters"] == ["幫我看這份合約有沒有風險"]
        # 指示不會出現在專案資訊裡。
        assert "instructions" not in mine[0]
        assert not any(a.get("custom") for a in bob_project["agents"])
        assert alice_project["features"]["userAgents"] is True
        assert bob_patch == 404
        assert boss_delete == 404
        assert bob_use == 404

    async def test_only_open_resources_can_be_chosen(self, site):
        s = await site(extra="models: [big-model]\n")
        boss = await s.login("boss", password_of("boss"))
        alice = await s.login("alice", password_of("alice"))
        await boss.api(
            "PATCH", "/admin/groups/everyone", {"toolsets": ["files"]}
        )

        shell, shell_error = await alice.api(
            "POST", "/agents", {"name": "a", "toolsets": ["shell"]}
        )
        model, _ = await alice.api(
            "POST", "/agents", {"name": "a", "model": "no-such-model"}
        )
        skill, _ = await alice.api(
            "POST", "/agents", {"name": "a", "skills": ["no-such-skill"]}
        )
        base, _ = await alice.api(
            "POST", "/agents", {"name": "a", "knowledgeBases": ["default"]}
        )
        ok, created = await alice.api(
            "POST",
            "/agents",
            {"name": "a", "toolsets": ["files"], "model": "big-model"},
        )
        boss_shell, _ = await boss.api(
            "POST", "/agents", {"name": "b", "toolsets": ["shell"]}
        )

        assert shell == 400 and "shell" in shell_error["error"]
        assert model == 400
        assert skill == 400
        assert base == 400
        assert ok == 201 and created["model"] == "big-model"
        assert boss_shell == 201

    async def test_changes_are_audited(self, site):
        s = await site()
        boss = await s.login("boss", password_of("boss"))
        alice = await s.login("alice", password_of("alice"))

        _, created = await alice.api("POST", "/agents", LAWYER)
        await alice.api(
            "PATCH", f"/agents/{created['id']}", {"description": "改"}
        )
        await alice.api("DELETE", f"/agents/{created['id']}")
        _, data = await boss.api("GET", "/admin/audit?category=agent")

        actions = [item["action"] for item in data["entries"]]
        assert actions == ["agent.delete", "agent.update", "agent.create"]
        assert "instructions" not in data["entries"][0]["detail"]


class TestRun:
    async def test_runs_with_own_instructions_and_tools(self, site):
        s = await site(script=[conftest.text_response("好")])
        alice = await s.login("alice", password_of("alice"))
        (s.root / "AGENTS.md").write_text("回答一律用繁體中文。", "utf-8")
        _, created = await alice.api("POST", "/agents", LAWYER)

        status, summary = await alice.api(
            "POST", "/sessions", {"text": "嗨", "agent": created["key"]}
        )
        await alice.wait_idle(summary["id"])
        _, sessions = await alice.api("GET", "/sessions")

        assert status == 201
        assert summary["agent"] == created["key"]
        assert summary["agentLabel"] == "合約小幫手"
        request = s.model.requests[0]
        system = request["messages"][0]["content"]
        assert "你是「合約小幫手」：檢查合約條款。" in system
        assert "你只回答合約相關的問題。" in system
        assert "回答一律用繁體中文。" in system
        names = tool_names(request)
        assert "read_file" in names
        assert "run_command" not in names
        assert sessions[0]["agentLabel"] == "合約小幫手"

    async def test_group_limits_apply_at_run_time(self, site):
        s = await site(script=[conftest.text_response("好")])
        boss = await s.login("boss", password_of("boss"))
        alice = await s.login("alice", password_of("alice"))
        _, created = await alice.api(
            "POST", "/agents", {"name": "a", "toolsets": ["files", "shell"]}
        )
        # 管理者事後收回 shell：自建的 agent 也跟著不能用。
        await boss.api(
            "PATCH", "/admin/groups/everyone", {"toolsets": ["files"]}
        )

        _, summary = await alice.api(
            "POST", "/sessions", {"text": "嗨", "agent": created["key"]}
        )
        await alice.wait_idle(summary["id"])

        names = tool_names(s.model.requests[0])
        assert "read_file" in names
        assert "run_command" not in names

    async def test_knowledge_follows_groups(self, site):
        s = await site(
            agent=KNOWLEDGE_AGENT,
            prepare=add_documents,
            script=[
                conftest.text_response("好"),
                conftest.text_response("好"),
            ],
        )
        boss = await s.login("boss", password_of("boss"))
        alice = await s.login("alice", password_of("alice"))
        _, created = await alice.api(
            "POST", "/agents", {"name": "a", "knowledgeBases": ["default"]}
        )
        _, project = await alice.api("GET", "/project")
        mine = next(a for a in project["agents"] if a.get("custom"))

        _, first = await alice.api(
            "POST", "/sessions", {"text": "嗨", "agent": created["key"]}
        )
        await alice.wait_idle(first["id"])
        await boss.api(
            "PATCH", "/admin/groups/everyone", {"knowledgeBases": []}
        )
        _, second = await alice.api(
            "POST", "/sessions", {"text": "嗨", "agent": created["key"]}
        )
        await alice.wait_idle(second["id"])

        assert mine["knowledge"] == ["default"]
        assert "search_knowledge" in tool_names(s.model.requests[0])
        assert "search_knowledge" not in tool_names(s.model.requests[1])

    async def test_edits_apply_to_next_turn(self, site):
        s = await site(
            script=[conftest.text_response("好"), conftest.text_response("好")]
        )
        alice = await s.login("alice", password_of("alice"))
        _, created = await alice.api("POST", "/agents", LAWYER)
        _, summary = await alice.api(
            "POST", "/sessions", {"text": "嗨", "agent": created["key"]}
        )
        await alice.wait_idle(summary["id"])

        await alice.api(
            "PATCH",
            f"/agents/{created['id']}",
            {"name": "條款檢查", "instructions": "只講重點。"},
        )
        await alice.api(
            "POST", f"/sessions/{summary['id']}/messages", {"text": "再一次"}
        )
        detail = await alice.wait_idle(summary["id"])

        system = s.model.requests[1]["messages"][0]["content"]
        assert "只講重點。" in system
        assert "你只回答合約相關的問題。" not in system
        assert detail["summary"]["agentLabel"] == "條款檢查"

    async def test_deleted_agent_keeps_history_but_cannot_continue(self, site):
        s = await site(script=[conftest.text_response("好")])
        alice = await s.login("alice", password_of("alice"))
        _, created = await alice.api("POST", "/agents", LAWYER)
        _, summary = await alice.api(
            "POST", "/sessions", {"text": "嗨", "agent": created["key"]}
        )
        await alice.wait_idle(summary["id"])

        await alice.api("DELETE", f"/agents/{created['id']}")
        status, detail = await alice.api("GET", f"/sessions/{summary['id']}")
        continued, error = await alice.api(
            "POST", f"/sessions/{summary['id']}/messages", {"text": "再一次"}
        )

        assert status == 200
        assert detail["summary"]["agentLabel"] == "合約小幫手"
        assert continued == 400
        assert "刪除" in error["error"]

    async def test_survives_restart(self, site, tmp_path):
        s = await site(script=[conftest.text_response("好")])
        alice = await s.login("alice", password_of("alice"))
        _, created = await alice.api("POST", "/agents", LAWYER)
        _, summary = await alice.api(
            "POST", "/sessions", {"text": "嗨", "agent": created["key"]}
        )
        await alice.wait_idle(summary["id"])
        await alice.api("DELETE", f"/agents/{created['id']}")
        # 直接讀存檔：名稱記在 .meta.json，重新啟動後仍然顯示得出來。
        metas = list(s.root.glob(".harness/users/*/sessions/*.meta.json"))

        assert len(metas) == 1
        assert '"agentLabel": "合約小幫手"' in metas[0].read_text("utf-8")


class TestLocalMode:
    async def test_works_without_login(self, start):
        h = await start(script=[conftest.text_response("好")])

        status, created = await h.api("POST", "/agents", LAWYER)
        _, summary = await h.api(
            "POST", "/sessions", {"text": "嗨", "agent": created["key"]}
        )
        await h.wait_for("run_end")

        assert status == 201
        system = h.model.requests[0]["messages"][0]["content"]
        assert "你是「合約小幫手」" in system
