# 內建工具

不用寫任何程式就能給 agent 的工具，設計參考 Claude Code 與 Codex。兩個版本的名稱、參數與輸出都相同。

內建工具**要在 agent 的 `tools` 明確列出**才會啟用；專案裡有同名的 toolset（例如 `tools/web.py` 或名為 `web` 的 MCP 伺服器）時以專案的為準。

| toolset | 工具 | 用途 | 需要同意 |
|---|---|---|---|
| `files` | `read_file` | 讀取文字檔；可用 `offset`、`limit` 只讀其中幾行。Python 版也直接讀 PDF、Word（.docx）、PowerPoint（.pptx）、Excel（.xlsx）的文字 | |
| | `list_dir` | 列出資料夾內容 | |
| | `find_files` | 用 glob 樣式找檔案，例如 `*.py`、`src/**/*.ts` | |
| | `search_files` | 用正規表示式搜尋檔案內容，回傳「路徑:行號: 內容」 | |
| | `write_file` | 寫入整個檔案 | ✓ |
| | `edit_file` | 把一段原文精準換成新文字，不必重寫整個檔案 | ✓ |
| `shell` | `run_command` | 在專案資料夾執行指令（測試、建置、git…），回傳結束代碼與輸出 | ✓ |
| `plan` | `update_plan` | 列出多步驟工作的計畫並更新每一步的狀態 | |
| `web` | `web_search` <span class="badge-py">Python 版</span> | 用關鍵字搜尋網路，回傳標題、網址與摘要；搜尋服務可以換，見[網頁搜尋](#網頁搜尋) | |
| | `web_fetch` | 讀取網址，HTML 轉成保留標題、清單與連結的純文字 | ✓ |
| `sandbox` <span class="badge-py">Python 版</span> | `run_python` | 在拋棄式 Docker 容器裡執行 agent 寫的 Python 程式，見[在沙盒裡執行程式](/advanced/sandbox) | |

```markdown
---
name: dev
description: 幫忙修改程式、跑測試
tools: [files, shell, plan]
---
修改前先讀檔；改完一定要跑測試確認。
```

## 設計重點

- **所有路徑都限制在專案資料夾裡**，`../` 或絕對路徑會被拒絕；搜尋會略過 `.git`、`node_modules`、`.harness`、`.venv` 等資料夾，也不跟著符號連結走。`.harness/secrets/`（網頁上設定的金鑰）一律不能存取。
- **`edit_file` 要求原文只出現一次**（或設定 `replace_all`），避免改錯地方；找不到或出現多次時，錯誤訊息會告訴模型怎麼修正。檔案原本的換行字元會保留。
- **`run_command` 沒有標準輸入、有逾時**（預設 120 秒，最多 600 秒），輸出過長時保留頭尾，逾時或使用者中斷時會連同子行程一起終止。指令在專案資料夾裡執行，但指令本身能做的事不受限制，所以預設需要同意；要隔離執行 agent 寫的程式，改用 [`sandbox`](/advanced/sandbox)。
- **`update_plan` 不存任何狀態**：每次傳入完整的步驟清單，最新一次呼叫就是目前的計畫，對話紀錄裡看得到、接續對話時也還在（同 Codex 的做法）。
- **`web_fetch` 會把網址送到外部**，所以預設需要同意。信任的話在 `harness.yaml` 加上 `permissions.allow: [web_fetch]`。它會使用 `HTTPS_PROXY` 等代理設定。
- **`read_file` 讀文件不需要沙盒** <span class="badge-py">Python 版</span>：PDF、.docx、.pptx、.xlsx 用和知識庫相同的解析器取出文字，PDF 依頁、PowerPoint 依投影片、Excel 依工作表分段，`offset`、`limit` 一樣可用。掃描的 PDF 沒有文字層，會提醒要先 OCR；舊格式的 .doc、.xls、.ppt 請先另存成新格式。單一文件最大 50 MB。要修改或產生 Office 檔與 PDF 時，改用[內建的 xlsx、docx、pptx、pdf skills](/advanced/skills#office-文件與-pdf-的-skills)（需要沙盒）。

## 網頁搜尋 <span class="badge-py">Python 版</span> {#網頁搜尋}

`web` 工具組有 `web_search` 與 `web_fetch`：先用 `web_search` 找到相關網頁，再用 `web_fetch` 讀需要的那幾頁。`web_search` 只送出搜尋字詞，所以不需要同意；`web_fetch` 一樣預設要同意。網頁版新建立的專案，主要的 agent 預設就有 `web` 工具組。

搜尋服務用環境變數設定，不需要寫程式：

| 環境變數 | 說明 |
|---|---|
| `HARNESS_WEB_SEARCH` | `duckduckgo`（預設，不需要金鑰）、`searxng`、`brave`、`tavily`，或 `off` 關閉 |
| `SEARXNG_URL` | 自架 [SearXNG](https://docs.searxng.org/) 的網址，例如 `http://searxng:8080`（要開啟 JSON 格式） |
| `BRAVE_API_KEY` | [Brave Search API](https://brave.com/search/api/) 的金鑰 |
| `TAVILY_API_KEY` | [Tavily](https://tavily.com/) 的金鑰 |
| `HARNESS_WEB_SEARCH_REGION` | DuckDuckGo 的地區，預設 `wt-wt`（不分地區），例如 `tw-tzh` |

沒有設定 `HARNESS_WEB_SEARCH` 時依序看有沒有 `TAVILY_API_KEY`、`BRAVE_API_KEY`、`SEARXNG_URL`，都沒有就用 DuckDuckGo。搜尋會使用 `HTTPS_PROXY` 等代理設定。

::: warning DuckDuckGo 只適合試用
DuckDuckGo 沒有正式的 API，常會擋下伺服器發出的搜尋（回應 202）。被擋時會先改用它的精簡版再試一次，還是不行就回報錯誤，agent 會改用 `web_fetch` 直接讀可能的網站。正式部署請設定 SearXNG、Brave 或 Tavily。
:::

**已經有搜尋 MCP 的話**（例如透過 [模型中台](/guide/web#模型中台) 的 webiq）：MCP 伺服器提供同名的 `web_search` 時，內建的會讓位給 MCP 的；不想要內建搜尋就設定 `HARNESS_WEB_SEARCH=off`，或不給 agent `web` 工具組。不能直接連外的環境（例如公司網路會攔截 SSL）請用 MCP 搜尋，並關掉內建的。

## 在程式裡使用 <span class="badge-py">Python 版</span> {#在程式裡使用}

```python
from harness import builtin

agent = harness.Agent(
    name="dev",
    instructions="...",
    tools=[*builtin.TOOLSETS["files"], *builtin.TOOLSETS["shell"]],
)
```

Python 版另外附帶幾個內建 skills（`code-review`、`debugging` 等，處理 Office 檔與 PDF 的 `xlsx`、`docx`、`pptx`、`pdf`，以及改寫自 Anthropic 官方的 `web-artifacts-builder`、`webapp-testing`、`mcp-builder`、`canvas-design` 等），見[內建 skills](/advanced/skills#內建-skills)。
