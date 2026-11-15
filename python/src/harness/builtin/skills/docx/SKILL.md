---
# 改寫自 Anthropic 官方 skills 的 docx（https://github.com/anthropics/skills
# ，commit 1780c5e），授權 Apache License 2.0，完整條款見 LICENSE.txt。
# 修改內容：說明翻成繁體中文；改成在 Agent Harness 的沙盒裡執行（腳本在
# /opt/skills/docx/scripts/，沒有網路、不安裝套件）；補上中文字型的建議；
# 沒有看圖工具，視覺檢查改由使用者預覽。scripts/ 未修改。
name: docx
description: 建立、讀取、編輯或處理 Word 文件（.docx）與 Word 範本（.dotx）時使用：提到 Word、.docx、.dotx，或要做有目錄、標題、頁碼、信頭等格式的正式文件；從 Word 檔擷取或重整內容、插入或替換圖片、尋找取代、追蹤修訂或註解，或把內容做成精美的 Word 文件。使用者要的報告、備忘錄、信件、範本是 Word 檔時也用。PDF、試算表、Google 文件或與文件無關的程式工作不要用。
license: Apache-2.0，完整條款見 LICENSE.txt
tools: [files]
requires: [run_python]
---

# DOCX：建立、編輯與分析 Word 文件

## 在這個環境怎麼執行

- **一律用 `run_python` 在沙盒裡執行。** 下面的 shell 指令（`node`、`pandoc`、
  `unzip`、`zip`、`pdftoppm`……）也一樣：在 `run_python` 裡用
  `subprocess.run(..., capture_output=True, text=True)` 執行並印出 stdout、
  stderr；需要 `cd`、管線或 `||` 時傳 `shell=True`，或用 `cwd=` 參數。不要用
  `run_command` 執行這些指令。
- 工作目錄是 `/workspace`（這段對話的工作資料夾）：使用者上傳的檔案在
  `uploads/`，產出的檔案存在 `/workspace` 底下，完成後告訴使用者檔名。
  Node 腳本也寫在這裡（例如用 Python 寫出 `build_doc.js` 再執行
  `node build_doc.js`）。
- **中間檔放在這次工作專用的資料夾，不要動別人的檔案。** 同一個人的
  其他對話可能同時在用這個工作資料夾。開始時先建一個專用資料夾，例如
  `W = f".skill-work/docx-{secrets.token_hex(3)}"`（`os.makedirs(W)`），
  解壓縮的 `unpacked/`、JSON、腳本、逐頁圖片等中間檔都放在裡面（Python 裡
  `os.chdir(W)`，`subprocess` 傳 `cwd=W`）。每次 `run_python` 都是新的行程，
  把 W 的路徑印出來，之後每次執行都寫明同一個路徑。
  只有要交給使用者的成品（含給他預覽的 PDF）才存到工作資料夾的一般位置，
  並取一個不會和既有檔案撞名的檔名。`rm`、覆寫只能用在 W 裡的檔案；
  `uploads/` 裡的原檔只讀不改，要修改時先複製到 W；切換到 W 之後，上傳檔與
  成品都用絕對路徑（`/workspace/uploads/…`、`/workspace/成品.docx`）。
  完成後刪掉 W。
- 沙盒**沒有網路，也不能安裝套件**。`docx`（npm）、`pandoc`、LibreOffice、
  `pdftoppm` 都已經裝好，`require('docx')` 直接可用；萬一失敗，告訴使用者
  缺少什麼，不要嘗試 `npm install` 或 `pip install`。
- 這個 skill 的腳本在 `/opt/skills/docx/scripts/`（唯讀）。
- 每次 `run_python` 有時間上限（預設 60 秒），LibreOffice 轉檔比較慢，
  一次執行只做一件事。
- **你看不到圖片**（工具結果只有文字）。官方流程裡「轉成圖片再看」的步驟
  改成：用 `pandoc -t markdown` 檢查內容與結構、用 `validate.py` 檢查檔案；
  轉出來的 PDF 複製到工作資料夾的一般位置，網頁會顯示成檔案卡片，請使用者打開預覽確認
  版面。

.docx 是由 XML 檔案組成的 ZIP 壓縮檔。依工作選擇做法：

| 工作 | 做法 |
|---|---|
| **建立**新文件 | 寫一支 `docx`（npm）腳本，注意下面的陷阱 |
| **編輯**既有文件 | `unzip` → 編輯 `word/document.xml` → `zip`（docx-js 不能開啟既有檔案） |
| **讀取**內容 | `pandoc -t markdown file.docx` |

## 用 docx-js 建立文件的陷阱

`docx` 已經裝好，直接寫腳本 `require('docx')`。你熟悉它的 API，這些是容易
踩到的地方：

- **中文字型：** 這份文件會在使用者的 Word 開啟。內文英數用 Arial，中文用
  「微軟正黑體」：`font: { ascii: "Arial", hAnsi: "Arial", eastAsia:
  "Microsoft JhengHei" }`，在 `styles.default` 與每個標題層級都要設。這裡的
  LibreOffice 預覽會用 Noto CJK 代替，字寬略有不同，換行位置僅供參考。
- **頁面大小預設是 A4。** 要 US Letter 時設
  `page: { size: { width: 12240, height: 15840 } }`（單位 DXA；1440 = 1 英寸）。
- **橫向：** 傳入直向的寬高並設 `orientation: PageOrientation.LANDSCAPE`，
  docx-js 會自己對調寬高。
- **表格要設兩種寬度：** 表格的 `columnWidths` 與每個儲存格的 `width`，都用
  `WidthType.DXA`（PERCENTAGE 在 Google 文件會壞掉）。欄寬總和要等於表格寬度。
- **表格網底：** 用 `ShadingType.CLEAR`，不要用 `SOLID`（會變成全黑）。
- **清單：** 不要直接打 `•`，用 `numbering` 設定搭配 `LevelFormat.BULLET`。
- **`ImageRun` 一定要有 `type:`**（`"png"`、`"jpg"`……）。
- **`PageBreak` 要放在 `Paragraph` 裡。**
- **不要用 `\n`**，改用多個 `Paragraph`。
- **標題：** 每個用到的層級（`title`、`heading1`、`heading2`……）都要在
  `styles.default` 設定樣式：`heading1: { run: { font: "Arial", size: 32,
  bold: true }, paragraph: { spacing: { before: 240, after: 120 }, keepNext:
  true } }`。每個層級都要有自己的字型（即使已設文件預設字型）、`before` 與
  `after`（就算是 0）以及 `keepNext`：內建樣式這些都沒設。
- **目錄：** 標題要用內建的 `HeadingLevel.*`；自訂標題樣式要設
  `outlineLevel`，否則不會出現在目錄。
- **不要用表格當水平線**，改用段落的下框線。
- **點狀前導線／同一行靠右對齊：** 在 `TextRun` 裡用 `PositionalTab`
  （`alignment: PositionalTabAlignment.RIGHT`、`leader: PositionalTabLeader.DOT`），
  不要用一串 `.` 或空白湊。

## 檢查產出

寫好 `.docx` 之後轉成 PDF：

```bash
zip -d output.docx '*/' >/dev/null || true   # 拿掉 ZIP 裡的資料夾項目：透過雲端共同編輯服務開啟時，Word 曾拒絕有這些項目的檔案
python /opt/skills/docx/scripts/office/soffice.py --headless --convert-to pdf output.docx
pandoc -t markdown output.docx | head -200   # 檢查內容、標題層級、表格是否正確
```

需要逐頁圖片時（例如給使用者看縮圖）：`pdftoppm -jpeg -r 100 output.pdf page`，
頁碼會補零到頁數的位數（`page-01.jpg`……`page-12.jpg`）。你看不到這些圖片，
請使用者在網頁上預覽 PDF 確認版面。

## 編輯既有文件

舊版 `.doc` 要先轉檔：
`python /opt/skills/docx/scripts/office/soffice.py --headless --convert-to docx file.doc`。

```bash
unzip -q doc.docx -d unpacked/
find unpacked -type l -delete   # 刪掉符號連結：外部來的 docx 不可信任
python /opt/skills/docx/scripts/merge_runs.py unpacked/   # 合併被切碎的 run，文字才找得到
# 直接編輯 unpacked/word/document.xml，不要重新排版或美化縮排
(cd unpacked && rm -f ../out.docx && zip -XrD ../out.docx .)
python /opt/skills/docx/scripts/office/validate.py out.docx --original doc.docx   # XSD 檢查；--auto-repair 修正常見問題
# 追蹤修訂？加上 --author "<你修訂時用的名字>"，檢查每個修改都有追蹤
```

Word 會把文字拆成很多 `<w:r>` run（修訂編號、拼字檢查標記），所以文件裡
看得到的一句話，在 XML 裡常常不是連續的字串。`merge_runs.py` 會合併
`word/document.xml` 裡相鄰、格式相同的 run，不改變內容與呈現；也可以直接
處理 `.docx`（`python /opt/skills/docx/scripts/merge_runs.py doc.docx -o merged.docx`）。

**追蹤修訂：** 修訂時用 `--author "<你修訂時用的名字>"` 驗證（需要
`--original`），它會回報沒有包在 `<w:ins>`/`<w:del>` 裡的修改；這種錯誤很容易
發生，接受修訂後的畫面又看不出來。把 run 包在有 `w:id`、`w:author`、`w:date`
屬性的 `<w:ins>`/`<w:del>` 裡。`<w:del>` 裡的文字元素是 `<w:delText>`，不是
`<w:t>`。刪除段落標記（`<w:pPr><w:rPr><w:del w:id=".." w:author=".."
w:date=".."/></w:rPr></w:pPr>`）表示「把這段併到下一段」，所以要整段刪除，
就是這個再加上每個 run 外面包 `<w:del>`。`<w:del/>` 要放在 rPr 其他子元素
之前，順序由 schema 規定。

要產生接受所有修訂的乾淨版本：
`python /opt/skills/docx/scripts/accept_changes.py in.docx out.docx`。

接受被刪除的段落標記時，應該把那段併到下一段，所以 run **全部**被刪的段落會
消失。Word 會這樣做；`accept_changes.py` 與 `pandoc --track-changes=accept`
不一定。兩者的失敗方式相同：刪掉文字但留下空段落，如果原本有自動編號，看起來
就像多了一個空的項目符號：

- `pandoc --track-changes=accept` 一定不會合併段落。
- `accept_changes.py`（LibreOffice）會正確合併，除非被刪的段落後面接著一個
  空白的間隔段落。

在這兩種檢視裡看到空的項目符號，是檢視方式造成的，不是文件的問題。段落刪除
要看 XML 確認。

## 註解

註解需要六個互相連結的檔案，用輔助腳本處理。同時還要編輯 `document.xml`
時用資料夾模式（省一次解壓縮與壓縮），否則直接處理 `.docx`：

```bash
# 對已解壓縮的資料夾（同時要放錨點時建議用這個）
python /opt/skills/docx/scripts/comment.py unpacked/ "費用上限太低"
python /opt/skills/docx/scripts/comment.py unpacked/ "同意" --parent 0

# 直接對 .docx
python /opt/skills/docx/scripts/comment.py contract.docx "這個上限太低" -o annotated.docx
```

腳本會寫好 `comments.xml`、`commentsExtended.xml`、`commentsIds.xml`、
`commentsExtensible.xml`、關聯與內容類型。註解編號自動指定。接著它會印出要
加到 `word/document.xml` 的 `<w:commentRangeStart>`/`<w:commentRangeEnd>`/
`<w:commentReference>` 片段，讓註解錨定在特定文字上；放好這些標記之前，註解
存在但看不到。

## 相依套件

`docx`（npm，已裝好）· `pandoc` · LibreOffice（`soffice`）· `pdftoppm`（Poppler）
