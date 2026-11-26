"""網頁上管理 skill：管理平台的公司 skill、群組權限，以及成員的個人 skill。
也測管理平台編輯公司 agent。"""

import io
import zipfile

import aiohttp

from tests import conftest
from tests import test_web_accounts
from tests.test_web_accounts import password_of

site = test_web_accounts.site
fast_hash = test_web_accounts.fast_hash

NOTES = {
    "name": "meeting-notes",
    "description": "整理會議記錄：使用者貼上逐字稿或筆記時使用",
    "instructions": "1. 列出決議\n2. 列出待辦與負責人",
}


def skill_zip(files: dict[str, str]) -> bytes:
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        for name, text in files.items():
            archive.writestr(name, text)
    return data.getvalue()


async def upload(s, person, data, where="admin", query=""):
    form = aiohttp.FormData()
    form.add_field("file", data, filename="skill.zip")
    response = await s.client.post(
        f"/api/{where}/skills/upload{query}",
        data=form,
        headers={**person.headers, "X-Harness-Upload": "1"},
    )
    return response.status, await response.json()


def skill_names(project: dict) -> list[str]:
    return [item["name"] for item in project["skills"]]


def system_prompt(request: dict) -> str:
    return request["messages"][0]["content"]


class TestCompanySkills:
    async def test_members_cannot_manage(self, site):
        s = await site()
        alice = await s.login("alice", password_of("alice"))

        listed, _ = await alice.api("GET", "/admin/skills")
        created, _ = await alice.api("POST", "/admin/skills", NOTES)
        agents, _ = await alice.api("GET", "/admin/agents")

        assert (listed, created, agents) == (403, 403, 403)

    async def test_create_edit_delete_reaches_members(self, site):
        s = await site(script=[conftest.text_response("好")])
        boss = await s.login("boss", password_of("boss"))
        alice = await s.login("alice", password_of("alice"))

        status, created = await boss.api("POST", "/admin/skills", NOTES)
        again, error = await boss.api("POST", "/admin/skills", NOTES)
        _, project = await alice.api("GET", "/project")
        _, chat = await alice.api(
            "POST",
            "/sessions",
            {"text": "整理", "options": {"skills": ["meeting-notes"]}},
        )
        await alice.wait_idle(chat["id"])

        assert status == 201
        assert created["source"] == "company"
        assert created["instructions"] == NOTES["instructions"]
        assert (s.root / "skills" / "meeting-notes" / "SKILL.md").is_file()
        assert again == 409 and "已經有" in error["error"]
        assert "meeting-notes" in skill_names(project)
        assert "meeting-notes：整理會議記錄" in system_prompt(
            s.model.requests[0]
        )

        status, edited = await boss.api(
            "PATCH",
            "/admin/skills/meeting-notes",
            {"description": "整理會議記錄（新版）", "instructions": "只列待辦"},
        )
        deleted, _ = await boss.api("DELETE", "/admin/skills/meeting-notes")
        _, after = await alice.api("GET", "/project")

        assert status == 200
        assert edited["description"] == "整理會議記錄（新版）"
        assert edited["instructions"] == "只列待辦"
        assert deleted == 200
        assert "meeting-notes" not in skill_names(after)
        assert not (s.root / "skills" / "meeting-notes").exists()

    async def test_invalid_input(self, site):
        s = await site()
        boss = await s.login("boss", password_of("boss"))

        bad_name, error = await boss.api(
            "POST", "/admin/skills", {**NOTES, "name": "Meeting Notes"}
        )
        no_description, _ = await boss.api(
            "POST", "/admin/skills", {**NOTES, "description": " "}
        )
        builtin, delete_error = await boss.api(
            "DELETE", "/admin/skills/planning"
        )

        assert bad_name == 400 and "小寫英文" in error["error"]
        assert no_description == 400
        assert builtin == 400 and "可以關閉" in delete_error["error"]

    async def test_editing_builtin_makes_company_copy(self, site):
        s = await site()
        boss = await s.login("boss", password_of("boss"))

        _, before = await boss.api("GET", "/admin/skills/pdf")
        status, edited = await boss.api(
            "PATCH", "/admin/skills/pdf", {"instructions": "公司版的 PDF 指示"}
        )
        copied = s.root / "skills" / "pdf"
        deleted, _ = await boss.api("DELETE", "/admin/skills/pdf")
        _, restored = await boss.api("GET", "/admin/skills/pdf")

        assert before["source"] == "builtin"
        assert status == 200
        assert edited["source"] == "company" and edited["overridesBuiltin"]
        assert edited["instructions"] == "公司版的 PDF 指示"
        # 參考檔案與腳本一起複製過來，SKILL.md 的其他設定（requires）保留。
        assert edited["files"] == before["files"]
        assert edited["requires"] == ["run_python"]
        assert deleted == 200 and not copied.exists()
        assert restored["source"] == "builtin"
        assert restored["instructions"] == before["instructions"]

    async def test_disable_and_default(self, site):
        s = await site()
        boss = await s.login("boss", password_of("boss"))
        alice = await s.login("alice", password_of("alice"))
        await boss.api("POST", "/admin/skills", NOTES)

        await boss.api("PATCH", "/admin/skills/planning", {"enabled": False})
        await boss.api(
            "PATCH", "/admin/skills/meeting-notes", {"default": True}
        )
        _, project = await alice.api("GET", "/project")
        _, listed = await boss.api("GET", "/admin/skills")
        state = {item["name"]: item for item in listed["skills"]}

        assert "planning" not in skill_names(project)
        assert "meeting-notes" in project["defaultSkills"]
        assert not state["planning"]["enabled"]
        assert state["meeting-notes"]["default"]
        assert state["docx"]["default"]  # 原本的預設清單保留

        await boss.api("PATCH", "/admin/skills/planning", {"enabled": True})
        _, project = await alice.api("GET", "/project")

        assert "planning" in skill_names(project)

    async def test_deleting_forgets_its_settings(self, site):
        s = await site()
        boss = await s.login("boss", password_of("boss"))
        await boss.api("POST", "/admin/skills", NOTES)
        await boss.api(
            "PATCH",
            "/admin/skills/meeting-notes",
            {"default": True, "enabled": False},
        )

        status, _ = await boss.api("DELETE", "/admin/skills/meeting-notes")
        await boss.api("POST", "/admin/skills", NOTES)
        _, listed = await boss.api("GET", "/admin/skills")
        state = {item["name"]: item for item in listed["skills"]}

        assert status == 200
        assert state["meeting-notes"]["enabled"]
        assert not state["meeting-notes"]["default"]
        assert state["docx"]["default"]

    async def test_groups_limit_skills(self, site):
        s = await site()
        boss = await s.login("boss", password_of("boss"))
        alice = await s.login("alice", password_of("alice"))

        status, _ = await boss.api(
            "PATCH", "/admin/groups/everyone", {"skills": ["planning"]}
        )
        _, project = await alice.api("GET", "/project")
        _, groups = await boss.api("GET", "/admin/groups")
        refused, error = await alice.api(
            "POST", "/sessions", {"text": "x", "options": {"skills": ["pdf"]}}
        )

        assert status == 200
        assert skill_names(project) == ["planning"]
        assert project["defaultSkills"] == []
        assert "pdf" in [item["name"] for item in groups["catalog"]["skills"]]
        assert refused == 400 and "pdf" in error["error"]

    async def test_cannot_delete_skill_an_agent_lists(self, site):
        agent = test_web_accounts.AGENT.replace(
            "description: 測試用的助手\n",
            "description: 測試用的助手\nskills: [meeting-notes]\n",
        )

        def prepare(root):
            folder = root / "skills" / "meeting-notes"
            folder.mkdir(parents=True)
            (folder / "SKILL.md").write_text(
                "---\nname: meeting-notes\ndescription: 會議\n---\n指示\n",
                encoding="utf-8",
            )

        s = await site(agent=agent, prepare=prepare)
        boss = await s.login("boss", password_of("boss"))

        status, error = await boss.api("DELETE", "/admin/skills/meeting-notes")
        _, listed = await boss.api("GET", "/admin/skills")
        used = {i["name"]: i["usedBy"] for i in listed["skills"]}

        assert status == 409 and "main" in error["error"]
        assert used["meeting-notes"] == ["main"]
        assert (s.root / "skills" / "meeting-notes" / "SKILL.md").exists()

    async def test_upload_zip(self, site):
        s = await site()
        boss = await s.login("boss", password_of("boss"))
        data = skill_zip(
            {
                "report-style/SKILL.md": (
                    "---\nname: report-style\ndescription: 公司報告格式\n"
                    "license: Apache-2.0\n---\n照 style.md 寫\n"
                ),
                "report-style/style.md": "標題用粗體",
                "report-style/scripts/check.py": "print(1)",
                "__MACOSX/report-style/._style.md": "x",
            }
        )

        status, info = await upload(s, boss, data)
        again, error = await upload(s, boss, data)
        replaced, _ = await upload(s, boss, data, query="?replace=1")

        assert status == 201, info
        assert info["name"] == "report-style"
        assert info["files"] == ["scripts/check.py", "style.md"]
        assert again == 409 and "取代" in error["error"]
        assert replaced == 201
        text = (s.root / "skills" / "report-style" / "SKILL.md").read_text()
        assert "license: Apache-2.0" in text

    async def test_upload_rejects_unsafe_zip(self, site):
        s = await site()
        boss = await s.login("boss", password_of("boss"))
        escape = skill_zip(
            {
                "SKILL.md": "---\nname: evil\ndescription: x\n---\n指示\n",
                "../outside.txt": "x",
            }
        )
        missing = skill_zip({"README.md": "沒有 SKILL.md"})
        bad_tools = skill_zip(
            {
                "SKILL.md": (
                    "---\nname: broken\ndescription: x\n"
                    "tools: [nope]\n---\n指示\n"
                )
            }
        )

        unsafe, error = await upload(s, boss, escape)
        empty, missing_error = await upload(s, boss, missing)
        broken, broken_error = await upload(s, boss, bad_tools)
        not_zip, _ = await upload(s, boss, b"hello")

        assert unsafe == 400 and "不安全" in error["error"]
        assert empty == 400 and "SKILL.md" in missing_error["error"]
        # 引用不存在的工具：重新載入失敗，檔案還原。
        assert broken == 400 and "nope" in broken_error["error"]
        assert not (s.root / "skills" / "broken").exists()
        assert not (s.root.parent / "outside.txt").exists()
        assert not_zip == 400


class TestPersonalSkills:
    async def test_private_to_owner_and_on_by_default(self, site):
        s = await site(script=[conftest.text_response("好")])
        alice = await s.login("alice", password_of("alice"))
        bob = await s.login("bob", password_of("bob"))

        status, created = await alice.api("POST", "/my/skills", NOTES)
        _, alice_project = await alice.api("GET", "/project")
        _, bob_project = await bob.api("GET", "/project")
        hidden, _ = await bob.api("GET", "/my/skills/meeting-notes")
        _, chat = await alice.api("POST", "/sessions", {"text": "整理"})
        await alice.wait_idle(chat["id"])
        _, mine = await alice.api("GET", "/my/skills")

        assert status == 201
        assert created["instructions"] == NOTES["instructions"]
        mine_info = next(
            i for i in alice_project["skills"] if i["name"] == "meeting-notes"
        )
        assert mine_info["personal"] is True
        assert "meeting-notes" in alice_project["defaultSkills"]
        assert "meeting-notes" not in skill_names(bob_project)
        assert hidden == 404
        assert "meeting-notes：整理會議記錄" in system_prompt(
            s.model.requests[0]
        )
        assert [i["name"] for i in mine["skills"]] == ["meeting-notes"]

        status, _ = await alice.api(
            "PATCH", "/my/skills/meeting-notes", {"instructions": "新的指示"}
        )
        _, detail = await alice.api("GET", "/my/skills/meeting-notes")
        deleted, _ = await alice.api("DELETE", "/my/skills/meeting-notes")
        _, after = await alice.api("GET", "/project")

        assert status == 200 and detail["instructions"] == "新的指示"
        assert deleted == 200
        assert "meeting-notes" not in skill_names(after)

    async def test_names_and_tools_are_checked(self, site):
        s = await site()
        alice = await s.login("alice", password_of("alice"))

        builtin, error = await alice.api(
            "POST", "/my/skills", {**NOTES, "name": "pdf"}
        )
        with_tools = skill_zip(
            {
                "SKILL.md": (
                    "---\nname: mine\ndescription: x\ntools: [files]\n---\n指示"
                )
            }
        )
        refused, tools_error = await upload(s, alice, with_tools, where="my")

        assert builtin == 409 and "換一個名稱" in error["error"]
        assert refused == 400 and "專屬工具" in tools_error["error"]

    async def test_user_agent_can_use_own_skill_and_purge(self, site):
        s = await site(script=[conftest.text_response("好")])
        boss = await s.login("boss", password_of("boss"))
        alice = await s.login("alice", password_of("alice"))
        await alice.api("POST", "/my/skills", NOTES)

        status, agent = await alice.api(
            "POST",
            "/agents",
            {"name": "會議助手", "toolsets": [], "skills": ["meeting-notes"]},
        )
        _, chat = await alice.api(
            "POST", "/sessions", {"text": "整理", "agent": agent["key"]}
        )
        await alice.wait_idle(chat["id"])

        assert status == 201, agent
        assert "meeting-notes" in system_prompt(s.model.requests[0])

        _, me = await alice.api("GET", "/auth/me")
        folder = s.root / ".harness" / "personal-skills" / me["id"]
        assert folder.is_dir()
        await boss.api("DELETE", f"/admin/users/{me['id']}")

        assert not folder.exists()


class TestCompanyAgents:
    async def test_edit_reaches_chats(self, site):
        s = await site(script=[conftest.text_response("好")])
        boss = await s.login("boss", password_of("boss"))
        alice = await s.login("alice", password_of("alice"))

        _, listed = await boss.api("GET", "/admin/agents")
        status, edited = await boss.api(
            "PATCH",
            "/admin/agents/main",
            {
                "description": "新的說明",
                "instructions": "你是改過的助手。",
                "tools": ["files", "web"],
                "skills": ["planning"],
            },
        )
        _, project = await alice.api("GET", "/project")
        _, chat = await alice.api("POST", "/sessions", {"text": "嗨"})
        await alice.wait_idle(chat["id"])

        main = listed["agents"][0]
        assert main["name"] == "main" and main["tools"] == ["files", "shell"]
        assert main["default"] is True
        assert "web" in [t["name"] for t in listed["catalog"]["toolsets"]]
        assert status == 200
        assert edited["description"] == "新的說明"
        assert edited["tools"] == ["files", "web"]
        agent = project["agents"][0]
        assert agent["description"] == "新的說明"
        assert "web_search" in agent["tools"]
        assert "run_command" not in agent["tools"]
        prompt = system_prompt(s.model.requests[0])
        assert prompt.startswith("你是改過的助手。")
        assert "planning：" in prompt
        text = (s.root / "agents" / "main.md").read_text(encoding="utf-8")
        assert "你是改過的助手。" in text

    async def test_invalid_settings_are_rolled_back(self, site):
        s = await site()
        boss = await s.login("boss", password_of("boss"))
        path = s.root / "agents" / "main.md"
        before = path.read_text(encoding="utf-8")

        status, error = await boss.api(
            "PATCH", "/admin/agents/main", {"tools": ["no-such-toolset"]}
        )
        bad_skill, _ = await boss.api(
            "PATCH", "/admin/agents/main", {"skills": ["no-such-skill"]}
        )
        empty, _ = await boss.api(
            "PATCH", "/admin/agents/main", {"instructions": "  "}
        )

        assert status == 400 and "no-such-toolset" in error["error"]
        assert bad_skill == 400
        assert empty == 400
        assert path.read_text(encoding="utf-8") == before

    async def test_create_agent(self, site):
        s = await site()
        boss = await s.login("boss", password_of("boss"))
        alice = await s.login("alice", password_of("alice"))

        status, created = await boss.api(
            "POST",
            "/admin/agents",
            {
                "name": "hr-helper",
                "description": "人資問題",
                "instructions": "你回答人資問題。",
                "tools": ["files"],
            },
        )
        again, _ = await boss.api(
            "POST",
            "/admin/agents",
            {"name": "main", "instructions": "x"},
        )
        _, project = await alice.api("GET", "/project")

        assert status == 201
        assert created["file"] == "agents/hr-helper.md"
        assert again == 409
        assert "hr-helper" in [a["name"] for a in project["agents"]]
