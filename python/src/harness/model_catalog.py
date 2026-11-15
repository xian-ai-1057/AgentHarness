"""向模型供應商或 OpenAI 相容端點查詢有哪些模型可以用。

網頁版的連線設定用它：填好端點網址或金鑰後，自動列出可以選的模型，
不必自己記模型名稱。

各家查詢的方式：

    endpoint    OpenAI 相容端點（LiteLLM Proxy、vLLM…）的 GET /models；
                網址沒有 /v1 而 /models 不存在時，再試 /v1/models。
                名稱原樣使用（見 llm._endpoint_model）。端點是
                api.anthropic.com 時改用 Anthropic 的查法（見下一行）。
    anthropic   GET https://api.anthropic.com/v1/models，金鑰放在 x-api-key、
                加上 anthropic-version 標頭，依 has_more / last_id 翻頁
    openai      GET https://api.openai.com/v1/models（只留對話用的模型）
    gemini      GET https://generativelanguage.googleapis.com/v1beta/models
                （只留支援 generateContent 的模型）
    openrouter  GET https://openrouter.ai/api/v1/models
    ollama      GET <位址>/api/tags

回傳的名稱是 litellm 的模型名稱（anthropic/claude-…），可以直接寫進
harness.yaml。會經過 HTTPS_PROXY 等環境變數設定的代理伺服器。
"""

import dataclasses
import json
import os
import re
import urllib.parse
from typing import Any

import aiohttp

from harness import providers

TIMEOUT_SECONDS = 15
# 回應最多讀這麼多（OpenRouter 的清單大約 1 MB）。
MAX_BYTES = 8 * 1024 * 1024
ANTHROPIC_VERSION = "2023-06-01"
ANTHROPIC_HOST = "api.anthropic.com"
# Anthropic 一頁最多 1000 個；翻頁最多這麼多次，避免伺服器一直說還有。
MAX_PAGES = 20

_OFFICIAL = {
    "anthropic": "https://api.anthropic.com/v1/models",
    "openai": "https://api.openai.com/v1/models",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/models?pageSize=1000",
    "openrouter": "https://openrouter.ai/api/v1/models",
}
# OpenAI 的清單裡有語音、圖片、向量等模型，對話用不到。
_OPENAI_CHAT = re.compile(r"^(gpt-|o\d|chatgpt-)")
_OPENAI_SKIP = re.compile(
    r"(audio|realtime|transcribe|tts|search|image|embedding|moderation|"
    r"instruct|davinci|babbage|whisper|dall-e)"
)


class CatalogError(Exception):
    """查不到模型清單，訊息是給使用者看的說明。"""


@dataclasses.dataclass(frozen=True)
class ModelChoice:
    """一個可以選的模型。

    Attributes:
        name: litellm 的模型名稱（端點則是端點上的名稱）。
        label: 顯示名稱；供應商沒有提供時和 name 相同。
    """

    name: str
    label: str

    def to_json(self) -> dict[str, str]:
        return {"name": self.name, "label": self.label}


async def list_models(
    provider_id: str,
    base_url: str = "",
    api_key: str = "",
    saved_key: bool = True,
    extra_headers: dict[str, str] | None = None,
) -> list[ModelChoice]:
    """查詢一家供應商（或端點）提供的模型。

    Args:
        provider_id: providers 的代號，或 providers.ENDPOINT。
        base_url: 端點或 Ollama 的網址；空的時用環境變數或預設值。
        api_key: 金鑰；空的時用已經設定的環境變數。
        saved_key: 端點可不可以用已經存好的 HARNESS_API_KEY。網址換成別的
            端點時要傳 False，存好的金鑰不能送到新的網址。
        extra_headers: 端點另外附帶的標頭，例如 LiteLLM 的
            x-litellm-end-user-id：中台支援時只列出這位使用者能用的模型。

    Returns:
        依名稱排序的模型。

    Raises:
        CatalogError: 設定不完整、連不上、金鑰不對，或回應看不懂。
    """
    if provider_id == providers.ENDPOINT:
        if not api_key and saved_key:
            api_key = _env(providers.API_KEY_VAR)
        return await _endpoint(base_url, api_key, extra_headers or {})
    provider = providers.find(provider_id)
    if provider is None:
        raise CatalogError(f"不認得這個供應商：{provider_id}")
    key = api_key or _env(provider.key_var)
    if provider.key_var and not key and provider.id != "openrouter":
        raise CatalogError("請先填上金鑰，才能列出可以用的模型")
    if provider.id == "ollama":
        url = base_url or _env(provider.base_url_var)
        url = url or provider.default_base_url or ""
        data = await _get_json(f"{url.rstrip('/')}/api/tags", {})
        names = [item.get("name") for item in _items(data, "models")]
        return _sorted(
            ModelChoice(f"ollama_chat/{n}", n) for n in _strings(names)
        )
    if provider.id == "anthropic":
        return _sorted(
            ModelChoice(f"anthropic/{item['id']}", _label(item, "display_name"))
            for item in await _anthropic_models(_OFFICIAL["anthropic"], key)
        )
    if provider.id == "openai":
        data = await _get_json(_OFFICIAL["openai"], _bearer(key))
        return _sorted(
            ModelChoice(f"openai/{item['id']}", item["id"])
            for item in _items(data, "data")
            if isinstance(item.get("id"), str)
            and _OPENAI_CHAT.match(item["id"])
            and not _OPENAI_SKIP.search(item["id"])
        )
    if provider.id == "gemini":
        data = await _get_json(_OFFICIAL["gemini"], {"x-goog-api-key": key})
        choices = []
        for item in _items(data, "models"):
            name = item.get("name")
            methods = item.get("supportedGenerationMethods") or []
            if isinstance(name, str) and "generateContent" in methods:
                short = name.removeprefix("models/")
                choices.append(
                    ModelChoice(f"gemini/{short}", _label(item, "displayName"))
                )
        return _sorted(choices)
    if provider.id == "openrouter":
        data = await _get_json(_OFFICIAL["openrouter"], _bearer(key))
        return _sorted(
            ModelChoice(f"openrouter/{item['id']}", _label(item, "name"))
            for item in _items(data, "data")
            if isinstance(item.get("id"), str)
        )
    raise CatalogError(f"{provider.label} 不支援列出模型，請直接填模型名稱")


async def _endpoint(
    base_url: str, api_key: str, extra_headers: dict[str, str]
) -> list[ModelChoice]:
    url = (base_url or _env(providers.BASE_URL_VAR)).rstrip("/")
    if not url:
        raise CatalogError("請先填上端點網址")
    if _is_anthropic(url):
        # Anthropic 的 OpenAI 相容端點可以對話，但模型清單要用它自己的查法。
        if not api_key:
            raise CatalogError(
                "請先填上 Anthropic 的金鑰，才能列出可以用的模型"
            )
        root = url.removesuffix("/v1")
        return _sorted(
            ModelChoice(item["id"], _label(item, "display_name"))
            for item in await _anthropic_models(f"{root}/v1/models", api_key)
        )
    headers = {**extra_headers, **_bearer(api_key)}
    try:
        data = await _get_json(f"{url}/models", headers)
    except _NotFound:
        if url.endswith("/v1"):
            raise CatalogError(
                f"{url}/models 不存在，這個端點可能不支援列出模型，"
                "請直接填模型名稱"
            ) from None
        try:
            data = await _get_json(f"{url}/v1/models", headers)
        except _NotFound:
            raise CatalogError(
                "這個端點沒有 /models 或 /v1/models，可能不支援列出模型，"
                "請直接填模型名稱"
            ) from None
    return _sorted(
        ModelChoice(item["id"], item["id"])
        for item in _items(data, "data")
        if isinstance(item.get("id"), str)
    )


def _is_anthropic(url: str) -> bool:
    try:
        host = urllib.parse.urlsplit(url).hostname
    except ValueError:
        return False
    return host == ANTHROPIC_HOST


async def _anthropic_models(url: str, key: str) -> list[dict[str, Any]]:
    """Anthropic 的 GET /v1/models，翻完所有頁。

    Returns:
        有字串 id 的模型（含 display_name）。
    """
    headers = {"x-api-key": key, "anthropic-version": ANTHROPIC_VERSION}
    params = {"limit": "1000"}
    models: list[dict[str, Any]] = []
    for _ in range(MAX_PAGES):
        data = await _get_json(url, headers, params)
        items = _items(data, "data")
        models.extend(item for item in items if isinstance(item.get("id"), str))
        last_id = data.get("last_id")
        if (
            not data.get("has_more")
            or not isinstance(last_id, str)
            or not items
        ):
            break
        params = {"limit": "1000", "after_id": last_id}
    return models


class _NotFound(CatalogError):
    """網址不存在（404）。"""


async def _get_json(
    url: str, headers: dict[str, str], params: dict[str, str] | None = None
) -> Any:
    timeout = aiohttp.ClientTimeout(total=TIMEOUT_SECONDS)
    try:
        async with (
            aiohttp.ClientSession(timeout=timeout, trust_env=True) as session,
            session.get(url, headers=headers, params=params) as response,
        ):
            body = await _read_body(response)
            if response.status >= 400:
                raise _http_error(url, response.status, body)
            try:
                return _json(body)
            except ValueError as error:
                raise CatalogError(
                    f"{url} 的回應不是模型清單"
                    f"（{_describe(response.content_type, body)}），"
                    "請確認網址是否正確"
                ) from error
    except TimeoutError as error:
        raise CatalogError(
            f"連到 {url} 超過 {TIMEOUT_SECONDS} 秒沒有回應"
        ) from error
    except aiohttp.ClientConnectorError as error:
        raise CatalogError(f"連不到 {url}，請確認網址與網路") from error
    except aiohttp.ClientError as error:
        raise CatalogError(f"連不到 {url}：{error}") from error


async def _read_body(response: aiohttp.ClientResponse) -> bytes:
    """讀完整個回應。

    content.read(n) 只回傳目前收到的部分；分好幾段送來的回應
    （例如 Anthropic 的清單）只讀一次會拿到半個 JSON。
    """
    chunks = []
    size = 0
    while chunk := await response.content.read(64 * 1024):
        size += len(chunk)
        if size > MAX_BYTES:
            raise CatalogError("模型清單太大，請直接填模型名稱")
        chunks.append(chunk)
    return b"".join(chunks)


def _http_error(url: str, status: int, body: bytes) -> CatalogError:
    detail = _error_detail(body)
    said = f"（對方的說明：{detail}）" if detail else ""
    if status == 404:
        return _NotFound(f"{url} 不存在{said}")
    if status == 401:
        return CatalogError(
            f"金鑰不正確或已經失效{said}，請確認貼上的是這家供應商"
            "（或這個端點）的金鑰"
        )
    if status == 403:
        return CatalogError(f"這把金鑰沒有權限列出模型{said}")
    if status == 429:
        return CatalogError(f"查詢太頻繁或額度用完了{said}，請稍後再試")
    return CatalogError(f"列出模型失敗：{url} 回應 HTTP {status}{said}")


def _error_detail(body: bytes) -> str:
    """從錯誤回應裡找出對方的說明（Anthropic、OpenAI、LiteLLM 的格式）。"""
    try:
        data = _json(body)
    except ValueError:
        return ""
    if not isinstance(data, dict):
        return ""
    error = data.get("error")
    candidates = [
        error.get("message") if isinstance(error, dict) else error,
        data.get("detail"),
        data.get("message"),
    ]
    for value in candidates:
        if isinstance(value, dict):
            value = value.get("error") or value.get("message")
        if isinstance(value, str) and value.strip():
            return value.strip()[:200]
    return ""


def _describe(content_type: str, body: bytes) -> str:
    if not body.strip():
        return "收到空白的回應"
    if "html" in content_type or body.lstrip()[:1] == b"<":
        return "收到的是網頁，不是 JSON"
    return f"收到的是 {content_type or '看不懂的內容'}，不是 JSON"


def _json(body: bytes) -> Any:
    return json.loads(body.decode("utf-8"))


def _items(data: Any, key: str) -> list[dict[str, Any]]:
    items = data.get(key) if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise CatalogError("回應不是模型清單，請確認網址是否正確")
    return [item for item in items if isinstance(item, dict)]


def _strings(values: list[Any]) -> list[str]:
    return [value for value in values if isinstance(value, str) and value]


def _label(item: dict[str, Any], key: str) -> str:
    """供應商提供的顯示名稱；沒有時用 id（Gemini 是 name）。"""
    label = item.get(key)
    if isinstance(label, str) and label.strip():
        return label.strip()
    fallback = item.get("id") or item.get("name") or ""
    return str(fallback).removeprefix("models/")


def _sorted(choices) -> list[ModelChoice]:
    unique = {choice.name: choice for choice in choices}
    return sorted(unique.values(), key=lambda choice: choice.name.lower())


def _bearer(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"} if key else {}


def _env(name: str | None) -> str:
    return os.environ.get(name, "") if name else ""
