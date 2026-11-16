"""管理者在管理平台掛載 MCP 伺服器：金鑰不外流、工具依群組開放。"""

import json
import os
import socket

import pytest

from harness.web import mcp_admin
from harness.web import server as server_lib
from tests import conftest
from tests import test_mcp_servers
from tests import test_web_accounts
from tests.test_web_accounts import password_of

pytest.importorskip("mcp")

site = test_web_accounts.site
fast_hash = test_web_accounts.fast_hash

KEY = "sk-secret-123456"

# 模擬 LiteLLM 上的 webiq：search 回傳查詢與收到的金鑰標頭。
SEARCH_SERVER = """\
import sys

from mcp.server.mcpserver import Context
from mcp.server.mcpserver import MCPServer

mcp = MCPServer("webiq")


@mcp.tool()
def web_search(query: str, ctx: Context) -> str:
    \"\"\"搜尋網路。\"\"\"
    headers = ctx.request_context.request.headers
    return f"{query}|{headers.get('x-litellm-api-key')}"


mcp.run("streamable-http", port=int(sys.argv[1]))
"""


@pytest.fixture
def search_url(tmp_path):
    process, port = test_mcp_servers._start_http_server(  # noqa: SLF001
        SEARCH_SERVER, tmp_path
    )
    yield f"http://127.0.0.1:{port}/mcp"
    process.terminate()
    process.wait(timeout=10)


def webiq(url: str, value: str = f"Bearer {KEY}", **extra) -> dict:
    return {
        "name": "webiq",
        "url": url,
        "description": "網頁搜尋",
        "headers": [{"name": "x-litellm-api-key", "value": value}],
        **extra,
    }


def workspace_of(s):
    return s.client.server.app[server_lib._WORKSPACE]  # noqa: SLF001


def unused_url() -> str:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    return f"http://127.0.0.1:{port}/mcp"


def toolsets(info: dict) -> list[str]:
    return [item["name"] for item in info["toolsets"]]


class TestAdminOnly:
    async def test_members_cannot_see_or_add_servers(self, site):
        s = await site()
        alice = await s.login("alice", password_of("alice"))

        listed, _ = await alice.api("GET", "/admin/mcp")
        created, _ = await alice.api(
            "POST", "/admin/mcp", webiq("http://x/mcp")
        )
        tested, _ = await alice.api(
            "POST", "/admin/mcp/test", webiq("http://x/mcp")
        )

        assert (listed, created, tested) == (403, 403, 403)
        assert not (s.root / mcp_admin.STORE_FILE).exists()


class TestMount:
    async def test_mounted_tools_reach_agents_and_key_stays_secret(
        self, site, search_url
    ):
        s = await site(
            script=[
                conftest.tool_response(("web_search", {"query": "台新"})),
                conftest.text_response("好"),
            ]
        )
        boss = await s.login("boss", password_of("boss"))
        alice = await s.login("alice", password_of("alice"))

        status, created = await boss.api(
            "POST", "/admin/mcp", webiq(search_url)
        )
        await workspace_of(s).mcp.wait()
        _, listed = await boss.api("GET", "/admin/mcp")
        _, alice_project = await alice.api("GET", "/project")
        _, chat = await alice.api("POST", "/sessions", {"text": "查一下"})
        await alice.wait_idle(chat["id"])

        assert status == 201
        [server] = listed["servers"]
        assert server["status"] == "connected"
        assert server["headers"] == [{"name": "x-litellm-api-key", "set": True}]
        assert [t["name"] for t in server["tools"]] == ["web_search"]
        # 金鑰不會送回瀏覽器，也不在一般的設定檔裡。
        assert KEY not in json.dumps(created) + json.dumps(listed)
        assert KEY not in (s.root / mcp_admin.STORE_FILE).read_text()
        secret = s.root / ".harness" / "secrets" / mcp_admin.SECRETS_FILE
        assert KEY in secret.read_text()
        assert os.stat(secret).st_mode & 0o777 == 0o600
        # 「所有人」群組沒有限制工具組：成員看得到，agent 也能呼叫。
        assert "webiq" in toolsets(alice_project)
        assert "web_search" in alice_project["agents"][0]["tools"]
        result = s.model.requests[1]["messages"][-1]["content"]
        assert result == f"台新|Bearer {KEY}"

    async def test_groups_decide_who_can_use_the_server(self, site, search_url):
        s = await site()
        boss = await s.login("boss", password_of("boss"))
        alice = await s.login("alice", password_of("alice"))
        await boss.api("POST", "/admin/mcp", webiq(search_url))
        await workspace_of(s).mcp.wait()

        await boss.api(
            "PATCH", "/admin/groups/everyone", {"toolsets": ["files"]}
        )
        _, closed = await alice.api("GET", "/project")
        _, groups = await boss.api("GET", "/admin/groups")
        await boss.api(
            "PATCH",
            "/admin/groups/everyone",
            {"toolsets": ["files", "webiq"]},
        )
        _, opened = await alice.api("GET", "/project")

        assert "webiq" in [t["name"] for t in groups["catalog"]["toolsets"]]
        assert "webiq" not in toolsets(closed)
        assert "webiq" in toolsets(opened)

    async def test_update_keeps_the_stored_key_and_delete_removes_tools(
        self, site, search_url
    ):
        s = await site(
            script=[
                conftest.tool_response(("web_search", {"query": "a"})),
                conftest.text_response("好"),
            ]
        )
        boss = await s.login("boss", password_of("boss"))
        ws = workspace_of(s)
        await boss.api("POST", "/admin/mcp", webiq(search_url))
        await ws.mcp.wait()

        status, updated = await boss.api(
            "PATCH",
            "/admin/mcp/webiq",
            {
                "description": "改過",
                "headers": [{"name": "x-litellm-api-key", "value": ""}],
            },
        )
        await ws.mcp.wait()
        _, chat = await boss.api("POST", "/sessions", {"text": "查"})
        await boss.wait_idle(chat["id"])
        result = s.model.requests[1]["messages"][-1]["content"]

        assert status == 200
        assert updated["description"] == "改過"
        assert result == f"a|Bearer {KEY}"

        deleted, _ = await boss.api("DELETE", "/admin/mcp/webiq")
        _, project = await boss.api("GET", "/project")

        assert deleted == 200
        assert "webiq" not in toolsets(project)
        assert "web_search" not in project["agents"][0]["tools"]
        assert "webiq" not in ws.project.toolsets
        secret = s.root / ".harness" / "secrets" / mcp_admin.SECRETS_FILE
        assert KEY not in secret.read_text()

    async def test_only_chosen_agents_get_the_tools(self, site, search_url):
        writer = test_web_accounts.AGENT.replace("name: main", "name: writer")
        s = await site(
            prepare=lambda root: (root / "agents" / "writer.md").write_text(
                writer, encoding="utf-8"
            )
        )
        boss = await s.login("boss", password_of("boss"))
        await boss.api(
            "POST", "/admin/mcp", webiq(search_url, agents=["writer"])
        )
        await workspace_of(s).mcp.wait()

        _, project = await boss.api("GET", "/project")
        tools = {a["name"]: a["tools"] for a in project["agents"]}

        assert "web_search" in tools["writer"]
        assert "web_search" not in tools["main"]

    async def test_disable_hides_the_tools(self, site, search_url):
        s = await site()
        boss = await s.login("boss", password_of("boss"))
        ws = workspace_of(s)
        await boss.api("POST", "/admin/mcp", webiq(search_url))
        await ws.mcp.wait()

        _, info = await boss.api(
            "PATCH", "/admin/mcp/webiq", {"enabled": False}
        )
        _, project = await boss.api("GET", "/project")

        assert info["status"] == "disabled"
        assert "webiq" not in toolsets(project)


class TestFailures:
    async def test_unreachable_server_shows_error_and_site_keeps_working(
        self, site
    ):
        s = await site(script=[conftest.text_response("好")])
        boss = await s.login("boss", password_of("boss"))

        status, _ = await boss.api("POST", "/admin/mcp", webiq(unused_url()))
        await workspace_of(s).mcp.wait()
        _, listed = await boss.api("GET", "/admin/mcp")
        _, chat = await boss.api("POST", "/sessions", {"text": "嗨"})
        detail = await boss.wait_idle(chat["id"])

        assert status == 201
        [server] = listed["servers"]
        assert server["status"] == "error"
        assert "無法連上" in server["error"]
        assert detail["summary"]["status"] == "done"

    @pytest.mark.parametrize(
        ("body", "message"),
        [
            (webiq("http://x/mcp", name="files"), "內建"),
            (webiq("http://x/mcp", name="1bad"), "名稱"),
            (webiq("ftp://x/mcp"), "http"),
            (webiq("http://x/sse"), "SSE"),
            (webiq("http://x/mcp", value=""), "請填寫標頭"),
            (webiq("http://x/mcp", agents=["nobody"]), "找不到"),
            ({"name": "local", "command": "python3"}, "網址"),
        ],
    )
    async def test_rejects_bad_settings(self, site, body, message):
        s = await site()
        boss = await s.login("boss", password_of("boss"))

        status, error = await boss.api("POST", "/admin/mcp", body)

        assert status == 400
        assert message in error["error"]

    async def test_name_cannot_repeat_harness_yaml_servers(self, site):
        s = await site()
        boss = await s.login("boss", password_of("boss"))
        # 部署時寫在 harness.yaml 的伺服器（這裡只寫設定，不必真的連上）。
        config = s.root / "harness.yaml"
        config.write_text(
            config.read_text()
            + "mcpServers:\n  webiq:\n    url: http://x/mcp\n"
        )

        status, _ = await boss.api("POST", "/admin/mcp", webiq("http://y/mcp"))

        assert status == 400


class TestTestConnection:
    async def test_lists_tools_without_saving(self, site, search_url):
        s = await site()
        boss = await s.login("boss", password_of("boss"))

        _, ok = await boss.api("POST", "/admin/mcp/test", webiq(search_url))
        _, failed = await boss.api(
            "POST", "/admin/mcp/test", webiq(unused_url())
        )

        assert ok["ok"] is True
        assert [t["name"] for t in ok["tools"]] == ["web_search"]
        assert failed["ok"] is False and failed["message"]
        assert not (s.root / mcp_admin.STORE_FILE).exists()

    async def test_reuses_the_stored_key_for_existing_servers(
        self, site, search_url
    ):
        s = await site()
        boss = await s.login("boss", password_of("boss"))
        await boss.api("POST", "/admin/mcp", webiq(search_url))
        await workspace_of(s).mcp.wait()

        _, result = await boss.api(
            "POST",
            "/admin/mcp/test",
            {**webiq(search_url, value=""), "existing": "webiq"},
        )

        assert result["ok"] is True


class TestAuditAndRestart:
    async def test_audit_records_header_names_only(self, site, search_url):
        s = await site()
        boss = await s.login("boss", password_of("boss"))
        await boss.api("POST", "/admin/mcp", webiq(search_url))
        await workspace_of(s).mcp.wait()

        _, audit = await boss.api("GET", "/admin/audit?category=mcp")

        [entry] = [e for e in audit["entries"] if e["action"] == "mcp.create"]
        assert entry["target"] == "webiq"
        assert KEY not in json.dumps(audit)

    async def test_saved_servers_connect_when_the_site_starts(
        self, site, search_url, tmp_path
    ):
        first = await site()
        boss = await first.login("boss", password_of("boss"))
        await boss.api("POST", "/admin/mcp", webiq(search_url))
        await workspace_of(first).mcp.wait()
        root = first.root

        def copy(target):
            for name in (str(mcp_admin.STORE_FILE),):
                (target / name).parent.mkdir(parents=True, exist_ok=True)
                (target / name).write_text((root / name).read_text())
            secret = root / ".harness" / "secrets" / mcp_admin.SECRETS_FILE
            (target / ".harness" / "secrets").mkdir(exist_ok=True)
            (target / ".harness" / "secrets" / secret.name).write_text(
                secret.read_text()
            )

        second = await site(prepare=copy)
        await workspace_of(second).mcp.wait()
        boss2 = await second.login("boss", password_of("boss"))
        _, listed = await boss2.api("GET", "/admin/mcp")

        assert listed["servers"][0]["status"] == "connected"
