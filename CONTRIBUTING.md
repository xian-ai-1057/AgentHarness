# 參與開發

謝謝你願意幫忙改進 Agent Harness。這份文件說明怎麼回報問題、怎麼在本機
開發與測試，以及送出 Pull Request（PR）前要確認的事。

## 回報問題與提出建議

- **錯誤**：到 [Issues](https://github.com/xian-ai-1057/AgentHarness/issues)
  開一則新的，寫下用的是哪個版本（TypeScript 版 `harness` 或 Python 版
  `pyharness`、網頁版或命令列）、怎麼重現、預期的結果與實際的結果。有錯誤
  訊息或畫面截圖的話一起附上。
- **新功能**：先開 Issue 說明想解決的問題與大致做法，討論過方向再動手，
  比較不會做白工。小修正（錯字、文件、明顯的錯誤）可以直接送 PR。
- **安全性問題**（例如可以繞過權限、讀到別人的對話）：請不要在公開的
  Issue 寫出細節。repo 的 Security 分頁有「Report a vulnerability」時用它
  私下回報；沒有的話，開一則只寫「有安全性問題需要私下回報」的 Issue，
  維護者會和你聯絡。

回報時請拿掉 API 金鑰、密碼、內部網址與個人資料。

## 授權

Agent Harness 以 [Apache License 2.0](LICENSE) 授權。依照授權條款第 5 條，
你送出的貢獻（程式碼、文件、圖片等）除非另外明確聲明，都以同一個授權提供，
不需要另外簽署貢獻者協議。

- 只送你有權利提供的內容。從別的專案複製或改寫的程式碼，要確認它的授權與
  Apache 2.0 相容，保留原本的著作權聲明，並在 [`NOTICE`](NOTICE) 與說明文件
  的[授權](docs/reference/license.md)頁加上這個第三方元件。
- 改 `NOTICE` 時，`python/NOTICE` 也要一起改（兩份要一模一樣，測試會檢查）。
- 新增前端套件後執行 `npm run build`，`THIRD_PARTY_LICENSES.md` 會自動更新。

## 專案結構

| 位置 | 內容 |
|---|---|
| `src/` | TypeScript 版（`harness` 指令與函式庫） |
| `python/src/harness/` | Python 版（`pyharness` 指令、網頁版伺服器、知識庫、沙盒等進階功能） |
| `web/` | 網頁版前端（React + Vite），兩個版本共用 |
| `python/src/harness/web/static/` | 打包好的前端，由 `npm run build` 產生，**要一起提交** |
| `tests/`、`python/tests/` | 兩個版本的測試 |
| `docs/` | 說明文件網站（VitePress） |
| `docker/`、`Dockerfile`、`docker-compose.yml` | 快速部署與沙盒映像檔 |
| `examples/` | 範例專案 |

第一次讀原始碼，建議照說明文件的[閱讀原始碼](docs/reference/source.md)順序
看。

## 建立開發環境

需要 Node.js 22.18 以上、Python 3.11 以上。

```bash
git clone https://github.com/xian-ai-1057/AgentHarness.git
cd AgentHarness

# TypeScript 版與網頁前端
npm install

# Python 版（可編輯安裝，含測試工具與選用功能）
cd python
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,pdf,vectors]"
```

### 修改網頁版

先在任一個專案資料夾啟動伺服器，再在這個 repo 啟動 Vite：

```bash
pyharness web          # 或 harness web；預設在 http://127.0.0.1:4321
npm run dev:web        # 另一個終端機；Vite 會把 /api 轉給上面的伺服器
```

伺服器不在 4321 埠時，用 `HARNESS_WEB_URL=http://127.0.0.1:8080 npm run dev:web`
指定。

改完前端一定要執行 `npm run build`，並把 `python/src/harness/web/static/` 的
變動一起提交：Python 版用 pip 從 git 安裝時拿不到 Node.js，只能用這份打包
好的檔案。CI 會檢查它是不是最新的。

### 用 Docker 整套跑起來

```bash
docker compose up -d --build   # http://localhost:4321
```

改了後端、前端或沙盒映像檔，要確認在部署的樣子下也正常時用這個方式測。

## 送 PR 前要跑的檢查

CI 會在每個 PR 跑下面這些檢查，全部通過才能合併。送出前請先在本機跑過：

```bash
# TypeScript 與前端
npm run lint           # Biome；npm run format 可以自動修正格式
npm run typecheck
npm test
npm run build          # 然後確認 git status 沒有沒提交的變動

# Python（在 python/ 資料夾）
ruff check .
ruff format --check .  # ruff format . 可以自動修正
pytest
```

只改了一小部分時，可以先只跑相關的測試（例如
`npx vitest run tests/web/chat-helpers.test.ts`、`pytest tests/test_knowledge.py`），
送出前再跑一次完整的。

## 程式風格

- **TypeScript**：照 Biome 的設定（`biome.json`）。
- **Python**：照 [Google Python Style Guide](https://google.github.io/styleguide/pyguide.html)，
  每行 80 字、每行只 import 一個名稱，函式與類別寫 Google 風格的 docstring
  （`Args:`、`Returns:`）。`ruff` 會檢查大部分規則。
- **語言**：註解、docstring、錯誤訊息、畫面上的文字與說明文件用繁體中文，
  用一般使用者看得懂的說法（例如步驟清單寫「搜尋知識庫」而不是工具名稱）。
  程式碼裡的名稱用英文。
- **簡單優先**：先用最直接的寫法完成，真的需要時再抽象化。不要為了想像中的
  需求加設定或參數。
- 收錄自 Anthropic 官方 skills 的檔案（`python/src/harness/builtin/skills/`
  底下有 `LICENSE.txt` 的資料夾）不套用本專案的風格，方便日後與上游同步；
  修改時在 `SKILL.md` 開頭註明改了什麼。

## 修改資料庫的資料表

網頁版的資料表在 `.harness/harness.db`。要加欄位或資料表時，在
`python/src/harness/web/datastore.py` 的 `MIGRATIONS` 最後加一個升級步驟
（版本號加一），不要改已經發布的步驟；同時更新該模組自己的
`CREATE TABLE IF NOT EXISTS`，讓新建的資料庫一開始就是最新的樣子（新建時
不執行升級步驟）。步驟要能重複執行，加欄位用 `datastore.add_column`。盡量
只做「新增」，舊版程式讀得懂，換回舊版時才不必還原。升級前的自動快照
與還原由 datastore 處理，不需要另外寫。

## 測試

- 修錯誤時，先寫一個會重現錯誤的測試，再修到它通過。
- 新功能要有測試。呼叫模型的地方用假的模型（見既有測試的寫法），測試不能
  需要真的 API 金鑰或網路。
- 不要為了讓 CI 變綠而跳過、刪掉或放寬既有的測試；測試真的過時了，在 PR
  說明裡講清楚為什麼要改。

## 說明文件

**新功能或行為改變時，同一個 PR 裡要一起更新說明文件**：`docs/` 底下相關的
頁面，以及根目錄的 `README.md`（或 `python/README.md`）裡提到這個功能的地方。
新增頁面時記得加進 `docs/.vitepress/config.mts` 的側邊欄。

預覽說明文件網站：

```bash
cd docs
npm install
npm run dev
```

## 提交與 PR

1. 從最新的 `main` 開一個分支，一個 PR 只做一件事。
2. 提交訊息寫清楚「改了什麼、為什麼」，中英文都可以。
3. PR 說明寫下：解決的問題（有 Issue 的話附上連結）、做法、怎麼測試的；
   改了畫面的話附上截圖。
4. 改了前端的 PR 和別的 PR 同時合併時，`python/src/harness/web/static/` 一定
   會衝突。解法是把 `main` 合併進來、重新 `npm run build`、提交新的打包結果。
5. 維護者 review 後可能會請你修改，修改直接推到同一個分支就好。

## 行為準則

請友善、尊重地交流：就事論事地討論程式與設計，不做人身攻擊，也不騷擾任何人。
維護者可以移除不符合這個原則的留言、Issue 或 PR。
