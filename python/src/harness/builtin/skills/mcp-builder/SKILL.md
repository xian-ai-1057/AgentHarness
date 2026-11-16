---
# 改寫自 Anthropic 官方 skills 的 mcp-builder（https://github.com/anthropics/skills
# ，commit 1780c5e），授權 Apache License 2.0，完整條款見 LICENSE.txt。
# 修改內容：說明翻成繁體中文；補上在 Agent Harness 裡的做法：參考文件用
# read_skill_file 讀取、沙盒沒有網路（SDK 建置時裝好、不能 npm install、
# 不能用 npx 的 MCP Inspector），評估腳本需要 Anthropic API 金鑰與網路，
# 只能在沙盒外執行；做好的伺服器由管理者加到 harness.yaml 的 mcpServers。
# reference/、scripts/ 未修改。
name: mcp-builder
description: 建立高品質 MCP（Model Context Protocol）伺服器的指引，讓 LLM 透過設計良好的工具操作外部服務。要建 MCP 伺服器來整合外部 API 或內部系統（Python FastMCP 或 Node／TypeScript MCP SDK）時使用。
license: Apache-2.0，完整條款見 LICENSE.txt
tools: [files]
---

# MCP 伺服器開發指南

## 概要

建立 MCP（Model Context Protocol）伺服器，讓 LLM 能透過設計良好的工具
操作外部服務。MCP 伺服器的品質，取決於它能多有效地讓 LLM 完成真實世界的
工作。

## 在這個環境怎麼做

- **參考文件都在這個 skill 裡**，用 `read_skill_file("mcp-builder",
  "reference/…")` 讀取（英文）。下面提到「用 WebFetch 載入」的線上文件：
  有 `web_fetch` 工具而且連得到時才讀，連不到就以 `reference/` 為準。
- **用 `run_python` 在沙盒裡寫程式、編譯、測試**；shell 指令用
  `subprocess.run(..., capture_output=True, text=True)` 執行並印出結果。
  專案放在 `.skill-work/mcp-builder-<隨機碼>/` 或使用者指定的資料夾，
  完成後把原始碼交給使用者。
- 沙盒**沒有網路，不能 `npm install`、`pip install` 或 `npx`**。已經裝好：
  - Python：`mcp` 1.x（含 FastMCP，和 `reference/python_mcp_server.md` 的
    寫法相同；2.x 把 FastMCP 改名為 MCPServer）、`httpx`、`pydantic`
  - Node：`@modelcontextprotocol/server`、`@modelcontextprotocol/node`、
    `@modelcontextprotocol/express`、`@modelcontextprotocol/client`（SDK v2）、
    `@modelcontextprotocol/sdk`（v1）、`express`、`zod`、`typescript`
    （`tsc`）、`tsx`、`@types/node`、`@types/express`。專案不用自己的
    `node_modules`，`import` 會找到全域安裝的套件；`package.json` 照常寫，
    使用者部署時再 `npm install`。
- **MCP Inspector（`npx @modelcontextprotocol/inspector`）不能用。** 改成
  寫一支自我檢查腳本：用 stdio 啟動伺服器、以客戶端身分呼叫工具（Python 用
  `mcp.ClientSession` + `stdio_client`，TypeScript 見 v2 指南的 self-check
  script），失敗時以非零結束。
- 沙盒連不到外部 API，呼叫真實服務的部分在沙盒裡只能用假資料或 mock 測試，
  上線前要在能連線的環境實測。
- **第 4 階段的評估**：`scripts/evaluation.py` 要用 Anthropic API 金鑰與
  網路呼叫 Claude，沙盒裡不能執行。照評估指南寫好 XML，交給使用者在能
  連線的環境執行。
- **接到 Agent Harness**：做好的伺服器由管理者加到專案 `harness.yaml` 的
  `mcpServers`（stdio 或 HTTP），再把工具開放給 agent 或群組。

---

# 流程

## 🚀 整體工作流程

建立高品質的 MCP 伺服器包含四個主要階段：

### 第 1 階段：深入研究與規劃

#### 1.1 了解現代 MCP 設計

**API 涵蓋範圍 vs. 工作流程工具：**
在完整涵蓋 API 端點與專門的工作流程工具之間取得平衡。工作流程工具對特定
工作比較方便，完整的涵蓋則讓 agent 能彈性組合操作。效果因客戶端而異：
有些客戶端從能組合基本工具的程式執行中受益，有些則用高階工作流程效果更好。
不確定時，優先完整涵蓋 API。

**工具命名與可發現性：**
清楚、描述性的工具名稱幫助 agent 快速找到對的工具。使用一致的前綴（例如
`github_create_issue`、`github_list_repos`）與以動作為主的命名。

**上下文管理：**
簡潔的工具說明，以及篩選、分頁結果的能力，對 agent 很有幫助。設計回傳
聚焦、相關資料的工具。有些客戶端支援程式執行，能幫 agent 有效率地篩選、
處理資料。

**可行動的錯誤訊息：**
錯誤訊息應該用具體的建議與下一步，引導 agent 找到解法。

#### 1.2 研讀 MCP 協定文件

**瀏覽 MCP 規格：**

從網站地圖找相關頁面：`https://modelcontextprotocol.io/sitemap.xml`

再讀取個別頁面，網址加上 `.md` 取得 Markdown 格式（例如
`https://modelcontextprotocol.io/specification/draft.md`）。（需要
`web_fetch` 而且連得到；否則以 `reference/mcp_best_practices.md` 為準。）

要讀的重點頁面：

- 規格總覽與架構
- 傳輸機制（streamable HTTP、stdio）
- 工具、資源與 prompt 的定義

#### 1.3 研讀框架文件

**建議的技術組合：**

- **語言**：TypeScript（SDK 支援品質高，在許多執行環境相容性好，例如
  MCPB。而且 AI 模型擅長產生 TypeScript 程式碼，受益於它的廣泛使用、
  靜態型別與好用的 lint 工具）
- **傳輸**：遠端伺服器用 Streamable HTTP，搭配無狀態的 JSON（相較於有狀態
  的 session 與串流回應，更容易擴展與維護）。本機伺服器用 stdio。

**載入框架文件：**

- **MCP 最佳做法**：`reference/mcp_best_practices.md`，核心準則

**TypeScript（建議）：**

TypeScript SDK 有兩個主要版本。寫程式前先選一個：

- **v2**（`@modelcontextprotocol/server`）：目前的穩定版。新的伺服器用它。
- **v1**（`@modelcontextprotocol/sdk`）：只接收錯誤與安全性修正。只有專案的
  `package.json` 已經依賴 `@modelcontextprotocol/sdk` 時才用，或用
  `npx @modelcontextprotocol/codemod@latest v1-to-v2 .` 遷移專案（需要
  網路，沙盒裡不能執行）。

如果專案已經在用 v1，用一兩句話告訴使用者一次：v2
（`@modelcontextprotocol/server`）是目前的穩定版、v1 只接收錯誤與安全性
修正，以及 `npx @modelcontextprotocol/codemod@latest v1-to-v2 .` 可以遷移
專案。然後除非使用者要求遷移，繼續用 v1。

不要在同一個專案混用兩者：v1 的程式範例（從 `@modelcontextprotocol/sdk/...`
匯入）不適用於 v2。

- **TypeScript SDK（v2）**：線上 README 是
  `https://raw.githubusercontent.com/modelcontextprotocol/typescript-sdk/main/README.md`；
  完整文件索引是 `https://ts.sdk.modelcontextprotocol.io/v2/llms.txt`
- `reference/node_mcp_server_v2.md`：TypeScript 模式與範例（v2）
- 只有 v1 專案：
  `https://raw.githubusercontent.com/modelcontextprotocol/typescript-sdk/v1.x/README.md`
  與 `reference/node_mcp_server.md`（v1 指南）

**Python：**

- **Python SDK**：線上 README 是
  `https://raw.githubusercontent.com/modelcontextprotocol/python-sdk/main/README.md`
- `reference/python_mcp_server.md`：Python 模式與範例

#### 1.4 規劃實作

**了解 API：**
閱讀服務的 API 文件，找出主要端點、驗證需求與資料模型。需要時用網頁
搜尋與 `web_fetch`，或請使用者提供文件。

**選擇工具：**
優先完整涵蓋 API。列出要實作的端點，從最常用的操作開始。

---

### 第 2 階段：實作

#### 2.1 建立專案結構

專案設定見各語言的指南：

- `reference/node_mcp_server_v2.md`：專案結構、package.json、tsconfig.json
  （既有 v1 專案見 `reference/node_mcp_server.md`）
- `reference/python_mcp_server.md`：模組組織、相依套件

#### 2.2 實作核心基礎

建立共用的工具函式：

- 有驗證功能的 API 客戶端
- 錯誤處理輔助函式
- 回應格式化（JSON／Markdown）
- 分頁支援

#### 2.3 實作工具

每個工具：

**輸入 schema：**

- 用 Zod（TypeScript）或 Pydantic（Python）
- 包含限制條件與清楚的說明
- 在欄位說明裡加上範例

**輸出 schema：**

- 盡量定義 `outputSchema` 給結構化資料
- 在工具回應裡使用 `structuredContent`（TypeScript SDK 的功能）
- 幫助客戶端理解、處理工具的輸出

**工具說明：**

- 簡潔的功能摘要
- 參數說明
- 回傳型別的 schema

**實作：**

- I/O 操作用 async/await
- 適當的錯誤處理，搭配可行動的訊息
- 適用時支援分頁
- 使用新版 SDK 時，同時回傳文字內容與結構化資料

**註記（annotations）：**

- `readOnlyHint`：true／false
- `destructiveHint`：true／false
- `idempotentHint`：true／false
- `openWorldHint`：true／false

---

### 第 3 階段：檢查與測試

#### 3.1 程式碼品質

檢查：

- 沒有重複的程式碼（DRY 原則）
- 一致的錯誤處理
- 完整的型別涵蓋
- 清楚的工具說明

#### 3.2 建置與測試

**TypeScript：**

- 執行 `tsc` 確認能編譯（沙盒裡沒有 npm，用 `tsc -p .` 取代
  `npm run build`）
- v2 專案：對建置好的伺服器執行 v2 指南裡的自我檢查腳本
  （`reference/node_mcp_server_v2.md#verify-your-server`）
- MCP Inspector（`npx @modelcontextprotocol/inspector`）在沙盒裡不能用，
  請使用者在自己的環境測試

**Python：**

- 確認語法：`python -m py_compile your_server.py`
- 寫一支用 `mcp.ClientSession` 透過 stdio 呼叫工具的自我檢查腳本

詳細的測試做法與品質檢查清單見各語言的指南。

---

### 第 4 階段：建立評估

實作好 MCP 伺服器後，建立完整的評估來測試它的效果。

**完整的評估準則見 `reference/evaluation.md`。**

#### 4.1 了解評估的目的

用評估測試 LLM 能不能有效地用你的 MCP 伺服器回答真實、複雜的問題。

#### 4.2 建立 10 個評估問題

照評估指南的流程建立有效的評估：

1. **檢視工具**：列出可用的工具並了解它們的能力
2. **探索內容**：用**唯讀**操作探索可用的資料
3. **產生問題**：建立 10 個複雜、真實的問題
4. **驗證答案**：自己解每個問題，確認答案

#### 4.3 評估的要求

確保每個問題：

- **獨立**：不依賴其他問題
- **唯讀**：只需要非破壞性的操作
- **複雜**：需要多次工具呼叫與深入探索
- **真實**：根據人們真正在意的使用情境
- **可驗證**：有單一、清楚、能用字串比對驗證的答案
- **穩定**：答案不會隨時間改變

#### 4.4 產出格式

建立這種結構的 XML 檔：

```xml
<evaluation>
  <qa_pair>
    <question>Find discussions about AI model launches with animal codenames. One model needed a specific safety designation that uses the format ASL-X. What number X was being determined for the model named after a spotted wild cat?</question>
    <answer>3</answer>
  </qa_pair>
<!-- 更多 qa_pair…… -->
</evaluation>
```

執行評估（`scripts/evaluation.py`）需要 Anthropic API 金鑰與網路，在沙盒
外執行，用法見 `reference/evaluation.md`。

---

# 參考檔案

## 📚 文件庫

開發時依需要載入這些資源（都用 `read_skill_file` 讀取）：

### MCP 核心文件（最先載入）

- **MCP 協定**：從網站地圖 `https://modelcontextprotocol.io/sitemap.xml`
  開始，再讀取個別頁面（網址加 `.md`）；需要網路
- `reference/mcp_best_practices.md`：MCP 通用準則，包括：
  - 伺服器與工具的命名慣例
  - 回應格式準則（JSON vs Markdown）
  - 分頁最佳做法
  - 傳輸方式的選擇（streamable HTTP vs stdio）
  - 安全性與錯誤處理標準

### SDK 文件（第 1、2 階段載入；需要網路）

- **Python SDK**：`https://raw.githubusercontent.com/modelcontextprotocol/python-sdk/main/README.md`
- **TypeScript SDK（v2）**：`https://raw.githubusercontent.com/modelcontextprotocol/typescript-sdk/main/README.md`；
  完整文件索引 `https://ts.sdk.modelcontextprotocol.io/v2/llms.txt`
- **TypeScript SDK（v1，只給既有的 v1 專案）**：
  `https://raw.githubusercontent.com/modelcontextprotocol/typescript-sdk/v1.x/README.md`

### 各語言的實作指南（第 2 階段載入）

- `reference/python_mcp_server.md`：完整的 Python／FastMCP 指南，包括：
  - 伺服器初始化模式
  - Pydantic 模型範例
  - 用 `@mcp.tool` 註冊工具
  - 完整可執行的範例
  - 品質檢查清單

- `reference/node_mcp_server_v2.md`：`@modelcontextprotocol/server` 的完整
  TypeScript 指南，包括：
  - 專案設定與伺服器工廠
  - 工具設計：Zod 4 schema、輸出格式、分頁、錯誤
  - 同時提供 stdio 與 Streamable HTTP 的完整範例，以及 bearer 驗證
  - 資源、prompt 與通知
  - 驗證建置好的伺服器的自我檢查腳本
  - 進階功能的 SDK 範例連結
  - v1 → v2 對照表、遷移步驟與品質檢查清單

- `reference/node_mcp_server.md`：既有 `@modelcontextprotocol/sdk` 專案的
  同類指南（SDK v1）

### 評估指南（第 4 階段載入）

- `reference/evaluation.md`：完整的評估建立指南，包括：
  - 問題的建立準則
  - 答案的驗證策略
  - XML 格式規格
  - 問題與答案的範例
  - 用附帶的腳本執行評估
