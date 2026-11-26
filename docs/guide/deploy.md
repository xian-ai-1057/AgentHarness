# 快速部署（Docker）<span class="badge-py">Python 版</span>

只想架起來給自己或團隊用、不寫任何設定時用這個方式。需要一台裝好 [Docker](https://docs.docker.com/engine/install/)（Docker 26、Compose 2.24 以上）的電腦。

```bash
git clone https://github.com/xian-ai-1057/AgentHarness.git
cd AgentHarness
docker compose up -d             # 第一次會建置映像檔，需要幾分鐘
docker compose logs harness      # 看網址與管理者 admin 自動產生的密碼
```

接著：

1. **登入**：用瀏覽器打開 `http://<這台電腦的位址>:4321`，帳號 `admin`，密碼在上面的 log 裡。第一次登入後請在帳號選單改密碼，再從帳號選單打開「管理平台 → 成員」幫其他人建立帳號（見[帳號與成員](/guide/web#帳號與成員)）。
2. **連接模型**：第一次會看到「還沒有連接模型」，按「前往管理平台」，選供應商、貼上金鑰，按「測試連線並儲存」（見[在網頁上連接模型](/guide/web#在網頁上連接模型)）。
3. **開始對話**：可以直接上傳 Excel、PDF、CSV 請它分析。

## 自動完成的設定

| 項目 | 自動的做法 | 想自己指定時 |
|---|---|---|
| 專案 | 建立一個通用助手：讀寫檔案、列計畫、讀取網頁、記住交代的事、寫程式分析上傳的檔案 | 修改 volume 裡的 `harness.yaml`、`agents/main.md`、`AGENTS.md` |
| 管理者密碼 | 第一次啟動時建立帳號 `admin` 並產生密碼，之後每次啟動都會顯示（admin 改過密碼後就不顯示） | `.env` 的 `HARNESS_WEB_PASSWORD`（只在建立 admin 時使用） |
| 模型與金鑰 | 在網頁上填寫 | `.env` 的 `ANTHROPIC_API_KEY` 等 |
| 沙盒 | 一併建置裝好 pandas、matplotlib、LibreOffice（Word、PowerPoint 預覽），以及內建 skills 需要的 Node.js、pandoc、qpdf、OCR、Playwright 與無頭 Chromium、MCP SDK、React 專案範本等工具的映像檔（約 4 GB，執行時不連外）；容器由另一個沙盒服務 `sandbox-runner` 啟動（見[沙盒服務](#沙盒服務)） | 修改 `docker/sandbox.Dockerfile` |
| 埠號 | 4321 | `.env` 的 `HARNESS_PORT` |

要調整時，把 `.env.example` 複製成 `.env` 再修改，然後重新執行 `docker compose up -d`。

要接上透過 LiteLLM Proxy 提供的 MCP 工具（例如網頁搜尋），見[連接 MCP 伺服器 → 用 Docker 部署時](/guide/mcp#litellm-docker)。

內建的網頁搜尋 `web_search` 預設用 DuckDuckGo，不需要設定；要換成自架的 SearXNG 或 Brave、Tavily，或改用搜尋 MCP 而關掉內建的（`HARNESS_WEB_SEARCH=off`），在 `.env` 設定，見[網頁搜尋](/guide/builtin-tools#網頁搜尋)。

## 透過 proxy 連外

公司網路要透過 proxy 才能連外時，在 `.env` 寫上：

```bash
HTTP_PROXY=http://proxy.example.com:3128
HTTPS_PROXY=http://proxy.example.com:3128
NO_PROXY=localhost,127.0.0.1,.example.internal   # 不經過 proxy 的位址
```

建置映像檔（pip、apt）與執行時（呼叫模型、讀取網頁）都會使用，容器裡大小寫兩種環境變數都會設定。proxy 不會寫進映像檔。執行 `docker compose` 的終端機已經設定這些環境變數時，不寫 `.env` 也會沿用。內網的模型端點（例如自架的 LiteLLM Proxy）記得放進 `NO_PROXY`。

## 資料放在哪裡

專案、帳號（`.harness/harness.db`）、每個人的對話紀錄與記憶、「我的檔案」（`private/`）、管理者開放的共用資料夾與金鑰都在名為 `harness-data` 的 Docker volume 裡，`docker compose down` 與重新建置都不會刪除它（`docker compose down -v` 才會）。

```bash
docker compose exec harness ls /assistant
docker compose restart harness   # 改了 harness.yaml 或 agent 之後重新載入
```

更新版本：`git pull && docker compose up -d --build`。

從多人帳號之前的版本升級時，第一次啟動會把原本的對話紀錄與記憶交給 `admin`，放在只有他看得到的「舊資料（專案資料夾）」裡，舊對話的附件與檔案照樣打得開；`workspace/` 裡的檔案不搬，也**不會**分享給其他成員。

**從 2026 年 11 月底之前的版本升級**：預設不再有所有人共用的「共用」資料夾（`shared/`），裡面的檔案原封不動，只是網頁上看不到，用過它的對話會請使用者開新的對話；`shared/` 裡有檔案時，啟動的 log 會提醒。要繼續使用，在 `harness.yaml` 的 `workspaces` 寫上它（見[工作資料夾](/guide/web#工作資料夾)）。另外管理者的指令也改在沙盒執行，「以後都允許」改成只對自己有效，見[正式上線前的安全設定](/advanced/server#正式上線前的安全設定)。

## 沙盒服務 {#沙盒服務}

agent 寫的程式與執行的指令都在拋棄式的沙盒容器裡執行。能使用 Docker socket 就等於擁有主機的 root 權限，所以平台容器（`harness`）**不掛 socket**，改由一個只做這件事的小服務 `sandbox-runner` 持有：

- 平台只能請它「在沙盒裡執行這段程式」。映像檔、容器裡的使用者、資源上限與網路都照服務自己的設定，請求只能要求更少的資源；只能掛載 `harness-data` 裡的工作資料夾，不能掛載 volume 的根目錄、`.harness/`（金鑰）或專案的設定與程式；網路一律關閉。
- 它只在 compose 的內部網路 `sandbox` 上，沒有開放埠號，也連不到外面；每次啟動產生一組通行碼，平台唯讀掛載來讀。
- 平台即使被攻破，能做的也只是在沙盒裡執行程式，碰不到主機。

| 服務的環境變數 | 用途 |
|---|---|
| `HARNESS_SANDBOX_RUNTIME` | 容器的 runtime。主機裝了 [gVisor](https://gvisor.dev/docs/user_guide/install/) 時在 `.env` 寫 `HARNESS_SANDBOX_RUNTIME=runsc`，沙盒多一層核心隔離（Docker Desktop 不支援） |
| `HARNESS_SANDBOX_MAX_MEMORY`、`HARNESS_SANDBOX_MAX_CPUS` | 每個沙盒最多能用的記憶體與 CPU（預設 `4g`、`2`），`harness.yaml` 的 `sandbox.memory`、`sandbox.cpus` 超過時以這裡為準 |
| `HARNESS_SANDBOX_USER` | 容器裡的使用者，預設 `1000:1000`（和平台相同，產生的檔案平台才能讀寫） |
| `HARNESS_SANDBOX_ALLOW_NETWORK` | 設成 `1` 才允許 `sandbox.network: true` |

不需要沙盒時，把 `docker-compose.yml` 裡的 `sandbox-runner` 服務與 `harness` 的 `HARNESS_SANDBOX_RUNNER` 一起刪掉（自動建立的助手就不會開啟沙盒）。檢查沙盒是否正常：`docker compose exec harness pyharness sandbox -p /assistant`。

## 安全上要知道的事

::: warning
- **`sandbox-runner` 掛載主機的 Docker socket**，平台容器沒有（見[沙盒服務](#沙盒服務)）。沙盒服務本身等於擁有主機的 root 權限，請放在專用的機器或虛擬機上，也不要把 `sandbox` 網路接到其他服務。
- **金鑰只給平台自己用**：agent 執行的指令、stdio MCP 伺服器拿到的環境變數會拿掉名稱像金鑰的變數（含 `KEY`、`SECRET`、`TOKEN`、`PASSWORD` 等字）與網頁上填的金鑰；沙盒容器裡完全沒有。
- **admin 的密碼會印在 log 裡**，看得到 `docker compose logs` 的人就能以管理者登入，直到 admin 自己改掉密碼。
- **這個設定是 http，沒有加密。** 只在內網或 VPN 裡使用；要從網際網路連線，請在前面加上 HTTPS 的反向代理（見[部署到伺服器](/advanced/server)），並在 `.env` 用 `HARNESS_TRUSTED_PROXIES` 寫上反向代理連進容器的位址（例如 `172.16.0.0/12`），登入限制才會依使用者真正的 IP 計算、cookie 才會加上 Secure。
- 每個人的對話與「我的檔案」分開，共用資料夾所有能使用的人都拿得到；成員與管理者的差別見[部署到伺服器](/advanced/server#安全上要知道的事)。
:::

## 不用 Docker

[安裝 Python 版](/guide/install#python-版)後，在一個空的資料夾執行 `pyharness web`，同樣會自動建立助手、在網頁上填金鑰（見[網頁版](/guide/web)）。
