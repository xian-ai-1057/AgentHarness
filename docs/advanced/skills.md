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
- 載入狀態是從對話紀錄推算的，接續對話時已載入的 skill 仍然有效。

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
| `skill-creator` | 建立或改寫 skill，附 SKILL.md 範本 | `files` |
| `code-review` | 審查 git 變更，依嚴重程度回報問題，附檢查清單 | `files`、`shell` |
| `debugging` | 重現 → 縮小範圍 → 驗證假設 → 修正 → 確認 | `files`、`shell`、`plan` |
| `planning` | 把多步驟工作拆成計畫並持續更新進度 | `plan` |
| `web-research` | 查證網路資料，整理成附來源的回答 | `web` |
| `git-commit` | 檢查變更、撰寫 commit 訊息，經確認後 commit | `shell` |
| `xlsx` | 建立、編輯、分析試算表，公式用 LibreOffice 重算並檢查錯誤 | `files`（另需 `sandbox`） |
| `docx` | 建立、編輯 Word 文件，追蹤修訂、註解、轉成 PDF | `files`（另需 `sandbox`） |
| `pptx` | 建立結構化簡報（佈景主題、版面配置、原生圖表），編輯範本並檢查 | `files`（另需 `sandbox`） |
| `pdf` | 擷取文字與表格、合併分割、產生中文 PDF、填寫表單、OCR | `files`（另需 `sandbox`） |

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
- **load_skill 不逐一列出 `scripts/` 裡的檔案**，只說有幾個（docx、pptx、
  xlsx 各有幾十個 XML schema）；用法寫在 `SKILL.md` 裡，需要時仍可用
  `read_skill_file` 讀取原始碼。這個規則適用於所有 skill 的 `scripts/` 資料夾。
- **用自己的映像檔時**，把 `python/src/harness/builtin/skills` 複製到映像檔的
  `/opt/skills`，並裝好上面的工具；`pyharness sandbox` 會列出缺少的項目。

**開啟：** 新建立的助手在有沙盒時會自動列在 `agents/main.md` 的 `skills`。
既有的專案要自己加上：

```yaml
tools: [files, plan, web, sandbox]
skills: [planning, web-research, xlsx, docx, pptx, pdf]
```

也可以在網頁上每段對話的「＋ → Skills」臨時選用。

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
