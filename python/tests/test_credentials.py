"""存在專案裡的金鑰與登入密碼的測試。"""

import json
import os
import stat

import pytest

from harness import credentials
from harness import tools
from harness.builtin import files


@pytest.fixture(autouse=True)
def restore_env(monkeypatch):
    """測試會改動的環境變數，結束後恢復原狀。"""
    for name in ("DEMO_API_KEY", "HARNESS_BASE_URL"):
        monkeypatch.delenv(name, raising=False)


def _mode(path):
    return stat.S_IMODE(path.stat().st_mode)


def test_update_saves_private_file_and_sets_environment(tmp_path):
    credentials.update(tmp_path, {"DEMO_API_KEY": "sk-1"})

    path = credentials.secrets_dir(tmp_path) / credentials.ENV_FILE
    assert json.loads(path.read_text("utf-8")) == {"DEMO_API_KEY": "sk-1"}
    assert _mode(path) == 0o600
    assert _mode(path.parent) == 0o700
    assert os.environ["DEMO_API_KEY"] == "sk-1"


def test_apply_overrides_environment_on_next_start(tmp_path, monkeypatch):
    credentials.update(tmp_path, {"DEMO_API_KEY": "from-web"})
    monkeypatch.setenv("DEMO_API_KEY", "from-deployment")

    applied = credentials.apply(tmp_path)

    assert applied == ["DEMO_API_KEY"]
    assert os.environ["DEMO_API_KEY"] == "from-web"


def test_empty_value_turns_off_a_variable_set_at_startup(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_BASE_URL", "http://proxy:4000")

    credentials.update(tmp_path, {"HARNESS_BASE_URL": ""})
    assert "HARNESS_BASE_URL" not in os.environ

    monkeypatch.setenv("HARNESS_BASE_URL", "http://proxy:4000")
    credentials.apply(tmp_path)
    assert "HARNESS_BASE_URL" not in os.environ


def test_none_forgets_a_saved_value(tmp_path):
    credentials.update(tmp_path, {"DEMO_API_KEY": "sk-1"})

    credentials.update(tmp_path, {"DEMO_API_KEY": None})

    assert credentials.load(tmp_path) == {}


def test_missing_or_broken_file_is_treated_as_empty(tmp_path):
    assert credentials.apply(tmp_path) == []

    path = credentials.secrets_dir(tmp_path) / credentials.ENV_FILE
    path.parent.mkdir(parents=True)
    path.write_text("{ not json", encoding="utf-8")

    assert credentials.load(tmp_path) == {}


def test_web_password_is_generated_once_and_kept_private(tmp_path):
    first, created = credentials.web_password(tmp_path)
    second, created_again = credentials.web_password(tmp_path)

    assert created is True
    assert created_again is False
    assert first == second
    assert len(first) >= 20
    path = credentials.secrets_dir(tmp_path) / credentials.PASSWORD_FILE
    assert _mode(path) == 0o600


@pytest.mark.parametrize(
    "path",
    [
        ".harness/secrets/env.json",
        ".harness/secrets",
        "a/../.harness/secrets/x",
    ],
)
async def test_file_tools_cannot_touch_saved_secrets(context, path):
    credentials.update(context.workdir, {"DEMO_API_KEY": "sk-1"})

    with pytest.raises(ValueError, match="金鑰"):
        files.resolve_path(context, path)
    with pytest.raises(ValueError, match="金鑰"):
        await tools.invoke(files.read_file, {"path": path}, context)
    with pytest.raises(ValueError, match="金鑰"):
        await tools.invoke(
            files.write_file, {"path": path, "content": "{}"}, context
        )


async def test_file_tools_can_still_read_other_harness_data(context):
    target = context.workdir / ".harness" / "memory.json"
    target.parent.mkdir()
    target.write_text("[]", encoding="utf-8")

    output = await tools.invoke(
        files.read_file, {"path": ".harness/memory.json"}, context
    )

    assert output == "[]"


class TestChildEnvironment:
    """harness 啟動的程式拿不到金鑰。"""

    def test_secret_looking_names_are_removed(self, monkeypatch):
        monkeypatch.setenv("DEMO_API_KEY", "sk-1")
        monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-2")
        monkeypatch.setenv("SOME_SECRET", "s")
        monkeypatch.setenv("GH_TOKEN", "t")
        monkeypatch.setenv("DB_PASSWORD", "p")
        monkeypatch.setenv("HTTPS_PROXY", "http://proxy:3128")
        monkeypatch.setenv("PLAIN_SETTING", "ok")

        env = credentials.child_environment()

        for name in (
            "DEMO_API_KEY",
            "LITELLM_MASTER_KEY",
            "SOME_SECRET",
            "GH_TOKEN",
            "DB_PASSWORD",
        ):
            assert name not in env
        assert env["HTTPS_PROXY"] == "http://proxy:3128"
        assert env["PLAIN_SETTING"] == "ok"
        assert "PATH" in env
        # 不影響 harness 自己的環境變數。
        assert os.environ["DEMO_API_KEY"] == "sk-1"

    def test_values_saved_on_the_web_are_removed(self, tmp_path, monkeypatch):
        credentials.update(tmp_path, {"HARNESS_BASE_URL": "http://gw"})

        assert "HARNESS_BASE_URL" in credentials.child_environment()
        assert "HARNESS_BASE_URL" not in credentials.child_environment(tmp_path)

    def test_keep_list(self, monkeypatch):
        monkeypatch.setenv("GH_TOKEN", "t")
        monkeypatch.setenv("NPM_TOKEN", "n")
        monkeypatch.setenv(credentials.KEEP_ENV, "GH_TOKEN, ")

        env = credentials.child_environment(keep=("NPM_TOKEN",))

        assert env["GH_TOKEN"] == "t"
        assert env["NPM_TOKEN"] == "n"

    async def test_run_command_does_not_see_keys(self, tmp_path, monkeypatch):
        from harness import datatypes
        from harness.builtin import shell

        monkeypatch.setenv("DEMO_API_KEY", "sk-should-not-leak")
        context = datatypes.RunContext("t", tmp_path, "s")

        output = await tools.invoke(
            shell.run_command, {"command": "env"}, context
        )

        assert "sk-should-not-leak" not in output
        assert "PATH=" in output

    def test_protect_process_on_linux(self):
        import subprocess
        import sys

        if not sys.platform.startswith("linux"):
            pytest.skip("只在 Linux 上有效")
        # 在子行程裡設定，不影響跑測試的行程。
        code = (
            "from harness import credentials; "
            "print(credentials.protect_process()); "
            "print(open('/proc/self/status').read().count('\\n') > 0)"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            check=True,
        )
        assert result.stdout.split() == ["True", "True"]
