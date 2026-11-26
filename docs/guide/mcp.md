# 連接 MCP 伺服器

除了自己寫的工具，agent 也可以使用現成的 [MCP](https://modelcontextprotocol.io/) 伺服器提供的工具，例如其他語言寫的服務、第三方提供的工具伺服器。兩個版本的設定方式相同。

Python 版需要先安裝 MCP 套件：`pip install "mcp>=2"`。

## 設定

```yaml
# harness.yaml
mcpServers:
  github:                   # 伺服器名稱，也是這組工具的 toolset 名稱
    command: npx            # 本機程式，透過 stdio 溝通
    args: ["-y", "@modelcontextprotocol/server-github"]
    env: {LOG_LEVEL: info}  # 選用，加在目前的環境變數之上（金鑰除外，見下方）
    timeoutSeconds: 120     # 選用，單次工具呼叫最多等幾秒，預設 300
  search:
    url: https://example.com/mcp           # 遠端伺服器（Streamable HTTP）
    headers:                               # 選用，附帶的 HTTP 標頭
      Authorization: Bearer ${SEARCH_API_KEY}
```

`args`、`env`、`url`、`headers` 裡可以寫 `${環境變數名稱}`，載入時換成環境變數的值，**金鑰就不必寫進 `harness.yaml`**。

本機程式（`command`）拿到的環境變數會**拿掉名稱像金鑰的變數**（含 `KEY`、`SECRET`、`TOKEN`、`PASSWORD` 等字）與網頁上填的金鑰，避免每個 MCP 伺服器都拿到模型供應商的金鑰。伺服器需要哪把金鑰，就在 `env` 明確寫出來，例如 `env: {GITHUB_TOKEN: "${GITHUB_TOKEN}"}`。`${NAME:-預設值}` 在環境變數沒有設定時使用預設值；沒有設定也沒有預設值時，載入會失敗並指出缺少哪個環境變數。

從 Claude Code、Cursor 等工具複製過來的設定可以直接用，裡面的 `type`（`stdio`、`http`）會被接受；舊的 `sse` 傳輸不支援，請改用伺服器的 Streamable HTTP 端點（通常是 `/mcp`）。

agent 用伺服器名稱引用整組工具，也可以只列出其中幾個工具的名稱：

```markdown
---
name: main
tools: [report, github]
---
```

## 透過 LiteLLM Proxy 使用（例：網頁搜尋 webiq） {#litellm-proxy}

[LiteLLM Proxy](https://docs.litellm.ai/docs/mcp) 可以集中管理 MCP 伺服器，用 LiteLLM 的金鑰控管誰能用哪些工具。在 OpenAI Responses API 裡的寫法是這樣：

```json
"tools": [{
  "type": "mcp",
  "server_label": "litellm",
  "server_url": "litellm_proxy/mcp/webiq",
  "require_approval": "never",
  "headers": {"x-litellm-api-key": "Bearer APIKEY"}
}]
```

其中 `litellm_proxy` 是「Proxy 自己」的簡寫，只在呼叫 Proxy 的模型 API 時有效。harness 是自己連 MCP 伺服器，所以要寫出 Proxy 的完整網址。換成 harness 的設定：

```yaml
# harness.yaml
mcpServers:
  webiq:                    # toolset 名稱，agent 的 tools 寫 webiq
    url: ${LITELLM_PROXY_URL}/webiq/mcp
    headers:
      x-litellm-api-key: Bearer ${LITELLM_API_KEY}
```

```bash
# .env（或啟動前的環境變數）
LITELLM_PROXY_URL=https://litellm.example.com   # Proxy 的網址，不含 /v1
LITELLM_API_KEY=sk-...
```

再把 `webiq` 加進 agent 的 `tools`：

```markdown
---
name: main
tools: [files, plan, web, webiq]
---
```

- 網址是 Proxy 替每個 MCP 伺服器開的端點 `/<伺服器名稱>/mcp`。Proxy 版本較舊、這個網址連不上時，改用 `${LITELLM_PROXY_URL}/mcp`，並在 `headers` 加上 `x-mcp-servers: webiq` 指定伺服器。
- 金鑰前面要有 `Bearer `，少了會得到 401。
- `require_approval: never` 不用另外設定：MCP 工具除非伺服器標記為破壞性操作，預設都直接執行。想每次都先問，用 `permissions.ask` 加上工具名稱。
- **使用者身分**（Python 版）：網頁版要登入時，工具呼叫會附上使用者的 `x-litellm-end-user-id` 與 `x-litellm-trace-id` 標頭，LiteLLM 才能依使用者記錄與管控 MCP 的使用（見[網頁版 → 模型中台](/guide/web#模型中台)）。伺服器網址和 `HARNESS_BASE_URL` 是同一台（scheme、主機、port 都相同）時自動開啟；不同台時預設不送，要送就在伺服器設定加上 `forwardUser: true`，同一台但不想送就寫 `forwardUser: false`。本機程式（`command`）的伺服器不適用。
- **連不上 Proxy 時整個專案會載入失敗**（網頁版無法啟動），錯誤訊息會寫出網址。啟動後在網頁版「設定 → 工具」看得到 webiq 的工具，就表示連上了。Python 版的網頁也可以改由管理者[在管理平台掛載](#管理平台掛載)，連不上時不會擋住網站。

### 用 Docker 部署時 {#litellm-docker}

[快速部署](/guide/deploy)的專案在 `harness-data` volume 裡，在 repo 根目錄這樣加上：

```bash
# 1. 在 .env 加上 LITELLM_PROXY_URL 與 LITELLM_API_KEY（見 .env.example）

# 2. 把設定加到 harness.yaml 的最後面（檔案裡原本沒有 mcpServers 時）
docker compose exec -T -u harness harness sh -c 'cat >> /assistant/harness.yaml' <<'YAML'

mcpServers:
  webiq:
    url: ${LITELLM_PROXY_URL}/webiq/mcp
    headers:
      x-litellm-api-key: Bearer ${LITELLM_API_KEY}
YAML

# 3. 讓助手可以使用：在 agents/main.md 的「- web」下面加一行「- webiq」
docker compose exec -u harness harness sed -i 's/^  - web$/&\n  - webiq/' /assistant/agents/main.md

# 4. 重新建立容器，讓 .env 的新設定生效
docker compose up -d --force-recreate harness
```

內網的 Proxy 記得放進 `.env` 的 `NO_PROXY`。這個版本之後自動建立的助手，`harness.yaml` 與 `agents/main.md` 裡已經有註解掉的 webiq 設定，也可以改成取消註解。

## 在管理平台掛載 <span class="badge-py">Python 版</span> {#管理平台掛載}

不想改 `harness.yaml`、重新啟動的話，管理者可以直接在網頁的「管理平台 → MCP 工具」（`/admin/mcp`）掛載**遠端**的 MCP 伺服器：

1. 按「掛載 MCP 伺服器」，填名稱（也是工具組名稱，英文字母開頭）、網址（Streamable HTTP，例如 `http://litellm:4000/webiq/mcp`）與認證用的標頭。
2. 按「測試連線」確認連得上、看有哪些工具，再按「掛載」。
3. 工具會加到所有專案 agent（也可以選「指定」只加到某幾個），成為一個工具組；到「管理平台 → [群組](/guide/web#存取群組)」勾選這個工具組，成員才看得到。「所有人」群組的工具組是「全部」時，所有成員馬上都能用。

**LiteLLM 的 webiq 有範本**：還沒有 webiq 時，頁面上會出現「網頁搜尋 webiq（LiteLLM）」，按「套用範本」會填好網址 `<模型中台>/webiq/mcp`（模型中台取自 `HARNESS_BASE_URL`，去掉 `/v1`）與標頭 `x-litellm-api-key`，只要在 `Bearer ` 後面貼上 LiteLLM 的金鑰。連不上時試試 `<模型中台>/mcp/webiq`，或 `<模型中台>/mcp` 加上標頭 `x-mcp-servers: webiq`（依 LiteLLM 版本而定）。

- **只有管理者能掛載**，一般成員看不到這一頁，直接呼叫 API（`/api/admin/mcp`）也會被拒絕。
- **只接受遠端伺服器**：在伺服器上啟動程式（`command`）等於讓網頁上的操作在伺服器執行任意指令，這類伺服器只能由部署的人寫在 `harness.yaml`。
- **金鑰不會再顯示**：標頭的值存在 `.harness/secrets/mcp-headers.json`（只有服務的帳號能讀，內建的檔案工具也讀不到），網頁與 API 只回傳標頭名稱；修改時值留空表示沿用原本的金鑰。稽核紀錄只記標頭名稱。
- **標頭可以引用的環境變數有限制**：`MCP_` 開頭的環境變數（部署的人特地留給 MCP 用）可以送到任何伺服器；模型中台的金鑰 `LITELLM_API_KEY`、`HARNESS_API_KEY` 只能送到模型中台（網址和 `HARNESS_BASE_URL` 或 `LITELLM_PROXY_URL` 同一台），例如 `Bearer ${LITELLM_API_KEY}`；其他環境變數（模型供應商的金鑰、密碼）一律不能引用，網址裡也不能寫。這樣管理平台的管理者就算不是主機的維運者，也拿不到容器裡的其他金鑰。
- **不能連到雲端 metadata 這類保留位址**（`169.254.0.0/16` 等），轉址過去也會被擋。內部網路與本機不擋，因為模型中台通常就在內網；連線失敗的原因會完整顯示給管理者，方便排除問題。
- **連不上不影響網站**：和 `harness.yaml` 不同，網頁上掛載的伺服器在背景連線，連不上時只有這一台顯示「連線失敗」與原因，修好後按「重新連線」。網站重新啟動時會自動重新連線。
- 停用的伺服器不連線，工具也不會出現；「拿掉」會關閉連線並刪除存起來的金鑰。群組裡勾選的名稱會留著，用同樣的名稱重新掛載就恢復。
- 名稱不能和現有的工具組（內建的 `files`、`web` 等、`tools/` 底下的檔案、`harness.yaml` 的 `mcpServers`）重複；工具名稱和其他工具重複時無法掛載，頁面會說明是哪一個。
- 網頁上掛載的伺服器只在網頁版使用，命令列（`pyharness chat`）不會載入。`harness.yaml` 裡的伺服器也會列在頁面下方，只能看、不能改。
- 使用者身分標頭（`x-litellm-end-user-id`）和 `harness.yaml` 的規則相同：網址和 `HARNESS_BASE_URL` 是同一台時自動附上。

## 運作方式

- **載入專案時就會啟動並連上所有伺服器**，連線在整個專案使用期間共用。伺服器無法啟動時，錯誤訊息會附上它輸出到 stderr 的最後一段。
- 伺服器平常的 log 不會印到聊天畫面，設定環境變數 `HARNESS_DEBUG=1` 才會顯示。
- **本機伺服器在專案根目錄執行**，並繼承目前所有的環境變數，所以金鑰這類設定用環境變數提供即可，不必寫進 `harness.yaml`；遠端伺服器的金鑰用 `${NAME}` 從環境變數帶入。專案使用虛擬環境時，先啟用虛擬環境，或把 `command` 改成虛擬環境裡的 Python（例如 `.venv/bin/python`）。
- 伺服器標記為破壞性操作（`destructiveHint`）的工具，執行前會先問使用者；其他工具一樣可以用 `permissions.ask` 規則指定。
- 不同伺服器（或與 `tools/` 裡的工具）有同名的工具時，載入會失敗。

## 同一個專案給兩個版本使用

**`tools/` 裡有與伺服器同名的 Python 檔時，Python 版直接載入那個檔案，不啟動伺服器。**

`examples/report_bot` 就是這樣寫的：`tools/report.py`（`@harness.tool`）與 `tools/report_server.py`（MCP 伺服器）包裝同一份既有程式碼，`mcpServers` 裡的伺服器也叫 `report`。agent 檔案寫 `tools: [report]`，兩個版本各自找到自己的那一份，Python 版執行它不需要安裝 MCP 套件。

## 在程式裡使用 <span class="badge-py">Python 版</span> {#在程式裡使用}

用完專案要關閉伺服器。命令列會自動處理；在程式裡使用時，呼叫 `project.close()` 或用 `with`：

```python
with harness.load_project(".") as project:
    result = harness.run_sync(project.agents["main"], "幫我查一下")
```

不使用專案資料夾時，用 `harness.connect_mcp_server` 自己建立連線：

```python
with harness.connect_mcp_server(
    "github", command="npx", args=["-y", "@modelcontextprotocol/server-github"]
) as github:
    agent = harness.Agent(
        name="bot",
        instructions="你是開發助手。",
        tools=[build_report, *github.tools],
    )
    result = harness.run_sync(agent, "列出我最近的 PR")
```

連線在自己的背景執行緒裡維持，不屬於任何一個事件迴圈，所以可以在 FastAPI、Streamlit 這類服務裡建立一次，給之後每個請求共用。

TypeScript 版用 `loadProject()` 載入專案時同樣會啟動伺服器，用完呼叫 `project.close()`（見[嵌進自己的程式](/guide/embed)）。

## 其他語言的專案

- 任何語言只要有 MCP SDK（Go、Java、C#、Rust 等都有），把 `command` 換成啟動那個程式的指令即可。
- 已經是 HTTP 服務、支援 MCP 的 Streamable HTTP 時，改用 `url`：

```yaml
mcpServers:
  backend:
    url: https://my-service.example.com/mcp
    headers:
      Authorization: Bearer ${BACKEND_TOKEN}
```
