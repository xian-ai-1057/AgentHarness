"""向供應商與端點查詢模型清單（harness.model_catalog）。

用本機的假伺服器代替各家的 API，記下收到的網址與標頭。
"""

import asyncio
import json

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from harness import model_catalog
from harness import providers

RESPONSES = {
    "/v1/models": {
        "data": [
            {"id": "qwen3-32b", "object": "model"},
            {"id": "gpt-oss-120b"},
            {"id": "qwen3-32b"},
        ]
    },
    "/anthropic": {
        "data": [
            {"id": "claude-opus-5-5", "display_name": "Claude Opus 5.5"},
            {"id": "claude-haiku-5-5", "display_name": ""},
        ]
    },
    "/openai": {
        "data": [
            {"id": "gpt-5"},
            {"id": "o4-mini"},
            {"id": "text-embedding-3-small"},
            {"id": "gpt-4o-realtime-preview"},
            {"id": "dall-e-3"},
        ]
    },
    "/gemini": {
        "models": [
            {
                "name": "models/gemini-2.5-pro",
                "displayName": "Gemini 2.5 Pro",
                "supportedGenerationMethods": ["generateContent"],
            },
            {
                "name": "models/text-embedding-004",
                "supportedGenerationMethods": ["embedContent"],
            },
        ]
    },
    "/openrouter": {"data": [{"id": "meta/llama-4", "name": "Llama 4"}]},
    "/litellm/model/info": {
        "data": [
            {
                "model_name": "text-embedding-3-small",
                "model_info": {"mode": "embedding"},
            },
            {"model_name": "cohere-rerank", "model_info": {"mode": "rerank"}},
            {
                "model_name": "gpt-5",
                "model_info": {"mode": "chat", "max_input_tokens": 272000},
            },
            # 沒標明用途的依名稱猜。
            {"model_name": "bge-m3", "model_info": {}},
            {"model_name": "my-chat"},
        ]
    },
    "/vllm/v1/models": {
        "data": [
            {"id": "Qwen3-Embedding-8B"},
            {"id": "bge-reranker-v2-m3"},
            {"id": "gemma-4-31b", "max_model_len": 196608},
        ]
    },
    "/api/tags": {"models": [{"name": "hermes3:latest"}, {"name": "qwen3"}]},
}
# Anthropic 的清單分兩頁：第一頁 has_more，第二頁用 after_id 取。
ANTHROPIC_PAGES = {
    None: {
        "data": [{"id": "claude-opus-5-5", "display_name": "Claude Opus 5.5"}],
        "has_more": True,
        "first_id": "claude-opus-5-5",
        "last_id": "claude-opus-5-5",
    },
    "claude-opus-5-5": {
        "data": [
            {"id": "claude-haiku-5-5", "display_name": "Claude Haiku 5.5"}
        ],
        "has_more": False,
        "first_id": "claude-haiku-5-5",
        "last_id": "claude-haiku-5-5",
    },
}
ANTHROPIC_ERROR = {
    "type": "error",
    "error": {"type": "authentication_error", "message": "invalid x-api-key"},
}


@pytest.fixture
async def fake(monkeypatch):
    """假的 API；回傳 (base_url, 收到的請求)。"""
    seen = []

    async def handle(request: web.Request) -> web.Response:
        seen.append((request.path_qs, dict(request.headers)))
        if request.path == "/broken/models":
            return web.Response(
                text="<html>not json</html>", content_type="text/html"
            )
        if request.path == "/denied/models":
            return web.Response(status=401)
        if request.path == "/badkey/models":
            return web.json_response(ANTHROPIC_ERROR, status=401)
        if request.path == "/forbidden/models":
            return web.json_response(
                {"error": {"message": "Key not allowed to list models"}},
                status=403,
            )
        if request.path == "/litellm-down/models":
            return web.json_response({"detail": "upstream down"}, status=500)
        if request.path == "/paged/v1/models":
            if request.headers.get("x-api-key") != "k":
                return web.json_response(ANTHROPIC_ERROR, status=401)
            return web.json_response(
                ANTHROPIC_PAGES[request.query.get("after_id")]
            )
        if request.path == "/chunked/models":
            # 分好幾段送出，模擬真實 API 的 chunked 回應。
            response = web.StreamResponse()
            response.content_type = "application/json"
            await response.prepare(request)
            body = json.dumps(RESPONSES["/v1/models"]).encode()
            for start in range(0, len(body), 20):
                await response.write(body[start : start + 20])
                await asyncio.sleep(0.01)
            await response.write_eof()
            return response
        body = RESPONSES.get(request.path)
        if body is None:
            return web.Response(status=404)
        return web.json_response(body)

    app = web.Application()
    app.router.add_get("/{tail:.*}", handle)
    server = TestServer(app)
    await server.start_server()
    base = str(server.make_url("")).rstrip("/")
    monkeypatch.setattr(
        model_catalog,
        "_OFFICIAL",
        {
            name: f"{base}/{name}"
            for name in ("anthropic", "openai", "gemini", "openrouter")
        },
    )
    for name in ("HARNESS_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    yield base, seen
    await server.close()


def names(found):
    return [item.name for item in found]


async def test_endpoint_lists_models_and_tries_v1(fake):
    base, seen = fake

    found = await model_catalog.list_models(providers.ENDPOINT, base, "sk-x")

    # 先試 /models（404），再試 /v1/models；重複的名稱只留一個。
    assert [path for path, _ in seen] == ["/models", "/v1/models"]
    assert seen[-1][1]["Authorization"] == "Bearer sk-x"
    assert names(found) == ["gpt-oss-120b", "qwen3-32b"]


async def test_endpoint_uses_the_saved_key_only_when_allowed(fake, monkeypatch):
    base, seen = fake
    monkeypatch.setenv("HARNESS_API_KEY", "saved")

    await model_catalog.list_models(providers.ENDPOINT, f"{base}/v1")
    await model_catalog.list_models(
        providers.ENDPOINT, f"{base}/v1", saved_key=False
    )

    assert seen[0][1]["Authorization"] == "Bearer saved"
    assert "Authorization" not in seen[1][1]


@pytest.mark.parametrize(
    ("provider", "expected", "header"),
    [
        (
            "anthropic",
            ["anthropic/claude-haiku-5-5", "anthropic/claude-opus-5-5"],
            ("x-api-key", "k"),
        ),
        (
            "openai",
            ["openai/gpt-5", "openai/o4-mini"],
            ("Authorization", "Bearer k"),
        ),
        ("gemini", ["gemini/gemini-2.5-pro"], ("x-goog-api-key", "k")),
        (
            "openrouter",
            ["openrouter/meta/llama-4"],
            ("Authorization", "Bearer k"),
        ),
    ],
)
async def test_providers_list_their_chat_models(
    fake, provider, expected, header
):
    _, seen = fake

    found = await model_catalog.list_models(provider, api_key="k")

    assert names(found) == expected
    assert seen[0][1][header[0]] == header[1]


async def test_labels_come_from_the_provider(fake):
    found = await model_catalog.list_models("anthropic", api_key="k")

    assert [item.label for item in found] == [
        "claude-haiku-5-5",
        "Claude Opus 5.5",
    ]


async def test_ollama_lists_local_models(fake):
    base, _ = fake

    found = await model_catalog.list_models("ollama", base)

    assert names(found) == ["ollama_chat/hermes3:latest", "ollama_chat/qwen3"]


@pytest.mark.parametrize(
    ("provider", "url", "key", "message"),
    [
        ("anthropic", "", "", "請先填上金鑰"),
        (providers.ENDPOINT, "", "", "請先填上端點網址"),
        (providers.ENDPOINT, "/denied", "k", "金鑰不正確"),
        (providers.ENDPOINT, "/badkey", "k", "金鑰不正確.*invalid x-api-key"),
        (providers.ENDPOINT, "/forbidden", "k", "沒有權限.*Key not allowed"),
        (providers.ENDPOINT, "/litellm-down", "k", "HTTP 500.*upstream down"),
        (providers.ENDPOINT, "/broken", "k", "不是模型清單.*網頁"),
        (providers.ENDPOINT, "/missing/v1", "k", "不支援列出模型"),
        ("nope", "", "", "不認得"),
    ],
)
async def test_problems_are_explained(
    fake, monkeypatch, provider, url, key, message
):
    base, _ = fake
    monkeypatch.delenv("HARNESS_BASE_URL", raising=False)

    with pytest.raises(model_catalog.CatalogError, match=message):
        await model_catalog.list_models(
            provider, f"{base}{url}" if url else "", key
        )


async def test_unreachable_endpoints_are_explained():
    with pytest.raises(model_catalog.CatalogError, match="連不到"):
        await model_catalog.list_models(
            providers.ENDPOINT, "http://127.0.0.1:9", "k"
        )


async def test_responses_sent_in_pieces_are_read_in_full(fake):
    base, _ = fake

    found = await model_catalog.list_models(
        providers.ENDPOINT, f"{base}/chunked", "k"
    )

    assert names(found) == ["gpt-oss-120b", "qwen3-32b"]


async def test_anthropic_follows_pages(fake, monkeypatch):
    base, seen = fake
    monkeypatch.setitem(
        model_catalog._OFFICIAL, "anthropic", f"{base}/paged/v1/models"
    )

    found = await model_catalog.list_models("anthropic", api_key="k")

    assert names(found) == [
        "anthropic/claude-haiku-5-5",
        "anthropic/claude-opus-5-5",
    ]
    assert [path for path, _ in seen] == [
        "/paged/v1/models?limit=1000",
        "/paged/v1/models?limit=1000&after_id=claude-opus-5-5",
    ]
    assert seen[0][1]["anthropic-version"] == model_catalog.ANTHROPIC_VERSION
    assert "Authorization" not in seen[0][1]


@pytest.mark.parametrize("suffix", ["", "/v1", "/v1/"])
async def test_anthropic_as_an_endpoint_uses_its_own_api(
    fake, monkeypatch, suffix
):
    """端點填 https://api.anthropic.com 時，用 x-api-key 而不是 Bearer。"""
    base, seen = fake
    monkeypatch.setattr(model_catalog, "ANTHROPIC_HOST", "127.0.0.1")

    found = await model_catalog.list_models(
        providers.ENDPOINT, f"{base}/paged{suffix}", "k"
    )

    # 端點的名稱原樣使用，不加 anthropic/。
    assert names(found) == ["claude-haiku-5-5", "claude-opus-5-5"]
    assert [item.label for item in found] == [
        "Claude Haiku 5.5",
        "Claude Opus 5.5",
    ]
    assert seen[0][1]["x-api-key"] == "k"
    assert "Authorization" not in seen[0][1]


async def test_anthropic_endpoint_needs_a_key(fake, monkeypatch):
    base, _ = fake
    monkeypatch.setattr(model_catalog, "ANTHROPIC_HOST", "127.0.0.1")

    with pytest.raises(model_catalog.CatalogError, match="Anthropic 的金鑰"):
        await model_catalog.list_models(providers.ENDPOINT, f"{base}/v1", "")


class TestRetrievalModels:
    """知識庫設定用的 embedding 與 rerank 模型清單。"""

    @pytest.fixture(autouse=True)
    def no_connection(self, monkeypatch):
        monkeypatch.delenv("HARNESS_BASE_URL", raising=False)

    async def test_litellm_model_info_says_what_each_model_is(
        self, fake, monkeypatch
    ):
        base, seen = fake
        monkeypatch.setenv("HARNESS_BASE_URL", f"{base}/litellm/v1")
        monkeypatch.setenv("HARNESS_API_KEY", "sk-proxy")

        found = await model_catalog.list_retrieval_models()

        assert seen[0][0] == "/litellm/model/info"
        assert seen[0][1]["Authorization"] == "Bearer sk-proxy"
        assert found.source == "model_info"
        assert names(found.embedding) == ["bge-m3", "text-embedding-3-small"]
        assert names(found.rerank) == ["cohere-rerank"]

    async def test_other_endpoints_are_guessed_by_name(self, fake, monkeypatch):
        base, seen = fake
        monkeypatch.setenv("HARNESS_BASE_URL", f"{base}/vllm/v1")

        found = await model_catalog.list_retrieval_models()

        assert [path for path, _ in seen] == [
            "/vllm/model/info",
            "/vllm/v1/models",
        ]
        assert found.source == "names"
        assert names(found.embedding) == ["Qwen3-Embedding-8B"]
        assert names(found.rerank) == ["bge-reranker-v2-m3"]

    async def test_openai_lists_its_embedding_models(self, fake, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")

        found = await model_catalog.list_retrieval_models()

        assert names(found.embedding) == ["openai/text-embedding-3-small"]
        assert found.rerank == []

    async def test_without_a_connection_there_is_no_list(self, fake):
        found = await model_catalog.list_retrieval_models()

        assert found.to_json() == {
            "embedding": [],
            "rerank": [],
            "source": "none",
        }

    async def test_endpoint_problems_are_explained(self, fake, monkeypatch):
        base, _ = fake
        monkeypatch.setenv("HARNESS_BASE_URL", f"{base}/denied")

        with pytest.raises(model_catalog.CatalogError, match="金鑰"):
            await model_catalog.list_retrieval_models()


class TestContextWindows:
    """對話壓縮用的各模型上下文上限。"""

    @pytest.fixture(autouse=True)
    def no_connection(self, monkeypatch):
        monkeypatch.delenv("HARNESS_BASE_URL", raising=False)

    async def test_vllm_max_model_len_is_read(self, fake, monkeypatch):
        base, _ = fake
        monkeypatch.setenv("HARNESS_BASE_URL", f"{base}/vllm/v1")

        found = await model_catalog.context_windows()

        assert found == {"gemma-4-31b": 196608}

    async def test_litellm_model_info_is_read(self, fake, monkeypatch):
        base, _ = fake
        monkeypatch.setenv("HARNESS_BASE_URL", f"{base}/litellm/v1")

        found = await model_catalog.context_windows()

        assert found == {"gpt-5": 272000}

    async def test_problems_give_an_empty_result(self, fake, monkeypatch):
        base, _ = fake
        monkeypatch.setenv("HARNESS_BASE_URL", f"{base}/denied")

        assert await model_catalog.context_windows() == {}

    async def test_without_an_endpoint_nothing_is_asked(self, fake):
        _, seen = fake

        assert await model_catalog.context_windows() == {}
        assert seen == []
