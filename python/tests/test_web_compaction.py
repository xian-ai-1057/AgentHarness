"""網頁版的對話壓縮：上下文用量、/compact 與管理平台的設定。"""

import pytest
import yaml

from harness import model_catalog
from tests import conftest
from tests.test_web import start  # noqa: F401  pytest fixture

MODEL = "test-model"
WINDOWS = f"""
compaction:
  contextWindows:
    {MODEL}: 100000
"""
SUMMARY = "## 使用者的需求與意圖\n- 查十月營收"


@pytest.fixture(autouse=True)
def fixed_model(monkeypatch):
    """固定預設模型，不向任何端點查上限。"""
    monkeypatch.setenv("HARNESS_MODEL", MODEL)
    monkeypatch.delenv("HARNESS_BASE_URL", raising=False)


def _ends(h):
    return [e for e in h.events if e["type"] == "run_end"]


async def _wait_runs(h, count):
    """等到第 count 次 run_end。"""
    return await h.wait_for("run_end", lambda _: len(_ends(h)) >= count)


async def _chat(h, *texts):
    """依序送出訊息，等每一輪跑完；回傳對話識別碼。"""
    _, created = await h.api("POST", "/sessions", {"text": texts[0]})
    await _wait_runs(h, 1)
    for index, text in enumerate(texts[1:], start=2):
        await h.api(
            "POST", f"/sessions/{created['id']}/messages", {"text": text}
        )
        await _wait_runs(h, index)
    return created["id"]


async def test_summary_reports_context_usage(start):  # noqa: F811
    h = await start([conftest.text_response("好")], extra=WINDOWS)

    session_id = await _chat(h, "嗨")

    _, detail = await h.api("GET", f"/sessions/{session_id}")
    usage = detail["summary"]["context"]
    assert usage["window"] == 100_000
    assert usage["threshold"] == 80_000
    assert usage["tokens"] > 0
    assert usage["auto"] is True


async def test_compact_command_summarizes_the_conversation(start):  # noqa: F811
    h = await start(
        [
            conftest.text_response("一" * 200),
            conftest.text_response("二" * 200),
            conftest.text_response(SUMMARY),
        ],
        extra=WINDOWS,
    )
    session_id = await _chat(h, "第一題" + "問" * 200, "第二題")

    status, summary = await h.api(
        "POST",
        f"/sessions/{session_id}/compact",
        {"instructions": "保留營收數字"},
    )
    await h.wait_for("session_reload")
    await _wait_runs(h, 3)
    end = _ends(h)[-1]

    assert status == 202
    assert summary["activity"] == {"kind": "compacting"}
    assert end["stopReason"] == "end_turn"
    prompt = h.model.requests[2]["messages"][-1]["content"]
    assert "保留營收數字" in prompt
    _, detail = await h.api("GET", f"/sessions/{session_id}")
    [record] = [m for m in detail["messages"] if m.get("type") == "compaction"]
    assert record["reason"] == "manual"
    assert record["summary"] == SUMMARY
    assert detail["summary"]["context"]["tokens"] == record["tokens_after"]


async def test_failed_compaction_is_shown_as_an_error(start):  # noqa: F811
    h = await start(
        [
            conftest.text_response("一" * 200),
            conftest.text_response("二"),
            conftest.text_response(""),
        ],
        extra=WINDOWS,
    )
    session_id = await _chat(h, "第一題", "第二題")

    await h.api("POST", f"/sessions/{session_id}/compact", {})
    await h.wait_for("run_error")

    _, detail = await h.api("GET", f"/sessions/{session_id}")
    assert detail["summary"]["status"] == "error"
    assert detail["summary"]["error"].startswith("壓縮失敗：")


async def test_auto_compaction_shows_compacting_activity(start):  # noqa: F811
    tiny = f"\ncompaction:\n  contextWindows:\n    {MODEL}: 1500\n"
    h = await start(
        [
            conftest.text_response("一" * 600),
            conftest.text_response(SUMMARY),
            conftest.text_response("好"),
        ],
        extra=tiny,
    )

    await _chat(h, "第一題" + "問" * 600, "第二題")

    activities = [
        e["summary"].get("activity") for e in h.events if e["type"] == "session"
    ]
    assert {"kind": "compacting"} in activities
    assert any(e["type"] == "session_reload" for e in h.events)


class TestAdminSettings:
    """管理平台的對話壓縮設定。"""

    async def test_lists_models_with_their_windows(self, start, monkeypatch):  # noqa: F811
        async def detected():
            return {"gemma-4-31b": 196608}

        monkeypatch.setattr(model_catalog, "context_windows", detected)
        h = await start(extra=WINDOWS)
        await h.api("PUT", "/settings/models", {"models": ["gemma-4-31b"]})

        status, settings = await h.api("GET", "/settings/compaction")

        assert status == 200
        assert settings["enabled"] is True
        assert settings["auto"] is True
        assert settings["thresholdRatio"] == 0.8
        models = {m["name"]: m for m in settings["models"]}
        assert models[MODEL]["window"] == 100_000
        assert models[MODEL]["source"] == "config"
        assert models["gemma-4-31b"]["window"] == 196608
        assert models["gemma-4-31b"]["source"] == "detected"
        assert models["gemma-4-31b"]["configured"] is None

    async def test_saving_writes_harness_yaml(self, start):  # noqa: F811
        h = await start()

        status, _ = await h.api(
            "PUT",
            "/settings/compaction",
            {
                "auto": False,
                "thresholdRatio": 0.7,
                "contextWindows": {MODEL: 32000, "other": None},
            },
        )

        assert status == 200
        config = yaml.safe_load((h.root / "harness.yaml").read_text("utf-8"))
        assert config["compaction"] == {
            "auto": False,
            "thresholdRatio": 0.7,
            "contextWindows": {MODEL: 32000},
        }
        _, settings = await h.api("GET", "/settings/compaction")
        assert settings["auto"] is False
        models = {m["name"]: m for m in settings["models"]}
        assert models[MODEL]["window"] == 32000

    async def test_defaults_remove_the_block(self, start):  # noqa: F811
        h = await start(extra=WINDOWS)

        await h.api(
            "PUT",
            "/settings/compaction",
            {"auto": True, "thresholdRatio": 0.8, "contextWindows": {}},
        )

        config = yaml.safe_load((h.root / "harness.yaml").read_text("utf-8"))
        assert "compaction" not in config

    @pytest.mark.parametrize(
        "body",
        [
            {"auto": True, "thresholdRatio": 0.2, "contextWindows": {}},
            {"auto": "yes", "thresholdRatio": 0.8, "contextWindows": {}},
            {"auto": True, "thresholdRatio": 0.8, "contextWindows": {"m": 5}},
            {"auto": True, "thresholdRatio": 0.8, "contextWindows": []},
        ],
    )
    async def test_invalid_settings_are_rejected(self, start, body):  # noqa: F811
        h = await start()

        status, _ = await h.api("PUT", "/settings/compaction", body)

        assert status == 400
