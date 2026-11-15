---
# 改寫自 Anthropic 官方 skills 的 pptx（https://github.com/anthropics/skills
# ，commit 1780c5e），授權 Apache License 2.0，完整條款見 LICENSE.txt。
# 修改內容：說明翻成繁體中文；改成在 Agent Harness 的沙盒裡執行（腳本在
# /opt/skills/pptx/scripts/，沒有網路、不安裝套件）；補上中文字型的建議；
# 沒有看圖工具，視覺檢查改由使用者預覽。scripts/ 未修改。
name: pptx
description: 只要用到 .pptx 或 .potx 檔就使用，不論是輸入、產出或兩者：建立投影片、簡報、提案簡報；讀取、解析或擷取 .pptx 的文字（即使內容要用在別的地方，例如寫信或摘要）；編輯或更新既有簡報；合併或分割投影片；處理範本、版面配置、講者備忘稿或註解。使用者提到「簡報」「投影片」「deck」或某個 .pptx/.potx 檔名時都用。
license: Apache-2.0，完整條款見 LICENSE.txt
tools: [files]
---

# PPTX：建立、編輯與分析簡報

## 在這個環境怎麼執行

- **一律用 `run_python` 在沙盒裡執行。** 下面的 shell 指令（`node`、`zip`、
  `pdftoppm`……）也一樣：在 `run_python` 裡用
  `subprocess.run(..., capture_output=True, text=True)` 執行並印出 stdout、
  stderr；需要 `cd`、管線或 `rm` 時傳 `shell=True`，或用 `cwd=` 參數。不要用
  `run_command` 執行這些指令。
- 工作目錄是 `/workspace`（這段對話的工作資料夾）：使用者上傳的檔案在
  `uploads/`，產出的檔案存在 `/workspace` 底下，完成後告訴使用者檔名。
  pptxgenjs 腳本也寫在這裡（例如用 Python 寫出 `build_deck.js` 再執行
  `node build_deck.js`）。
- 沙盒**沒有網路，也不能安裝套件**。`pptxgenjs`、`react-icons`、`react`、
  `react-dom`、`sharp`（npm）與 `python-pptx`、`Pillow`、`defusedxml`、`lxml`
  （pip）、LibreOffice、`pdftoppm` 都已經裝好，直接 `require` 或 import；萬一
  失敗，告訴使用者缺少什麼，不要嘗試 `npm install` 或 `pip install`。
- 這個 skill 的腳本在 `/opt/skills/pptx/scripts/`（唯讀）。
- 每次 `run_python` 有時間上限（預設 60 秒），LibreOffice 轉檔比較慢，
  一次執行只做一件事。
- **你看不到圖片**（工具結果只有文字）。官方流程裡「看縮圖、看轉出來的
  投影片圖片」的步驟，改成下面〈品質檢查〉的文字檢查與版面計算；轉出來的
  PDF 留在工作資料夾，網頁會顯示成檔案卡片，請使用者打開預覽確認版面。

.pptx 是由 XML 檔案組成的 ZIP 壓縮檔。依工作選擇做法：

| 工作 | 做法 |
|---|---|
| **建立**新簡報 | 寫一支 `pptxgenjs` 腳本（注意下面的陷阱），除非使用者只要一份隨手用的草稿，否則做成[結構化簡報](#結構化簡報) |
| **編輯**既有簡報，或從範本製作 | 解壓縮 → 編輯 `ppt/slides/slideN.xml` → 壓縮 |
| **讀取**內容 | `python /opt/skills/pptx/scripts/slide_text.py deck.pptx`（每張投影片一段，以 `<!-- Slide number: N -->` 分隔）；縮圖總覽：`python /opt/skills/pptx/scripts/thumbnail.py deck.pptx`（給使用者看） |

## 腳本

都在 `/opt/skills/pptx/scripts/`。其他都是一般的 Python、`node` 或 shell。

| 腳本 | 用途 |
|---|---|
| `slide_text.py deck.pptx` | 以 markdown 輸出每張投影片的標題、文字、表格、圖表資料（散佈圖與泡泡圖只有數列名稱）、圖片替代文字與講者備忘稿。也能讀 `.potx` |
| `thumbnail.py deck.pptx [prefix]` | 每張投影片加上標籤排成一張總覽圖，用來挑範本的版面。只接受 `.pptx`。一定要傳 `prefix`：預設是 `thumbnails`，同一個資料夾裡處理其他簡報時會被覆蓋 |
| `add_slide.py unpacked/ slide2.xml [--after slideN.xml]` | 複製一張投影片（或 `slideLayoutN.xml`），並處理好所有套件的登記。也能用 `-o out.pptx` 直接處理 `.pptx` |
| `clean.py unpacked/` | 刪掉不再被參照的投影片、媒體與關聯。**`<p:sldIdLst>` 確定之後**才執行 |
| `apply_theme.js` | Node 模組：`const { applyTheme } = require("/opt/skills/pptx/scripts/apply_theme.js")`。在 `pres.writeFile()` 之後執行 `await applyTheme("deck.pptx", THEME)`，把 `THEME` 的顏色與名稱（會做 XML 跳脫）寫進簡報的佈景主題，給[結構化簡報](#結構化簡報)用。也可以當命令列工具：`node /opt/skills/pptx/scripts/apply_theme.js deck.pptx theme.json` |
| `office/validate.py deck.pptx [--original src.pptx]` | 檢查 schema、關聯、內容類型、圖表與投影片，每個錯誤都會說明怎麼修。從範本做的簡報一定要傳 `--original`：以範本為基準比對 schema 檢查，範本本身的 XSD 錯誤才不會被當成你造成的 |
| `office/soffice.py --headless --convert-to pdf deck.pptx` | LibreOffice 的包裝；直接執行 `soffice` 在沙盒裡會卡住 |

## 用 pptxgenjs 建立簡報的陷阱

`pptxgenjs` 已經裝好，直接寫腳本 `require('pptxgenjs')`。你熟悉它的 API，
這些是容易踩到的地方：

- **先設 `pres.layout` 再加投影片。** 預設的 `LAYOUT_16x9` 是
  **10 × 5.625 英寸**，不是 13.3 英寸寬。超出邊界的座標照樣寫入、不會被
  夾回來，只是形狀不在投影片上。（`LAYOUT_WIDE` 是 13.3 × 7.5 英寸。）
- **色碼不要加 `#`，也不要 8 位數。** `color: "FF0000"`。`"#FF0000"` 與把
  透明度寫進色碼（`"00000020"`）都會**讓檔案損毀**。要半透明時：填滿與圖片用
  `transparency: 0-100`，陰影用 `opacity: 0.0-1.0`，用錯地方會被默默忽略。
- **pptxgenjs 會直接修改傳入的選項物件**（第一次使用時換算成 EMU）。不要讓
  兩次 `add*` 呼叫共用同一個 `shadow` 或選項物件，每次都建新的。
- **陰影的 `offset` 必須 ≥ 0**，負值會讓檔案損毀。要讓陰影往上，用
  `angle: 270` 搭配正的 offset。
- **`letterSpacing` 會被默默忽略**，正確的選項是 `charSpacing`。
- **清單：** 每個項目設 `bullet: true`，不要直接打 `•`（會出現兩個符號）。
  陣列裡除了最後一項，每項都設 `breakLine: true`。項目間距用
  `paraSpaceAfter`，不要用 `lineSpacing`（間距會變很大）。
- **每個輸出檔案用一個 `new pptxgen()`**，不要重複使用同一個實例。
- **`rectRadius` 只對 `ROUNDED_RECTANGLE` 有效**，`RECTANGLE` 沒有作用。
- **不支援漸層填滿**，改用漸層圖片當背景。
- **每個沒有 `placeholder` 的 `addText` 都要加 `isTextBox: true`**：沒加的話
  形狀少了 `txBox="1"`，螢幕閱讀器會把文字唸成「圖形」而不是文字方塊。
  畫面上看不出差別。
- **文字方塊有內建的內距**：文字要和同一個 x 的形狀、線條或圖示對齊時，設
  `margin: 0`。
- **講者備忘稿用 `slide.addNotes("...")`**（純文字，每張一次），不要放在投影片
  上的文字方塊。
- **圖表用原生的。** PowerPoint 畫得出來的都用 `addChart()`（組合圖傳
  `{type, data, options}` 的陣列）。函式庫沒提供的 PowerPoint 原生功能（趨勢線、
  誤差線），自己算出額外的數列，或後製產生的 OOXML，不要改用圖片。只有
  PowerPoint 沒有原生形式的圖表（Sankey、網路圖、和弦圖）才用圖片。
- **預設的圖表很陽春**：沒有標題、沒有資料標籤、配色老舊。設 `showTitle` +
  `title`、`showValue: true` + `dataLabelPosition`、用你的配色設
  `chartColors: [...]`，並淡化框線（`catAxisLabelColor`/`valAxisLabelColor`、
  `valGridLine: { color, size }`、`catGridLine: { style: "none" }`，只有一個數列時
  `showLegend: false`）。
- **堆疊長條圖或直條圖的 `dataLabelPosition` 只能是 `ctr`、`inEnd` 或
  `inBase`。** `outEnd` 會**讓檔案損毀**。
- **組合圖的數列用到 `secondaryValAxis`/`secondaryCatAxis` 時，圖表選項要同時
  有 `valAxes` 與 `catAxes`，各兩個。** 少了的話 pptxgenjs 會寫入沒有宣告的
  座標軸編號，PowerPoint 會**丟掉那張圖表**並說檔案損毀。只給 `valAxes`
  不夠。
- **`writeFile()` 之後執行
  `python /opt/skills/pptx/scripts/office/validate.py deck.pptx`。** 它會回報
  許多 PowerPoint 拒絕或要修復的圖表與投影片 XML 問題（包括上面兩個），並
  說明怎麼修。在產生腳本裡修，不要手改打包好的 XML。
- **不要調整 `<p:presentation>` 子元素的順序。** pptxgenjs 把
  `<p:notesMasterIdLst>` 寫在 `<p:sldIdLst>` 後面，並讓兩個母片指向同一個
  佈景主題。PowerPoint 讀得了；移動那個元素，同一份簡報就打不開了。
- **圖示：** 用 `ReactDOMServer.renderToStaticMarkup` 把 `react-icons` 轉成
  SVG，用 `sharp` 轉成至少 256px 的點陣圖，再用
  `addImage({ data: "image/png;base64," + buf.toString("base64") })` 插入；
  `image/png;base64,` 前綴一定要有（`react-icons`、`react`、`react-dom`、`sharp`
  都已經裝好）。
- **`defineSlideMaster()` 建立的是投影片「版面配置」，不是母片**：每次呼叫
  產生一個 `slideLayoutN.xml`，都在同一個你改不了的母片底下。跟使用者說明時
  稱為版面配置。
- **`pres.company` 與 `defineSlideMaster()` 的 `title` 寫進 XML 時不會跳脫**：
  其中有 `&`（`"Harrow & Sons"`）會讓 `docProps/app.xml` 或版面配置無法解析，
  `validate.py` 會失敗。那裡要寫 `&amp;`，對應的 `masterName` 也一樣。`title`、
  `subject`、`author`、章節標題、`objectName`、備忘稿與投影片文字會自動跳脫。

### 結構化簡報

以佈景主題、版面配置、版面配置區（placeholder）與章節做成的簡報，可以在
一個地方改樣式，在 PowerPoint 裡編輯也順手。除非使用者只要隨手用的草稿，
每份新簡報都這樣做。

1. **先定佈景主題：** `const THEME = { name, headFontFace, bodyFontFace,
   colors: { dk1, lt1, dk2, lt2, accent1 … accent6, hlink, folHlink } }`，顏色用
   色碼。`pres.theme` 只接受兩個字型。之後不要再指定字型（標題用標題字型，
   其他用內文字型），只有圖表文字例外：圖表文字寫死成 Arial，要在它的
   `*FontFace` 選項寫 `"+mn-lt"`（佈景主題的內文字型；`"+mj-lt"` 是標題字型）。
2. **所有顏色都用 `const C = pres.SchemeColor`**：`C.text1`/`C.text2` 是
   `dk1`/`dk2`，`C.background1`/`C.background2` 是 `lt1`/`lt2`。下面這些只接受
   色碼，從 `THEME` 取值：`valGridLine.color`、`catGridLine.color`、
   `shadow.color`，以及單一數列長條圖的 `invertedColors` 或多於一個的
   `chartColors`。在這些地方用配色名稱會被寫成 `<a:srgbClr val="bg2"/>` 而
   不報錯；而且因為是色碼，之後換佈景主題時它們不會跟著變。
3. **章節：** 在每個章節的第一張投影片前呼叫 `pres.addSection({ title })`，
   每次 `addSlide` 都帶 `sectionTitle`。沒帶的投影片（或章節一次全部宣告時，
   表格自動分頁產生的接續投影片）會落到多出來的「Default-N」章節。
4. **每種投影片框架一個版面配置**（`defineSlideMaster()`）：標題、章節分隔、
   只有標題、圖表加說明、表格；設計有深淺交替時各做一個版本。文字區域是
   有名稱的版面配置區，帶有位置、大小、粗細與 `color`；圖表、圖片與表格的
   版面配置區也要有 `color`，否則提示文字與多段文字會被寫死成 `000000`。
   頁尾文字、標誌與 `slideNumber` 放在版面配置上，不要放在投影片上。
5. **依名稱填入：** `addSlide({ masterName, sectionTitle })`，再用
   `addText("…", { placeholder: "title" })`，不給位置、大小或顏色：以版面配置區
   自己的設定為準，它沒設定的（斜體、`align`、`fontFace`）照樣套用；要單獨
   設定某段文字用 `[{ text, options }]`。`placeholder` 或 `masterName` 拼錯
   不會報錯（會在 0,0 出現多餘的文字方塊，或用到空白版面配置）。只有
   `title`、`body` 與 `chart` 版面配置區可以只靠名稱填入：
   `addImage({ placeholder })` 只取版面配置區的 x、y，不取大小（會變成 1 × 1
   英寸），要另外傳 `w`/`h`。`addTable({ placeholder })` 只取 x、y，一定要傳
   `w`；它自動分頁時會忽略版面配置區而超出投影片，所以也要傳 `x`、`y` 與
   `autoPageSlideStartY`（和 `y` 相同，否則接續頁從上邊界開始排），版面配置
   要有底部避開頁尾的 `margin`，接續投影片的標題用 `slide.newAutoPagedSlides`
   填入。
6. **版面配置是框架，不是「設計構想」說的版面。** 卡片、圖示、數字重點與
   圖片仍然要一張一張疊在上面，用配色顏色，每個都設 `objectName`；所有
   設計構想都適用，大部分內容投影片用「只有標題」的版面配置。
7. **先寫檔再套佈景主題：** `await pres.writeFile({ fileName: "deck.pptx" })`，
   再 `await applyTheme("deck.pptx", THEME)`。pptxgenjs 寫不了佈景主題的顏色：
   套用之前，配色顏色都會變成 Office 的預設色盤。在只接受色碼的選項用了
   配色名稱時，它會丟出錯誤且不做任何修改；修正它指出的地方再重新產生。

## 編輯既有簡報與範本

先挑版面配置：用 `slide_text.py` 讀出每張投影片的內容與版面名稱，把每段內容
對應到一張範本投影片，並變化版面，不要每段都用同一種「標題加項目」投影片。
`python /opt/skills/pptx/scripts/thumbnail.py template.pptx template-thumbs`
會產生加上標籤的總覽圖（超過 12 張時分成 `template-thumbs-N.jpg`），你看不到
它，但可以請使用者看圖指定要用哪幾張。**一定要傳第二個參數**，用簡報命名：
預設的 `thumbnails` 會讓同一個資料夾裡的兩份簡報互相覆蓋。（它只接受
`.pptx`，`.potx` 先複製成 `.pptx` 檔名。）

```bash
python3 -c "import sys,zipfile; zipfile.ZipFile(sys.argv[1]).extractall('unpacked')" deck.pptx
python /opt/skills/pptx/scripts/add_slide.py unpacked/ slide2.xml --after slide2.xml   # 複製一張投影片（或 slideLayoutN.xml），會印出新投影片的路徑
# 調整順序或刪除投影片 = 編輯 ppt/presentation.xml 的 <p:sldIdLst>
python /opt/skills/pptx/scripts/clean.py unpacked/                                     # 刪除後執行：移除沒人參照的投影片、媒體與關聯
# 編輯 ppt/slides/slideN.xml 的內容
(cd unpacked && rm -f ../out.pptx && zip -XrD ../out.pptx .)          # 在資料夾**裡面**壓縮；先 rm，否則刪掉的部分會殘留
python /opt/skills/pptx/scripts/office/validate.py out.pptx --original deck.pptx
```

- **所有結構性的工作（新增、刪除、調整順序）都在編輯內容之前完成。**
  `add_slide.py` 原樣複製投影片檔案，編輯後再複製會連內容一起複製；而且
  `clean.py` 會刪掉不在 `<p:sldIdLst>` 裡的投影片，包括你剛寫好的。
- **不要手動複製投影片檔案**：`add_slide.py` 會做好新投影片需要的所有登記，
  並回報做了什麼（`Created ppt/slides/slide17.xml from slide2.xml`）。它也能
  直接處理檔案：`add_slide.py deck.pptx slide2.xml -o out.pptx`，**要傳 `-o`，
  否則會直接改寫輸入的簡報**。複製出來的投影片仍然*參照*原投影片的圖表、
  SmartArt 與內嵌物件，不會另外複製，所以改一張的圖表另一張也會變。
- **用 `python-pptx` 時**，有三件事它做不到：複製投影片（只能
  `add_slide(layout)`）、用 `text_frame.text = "..."` 保留格式（會把段落壓成
  一個沒有樣式的 run，改成設定 `run.text`）、讀取大部分範本圖案用的 SVG/EMF
  （`add_picture` 會丟出 `UnidentifiedImageError`）。
- 舊版 `.ppt` 要先轉檔：
  `python /opt/skills/pptx/scripts/office/soffice.py --headless --convert-to pptx file.ppt`。
  `.potx` 範本的解壓縮與打包方式相同，產出時保留 `.potx` 副檔名。
- 要重複使用範本裡的圖示或圖片，複製已經有它的投影片或版面配置。

套用範本時：

- 用程式轉換 XML 時，用 `defusedxml.minidom` 解析；用 `xml.etree.ElementTree`
  讀寫 OOXML 會改寫命名空間前綴，讓簡報損毀。
- **範本的格數 ≠ 資料的項目數。** 範本有 4 位成員而你只有 3 位時，刪掉第 4
  位的整個群組（圖片 + 文字方塊），不是只清掉文字，再檢查有沒有殘留的圖案。
- 每個清單項目一個 `<a:p>`，不要把多個項目接在同一段。複製同層的 `<a:pPr>`
  保留間距，標題、章節標題與行內標籤（`狀態：`、`負責人：`）的 `<a:rPr>` 加
  `b="1"`。
- 項目符號沿用版面配置；只有要改的時候才加 `<a:buChar>`、`<a:buAutoNum>`
  （編號）或 `<a:buNone>`，不要在文字裡直接打 `•`。
- 開頭或結尾有空白的文字，`<a:t>` 要加 `xml:space="preserve"`。

## 內容與脈絡

- **一張投影片一個訊息。** 簡報依主題、依訊息推進。
- **常見的結構是金字塔：** 先講主要訊息，接著是預告各章節的摘要，然後是
  各章節，最後是結論，通常附上依結論行動的下一步。
- **結構配合簡報長度。** 短簡報可能不需要前言與結論；長簡報可能需要主題
  之間的分隔頁。
- **朝簡報的目的推進：** 做決定、取得共識、慶祝、解決歧見，或開啟討論。
- **配合使用方式。** 現場簡報有人講解，可能還有討論；會前閱讀的簡報要自己
  說完整個故事。現場的主管簡報字要少、要很視覺化。給專家看或離線閱讀時，
  細節多、字多的投影片有時是對的。分析報告以圖表與表格為主。
- **現場簡報的張數配合時間：** 每張大約 1.5～2 分鐘，有問答時要預留時間。

## 設計構想

**不要做無聊的投影片。** 白底加項目符號打動不了任何人。每張投影片都考慮
下面的構想。

### 開始之前

- **依內容選一組鮮明的配色**：配色要像是為這個主題設計的。如果把你的配色
  換到完全不同的簡報上也一樣「可以」，就表示選得不夠具體。使用者或公司有
  品牌色時用品牌色。
- **主從分明**：一個顏色佔主導（60–70% 的視覺比重），搭配 1～2 個輔助色與
  一個鮮明的強調色。不要讓每個顏色比重相同。
- **深淺對比**：標題與結論頁用深色背景，內容頁用淺色（「三明治」結構）；
  或整份都用深色，營造質感。
- **選定一個視覺主題元素**：挑一個有辨識度的元素並重複使用，例如圓角的圖片
  框、放在彩色圓形裡的圖示，每張投影片都用。**不要用色條或強調線當主題元素**
  （見〈避免〉）。

### 配色

依主題選色，不要預設用藍色。這些配色可以當靈感：

| 主題 | 主色 | 輔助色 | 強調色 |
|-------|---------|-----------|--------|
| **Midnight Executive** | `1E2761`（海軍藍） | `CADCFC`（冰藍） | `FFFFFF`（白） |
| **Forest & Moss** | `2C5F2D`（森林綠） | `97BC62`（苔綠） | `F5F5F5`（米白） |
| **Coral Energy** | `F96167`（珊瑚紅） | `F9E795`（金黃） | `2F3C7E`（海軍藍） |
| **Warm Terracotta** | `B85042`（陶土） | `E7E8D1`（沙色） | `A7BEAE`（鼠尾草綠） |
| **Ocean Gradient** | `065A82`（深藍） | `1C7293`（藍綠） | `21295C`（午夜藍） |
| **Charcoal Minimal** | `36454F`（炭灰） | `F2F2F2`（灰白） | `212121`（黑） |
| **Teal Trust** | `028090`（藍綠） | `00A896`（海沫綠） | `02C39A`（薄荷綠） |
| **Berry & Cream** | `6D2E46`（莓紅） | `A26769`（灰玫瑰） | `ECE2D0`（奶油色） |
| **Sage Calm** | `84B59F`（鼠尾草綠） | `69A297`（尤加利） | `50808E`（石板藍） |
| **Cherry Bold** | `990011`（櫻桃紅） | `FCF6F5`（灰白） | `2F3C7E`（海軍藍） |

### 每張投影片

**每張投影片都要有視覺元素**：圖片、圖表、圖示或形狀。只有文字的投影片
沒人記得。

**版面選擇：**
- 兩欄（左邊文字，右邊圖）
- 圖示加文字的列（圖示放在彩色圓形裡，粗體標題，下面說明）
- 2×2 或 2×3 方格（一邊圖片，另一邊內容區塊）
- 半版出血的圖片（整個左半或右半），內容疊在上面

**資料呈現：**
- 大數字重點（60–72pt 的數字，下方小標籤）
- 比較欄（前後、優缺點、並列選項）
- 時間軸或流程（編號步驟、箭頭）

**視覺修飾：**
- 章節標題旁放在小彩色圓形裡的圖示
- 關鍵數字或標語用斜體強調

### 字型

**你寫進 .pptx 的字型由使用者的 PowerPoint 繪製，不是這個環境。** 這裡的
預覽用 LibreOffice 轉檔，它會替換沒有的字型，有些替代字型的字寬不同，所以
預覽可能顯示實際簡報不會有的文字溢出（或反過來）。為了讓檢查可信：

- **中文：** 用「微軟正黑體」（`Microsoft JhengHei`）。這裡的預覽會用 Noto
  Sans CJK 代替，字寬接近但不完全相同，中文文字框要多留約 10% 的空間。
- **安全字型**（預覽的字寬正確，Office 也都有）：**Arial、Calibri、Cambria、
  Times New Roman、Courier New、Bookman Old Style、Century Schoolbook**。內文與
  任何需要精準排版的地方用這些。
- **有個性又零風險的標題**：安全清單裡的襯線字（Cambria、Bookman Old Style、
  Century Schoolbook）當標題，搭配安全清單的無襯線字（Calibri 或 Arial）當
  內文，有對比又不影響溢出檢查。
- **使用者指定安全清單以外的字型**（例如 Georgia 或 Trebuchet MS）：在他指定
  的地方使用，但文字框多留約 10% 的空間，那些元素的預覽排版不要盡信。使用者
  沒指定時，內文優先用安全字型。
- **預覽不可靠的字型**（替代字型字寬不同，溢出檢查可能出錯）：Georgia、
  Trebuchet MS、Impact、Arial Black、Garamond、Consolas、Palatino Linotype。
  Calibri Light 的替代結果因環境而異，也視為不可靠。用在標題或強調可以，但要
  留空間，不要相信預覽的排版。
- **不要預設用 Aptos**：Office 2023 之後的預設字型，這裡沒有字寬相容的替代
  字型，較舊的 Office 也沒有，兩頭都不可靠。

| 元素 | 大小 |
|---------|------|
| 投影片標題 | 36–44pt 粗體 |
| 章節標題 | 20–24pt 粗體 |
| 內文 | 14–16pt |
| 說明文字 | 10–12pt 淡色 |

### 間距

- 邊界至少 0.5 英寸
- 內容區塊之間 0.3～0.5 英寸
- 留白，不要塞滿每一寸

### 避免（常見錯誤）

- **不要重複同一種版面**：變化欄數、卡片與重點數字
- **投影片標題結尾不要加句號**
- **同類投影片的標題位置不要飄移**：標題在上方的內容頁，每張的位置、字型、
  大小與對齊都要相同；不同類型的投影片（標題在中間的章節分隔頁）可以不同
- **圖表標籤的樣式不要每張都不一樣**：整份簡報所有圖表的座標軸與資料標籤
  用相同的顏色、字型與大小；只有圖表需要時才改（第二座標軸、強調的數列、
  在深色長條上的標籤）
- **內文不要置中**：段落與清單靠左，只有標題置中
- **大小對比要夠**：標題 36pt 以上，才能和 14–16pt 的內文區分
- **不要預設用藍色**：選反映主題的顏色
- **間距不要隨意混用**：選定 0.3 或 0.5 英寸並一致使用
- **不要只設計一張而其他維持陽春**：要嘛全部做到，要嘛整份保持簡單
- **不要做只有文字的投影片**：加圖片、圖示、圖表或視覺元素；避免單純的標題
  加項目
- **別忘了文字方塊的內距**：要讓線條或形狀對齊文字邊緣時，文字方塊設
  `margin: 0`，或把形狀位移以抵銷內距
- **不要用低對比的元素**：圖示**和**文字都要和背景有強烈對比；避免淺底淺字
  或深底深字
- **絕對不要在標題下面加強調線**：這是 AI 產生投影片的典型特徵；改用留白或
  背景色
- **絕對不要加裝飾用的色條或強調條**：包括橫跨投影片寬度的頁首／頁尾色條、
  沿著投影片一側的直條、卡片或內容區塊一側的細強調條，以及「只有一邊框線」
  的矩形。這些看起來像 AI 產生的填充物。要突顯卡片，用淡淡的底色、陰影或
  圖示，不要用邊條。
- **不要預設用米色／奶油色背景**：沒指定背景時用白色（`FFFFFF`）或使用者的
  品牌色；避免 `F5F5DC`、`FAF0E6`、`FAEBD7`、`FFF8E1` 這類暖中性色
- **不要交出文字溢出形狀的簡報**：放不下時縮小字級、拆成多張或加大文字框；
  不要讓內容被截斷或超出邊界。**你建立的簡報不要縮到比字型表更小**（內文
  14pt、說明 10pt）；到了下限就刪字、加大文字框或拆張。編輯既有簡報或範本
  時，照它原本的大小

## 品質檢查（必做）

第一次產出通常會有幾個真正的問題：重疊、溢出、沒對齊。找出來修好，只重新
檢查改過的投影片，然後停止。

### 內容檢查（必做）

```bash
python /opt/skills/pptx/scripts/slide_text.py output.pptx
```

檢查有沒有漏掉內容、錯字、順序錯誤。

**用範本時，檢查有沒有殘留的範本文字：**

```bash
python /opt/skills/pptx/scripts/slide_text.py output.pptx | grep -iE "\bx{3,}\b|lorem|ipsum|\bTODO|\[insert|this.*(page|slide).*layout"
```

有找到就先修好，才能說完成。

### 檔案檢查（必做）

```bash
python /opt/skills/pptx/scripts/office/validate.py output.pptx                      # 從頭建立的
python /opt/skills/pptx/scripts/office/validate.py output.pptx --original src.pptx  # 從範本做的
```

**從範本做的簡報一定要傳 `--original`。** 範本本身可能就有 XSD 不接受的部分，
不傳的話會回報不是你造成的錯誤，真正的退步也可能混在裡面。`--original` 以
範本為基準比對 schema 與投影片檢查，排除範本原本就有的錯誤。結構檢查（關聯、
內容類型、圖表）不看 `--original`，範本帶來的問題也照樣回報，要個別判斷。

pptxgenjs 會產生 PowerPoint 拒絕開啟、其他工具卻都接受的圖表 XML：
python-pptx 打得開、LibreOffice 畫得出來、XSD 也通過。每個錯誤都會說明怎麼
修。在產生腳本裡修好再重新產生。

**通過不代表檔案一定沒問題：** `validate.py` 抓不到所有 PowerPoint 會修復的
問題（圖表元素重複超過上限會通過）；從範本投影片刪掉有動畫的形狀時，也要
刪掉那張投影片的 `<p:timing>` 元素（動畫一起刪），否則 PowerPoint 會要求修復。

### 版面檢查（必做）

你看不到投影片的圖片，所以用兩種方式補上：

1. **自己檢查座標。** 產生腳本裡的每個形狀都有 x、y、w、h，寫一小段程式
   （或用 python-pptx 讀回 `output.pptx`）檢查：有沒有超出投影片邊界、
   離邊界小於 0.5 英寸、元素互相重疊或間距小於 0.3 英寸、同類投影片的標題
   位置不一致。估算文字是否放得下：中文字寬約等於字級，英數約 0.5 倍字級，
   行高約 1.2 倍字級。
2. **請使用者看預覽。** 轉成 PDF（見下一節）留在工作資料夾，告訴使用者檔名，
   請他打開預覽並特別留意：文字溢出或被截斷、元素重疊、頁尾和上方內容
   相撞、對比不足、同類投影片的標題高低不一、殘留的範本內容。

## 轉成 PDF 與圖片

```bash
python /opt/skills/pptx/scripts/office/soffice.py --headless --convert-to pdf output.pptx
rm -f slide-*.jpg
pdftoppm -jpeg -r 150 output.pdf slide
ls -1 "$PWD"/slide-*.jpg
```

`rm` 會清掉上次留下的圖片。`pdftoppm` 依頁數補零：不到 10 頁是
`slide-1.jpg`，10–99 頁是 `slide-01.jpg`，100 頁以上是 `slide-001.jpg`。圖片
給使用者看；你只要確認檔案有產生。

**修改之後四個指令都要重跑**：PDF 要從改過的 `.pptx` 重新產生，`pdftoppm`
才會反映修改。

## 相依套件

`pptxgenjs`（npm，已裝好）· `python-pptx`、`Pillow`、`defusedxml`、`lxml`
（pip，slide_text、thumbnail、clean、validate 會用到）· LibreOffice（`soffice`，
由 `/opt/skills/pptx/scripts/office/soffice.py` 自動設定）· `pdftoppm`（Poppler）
