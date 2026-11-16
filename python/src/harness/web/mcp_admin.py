"""管理者在管理平台掛載的 MCP 伺服器。

harness.yaml 的 mcpServers 是部署時寫好的，專案載入時就連線，連不上整個
專案就啟動不了。這裡是另一種來源：管理者在網頁上新增遠端的 MCP 伺服器
（Streamable HTTP），連上之後它的工具就和其他工具組一樣，出現在工具清單，
由存取群組決定哪些成員能用。

- 只接受遠端伺服器（url）。在伺服器上啟動程式（command）等於讓網頁上的
  操作在伺服器執行任意指令，所以只能寫在 harness.yaml。
- 設定存在 .harness/mcp-servers.json；標頭的值（API 金鑰）另外存在
  .harness/secrets/mcp-headers.json（0600，內建的檔案工具也讀不到），
  API 只回傳標頭名稱，不會把值送回瀏覽器。
- 標頭的值可以寫 ${環境變數}（例如 Bearer ${LITELLM_API_KEY}），沿用
  .env 裡的金鑰。
- 連線在背景建立，連不上只會讓這一台顯示錯誤，不影響網站其他功能。
- 伺服器名稱就是工具組名稱；工具加到選定的 agent（預設全部的專案
  agent）。成員自建的 agent 可以在工具組清單勾選它。

一般成員不能新增 MCP 伺服器，所有 API 都只給管理者（見 server.py）。
"""

import asyncio
import dataclasses
import json
import os
import pathlib
import re
import threading
import time
from collections.abc import Callable
from typing import Any
from urllib import parse

import yaml

from harness import builtin
from harness import credentials
from harness import mcp_servers
from harness import project as project_lib
from harness import sandbox as sandbox_lib
from harness import tools as tools_lib

STORE_FILE = project_lib.DATA_DIR / "mcp-servers.json"
SECRETS_FILE = "mcp-headers.json"
# 網頁上新增的伺服器，啟動與測試連線最多等多久（秒）。
CONNECT_TIMEOUT_SECONDS = 30
_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,39}$")
_HEADER_NAME = re.compile(r"^[A-Za-z0-9!#$%&'*+.^_`|~-]{1,100}$")
_MAX_HEADERS = 20
_MAX_VALUE = 4000
_MAX_URL = 2000
_MAX_DESCRIPTION = 200
STATUSES = ("connecting", "connected", "error", "disabled")


class McpAdminError(Exception):
    """設定內容不對，或找不到伺服器。

    Attributes:
        status: HTTP 狀態碼。
    """

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


@dataclasses.dataclass
class Server:
    """一台管理者掛載的 MCP 伺服器（不含標頭的值）。

    Attributes:
        name: 伺服器名稱，也是工具組名稱。
        url: Streamable HTTP 端點。
        description: 給管理者看的說明。
        headers: 標頭名稱（值存在 secrets 裡）。
        agents: 工具要加到哪些專案 agent；None 表示全部。
        enabled: 停用時不連線，工具也不出現。
        created_at: 建立時間（epoch 秒）。
        updated_at: 最後修改時間。
    """

    name: str
    url: str
    description: str = ""
    headers: tuple[str, ...] = ()
    agents: tuple[str, ...] | None = None
    enabled: bool = True
    created_at: float = 0.0
    updated_at: float = 0.0

    def record(self) -> dict[str, Any]:
        """存進 mcp-servers.json 的內容。"""
        return {
            "name": self.name,
            "url": self.url,
            "description": self.description,
            "headers": list(self.headers),
            "agents": None if self.agents is None else list(self.agents),
            "enabled": self.enabled,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }


@dataclasses.dataclass
class _Live:
    """一台伺服器目前的連線狀態。"""

    status: str = "connecting"
    error: str = ""
    connection: mcp_servers.McpConnection | None = None
    tools: list[tools_lib.Tool] = dataclasses.field(default_factory=list)
    # 每次重新連線加一；舊的連線結果回來時不採用。
    generation: int = 0


class McpAdmin:
    """管理者掛載的 MCP 伺服器：設定、金鑰與連線。

    連上的工具直接加進 project.toolsets、project.tools 與選定 agent 的
    tools，拿掉時再移除，所以存取群組、對話的工具選單與自建 agent 都不必
    另外處理。
    """

    def __init__(
        self,
        project: project_lib.Project,
        on_change: Callable[[], None] | None = None,
        *,
        connect_timeout: float = CONNECT_TIMEOUT_SECONDS,
    ) -> None:
        self.project = project
        self._on_change = on_change or (lambda: None)
        self._timeout = connect_timeout
        self._path = project.root / STORE_FILE
        self._lock = threading.Lock()
        self._servers = {item.name: item for item in self._load()}
        self._live: dict[str, _Live] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self._closed = False

    # ---- 讀取 ----------------------------------------------------------

    def list_info(self) -> dict[str, Any]:
        """管理平台 MCP 頁的內容。"""
        project = self.project
        configured = config_servers(project.root)
        return {
            "servers": [self.info(name) for name in self._servers],
            "configured": [
                {
                    "name": name,
                    "url": str((config or {}).get("url") or ""),
                    "command": bool((config or {}).get("command")),
                    "tools": [
                        item.name for item in project.toolsets.get(name, [])
                    ],
                }
                for name, config in configured.items()
            ],
            "agents": [
                {"name": name, "description": agent.description}
                for name, agent in project.agents.items()
            ],
            "gateway": _gateway_origin(),
        }

    def info(self, name: str) -> dict[str, Any]:
        """一台伺服器的設定與狀態；標頭只列名稱。"""
        server = self._require(name)
        live = self._live.get(name)
        if not server.enabled:
            status, error = "disabled", ""
        elif live is None:
            status, error = "connecting", ""
        else:
            status, error = live.status, live.error
        tools = live.tools if live and status == "connected" else []
        return {
            **server.record(),
            "headers": [{"name": item, "set": True} for item in server.headers],
            "status": status,
            "error": error,
            "tools": [
                {"name": item.name, "description": item.description}
                for item in tools
            ],
        }

    def names(self) -> list[str]:
        return list(self._servers)

    # ---- 修改 ----------------------------------------------------------

    async def create(self, body: Any) -> dict[str, Any]:
        """新增一台伺服器並開始連線。

        Args:
            body: {"name", "url", "description"?, "headers"?: [{"name",
                "value"}], "agents"?: [...] | null, "enabled"?}。

        Raises:
            McpAdminError: 內容不對，或名稱已經被使用。
        """
        if not isinstance(body, dict):
            raise McpAdminError("內容必須是物件")
        name = _checked_name(body.get("name"))
        if name in self._servers:
            raise McpAdminError(f"已經有名稱是 {name} 的 MCP 伺服器")
        self._check_free(name)
        headers = _checked_headers(body.get("headers"), {})
        now = time.time()
        server = Server(
            name=name,
            url=_checked_url(body.get("url")),
            description=_checked_description(body.get("description")),
            headers=tuple(headers),
            agents=self._checked_agents(body.get("agents")),
            enabled=_checked_bool(body.get("enabled", True), "enabled"),
            created_at=now,
            updated_at=now,
        )
        self._servers[name] = server
        self._write(server_secrets={name: headers})
        await self._restart(name)
        return self.info(name)

    async def update(self, name: str, body: Any) -> dict[str, Any]:
        """修改設定後重新連線。

        標頭的 value 留空表示沿用原本存的值；沒列出的標頭會被刪掉。名稱
        不能改（群組是依名稱開放的）。
        """
        server = self._require(name)
        if not isinstance(body, dict):
            raise McpAdminError("內容必須是物件")
        if "name" in body and body["name"] != name:
            raise McpAdminError("名稱不能修改；要換名稱請刪除後重新新增")
        changes: dict[str, Any] = {}
        if "url" in body:
            changes["url"] = _checked_url(body["url"])
        if "description" in body:
            changes["description"] = _checked_description(body["description"])
        if "agents" in body:
            changes["agents"] = self._checked_agents(body["agents"])
        if "enabled" in body:
            changes["enabled"] = _checked_bool(body["enabled"], "enabled")
        secrets = None
        if "headers" in body:
            secrets = _checked_headers(body["headers"], self._secrets(name))
            changes["headers"] = tuple(secrets)
        self._servers[name] = dataclasses.replace(
            server, **changes, updated_at=time.time()
        )
        self._write(None if secrets is None else {name: secrets})
        await self._restart(name)
        return self.info(name)

    async def delete(self, name: str) -> dict[str, Any]:
        """拿掉伺服器、關閉連線，回傳刪除前的資訊（稽核紀錄用）。"""
        info = self.info(name)
        del self._servers[name]
        self._write(server_secrets={name: None})
        await self._disconnect(name)
        self._live.pop(name, None)
        self._on_change()
        return info

    async def reconnect(self, name: str) -> dict[str, Any]:
        """重新連線（例如 LiteLLM 的設定改過、伺服器剛恢復）。"""
        self._require(name)
        await self._restart(name)
        return self.info(name)

    async def test(self, body: Any) -> dict[str, Any]:
        """用表單上的設定試著連線，列出工具；不會儲存。

        body 有 existing（已儲存的伺服器名稱）時，留空的標頭值用存起來的。
        """
        if not isinstance(body, dict):
            raise McpAdminError("內容必須是物件")
        existing = body.get("existing")
        stored = (
            self._secrets(existing)
            if isinstance(existing, str) and existing in self._servers
            else {}
        )
        headers = _checked_headers(body.get("headers"), stored)
        url = _checked_url(body.get("url"))
        name = str(body.get("name") or "test")
        try:
            connection = await asyncio.to_thread(self._open, name, url, headers)
        except Exception as error:  # noqa: BLE001 - 錯誤原樣顯示給管理者
            return {"ok": False, "message": _short(error)}
        try:
            return {
                "ok": True,
                "tools": [
                    {"name": item.name, "description": item.description}
                    for item in connection.tools
                ],
            }
        finally:
            await asyncio.to_thread(connection.close)

    # ---- 連線 ----------------------------------------------------------

    def start(self) -> None:
        """在背景連上所有啟用的伺服器（網站啟動時呼叫一次）。"""
        for name, server in self._servers.items():
            if server.enabled:
                self._spawn(self._restart(name))

    async def wait(self) -> None:
        """等背景的連線都完成（測試用）。"""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def close(self) -> None:
        """關閉所有連線（網站結束時）。"""
        self._closed = True
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*list(self._tasks), return_exceptions=True)
        for name in list(self._live):
            await self._disconnect(name)

    def _spawn(self, coroutine: Any) -> None:
        task = asyncio.ensure_future(coroutine)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _restart(self, name: str) -> None:
        """關掉舊的連線，依目前的設定重新連線並掛上工具。"""
        await self._disconnect(name)
        server = self._servers.get(name)
        live = self._live.setdefault(name, _Live())
        live.generation += 1
        generation = live.generation
        if server is None or not server.enabled or self._closed:
            live.status, live.error = "disabled", ""
            self._on_change()
            return
        live.status, live.error = "connecting", ""
        self._on_change()
        try:
            connection = await asyncio.to_thread(
                self._open, name, server.url, self._secrets(name)
            )
        except Exception as error:  # noqa: BLE001 - 顯示在管理平台
            if live.generation == generation:
                live.status, live.error = "error", _short(error)
                self._on_change()
            return
        if live.generation != generation or self._closed:
            await asyncio.to_thread(connection.close)
            return
        problem = self._conflict(name, connection.tools)
        if problem:
            await asyncio.to_thread(connection.close)
            live.status, live.error = "error", problem
            self._on_change()
            return
        live.connection = connection
        live.tools = list(connection.tools)
        live.status, live.error = "connected", ""
        self._attach(server, live.tools)
        self._on_change()

    def _open(
        self, name: str, url: str, headers: dict[str, str]
    ) -> mcp_servers.McpConnection:
        """建立連線（會等，要在背景執行緒呼叫）。"""
        return mcp_servers.from_config(
            name,
            {"type": "http", "url": url, "headers": headers},
            self.project.root,
            startup_timeout_seconds=self._timeout,
        )

    async def _disconnect(self, name: str) -> None:
        """拿掉工具並關閉連線。"""
        live = self._live.get(name)
        if live is None:
            return
        self._detach(name, live.tools)
        connection, live.connection, live.tools = live.connection, None, []
        if connection is not None:
            await asyncio.to_thread(connection.close)

    def _attach(self, server: Server, items: list[tools_lib.Tool]) -> None:
        """把工具加進專案與選定的 agent（換成新的清單，不改正在用的）。"""
        project = self.project
        project.toolsets[server.name] = items
        project.tools = {**project.tools, **{t.name: t for t in items}}
        for agent_name, agent in project.agents.items():
            if server.agents is None or agent_name in server.agents:
                agent.tools = [*agent.tools, *items]

    def _detach(self, name: str, items: list[tools_lib.Tool]) -> None:
        project = self.project
        if project.toolsets.get(name) is items:
            del project.toolsets[name]
        ids = {id(item) for item in items}
        project.tools = {
            key: value
            for key, value in project.tools.items()
            if id(value) not in ids
        }
        for agent in project.agents.values():
            if any(id(item) in ids for item in agent.tools):
                agent.tools = [t for t in agent.tools if id(t) not in ids]

    def _conflict(self, name: str, items: list[tools_lib.Tool]) -> str:
        """工具名稱和其他工具組重複時的說明；沒有重複時是空字串。"""
        owners = {
            item.name: set_name
            for set_name, set_items in self.project.toolsets.items()
            if set_name != name
            for item in set_items
        }
        for agent in self.project.agents.values():
            for item in agent.tools:
                owners.setdefault(item.name, f"agent {agent.name}")
        for item in items:
            if item.name in owners:
                return (
                    f"工具 {item.name} 和 {owners[item.name]} 裡的工具同名，"
                    "無法掛載；請在 MCP 伺服器那一端改名或拿掉這個工具"
                )
        return ""

    # ---- 儲存 ----------------------------------------------------------

    def _load(self) -> list[Server]:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        found = []
        for item in data.get("servers") or [] if isinstance(data, dict) else []:
            try:
                agents = item.get("agents")
                found.append(
                    Server(
                        name=_checked_name(item.get("name")),
                        url=_checked_url(item.get("url")),
                        description=str(item.get("description") or ""),
                        headers=tuple(
                            str(h) for h in item.get("headers") or []
                        ),
                        agents=None
                        if agents is None
                        else tuple(str(a) for a in agents),
                        enabled=bool(item.get("enabled", True)),
                        created_at=float(item.get("createdAt") or 0),
                        updated_at=float(item.get("updatedAt") or 0),
                    )
                )
            except (McpAdminError, AttributeError, TypeError, ValueError):
                continue
        return found

    def _all_secrets(self) -> dict[str, dict[str, str]]:
        path = credentials.secrets_dir(self.project.root) / SECRETS_FILE
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(data, dict):
            return {}
        return {
            name: {
                str(key): str(value)
                for key, value in values.items()
                if isinstance(value, str)
            }
            for name, values in data.items()
            if isinstance(values, dict)
        }

    def _secrets(self, name: str) -> dict[str, str]:
        server = self._servers.get(name)
        stored = self._all_secrets().get(name, {})
        if server is None:
            return {}
        return {key: stored[key] for key in server.headers if key in stored}

    def _write(
        self, server_secrets: dict[str, dict[str, str] | None] | None = None
    ) -> None:
        """寫回設定檔；server_secrets 給的伺服器同時更新標頭的值。"""
        with self._lock:
            if server_secrets:
                secrets = self._all_secrets()
                for name, values in server_secrets.items():
                    if values is None:
                        secrets.pop(name, None)
                    else:
                        secrets[name] = values
                credentials.write_private(
                    credentials.secrets_dir(self.project.root) / SECRETS_FILE,
                    json.dumps(secrets, ensure_ascii=False, indent=2) + "\n",
                )
            self._path.parent.mkdir(parents=True, exist_ok=True)
            text = json.dumps(
                {"servers": [s.record() for s in self._servers.values()]},
                ensure_ascii=False,
                indent=2,
            )
            temporary = self._path.with_suffix(".tmp")
            temporary.write_text(text + "\n", encoding="utf-8")
            temporary.replace(self._path)

    # ---- 檢查 ----------------------------------------------------------

    def _require(self, name: str) -> Server:
        server = self._servers.get(name)
        if server is None:
            raise McpAdminError(f"找不到 MCP 伺服器：{name}", 404)
        return server

    def _check_free(self, name: str) -> None:
        """名稱不能和現有的工具組（內建、tools/、harness.yaml）重複。"""
        if name in builtin.TOOLSETS or name == sandbox_lib.TOOLSET:
            raise McpAdminError(f"{name} 保留給內建工具，請換一個名稱")
        if name in config_servers(self.project.root) or (
            name in self.project.toolsets and name not in self._servers
        ):
            raise McpAdminError(f"{name} 已經是現有的工具組名稱，請換一個名稱")

    def _checked_agents(self, value: Any) -> tuple[str, ...] | None:
        if value is None:
            return None
        if not isinstance(value, list) or not all(
            isinstance(item, str) for item in value
        ):
            raise McpAdminError(
                "agents 必須是 agent 名稱的清單，或 null（全部）"
            )
        unknown = [item for item in value if item not in self.project.agents]
        if unknown:
            raise McpAdminError(f"找不到這些 agent：{'、'.join(unknown)}")
        return tuple(dict.fromkeys(value))


def config_servers(root: pathlib.Path) -> dict[str, Any]:
    """harness.yaml 裡部署時設定的 mcpServers（網頁上只能看）。"""
    path = root / project_lib.CONFIG_FILE
    try:
        config = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, ValueError):
        return {}
    servers = config.get("mcpServers") if isinstance(config, dict) else None
    return servers if isinstance(servers, dict) else {}


def _gateway_origin() -> str:
    """模型中台（HARNESS_BASE_URL）的網址去掉 /v1，給 LiteLLM 範本用。"""
    base = os.environ.get("HARNESS_BASE_URL", "").strip().rstrip("/")
    if not base:
        return ""
    parts = parse.urlsplit(base)
    path = re.sub(r"/v1$", "", parts.path)
    return parse.urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def _checked_name(value: Any) -> str:
    if not isinstance(value, str) or not _NAME.match(value.strip()):
        raise McpAdminError(
            "名稱只能用英文字母開頭，接英文字母、數字、- 或 _，最多 40 字"
        )
    return value.strip()


def _checked_url(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise McpAdminError("請填寫 MCP 伺服器的網址")
    url = value.strip()
    if len(url) > _MAX_URL:
        raise McpAdminError("網址太長")
    # ${環境變數} 在連線時才換掉，這裡先代入範例值檢查格式。
    sample = mcp_servers._ENV_REFERENCE.sub("http://example", url)  # noqa: SLF001
    parts = parse.urlsplit(sample)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise McpAdminError(
            "網址必須以 http:// 或 https:// 開頭，例如 "
            "http://litellm:4000/webiq/mcp"
        )
    if url.rstrip("/").endswith("/sse"):
        raise McpAdminError(
            "不支援舊的 SSE 傳輸，請改用伺服器的 Streamable HTTP 端點"
            "（通常是 /mcp）"
        )
    return url


def _checked_description(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise McpAdminError("說明必須是文字")
    if len(value.strip()) > _MAX_DESCRIPTION:
        raise McpAdminError(f"說明最多 {_MAX_DESCRIPTION} 字")
    return value.strip()


def _checked_bool(value: Any, what: str) -> bool:
    if not isinstance(value, bool):
        raise McpAdminError(f"{what} 必須是 true 或 false")
    return value


def _checked_headers(value: Any, stored: dict[str, str]) -> dict[str, str]:
    """[{name, value}] → {name: value}；value 留空時用 stored 裡存的值。"""
    if value is None:
        return {}
    if not isinstance(value, list) or len(value) > _MAX_HEADERS:
        raise McpAdminError(f"headers 必須是清單，最多 {_MAX_HEADERS} 個")
    found: dict[str, str] = {}
    for item in value:
        if not isinstance(item, dict):
            raise McpAdminError("每個標頭都要有 name 與 value")
        name = item.get("name")
        if not isinstance(name, str) or not _HEADER_NAME.match(name.strip()):
            raise McpAdminError(f"標頭名稱不對：{name}")
        name = name.strip()
        if name.lower() in (key.lower() for key in found):
            raise McpAdminError(f"標頭 {name} 重複了")
        raw = item.get("value")
        if raw is not None and not isinstance(raw, str):
            raise McpAdminError(f"標頭 {name} 的值必須是文字")
        text = (raw or "").strip()
        if not text:
            if name not in stored:
                raise McpAdminError(f"請填寫標頭 {name} 的值")
            text = stored[name]
        if len(text) > _MAX_VALUE or "\n" in text or "\r" in text:
            raise McpAdminError(f"標頭 {name} 的值不對（太長或有換行）")
        found[name] = text
    return found


def _short(error: BaseException) -> str:
    """錯誤訊息，太長時截斷。"""
    text = str(error) or type(error).__name__
    return text if len(text) <= 600 else text[:600] + "…"
