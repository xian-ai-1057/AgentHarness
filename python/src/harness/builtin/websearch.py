"""內建的網頁搜尋工具 web_search（屬於 web 工具組）。

web_fetch 要先知道網址；web_search 用關鍵字找到網址、標題與摘要，再交給
web_fetch 讀全文。和 Claude、ChatGPT 一樣，搜尋不必每次都問使用者；要
先問的話，在 harness.yaml 的 permissions.ask 加上 web_search。

搜尋服務用環境變數設定（部署時寫在 .env，金鑰不進 harness.yaml）：

    HARNESS_WEB_SEARCH   duckduckgo、searxng、brave、tavily 或 off。
                         沒有設定時：有 TAVILY_API_KEY 用 Tavily，有
                         BRAVE_API_KEY 用 Brave，有 SEARXNG_URL 用 SearXNG，
                         都沒有時用 DuckDuckGo（不需要金鑰）。
    SEARXNG_URL          自架的 SearXNG，例如 http://searxng:8080（要在
                         SearXNG 的 settings.yml 開啟 json 格式）。
    BRAVE_API_KEY        Brave Search API 的金鑰。
    TAVILY_API_KEY       Tavily 的金鑰。
    HARNESS_WEB_SEARCH_REGION
                         DuckDuckGo 的地區，例如 tw-tzh（台灣繁中）；
                         預設 wt-wt（不分地區）。

不能連外網的環境（例如銀行內部）設 HARNESS_WEB_SEARCH=off，改用管理者
掛載的搜尋 MCP（例如模型中台上的 webiq）。
"""

import html
import json
import os
import re
import urllib.parse

import aiohttp

from harness import tools

PROVIDERS = ("duckduckgo", "searxng", "brave", "tavily")
OFF = "off"
DEFAULT_RESULTS = 8
MAX_RESULTS = 20
MAX_QUERY_CHARS = 400
_TIMEOUT_SECONDS = 20
_SNIPPET_CHARS = 300
# DuckDuckGo 的 HTML 版會擋看起來像機器人的 User-Agent。
_BROWSER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
DUCKDUCKGO_URL = "https://html.duckduckgo.com/html/"
BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"
TAVILY_URL = "https://api.tavily.com/search"

_DDG_RESULT = re.compile(
    r'<a[^>]*class="[^"]*\bresult__a\b[^"]*"[^>]*href="([^"]*)"[^>]*>'
    r"([\s\S]*?)</a>"
    r"([\s\S]*?)(?=<a[^>]*class=\"[^\"]*\bresult__a\b|$)",
)
_DDG_SNIPPET = re.compile(
    r'class="[^"]*\bresult__snippet\b[^"]*"[^>]*>([\s\S]*?)</(?:a|div|td)>'
)
_TAG = re.compile(r"<[^>]*>")


class SearchError(Exception):
    """搜尋服務沒有設定好，或回應不正常。"""


def provider() -> str:
    """目前使用的搜尋服務名稱（PROVIDERS 之一或 off）。

    Raises:
        SearchError: HARNESS_WEB_SEARCH 寫了不認得的名稱。
    """
    chosen = os.environ.get("HARNESS_WEB_SEARCH", "").strip().lower()
    if chosen:
        if chosen in ("none", "false", "0", "disabled"):
            return OFF
        if chosen not in (*PROVIDERS, OFF):
            raise SearchError(
                f"HARNESS_WEB_SEARCH 不認得 {chosen}，可以寫："
                f"{'、'.join((*PROVIDERS, OFF))}"
            )
        return chosen
    if os.environ.get("TAVILY_API_KEY"):
        return "tavily"
    if os.environ.get("BRAVE_API_KEY"):
        return "brave"
    if os.environ.get("SEARXNG_URL"):
        return "searxng"
    return "duckduckgo"


def _clean(fragment: str) -> str:
    """HTML 片段轉成一行純文字。"""
    text = html.unescape(_TAG.sub("", fragment))
    return re.sub(r"\s+", " ", text).strip()


def _short(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= _SNIPPET_CHARS:
        return text
    return text[: _SNIPPET_CHARS - 1] + "…"


def _ddg_target(href: str) -> str | None:
    """DuckDuckGo 的結果連結會包一層轉址（/l/?uddg=真正的網址）。"""
    href = html.unescape(href)
    if href.startswith("//"):
        href = "https:" + href
    parts = urllib.parse.urlsplit(href)
    if parts.path.startswith("/l/"):
        target = urllib.parse.parse_qs(parts.query).get("uddg")
        href = target[0] if target else ""
    if urllib.parse.urlsplit(href).scheme not in ("http", "https"):
        return None
    return href


def parse_duckduckgo(source: str) -> list[dict[str, str]]:
    """從 DuckDuckGo HTML 版的頁面取出搜尋結果（略過廣告）。

    Args:
        source: html.duckduckgo.com 回傳的 HTML。

    Returns:
        每筆有 title、url、snippet 的結果。
    """
    results = []
    seen = set()
    for match in _DDG_RESULT.finditer(source):
        url = _ddg_target(match.group(1))
        if url is None or url in seen:
            continue
        # 廣告的連結指向 duckduckgo.com/y.js。
        if urllib.parse.urlsplit(url).hostname in ("duckduckgo.com",):
            continue
        seen.add(url)
        snippet = _DDG_SNIPPET.search(match.group(3))
        results.append(
            {
                "title": _clean(match.group(2)) or url,
                "url": url,
                "snippet": _clean(snippet.group(1)) if snippet else "",
            }
        )
    return results


async def _duckduckgo(
    session: aiohttp.ClientSession, query: str, count: int
) -> list[dict[str, str]]:
    region = os.environ.get("HARNESS_WEB_SEARCH_REGION", "").strip() or "wt-wt"
    async with session.post(
        DUCKDUCKGO_URL,
        data={"q": query, "kl": region},
        headers={"User-Agent": _BROWSER_AGENT},
    ) as response:
        if response.status >= 400 or response.status == 202:
            raise SearchError(
                f"DuckDuckGo 回應 {response.status}（可能暫時限制了搜尋次數），"
                "請稍後再試，或請管理者改用其他搜尋服務"
            )
        source = await response.text(errors="replace")
    return parse_duckduckgo(source)[:count]


async def _searxng(
    session: aiohttp.ClientSession, query: str, count: int
) -> list[dict[str, str]]:
    base = os.environ.get("SEARXNG_URL", "").strip().rstrip("/")
    if not base:
        raise SearchError("使用 SearXNG 要設定 SEARXNG_URL")
    async with session.get(
        f"{base}/search", params={"q": query, "format": "json"}
    ) as response:
        if response.status == 403:
            raise SearchError(
                "SearXNG 拒絕 json 格式，請在它的 settings.yml 的 "
                "search.formats 加上 json"
            )
        if response.status >= 400:
            raise SearchError(f"SearXNG 回應 {response.status}")
        data = await response.json(content_type=None)
    return [
        {
            "title": str(item.get("title") or item.get("url") or ""),
            "url": str(item.get("url") or ""),
            "snippet": str(item.get("content") or ""),
        }
        for item in (data.get("results") or [])[:count]
        if item.get("url")
    ]


async def _brave(
    session: aiohttp.ClientSession, query: str, count: int
) -> list[dict[str, str]]:
    key = os.environ.get("BRAVE_API_KEY", "").strip()
    if not key:
        raise SearchError("使用 Brave 要設定 BRAVE_API_KEY")
    async with session.get(
        BRAVE_URL,
        params={"q": query, "count": str(count)},
        headers={"X-Subscription-Token": key, "Accept": "application/json"},
    ) as response:
        if response.status >= 400:
            raise SearchError(f"Brave Search 回應 {response.status}")
        data = await response.json(content_type=None)
    items = ((data.get("web") or {}).get("results")) or []
    return [
        {
            "title": _clean(str(item.get("title") or "")),
            "url": str(item.get("url") or ""),
            "snippet": _clean(str(item.get("description") or "")),
        }
        for item in items[:count]
        if item.get("url")
    ]


async def _tavily(
    session: aiohttp.ClientSession, query: str, count: int
) -> list[dict[str, str]]:
    key = os.environ.get("TAVILY_API_KEY", "").strip()
    if not key:
        raise SearchError("使用 Tavily 要設定 TAVILY_API_KEY")
    async with session.post(
        TAVILY_URL,
        json={"query": query, "max_results": count},
        headers={"Authorization": f"Bearer {key}"},
    ) as response:
        if response.status >= 400:
            raise SearchError(f"Tavily 回應 {response.status}")
        data = await response.json(content_type=None)
    return [
        {
            "title": str(item.get("title") or item.get("url") or ""),
            "url": str(item.get("url") or ""),
            "snippet": str(item.get("content") or ""),
        }
        for item in (data.get("results") or [])[:count]
        if item.get("url")
    ]


_SEARCHERS = {
    "duckduckgo": _duckduckgo,
    "searxng": _searxng,
    "brave": _brave,
    "tavily": _tavily,
}


def format_results(query: str, results: list[dict[str, str]]) -> str:
    """把搜尋結果排成給模型看的文字。"""
    if not results:
        return f"搜尋「{query}」沒有找到結果，換個關鍵字再試。"
    lines = [f"搜尋「{query}」的結果（要看全文用 web_fetch 讀取網址）：", ""]
    for number, item in enumerate(results, 1):
        lines.append(f"{number}. {item['title']}")
        lines.append(f"   {item['url']}")
        snippet = _short(item.get("snippet", ""))
        if snippet:
            lines.append(f"   {snippet}")
    return "\n".join(lines)


@tools.tool
async def web_search(query: str, max_results: int = DEFAULT_RESULTS) -> str:
    """用關鍵字搜尋網路，回傳相關網頁的標題、網址與摘要。

    需要最新資訊、查不到網址或要比對多個來源時使用；要看某一頁的全文，
    再用 web_fetch 讀取它的網址。回答時附上來源網址。

    Args:
        query: 搜尋關鍵字，和在搜尋引擎輸入的一樣。
        max_results: 最多回傳幾筆（1 到 20）。
    """
    query = (query or "").strip()
    if not query:
        raise tools.ToolError("query 不能是空的")
    if len(query) > MAX_QUERY_CHARS:
        raise tools.ToolError(f"query 最多 {MAX_QUERY_CHARS} 個字元")
    if not 1 <= max_results <= MAX_RESULTS:
        raise tools.ToolError(f"max_results 必須介於 1 到 {MAX_RESULTS}")
    try:
        name = provider()
    except SearchError as error:
        raise tools.ToolError(str(error)) from error
    if name == OFF:
        raise tools.ToolError(
            "管理者關閉了內建的網頁搜尋（HARNESS_WEB_SEARCH=off），"
            "請改用其他搜尋工具，或請使用者提供網址"
        )
    timeout = aiohttp.ClientTimeout(total=_TIMEOUT_SECONDS)
    try:
        # trust_env 讓請求走 HTTPS_PROXY 等環境變數設定的代理伺服器。
        async with aiohttp.ClientSession(
            timeout=timeout, trust_env=True
        ) as session:
            results = await _SEARCHERS[name](session, query, max_results)
    except SearchError as error:
        raise tools.ToolError(f"網頁搜尋失敗：{error}") from error
    except TimeoutError as error:
        raise tools.ToolError(
            f"網頁搜尋失敗：{_TIMEOUT_SECONDS} 秒內沒有回應"
        ) from error
    except (aiohttp.ClientError, json.JSONDecodeError, ValueError) as error:
        raise tools.ToolError(f"網頁搜尋失敗：{error}") from error
    return format_results(query, results)
