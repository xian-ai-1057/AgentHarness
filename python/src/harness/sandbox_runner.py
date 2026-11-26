"""沙盒服務：唯一能啟動容器的地方（pyharness sandbox-runner）。

能使用 Docker socket 就能以 root 身分在主機上做任何事（例如啟動一個掛載
主機根目錄的特權容器）。所以 docker compose 部署時，平台容器不掛 socket，
改由這個只做一件事的小服務持有：平台把「在沙盒裡執行這段程式」的請求送
過來，服務照自己的設定組出 docker run 的參數。平台即使被攻破，能做的也
只是請服務在沙盒裡執行程式，碰不到主機：

    - 映像檔、容器裡的使用者、runtime（例如 gVisor 的 runsc）與資源上限
      都由服務的環境變數決定，請求只能要求更少的資源。
    - 只掛載 HARNESS_SANDBOX_VOLUME 這個 volume 裡的一個子資料夾，而且不能
      是 volume 的根目錄、不能含 ..，也不能是專案的設定與程式
      （harness.yaml、agents/、tools/、skills/、.harness/ 等）。
    - 一律沒有網路，除非服務設定 HARNESS_SANDBOX_ALLOW_NETWORK=1。
    - 只接受 python - 與 bash -lc <指令> 兩種執行方式。
    - 容器名稱必須是 harness-sandbox-<12 位十六進位>，/kill 只停得掉這種
      名稱的容器。

服務只在 compose 的內部網路上提供，另外每次啟動產生一組通行碼寫進
HARNESS_SANDBOX_TOKEN_FILE（平台唯讀掛載同一個 volume 讀取），請求要帶
Authorization: Bearer <通行碼>。

    POST /run   {"name", "argv", "stdin", "workdir", "timeout", "subpath",
                 "readOnly", "memory", "cpus", "network"}
                → {"exitCode", "stdout", "stderr", "timedOut"}
    POST /kill  {"name"} → {"ok": true}
    GET  /health → {"ok": true}
"""

import dataclasses
import hmac
import os
import pathlib
import re
import secrets
from typing import Any

from aiohttp import web

from harness import credentials
from harness import sandbox as sandbox_lib

DEFAULT_PORT = 4322
ALLOW_NETWORK_ENV = "HARNESS_SANDBOX_ALLOW_NETWORK"
USER_ENV = "HARNESS_SANDBOX_USER"
MAX_MEMORY_ENV = "HARNESS_SANDBOX_MAX_MEMORY"
MAX_CPUS_ENV = "HARNESS_SANDBOX_MAX_CPUS"
DEFAULT_USER = "1000:1000"
DEFAULT_MAX_MEMORY = "4g"
DEFAULT_MAX_CPUS = 2.0
MAX_TIMEOUT_SECONDS = 900
# 一段程式（從標準輸入交給 python）最多多大。
MAX_STDIN_BYTES = 2_000_000
# 網頁版 Office 預覽的轉檔暫存資料夾（web.office 的 _convert）。
PREVIEW_JOB = re.compile(r"^\.harness/previews/jobs/[0-9a-f]{32}$")
_MEMORY = re.compile(r"^([0-9]+)([kmg]?)$", re.IGNORECASE)
_UNITS = {"": 1, "k": 1024, "m": 1024**2, "g": 1024**3}


@dataclasses.dataclass(frozen=True)
class Settings:
    """沙盒服務的設定，全部來自服務自己的環境變數。

    Attributes:
        image: 沙盒的映像檔。
        volume: 工作資料夾所在的 Docker volume。
        user: 容器裡的使用者（uid:gid）。
        runtime: 容器的 runtime，例如 runsc；None 表示 Docker 的預設值。
        allow_network: 請求要求連網時是否允許。
        max_memory: 記憶體上限（位元組）。
        max_cpus: CPU 上限。
        token: 平台要帶的通行碼。
        command: docker 或 podman。
    """

    image: str
    volume: str
    user: str = DEFAULT_USER
    runtime: str | None = None
    allow_network: bool = False
    max_memory: int = 4 * 1024**3
    max_cpus: float = DEFAULT_MAX_CPUS
    token: str = ""
    command: str = "docker"


def settings_from_env(token: str) -> Settings:
    """依環境變數建立設定。

    Args:
        token: 這次啟動產生的通行碼。

    Raises:
        ValueError: 少了必要的設定或寫錯。
    """
    volume = os.environ.get(sandbox_lib.VOLUME_ENV, "").strip()
    if not volume:
        raise ValueError(
            f"沙盒服務需要 {sandbox_lib.VOLUME_ENV}（工作資料夾所在的 volume）"
        )
    image = (
        os.environ.get(sandbox_lib.IMAGE_ENV, "").strip()
        or sandbox_lib.DEFAULT_IMAGE
    )
    max_memory = parse_memory(
        os.environ.get(MAX_MEMORY_ENV, "").strip() or DEFAULT_MAX_MEMORY
    )
    try:
        max_cpus = float(os.environ.get(MAX_CPUS_ENV) or DEFAULT_MAX_CPUS)
    except ValueError as error:
        raise ValueError(f"{MAX_CPUS_ENV} 必須是數字") from error
    return Settings(
        image=image,
        volume=volume,
        user=os.environ.get(USER_ENV, "").strip() or DEFAULT_USER,
        runtime=os.environ.get(sandbox_lib.RUNTIME_ENV, "").strip() or None,
        allow_network=os.environ.get(ALLOW_NETWORK_ENV, "") == "1",
        max_memory=max_memory,
        max_cpus=max_cpus,
        token=token,
    )


def parse_memory(text: str) -> int:
    """把 Docker 寫法的記憶體大小（512m、1g）換成位元組。

    Raises:
        ValueError: 寫法不對。
    """
    match = _MEMORY.match(text.strip())
    if not match:
        raise ValueError(f"記憶體的寫法不對：{text}（例如 512m、1g）")
    return int(match.group(1)) * _UNITS[match.group(2).lower()]


def check_subpath(subpath: Any) -> str:
    """檢查要掛載的子資料夾，回傳整理過的寫法。

    .harness/ 底下只有一個例外：網頁把 Office 檔轉成 PDF 預覽時的暫存
    資料夾 .harness/previews/jobs/<32 位十六進位>（見 web.office），裡面
    只有要轉的那一份檔案。

    Raises:
        ValueError: 不是 volume 裡一個允許掛載的子資料夾。
    """
    if isinstance(subpath, str) and PREVIEW_JOB.match(subpath):
        return subpath
    if not isinstance(subpath, str) or not subpath.strip():
        raise ValueError("subpath 不能是空的：不能掛載整個 volume")
    if subpath.startswith("/") or "\\" in subpath or "\0" in subpath:
        raise ValueError("subpath 必須是 volume 裡的相對路徑")
    parts = [part for part in subpath.split("/") if part not in ("", ".")]
    if not parts or ".." in parts:
        raise ValueError("subpath 不能含 ..，也不能是 volume 的根目錄")
    first = parts[0].casefold()
    if any(first == item.casefold() for item in sandbox_lib.PROTECTED):
        raise ValueError(f"不能掛載專案的設定與程式（{parts[0]}）")
    if any(part.startswith(".") for part in parts):
        raise ValueError("不能掛載以點開頭的資料夾")
    return "/".join(parts)


def check_request(settings: Settings, body: Any) -> dict[str, Any]:
    """檢查 /run 的請求，回傳執行需要的值。

    Raises:
        ValueError: 請求不合法；訊息會原樣回給平台。
    """
    if not isinstance(body, dict):
        raise ValueError("請求必須是 JSON 物件")
    name = body.get("name")
    if not isinstance(name, str) or not sandbox_lib.NAME_PATTERN.match(name):
        raise ValueError("name 必須是 harness-sandbox-<12 位十六進位>")
    argv = body.get("argv")
    if argv == ["python", "-"]:
        pass
    elif (
        isinstance(argv, list)
        and len(argv) == 3
        and argv[:2] == ["bash", "-lc"]
        and isinstance(argv[2], str)
        and argv[2].strip()
    ):
        pass
    else:
        raise ValueError("argv 只能是 [python, -] 或 [bash, -lc, 指令]")
    stdin = body.get("stdin", "")
    if not isinstance(stdin, str) or len(stdin.encode()) > MAX_STDIN_BYTES:
        raise ValueError("stdin 必須是文字，而且不能超過 2 MB")
    workdir = body.get("workdir", sandbox_lib.CONTAINER_WORKDIR)
    base = sandbox_lib.CONTAINER_WORKDIR
    if not isinstance(workdir, str) or not (
        workdir == base or workdir.startswith(f"{base}/")
    ):
        raise ValueError(f"workdir 必須在 {base} 裡")
    if ".." in workdir.split("/"):
        raise ValueError("workdir 不能含 ..")
    timeout = body.get("timeout")
    if (
        not isinstance(timeout, int | float)
        or isinstance(timeout, bool)
        or not 0 < timeout <= MAX_TIMEOUT_SECONDS
    ):
        raise ValueError(f"timeout 必須介於 0 到 {MAX_TIMEOUT_SECONDS} 秒")
    network = body.get("network", False) is True
    if network and not settings.allow_network:
        raise ValueError(
            f"沙盒服務不允許連網（要開放請在服務設定 {ALLOW_NETWORK_ENV}=1）"
        )
    memory = settings.max_memory
    if isinstance(body.get("memory"), str):
        memory = min(memory, parse_memory(body["memory"]))
    cpus = settings.max_cpus
    if isinstance(body.get("cpus"), int | float) and body["cpus"] > 0:
        cpus = min(cpus, float(body["cpus"]))
    return {
        "name": name,
        "argv": tuple(argv),
        "stdin": stdin,
        "workdir": workdir,
        "timeout": float(timeout),
        "subpath": check_subpath(body.get("subpath")),
        "read_only": body.get("readOnly") is True,
        "memory": memory,
        "cpus": cpus,
        "network": network,
    }


def sandbox_for(
    settings: Settings, request: dict[str, Any]
) -> sandbox_lib.Sandbox:
    """依服務的設定與檢查過的請求建立沙盒。"""
    return sandbox_lib.Sandbox(
        # 服務看不到 volume 的內容，workspace 只是佔位用，不會被讀寫。
        workspace=pathlib.Path("/nonexistent"),
        image=settings.image,
        timeout_seconds=request["timeout"],
        memory=str(request["memory"]),
        cpus=request["cpus"],
        network=request["network"],
        command=settings.command,
        volume=settings.volume,
        volume_subpath=request["subpath"],
        read_only=request["read_only"],
        runtime=settings.runtime,
        user=settings.user,
    )


def build_app(settings: Settings) -> web.Application:
    """建立沙盒服務的 aiohttp 應用程式。"""

    @web.middleware
    async def authorize(
        request: web.Request, handler: Any
    ) -> web.StreamResponse:
        if request.path == "/health":
            return await handler(request)
        given = request.headers.get("Authorization", "")
        expected = f"Bearer {settings.token}"
        if not settings.token or not hmac.compare_digest(
            given.encode(), expected.encode()
        ):
            return web.json_response({"error": "通行碼不正確"}, status=401)
        return await handler(request)

    async def health(_: web.Request) -> web.Response:
        return web.json_response({"ok": True})

    async def run(request: web.Request) -> web.Response:
        try:
            body = await request.json()
            checked = check_request(settings, body)
        except ValueError as error:
            return web.json_response({"error": str(error)}, status=400)
        box = sandbox_for(settings, checked)
        try:
            result = await box.run_container(
                checked["name"],
                checked["argv"],
                checked["stdin"],
                checked["workdir"],
                checked["timeout"],
            )
        except RuntimeError as error:
            return web.json_response({"error": str(error)}, status=503)
        return web.json_response(
            {
                "exitCode": result.exit_code,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "timedOut": result.timed_out,
            }
        )

    async def kill(request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except ValueError:
            body = None
        name = body.get("name") if isinstance(body, dict) else None
        if not isinstance(name, str) or not sandbox_lib.NAME_PATTERN.match(
            name
        ):
            return web.json_response({"error": "name 不正確"}, status=400)
        process = await _docker(settings.command, "kill", name)
        return web.json_response({"ok": process == 0})

    app = web.Application(middlewares=[authorize], client_max_size=4 * 1024**2)
    app.router.add_get("/health", health)
    app.router.add_post("/run", run)
    app.router.add_post("/kill", kill)
    return app


async def _docker(command: str, *args: str) -> int | None:
    import asyncio

    try:
        process = await asyncio.create_subprocess_exec(
            command,
            *args,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(process.wait(), 15)
    except (OSError, TimeoutError):
        return None
    return process.returncode


def write_token(path: str | pathlib.Path) -> str:
    """產生一組新的通行碼寫進檔案（只有擁有者能讀），回傳通行碼。"""
    token = secrets.token_urlsafe(32)
    target = pathlib.Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    # 資料夾由平台唯讀掛載，平台以同一個使用者執行，所以不必開放給其他人。
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as file:
        file.write(token + "\n")
    target.chmod(0o600)
    return token


def serve(host: str, port: int) -> None:
    """啟動沙盒服務，直到被停止。"""
    token_file = os.environ.get(sandbox_lib.TOKEN_FILE_ENV, "").strip()
    if not token_file:
        raise ValueError(
            f"沙盒服務需要 {sandbox_lib.TOKEN_FILE_ENV}（通行碼要寫在哪裡）"
        )
    settings = settings_from_env(write_token(token_file))
    # 服務本身不需要任何金鑰；docker 指令也不必知道。
    for name in list(os.environ):
        if credentials.is_secret_name(name):
            os.environ.pop(name, None)
    runtime = settings.runtime or "Docker 預設（runc）"
    network = "允許" if settings.allow_network else "一律關閉"
    print(
        f"沙盒服務已啟動：{host}:{port}\n"
        f"  映像檔 {settings.image}、volume {settings.volume}、"
        f"使用者 {settings.user}、runtime {runtime}、網路{network}",
        flush=True,
    )
    web.run_app(build_app(settings), host=host, port=port, print=None)
