# Skills <span class="badge-py">Python 版</span>

把一段任務指示（加上專屬的工具與參考檔案）打包成 skill。agent 平常只
看得到每個 skill 的名稱與一句說明，判斷用得到時才呼叫 `load_skill`
讀進完整指示，skill 的專屬工具也在這時才開放。agent 可以掛很多 skill，
又不會讓 system prompt 塞滿用不到的說明。

```
skills/
└── refund/
    ├── SKILL.md
    └── policy.md       參考檔案，agent 用 read_skill_file 讀取
```

`SKILL.md`：

```markdown
---
name: refund                           # 省略時用資料夾名稱
description: 處理退款申請，依退款政策判斷能不能退
tools: [find_order, issue_refund]      # 選用，tools/ 裡的工具或 toolset
requires: [run_python]                 # 選用，agent 要有這些工具才用得上
---
1. 先用 find_order 查訂單，確認付款日期。
2. 讀 policy.md 判斷是否在可退款期間內。
3. 符合條件才呼叫 issue_refund。
```

- **`description` 必填**，agent 靠它決定什麼時候載入，寫清楚「什麼情況
  要用」。
- agent 設定沒寫 `skills` 欄位時可以使用全部 skill；用 `skills: [refund]`
  指定，`skills: []` 表示不用。
- skill 的專屬工具在 skill 載入前不會出現在 agent 的工具裡（即使 agent
  沒寫 `tools` 欄位）。想讓 agent 隨時都能用，就在 agent 的 `tools`
  明確列出。
- `requires` 列出 skill 用得上的前提工具（例如要在沙盒裡執行腳本的
  skill 寫 `run_python`）。網頁上這段對話的 agent 沒有這些工具（專案沒有
  沙盒、群組沒開放，或在「＋ → 工具」取消了）時，這個 skill 不會預設開啟，
  使用者挑了也不會套用。
- 載入狀態是從對話紀錄推算的，接續對話時已載入的 skill 仍然有效。

## 在網頁上管理 skills {#在網頁上管理}

網頁版不用碰檔案也能新增、修改與刪除 skill：

- **管理平台 → Skills**（只有管理者）：列出內建與公司的 skill。
  - **新增**：填名稱（小寫英文、數字與連字號）、說明與指示，存成專案的
    `skills/<名稱>/SKILL.md`，馬上生效，不必重新啟動。
  - **上傳 zip**：整個 skill 資料夾（含參考檔案與腳本）壓成 zip 上傳，
    例如從 [Anthropic skills](https://github.com/anthropics/skills) 下載的
    資料夾。同名時會先問要不要取代。上限 30 MB、1,000 個檔案；不接受
    符號連結與跳出資料夾的路徑。
  - **啟用／預設開啟**：關掉的 skill 誰都不能用（agent 設定有寫也一樣）；
    預設開啟的每段對話都會列給 agent，其他的使用者可以在輸入框的
    ＋ → Skills 自己勾選。設定存在 `harness.yaml` 的 `web.disabledSkills`、
    `web.defaultSkills`。
  - **內建的 skill 不能刪除**：修改內容時會複製一份成公司版本（連同參考
    檔案）取代內建的；刪掉公司版本就還原成內建的。
  - 有公司 agent 在 `skills` 欄位列出的公司 skill 不能刪，要先在
    [管理平台 → Agent](/guide/web#公司-agent) 拿掉。
- **群組**：[存取群組](/guide/web#存取群組) 多了「Skills」一項，可以只開放
  某些 skill 給某個群組。
- **Skills 頁（`/skills`，每個人都有）**：列出可以用的公司與內建 skill；
  要登入的網頁版還可以建立**個人 skill**。個人 skill 只有建立的人看得到、
  用得到，在自己的對話預設開啟，自建 Agent 也能勾選；不能分享，要給別人
  用的請管理者建成公司 skill。個人 skill 不能有專屬工具，名稱不能和公司或
  內建的 skill 相同，每人最多 50 個，zip 上限 5 MB。存在
  `.harness/personal-skills/<帳號 id>/`，刪除成員時一併刪除。

新增、修改、刪除與上傳都會記在[稽核紀錄](/guide/web#稽核紀錄)。

## 在程式裡使用

```python
refund = harness.Skill(
    name="refund",
    description="處理退款申請",
    instructions="1. 先用 find_order 查訂單……",
    tools=[issue_refund],
    root=pathlib.Path("skills/refund"),  # 有參考檔案時才需要
)
agent = harness.Agent(name="cs", instructions="...", skills=[refund])
```

## 內建 skills

框架附帶幾個常用的 skill，寫法參考 Claude 與 Codex 的 skills。在 agent
的 `skills` 欄位列出名稱就能使用（沒寫 `skills` 欄位時只會拿到專案自己
的 skill，不含內建的）：

| skill | 用途 | 載入後開放的工具 |
|---|---|---|
| `skill-creator` | 建立、改寫與測試 skill，附 SKILL.md 範本（改寫自官方） | `files` |
| `code-review` | 審查 git 變更，依嚴重程度回報問題，附檢查清單 | `files`、`shell` |
| `debugging` | 重現 → 縮小範圍 → 驗證假設 → 修正 → 確認 | `files`、`shell`、`plan` |
| `planning` | 把多步驟工作拆成計畫並持續更新進度 | `plan` |
| `web-research` | 查證網路資料，整理成附來源的回答 | `web` |
| `git-commit` | 檢查變更、撰寫 commit 訊息，經確認後 commit | `shell` |
| `doc-coauthoring` | 帶使用者寫提案、規格、決策文件：蒐集背景 → 架構 → 逐節撰寫 → 讀者測試 | `files` |
| `xlsx` | 建立、編輯、分析試算表，公式用 LibreOffice 重算並檢查錯誤 | `files`（另需 `sandbox`） |
| `docx` | 建立、編輯 Word 文件，追蹤修訂、註解、轉成 PDF | `files`（另需 `sandbox`） |
| `pptx` | 建立結構化簡報（佈景主題、版面配置、原生圖表），編輯範本並檢查 | `files`（另需 `sandbox`） |
| `pdf` | 擷取文字與表格、合併分割、產生中文 PDF、填寫表單、OCR | `files`（另需 `sandbox`） |
| `internal-comms` | 依格式寫週報、3P 更新、電子報、FAQ、事件報告 | `files` |
| `brand-guidelines` | 套用 Anthropic 的品牌色與字型（可複製改成自己公司的） | `files` |
| `theme-factory` | 10 套配色與字型主題，套用到簡報、文件、網頁 | `files` |
| `frontend-design` | 有辨識度的網頁與介面設計指引 | `files` |
| `canvas-design` | 以設計哲學創作海報、主視覺（PNG／PDF） | `files`（另需 `sandbox`） |
| `algorithmic-art` | 用 p5.js 創作可調參數的生成藝術（單一 HTML） | `files`（建議 `sandbox`） |
| `web-artifacts-builder` | React + Tailwind + shadcn/ui 的複雜網頁應用，打包成單一 HTML | `files`（另需 `sandbox`） |
| `webapp-testing` | 用 Playwright 測試沙盒裡的網頁、截圖、讀主控台 | `files`（另需 `sandbox`） |
| `mcp-builder` | 設計、實作、測試 MCP 伺服器（Python 或 TypeScript） | `files`（另需 `sandbox`） |

```yaml
skills: [code-review, git-commit]
```

- 專案 `skills/` 裡有同名的 skill 時以專案的為準，所以想調整內建 skill
  的做法，可以把 `harness/builtin/skills/<名稱>/` 複製到專案的 `skills/`
  再修改（或請 agent 用 `skill-creator` 幫你改）。
- 內建 skill 的專屬工具一律來自內建 toolsets，而且照樣受權限設定管制
  （例如 `run_command` 仍會先問使用者）。
- 不使用專案資料夾時：`harness.builtin_skills()["code-review"]`。

### Office 文件與 PDF 的 skills {#office-文件與-pdf-的-skills}

`xlsx`、`docx`、`pptx`、`pdf` 改寫自 Anthropic 官方的
[anthropics/skills](https://github.com/anthropics/skills)（commit `1780c5e`，
Claude 本身產生 Office 檔與 PDF 用的就是這幾個 skill），授權是 Apache
License 2.0：

- 每個資料夾保留官方的 `LICENSE.txt`，`SKILL.md` 開頭註明來源與修改內容。
- `scripts/`（驗證 OOXML、重算公式、複製投影片、填寫表單等腳本）與 pdf 的
  `REFERENCE.md`、`FORMS.md` 照原樣收錄，沒有修改。
- `SKILL.md` 翻成繁體中文，改成在沙盒裡執行，並補上中文字型（Word、
  PowerPoint 用微軟正黑體，reportlab 用沙盒裡的 AR PL UMing）與中文 OCR
  的做法。

**需要沙盒。** 這幾個 skill 靠 agent 寫程式、執行腳本完成工作，agent 的
`tools` 要有 `sandbox`，映像檔也要裝好需要的工具。用
[Docker Compose 部署](/guide/deploy)時 `docker/sandbox.Dockerfile` 都已經
裝好（LibreOffice、pandoc、qpdf、poppler-utils、tesseract 繁中與簡中、
Node.js 與 pptxgenjs、docx、pdf-lib，以及 pypdf、reportlab、markitdown 等），
並把 `harness/builtin/skills/` 複製到映像檔的 `/opt/skills/`。沙盒沒有網路，
所以全部在建置映像檔時裝好，執行時不會下載任何東西。

- **腳本在沙盒裡唯讀。** `/opt/skills/` 在映像檔的系統目錄裡，容器以唯讀
  方式執行，agent 寫的程式改不到這些腳本；專案的 `skills/` 資料夾仍然不會
  掛進沙盒。
- **中間檔放在每次工作專用的資料夾。** 同一個人的多段對話可能共用同一個
  工作資料夾（例如「我的檔案」），所以這幾個 skill 要求 agent 把解壓縮的
  檔案、JSON、逐頁圖片等放在 `.skill-work/<skill>-<隨機碼>/`，只刪除那裡的
  檔案，做完就刪掉；成品才存到工作資料夾，並避開既有的檔名。以點開頭的
  資料夾不會出現在產生的檔案卡片裡。
- **load_skill 不逐一列出 `scripts/` 裡的檔案**，只說有幾個（docx、pptx、
  xlsx 各有幾十個 XML schema）；用法寫在 `SKILL.md` 裡，需要時仍可用
  `read_skill_file` 讀取原始碼。這個規則適用於所有 skill 的 `scripts/` 資料夾。
- **用自己的映像檔時**，把 `python/src/harness/builtin/skills` 複製到映像檔的
  `/opt/skills`，並裝好上面的工具；`pyharness sandbox` 會列出缺少的項目。

**在網頁上預設開啟。** 和 Claude 一樣，網頁上的每段對話預設就能用這四個
skill 與[其他改寫自官方的 skills](#其他改寫自官方的-skills)，不用在 agent 的
`skills` 裡列出，伺服器自動把它們加進技能清單。agent 只在工作需要時才載入，
不會每次都讀。

- 需要執行程式的（`SKILL.md` 寫了 `requires: [run_python]`：這四個加上
  `algorithmic-art`、`canvas-design`、`web-artifacts-builder`、
  `webapp-testing`）只在專案有開沙盒，而且這段對話的 agent 能執行程式時
  才開：工具有 `run_python`，沒有被群組或這段對話關掉，也不是「舊資料」
  資料夾。群組沒有開放沙盒時，「＋ → Skills」也不列出它們。
- 使用者可以在「＋ → Skills」取消勾選（標「預設」的項目），只影響這段
  對話；輸入框會顯示「已關閉 N 個預設 skill」，按 × 全部開回來。
- 在「＋ → 工具」取消 `run_python` 時，需要它的 skill 變成灰色、不能勾選，
  並說明要先開啟 `run_python`。
- 要換成別的清單或全部關掉，在 `harness.yaml` 設定（只能列內建或專案裡
  有的 skill）：

```yaml
web:
  defaultSkills: [xlsx, pdf]   # [] 表示不預設開啟任何 skill
```

命令列（`pyharness chat`）與 API 不套用預設，要用的話在 agent 列出：

```yaml
tools: [files, plan, web, sandbox]
skills: [planning, web-research, xlsx, docx, pptx, pdf]
```

**目前的限制：**

- **agent 看不到圖片。** 官方流程會把投影片、Word 轉成圖片給模型檢查版面；
  這裡改成用文字檢查（`slide_text.py`、`validate.py`、`pandoc`）並計算座標，
  轉好的 PDF 存在工作資料夾，請使用者在網頁上預覽確認。
- **填寫中文 PDF 表單**時，表單欄位的字型通常沒有中文字，所以 `pdf` skill
  改成把文字畫在頁面上並拿掉表單欄位（填好後不能再當表單編輯）。
- **字型以使用者的 Office 為準。** 沙盒裡沒有微軟正黑體，LibreOffice 預覽用
  Noto CJK 代替，換行位置可能和 Office 略有不同。

**跟上官方的更新：** 把官方 repo 裡同名資料夾的 `scripts/`、`LICENSE.txt`
（以及 pdf 的 `REFERENCE.md`、`FORMS.md`）覆蓋過來，比對官方 `SKILL.md` 的
差異後改寫到我們的繁體中文版，更新 `SKILL.md` 開頭的 commit，再重新建置
沙盒映像檔（`docker compose build sandbox-image`）。

### 其他改寫自官方的 skills {#其他改寫自官方的-skills}

除了上面的文件 skills，[anthropics/skills](https://github.com/anthropics/skills)
（commit `1780c5e`）的範例 skills 也收錄了，只有 `slack-gif-creator` 沒有
加。網頁上每段對話**預設開啟**（見上面的「在網頁上預設開啟」），需要執行
程式的只在能執行程式時才開；命令列與 API 要在 agent 的 `skills` 列出。授權與改寫方式和文件 skills 相同：保留
`LICENSE.txt`（Apache 2.0），`SKILL.md` 開頭註明來源與修改內容，附帶的腳本、
範本、參考文件照原樣收錄。

- **`doc-coauthoring` 是自己寫的。** 官方的同名 skill 沒有附授權條款，不能
  確定可以轉載，所以沒有收錄或翻譯它，改寫一份同樣用途、內容獨立的版本。
- **`skill-creator` 換成官方版改寫。** 原本內建的 skill-creator 併進來
  （`template.md` 與 Agent Harness 的 frontmatter 說明）；官方流程裡需要
  subagent 或 `claude` 命令列的步驟（平行測試、基準比較、自動最佳化描述）
  改成自己逐一測試與人工檢視。
- **`brand-guidelines` 是 Anthropic 的品牌。** 要套用自己公司的品牌，把它
  複製到專案的 `skills/` 改成自己的色碼與字型。

**沙盒裡都在建置時裝好，執行時不下載任何東西：**

| skill | 沙盒映像檔裡準備的東西 | 限制 |
|---|---|---|
| `web-artifacts-builder` | 用官方 `init-artifact.sh` 建好的 React 專案範本 `/opt/web-artifact`（含 Parcel、html-inline）；`offline/init-artifact.sh` 複製範本並連結它的 `node_modules`，`offline/bundle-artifact.sh` 不用 `pnpm add` 直接打包 | 只能用範本裡已有的套件；打包約數秒到數十秒 |
| `webapp-testing` | Playwright（Python）與無頭 Chromium | 沙盒沒有網路，只能測工作資料夾裡的 HTML 或在沙盒裡啟動的伺服器 |
| `mcp-builder` | Python `mcp` 1.x（FastMCP）、Node 的 MCP SDK v2／v1、express、zod、`tsc`、`tsx` | MCP Inspector 與 `scripts/evaluation.py`（要 Anthropic API 與網路）不能在沙盒裡執行；做好的伺服器由管理者加到 `harness.yaml` 的 `mcpServers` |
| `algorithmic-art` | p5.js 1.7.0；`offline/inline_p5.py` 把它內嵌進 HTML 並拿掉 Google Fonts 連結 | 產出的 HTML 下載後用瀏覽器開啟 |
| `canvas-design` | 附帶的 54 個字型（SIL OFL）登記成系統字型，LibreOffice、matplotlib 也能用 | 字型都是英數字型，中文用 Noto CJK；agent 看不到成品，改用程式量測版面並請使用者預覽 |

`frontend-design`、`theme-factory`、`internal-comms`、`brand-guidelines`、
`doc-coauthoring` 只是寫作與設計的指引，不需要沙盒（`theme-factory` 有沙盒
時會把主題展示 PDF 複製給使用者看）。`internal-comms` 官方提到用 Slack、
Google Drive 找資料，這裡改成用上傳的檔案、知識庫與網頁工具。

