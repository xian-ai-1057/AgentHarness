"""沙盒服務（sandbox_runner）與沙盒透過服務執行的測試。"""

import asyncio
import pathlib

import pytest
from aiohttp import test_utils

from harness import sandbox
from harness import sandbox_runner

NAME = "harness-sandbox-0123456789ab"


def _settings(**changes):
    values = {
        "image": "harness-sandbox",
        "volume": "harness-data",
        "token": "secret-token",
    }
    values.update(changes)
    return sandbox_runner.Settings(**values)


def _body(**changes):
    body = {
        "name": NAME,
        "argv": ["python", "-"],
        "stdin": "print(1)",
        "workdir": "/workspace",
        "timeout": 30,
        "subpath": "private/u1",
        "readOnly": False,
        "memory": "1g",
        "cpus": 1,
        "network": False,
    }
    body.update(changes)
    return body


class TestCheckRequest:
    """服務只接受安全的請求。"""

    def test_accepts_a_normal_run(self):
        checked = sandbox_runner.check_request(_settings(), _body())

        assert checked["subpath"] == "private/u1"
        assert checked["argv"] == ("python", "-")
        assert checked["memory"] == 1024**3
        assert checked["network"] is False

    @pytest.mark.parametrize(
        "subpath",
        [
            "",
            ".",
            "/etc",
            "../other",
            "private/../.harness",
            ".harness/secrets",
            "harness.yaml",
            "Tools",
            "agents/x",
            "skills",
            "private/.ssh",
            None,
        ],
    )
    def test_refuses_dangerous_mounts(self, subpath):
        with pytest.raises(ValueError):
            sandbox_runner.check_request(_settings(), _body(subpath=subpath))

    @pytest.mark.parametrize(
        "argv",
        [
            ["sh", "-c", "id"],
            ["python", "-c", "1"],
            ["bash", "-lc", ""],
            ["bash", "-lc", "ls", "extra"],
            "python -",
        ],
    )
    def test_only_python_and_bash_lc(self, argv):
        with pytest.raises(ValueError, match="argv"):
            sandbox_runner.check_request(_settings(), _body(argv=argv))

    @pytest.mark.parametrize(
        "name", ["x", "harness-sandbox-xyz", "other-0123456789ab", 5]
    )
    def test_container_name_must_be_ours(self, name):
        with pytest.raises(ValueError, match="name"):
            sandbox_runner.check_request(_settings(), _body(name=name))

    @pytest.mark.parametrize("workdir", ["/", "/etc", "/workspace/../etc"])
    def test_workdir_stays_in_workspace(self, workdir):
        with pytest.raises(ValueError, match="workdir"):
            sandbox_runner.check_request(_settings(), _body(workdir=workdir))

    @pytest.mark.parametrize("timeout", [0, -1, 10_000, "30", True])
    def test_timeout_is_bounded(self, timeout):
        with pytest.raises(ValueError, match="timeout"):
            sandbox_runner.check_request(_settings(), _body(timeout=timeout))

    def test_network_needs_the_runner_to_allow_it(self):
        with pytest.raises(ValueError, match="連網"):
            sandbox_runner.check_request(_settings(), _body(network=True))

        allowed = _settings(allow_network=True)
        checked = sandbox_runner.check_request(allowed, _body(network=True))
        assert checked["network"] is True

    def test_resources_are_capped_by_the_runner(self):
        settings = _settings(max_memory=2 * 1024**3, max_cpus=2.0)

        more = sandbox_runner.check_request(
            settings, _body(memory="64g", cpus=32)
        )
        less = sandbox_runner.check_request(
            settings, _body(memory="512m", cpus=0.5)
        )

        assert (more["memory"], more["cpus"]) == (2 * 1024**3, 2.0)
        assert (less["memory"], less["cpus"]) == (512 * 1024**2, 0.5)


class TestDockerArgsFromRunner:
    """服務組出的 docker run：映像檔、使用者與 runtime 由服務決定。"""

    def test_uses_runner_settings_not_the_request(self):
        settings = _settings(user="1000:1000", runtime="runsc")
        checked = sandbox_runner.check_request(
            settings, _body(subpath="shared", readOnly=True)
        )
        box = sandbox_runner.sandbox_for(settings, checked)

        args = box.docker_args(NAME)

        assert args[args.index("--user") + 1] == "1000:1000"
        assert args[args.index("--runtime") + 1] == "runsc"
        assert args[args.index("--network") + 1] == "none"
        mount = args[args.index("--mount") + 1]
        assert "src=harness-data" in mount
        assert "volume-subpath=shared" in mount
        assert mount.endswith(",readonly")
        assert "harness-sandbox" in args
        assert "--privileged" not in args
        assert "-v" not in args


@pytest.fixture
async def runner(monkeypatch, tmp_path):
    """在本機啟動沙盒服務；docker 換成記錄呼叫的假函式。"""
    calls = []
    kills = []
    started = asyncio.Event()
    release = asyncio.Event()

    async def fake_run(self, name, argv, stdin, workdir, timeout):
        calls.append(
            {
                "name": name,
                "argv": argv,
                "stdin": stdin,
                "workdir": workdir,
                "args": self.docker_args(name, argv, workdir),
            }
        )
        if stdin == "block":
            started.set()
            await release.wait()
        return sandbox.Result(0, f"ran {argv[0]}\n", "")

    async def fake_docker(command, *args):
        kills.append(args)
        release.set()
        return 0

    monkeypatch.setattr(sandbox.Sandbox, "run_container", fake_run)
    monkeypatch.setattr(sandbox_runner, "_docker", fake_docker)
    token_file = tmp_path / "runner" / "token"
    token = sandbox_runner.write_token(token_file)
    app = sandbox_runner.build_app(_settings(token=token))
    server = test_utils.TestServer(app)
    await server.start_server()
    yield _Runner(server, token_file, calls, kills, started)
    await server.close()


class _Runner:
    def __init__(self, server, token_file, calls, kills, started):
        self.url = str(server.make_url("")).rstrip("/")
        self.token_file = token_file
        self.calls = calls
        self.kills = kills
        self.started = started


def _remote_box(tmp_path, runner, **changes):
    values = {
        "workspace": tmp_path / "data" / "private" / "u1",
        "volume": "harness-data",
        "volume_subpath": "private/u1",
        "runner": runner.url,
        "runner_token_file": str(runner.token_file),
    }
    values.update(changes)
    return sandbox.Sandbox(**values)


class TestRemoteSandbox:
    """平台透過服務執行沙盒。"""

    async def test_python_runs_through_the_runner(self, tmp_path, runner):
        box = _remote_box(tmp_path, runner)

        result = await box.run("print(1)")

        assert result.exit_code == 0
        assert result.stdout == "ran python\n"
        [call] = runner.calls
        assert call["argv"] == ("python", "-")
        assert call["stdin"] == "print(1)"
        assert box.workspace.is_dir()

    async def test_shell_command_runs_through_the_runner(
        self, tmp_path, runner
    ):
        box = _remote_box(tmp_path, runner)

        result = await box.run_shell("ls", "/workspace/sub", 20)

        assert result.stdout == "ran bash\n"
        [call] = runner.calls
        assert call["argv"] == ("bash", "-lc", "ls")
        assert call["workdir"] == "/workspace/sub"

    async def test_wrong_token_is_refused(self, tmp_path, runner):
        wrong = tmp_path / "wrong-token"
        wrong.write_text("nope")
        box = _remote_box(tmp_path, runner, runner_token_file=str(wrong))

        with pytest.raises(RuntimeError, match="通行碼"):
            await box.run("print(1)")
        assert runner.calls == []

    async def test_refusal_is_explained(self, tmp_path, runner):
        box = _remote_box(tmp_path, runner, volume_subpath=".harness")

        with pytest.raises(RuntimeError, match="拒絕執行"):
            await box.run("print(1)")

    async def test_cancelling_asks_the_runner_to_stop_the_container(
        self, tmp_path, runner
    ):
        box = _remote_box(tmp_path, runner)

        task = asyncio.create_task(box.run("block"))
        await asyncio.wait_for(runner.started.wait(), 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        [call] = runner.calls
        assert runner.kills == [("kill", call["name"])]

    async def test_unreachable_runner_is_explained(self, tmp_path):
        box = sandbox.Sandbox(
            workspace=tmp_path / "w",
            volume="harness-data",
            volume_subpath="w",
            runner="http://127.0.0.1:9",
        )

        with pytest.raises(RuntimeError, match="連不上沙盒服務"):
            await box.run("print(1)")

    async def test_runner_needs_a_volume(self, tmp_path, runner):
        box = _remote_box(tmp_path, runner, volume=None)

        with pytest.raises(RuntimeError, match="volume"):
            await box.run("print(1)")

    async def test_health_needs_no_token(self, runner):
        import aiohttp

        async with aiohttp.ClientSession() as session:
            async with session.get(f"{runner.url}/health") as response:
                assert response.status == 200
            async with session.post(f"{runner.url}/run", json={}) as response:
                assert response.status == 401


class TestFromConfig:
    """環境變數讓 harness.yaml 的沙盒改用服務。"""

    def test_runner_env_switches_to_the_runner(self, tmp_path, monkeypatch):
        monkeypatch.setenv(sandbox.RUNNER_ENV, "http://sandbox-runner:4322")
        monkeypatch.setenv(sandbox.TOKEN_FILE_ENV, "/run/harness-runner/token")
        monkeypatch.setenv(sandbox.VOLUME_ENV, "harness-data")

        box = sandbox.from_config(tmp_path, True)

        assert box.runner == "http://sandbox-runner:4322"
        assert box.runner_token_file == "/run/harness-runner/token"
        assert box.volume == "harness-data"
        assert sandbox.available("no-such-docker")

    def test_runtime_from_env_or_config(self, tmp_path, monkeypatch):
        monkeypatch.setenv(sandbox.RUNTIME_ENV, "runsc")
        assert sandbox.from_config(tmp_path, True).runtime == "runsc"
        box = sandbox.from_config(tmp_path, {"runtime": "kata"})
        assert box.runtime == "kata"
        assert "--runtime" in box.docker_args("x")


class TestSettings:
    """服務的設定來自自己的環境變數。"""

    def test_needs_a_volume(self, monkeypatch):
        monkeypatch.delenv(sandbox.VOLUME_ENV, raising=False)

        with pytest.raises(ValueError, match="VOLUME"):
            sandbox_runner.settings_from_env("t")

    def test_reads_limits(self, monkeypatch):
        monkeypatch.setenv(sandbox.VOLUME_ENV, "v")
        monkeypatch.setenv(sandbox.IMAGE_ENV, "img")
        monkeypatch.setenv(sandbox_runner.MAX_MEMORY_ENV, "2g")
        monkeypatch.setenv(sandbox_runner.ALLOW_NETWORK_ENV, "1")
        monkeypatch.setenv(sandbox.RUNTIME_ENV, "runsc")

        settings = sandbox_runner.settings_from_env("t")

        assert settings.image == "img"
        assert settings.max_memory == 2 * 1024**3
        assert settings.allow_network is True
        assert settings.runtime == "runsc"
        assert settings.user == sandbox_runner.DEFAULT_USER

    def test_token_file_is_private(self, tmp_path):
        path = tmp_path / "t" / "token"

        token = sandbox_runner.write_token(path)

        assert pathlib.Path(path).read_text().strip() == token
        assert path.stat().st_mode & 0o777 == 0o600
