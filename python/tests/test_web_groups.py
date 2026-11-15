"""存取群組：管理者決定每位成員可以使用的 agent、工具組與知識庫。

模型不歸群組管，由模型中台（LiteLLM Proxy）決定，見 TestModelsFromGateway。
"""

import pathlib

import pytest

from harness.web import accounts as accounts_lib
from harness.web import groups as groups_lib
from harness.web import personal_knowledge as personal_lib
from harness.web import user_agents as user_agents_lib
from tests import conftest
from tests import test_web_accounts
from tests.test_web_accounts import AGENT
from tests.test_web_accounts import password_of
from tests.test_web_accounts import user_id

# 沿用帳號測試的 fixture：一個要登入的網站（boss 是管理者、alice 是成員）。
site = test_web_accounts.site
fast_hash = test_web_accounts.fast_hash

WRITER = """---
name: writer
description: 寫作助手
tools:
  - files
---
你負責寫作。
"""

KNOWLEDGE_AGENT = AGENT.replace(
    "description: 測試用的助手\n",
    "description: 測試用的助手\nknowledge: true\n",
)


def groups_of(root: pathlib.Path) -> groups_lib.GroupStore:
    return groups_lib.GroupStore.for_project(root)


def member(name: str = "amy") -> accounts_lib.User:
    return accounts_lib.User(f"id-{name}", name, name, "member")


class TestGroupStore:
    def test_everyone_starts_with_full_access(self, tmp_path):
        store = groups_of(tmp_path)

        [everyone] = store.list_groups()

        assert everyone.id == groups_lib.EVERYONE_ID
        assert everyone.builtin
        assert store.access_for(member()) == groups_lib.FULL_ACCESS

    def test_new_group_starts_empty_and_access_is_a_union(self, tmp_path):
        store = groups_of(tmp_path)
        store.update_group(
            groups_lib.EVERYONE_ID,
            {
                "agents": ["main"],
                "toolsets": [],
                "knowledge": [],
            },
        )
        empty = store.create_group("空的")
        it = store.create_group(
            "資訊處",
            resources={"agents": ["writer"], "toolsets": ["shell"]},
            members=["id-amy"],
        )

        amy = store.access_for(member("amy"))
        bob = store.access_for(member("bob"))

        assert empty.agents == () and empty.toolsets == ()
        assert it.members == ("id-amy",)
        assert amy.agents == {"main", "writer"}
        assert amy.toolsets == {"shell"}
        assert bob.agents == {"main"}
        assert bob.toolsets == frozenset()
        # 模型不歸群組管：一律不限制，由模型中台決定。
        assert amy.models is None and bob.models is None

    def test_one_group_with_everything_opens_that_kind(self, tmp_path):
        store = groups_of(tmp_path)
        store.update_group(groups_lib.EVERYONE_ID, {"toolsets": []})
        store.create_group(
            "全部工具", resources={"toolsets": None}, members=["id-amy"]
        )

        assert store.access_for(member("amy")).toolsets is None
        assert store.access_for(member("bob")).toolsets == frozenset()

    def test_models_are_not_managed_by_groups(self, tmp_path):
        store = groups_of(tmp_path)

        store.update_group(groups_lib.EVERYONE_ID, {"models": []})
        group = store.create_group("x", resources={"models": ["big"]})

        assert "models" not in group.info()
        assert store.access_for(member()).models is None

    def test_admins_are_never_limited(self, tmp_path):
        store = groups_of(tmp_path)
        store.update_group(groups_lib.EVERYONE_ID, {"agents": []})
        boss = accounts_lib.User("id-boss", "boss", "boss", "admin")

        assert store.access_for(boss) == groups_lib.FULL_ACCESS

    def test_everyone_cannot_be_renamed_deleted_or_given_members(
        self, tmp_path
    ):
        store = groups_of(tmp_path)

        for change in ({"name": "別的"}, {"members": ["id-amy"]}):
            with pytest.raises(groups_lib.GroupError):
                store.update_group(groups_lib.EVERYONE_ID, change)
        with pytest.raises(groups_lib.GroupError):
            store.delete_group(groups_lib.EVERYONE_ID)

    def test_names_are_unique_and_checked(self, tmp_path):
        store = groups_of(tmp_path)
        store.create_group("業務")

        with pytest.raises(groups_lib.GroupError, match="同名"):
            store.create_group(" 業務 ")
        with pytest.raises(groups_lib.GroupError):
            store.create_group("  ")
        with pytest.raises(groups_lib.GroupError):
            store.create_group("x", resources={"agents": "main"})

    def test_delete_group(self, tmp_path):
        store = groups_of(tmp_path)
        group = store.create_group("暫時", members=["id-amy"])

        store.delete_group(group.id)

        assert [item.id for item in store.list_groups()] == ["everyone"]
        with pytest.raises(groups_lib.GroupError):
            store.delete_group(group.id)


class TestGroupApi:
    async def test_only_admins_can_manage_groups(self, site):
        s = await site()
        alice = await s.login("alice", password_of("alice"))

        calls = [
            ("GET", "/admin/groups", None),
            ("POST", "/admin/groups", {"name": "x"}),
            ("PATCH", "/admin/groups/everyone", {"agents": []}),
            ("DELETE", "/admin/groups/everyone", None),
        ]
        for method, path, body in calls:
            status, _ = await alice.api(method, path, body)
            assert status == 403, path

        assert groups_of(s.root).access_for(member()).agents is None

    async def test_admin_lists_groups_with_catalog(self, site):
        s = await site(extra="models: [big-model]\n")
        boss = await s.login("boss", password_of("boss"))

        status, data = await boss.api("GET", "/admin/groups")
        _, project = await boss.api("GET", "/project")

        assert status == 200
        assert [item["id"] for item in data["groups"]] == ["everyone"]
        assert data["groups"][0]["agents"] is None
        # 模型由模型中台管，群組頁沒有模型可以勾選。
        assert "models" not in data["groups"][0]
        assert "models" not in data["catalog"]
        assert [item["name"] for item in data["catalog"]["agents"]] == ["main"]
        assert "shell" in [item["name"] for item in data["catalog"]["toolsets"]]
        assert data["catalog"]["hasKnowledge"] is False
        assert project["features"]["groups"] is True

    async def test_create_update_delete(self, site):
        s = await site()
        boss = await s.login("boss", password_of("boss"))
        alice_id = user_id(s.root, "alice")

        status, created = await boss.api(
            "POST",
            "/admin/groups",
            {"name": "資訊處", "toolsets": ["shell"], "members": [alice_id]},
        )
        _, updated = await boss.api(
            "PATCH",
            f"/admin/groups/{created['id']}",
            {"description": "可以執行指令", "ignored": 1},
        )
        duplicate, _ = await boss.api(
            "POST", "/admin/groups", {"name": "資訊處"}
        )
        deleted, _ = await boss.api("DELETE", f"/admin/groups/{created['id']}")
        missing, _ = await boss.api("DELETE", f"/admin/groups/{created['id']}")

        assert status == 201
        assert created["agents"] == [] and created["toolsets"] == ["shell"]
        assert created["members"] == [alice_id]
        assert updated["description"] == "可以執行指令"
        assert duplicate == 400
        assert deleted == 200
        assert missing == 404


class TestEnforcement:
    async def test_members_only_see_open_toolsets(self, site):
        s = await site()
        boss = await s.login("boss", password_of("boss"))
        alice = await s.login("alice", password_of("alice"))
        bob = await s.login("bob", password_of("bob"))
        await alice.listen()
        await boss.api(
            "PATCH", "/admin/groups/everyone", {"toolsets": ["files"]}
        )
        await boss.api(
            "POST",
            "/admin/groups",
            {
                "name": "資訊處",
                "toolsets": ["shell"],
                "members": [user_id(s.root, "bob")],
            },
        )

        _, alice_project = await alice.api("GET", "/project")
        _, bob_project = await bob.api("GET", "/project")
        _, boss_project = await boss.api("GET", "/project")

        def toolsets(info):
            return [item["name"] for item in info["toolsets"]]

        assert "shell" not in toolsets(alice_project)
        assert "run_command" not in alice_project["agents"][0]["tools"]
        assert "read_file" in alice_project["agents"][0]["tools"]
        assert "shell" in toolsets(bob_project)
        assert "shell" in toolsets(boss_project)
        # 改了群組會通知瀏覽器重新讀取專案。
        await alice.wait_for("project")

    async def test_closed_tools_are_removed_at_run_time(self, site):
        s = await site(
            script=[conftest.text_response("好")],
        )
        boss = await s.login("boss", password_of("boss"))
        alice = await s.login("alice", password_of("alice"))
        await boss.api(
            "PATCH", "/admin/groups/everyone", {"toolsets": ["files"]}
        )

        _, created = await alice.api("POST", "/sessions", {"text": "嗨"})
        await alice.wait_idle(created["id"])

        names = [
            tool["function"]["name"] for tool in s.model.requests[0]["tools"]
        ]
        assert "read_file" in names
        assert "run_command" not in names

    async def test_closed_tools_cannot_be_chosen(self, site):
        s = await site()
        boss = await s.login("boss", password_of("boss"))
        alice = await s.login("alice", password_of("alice"))
        await boss.api(
            "PATCH", "/admin/groups/everyone", {"toolsets": ["files"]}
        )

        status, _ = await alice.api(
            "POST",
            "/sessions",
            {"text": "嗨", "options": {"tools": ["run_command"]}},
        )

        assert status == 400

    async def test_agents_are_limited(self, site):
        def add_writer(root):
            (root / "agents" / "writer.md").write_text(WRITER, "utf-8")

        s = await site(
            prepare=add_writer, script=[conftest.text_response("好")]
        )
        boss = await s.login("boss", password_of("boss"))
        alice = await s.login("alice", password_of("alice"))
        _, before = await alice.api("POST", "/sessions", {"text": "嗨"})
        await alice.wait_idle(before["id"])
        await boss.api(
            "PATCH", "/admin/groups/everyone", {"agents": ["writer"]}
        )

        _, project = await alice.api("GET", "/project")
        refused, _ = await alice.api(
            "POST", "/sessions", {"text": "嗨", "agent": "main"}
        )
        # 已經開始的對話用的 agent 被收回後也不能再繼續。
        continued, _ = await alice.api(
            "POST", f"/sessions/{before['id']}/messages", {"text": "再一次"}
        )

        assert [item["name"] for item in project["agents"]] == ["writer"]
        assert project["defaultAgent"] == "writer"
        assert refused == 403
        assert continued == 403


class TestKnowledge:
    @staticmethod
    def add_documents(root: pathlib.Path) -> None:
        folder = root / "knowledge"
        folder.mkdir()
        (folder / "public.md").write_text("特休公告：所有人都看得到。", "utf-8")
        (folder / "hr.md").write_text(
            "---\nlabels: [hr]\n---\n特休計算：只有人資看得到。", "utf-8"
        )

    async def run_search(self, s, person) -> str:
        _, created = await person.api("POST", "/sessions", {"text": "特休"})
        await person.wait_idle(created["id"])
        tool_message = s.model.requests[-1]["messages"][-1]
        return tool_message["content"]

    def script(self):
        return [
            conftest.tool_response(("search_knowledge", {"query": "特休"})),
            conftest.text_response("好"),
        ]

    async def test_members_only_search_open_labels(self, site):
        s = await site(
            agent=KNOWLEDGE_AGENT,
            prepare=self.add_documents,
            script=self.script() * 2,
        )
        boss = await s.login("boss", password_of("boss"))
        alice = await s.login("alice", password_of("alice"))
        bob = await s.login("bob", password_of("bob"))
        await boss.api("PATCH", "/admin/groups/everyone", {"knowledge": []})
        await boss.api(
            "POST",
            "/admin/groups",
            {
                "name": "人資",
                "agents": None,
                "toolsets": None,
                "knowledge": ["hr"],
                "members": [user_id(s.root, "bob")],
            },
        )
        _, data = await boss.api("GET", "/admin/groups")

        alice_found = await self.run_search(s, alice)
        bob_found = await self.run_search(s, bob)

        assert data["catalog"]["knowledge"] == ["hr"]
        assert "public.md" in alice_found
        assert "hr.md" not in alice_found
        assert "hr.md" in bob_found


class TestMemberGroups:
    """從成員那一邊調整群組，以及新增成員時一起選群組。"""

    def test_set_groups_of_replaces_only_this_member(self, tmp_path):
        store = groups_of(tmp_path)
        first = store.create_group("資訊處", members=["id-amy", "id-ben"])
        second = store.create_group("法遵")

        groups = store.set_groups_of("id-amy", [second.id, second.id])

        assert [item.id for item in groups] == ["everyone", second.id]
        assert store.get_group(first.id).members == ("id-ben",)
        assert store.get_group(second.id).members == ("id-amy",)
        with pytest.raises(groups_lib.GroupError):
            store.set_groups_of("id-amy", ["everyone"])
        with pytest.raises(groups_lib.GroupError):
            store.set_groups_of("id-amy", "nope")

    async def test_admin_sets_groups_from_member_side(self, site):
        s = await site()
        boss = await s.login("boss", password_of("boss"))
        alice = await s.login("alice", password_of("alice"))
        alice_id = user_id(s.root, "alice")
        bob_id = user_id(s.root, "bob")
        _, group = await boss.api("POST", "/admin/groups", {"name": "資訊處"})

        status, changed = await boss.api(
            "PUT", f"/admin/users/{alice_id}/groups", {"groups": [group["id"]]}
        )
        _, members = await boss.api("GET", "/admin/users")
        missing, _ = await boss.api(
            "PUT", f"/admin/users/{alice_id}/groups", {"groups": ["nope"]}
        )
        nobody, _ = await boss.api(
            "PUT", "/admin/users/nobody/groups", {"groups": []}
        )
        forbidden, _ = await alice.api(
            "PUT", f"/admin/users/{bob_id}/groups", {"groups": [group["id"]]}
        )

        assert status == 200
        assert changed["groups"] == [group["id"]]
        by_name = {item["username"]: item for item in members}
        assert by_name["alice"]["groups"] == [group["id"]]
        assert by_name["bob"]["groups"] == []
        assert missing == 404
        assert nobody == 404
        assert forbidden == 403
        assert groups_of(s.root).get_group(group["id"]).members == (alice_id,)

    async def test_add_member_with_groups(self, site):
        s = await site()
        boss = await s.login("boss", password_of("boss"))
        _, group = await boss.api("POST", "/admin/groups", {"name": "資訊處"})

        status, issued = await boss.api(
            "POST",
            "/admin/users",
            {
                "username": "carol",
                "displayName": "卡蘿",
                "groups": [group["id"]],
            },
        )
        bad, _ = await boss.api(
            "POST", "/admin/users", {"username": "dave", "groups": ["nope"]}
        )

        assert status == 201
        assert issued["user"]["groups"] == [group["id"]]
        assert bad == 404
        # 群組不對時不會留下建了一半的帳號。
        assert (
            accounts_lib.AccountStore.for_project(s.root).find_user("dave")
            is None
        )


class TestDeleteMember:
    async def test_admin_deletes_member_and_their_data(self, site):
        s = await site([conftest.text_response("好")])
        boss = await s.login("boss", password_of("boss"))
        alice = await s.login("alice", password_of("alice"))
        alice_id = user_id(s.root, "alice")
        _, group = await boss.api(
            "POST", "/admin/groups", {"name": "資訊處", "members": [alice_id]}
        )
        _, created = await alice.api("POST", "/sessions", {"text": "嗨"})
        await alice.wait_idle(created["id"])
        _, base = await alice.api("POST", "/my/knowledge", {"name": "筆記"})
        _, agent = await alice.api("POST", "/agents", {"name": "小幫手"})
        private = test_web_accounts.private(s.root, alice_id)
        private.mkdir(parents=True, exist_ok=True)
        (private / "a.txt").write_text("hi", "utf-8")
        user_dir = s.root / accounts_lib.USERS_DIR / alice_id
        assert user_dir.exists()

        status, _ = await boss.api("DELETE", f"/admin/users/{alice_id}")
        _, members = await boss.api("GET", "/admin/users")
        after, _ = await alice.api("GET", "/sessions")
        again, _ = await boss.api("DELETE", f"/admin/users/{alice_id}")
        _, audit = await boss.api("GET", "/admin/audit")

        assert status == 200
        assert "alice" not in [item["username"] for item in members]
        assert after == 401
        assert again == 404
        assert not user_dir.exists()
        assert not private.exists()
        assert groups_of(s.root).get_group(group["id"]).members == ()
        personal = personal_lib.PersonalKnowledgeStore(s.root)
        assert personal.owned_by(alice_id) == []
        assert not personal.files_path(base["id"]).exists()
        agents = user_agents_lib.UserAgentStore.for_project(s.root)
        assert agents.get(agent["id"]) is None
        actions = [item["action"] for item in audit["entries"]]
        assert "member.delete" in actions
        # 名稱可以再用。
        reuse, issued = await boss.api(
            "POST", "/admin/users", {"username": "alice"}
        )
        assert reuse == 201
        assert issued["user"]["id"] != alice_id

    async def test_cannot_delete_self_or_last_admin(self, site):
        s = await site(users=(("boss", "admin"), ("alice", "member")))
        boss = await s.login("boss", password_of("boss"))
        alice = await s.login("alice", password_of("alice"))
        boss_id = user_id(s.root, "boss")

        own, error = await boss.api("DELETE", f"/admin/users/{boss_id}")
        forbidden, _ = await alice.api("DELETE", f"/admin/users/{boss_id}")

        assert own == 400
        assert "自己" in error["error"]
        assert forbidden == 403
        store = accounts_lib.AccountStore.for_project(s.root)
        assert store.find_user("boss") is not None
        with pytest.raises(accounts_lib.AccountError):
            store.delete_user(boss_id)


class TestGroupAudit:
    async def test_group_page_save_records_only_real_changes(self, site):
        s = await site()
        boss = await s.login("boss", password_of("boss"))
        alice_id = user_id(s.root, "alice")
        bob_id = user_id(s.root, "bob")
        _, group = await boss.api(
            "POST", "/admin/groups", {"name": "資訊處", "members": [alice_id]}
        )
        # 群組頁存檔會送出全部欄位；只有成員有變。
        full = {
            key: group[key]
            for key in (
                "name",
                "description",
                "agents",
                "toolsets",
                "knowledgeBases",
                "knowledge",
            )
        }
        await boss.api(
            "PATCH",
            f"/admin/groups/{group['id']}",
            {**full, "members": [bob_id]},
        )
        await boss.api(
            "PATCH",
            f"/admin/groups/{group['id']}",
            {**full, "members": [bob_id]},
        )

        _, audit = await boss.api("GET", "/admin/audit?category=group")
        updates = [
            item
            for item in audit["entries"]
            if item["action"] == "group.update"
        ]

        # 第二次什麼都沒改，不記。
        assert len(updates) == 1
        assert updates[0]["detail"]["changes"] == {}
        assert updates[0]["detail"]["membersAdded"] == ["bob"]
        assert updates[0]["detail"]["membersRemoved"] == ["alice"]
