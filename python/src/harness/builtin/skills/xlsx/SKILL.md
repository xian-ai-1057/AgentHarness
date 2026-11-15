---
# 改寫自 Anthropic 官方 skills 的 xlsx（https://github.com/anthropics/skills
# ，commit 1780c5e），授權 Apache License 2.0，完整條款見 LICENSE.txt。
# 修改內容：說明翻成繁體中文；改成在 Agent Harness 的沙盒裡執行（腳本在
# /opt/skills/xlsx/scripts/，沒有網路、不安裝套件）。scripts/ 未修改。
name: xlsx
description: 試算表檔案是主要的輸入或產出時使用：開啟、讀取、編輯或修正 .xlsx、.xlsm、.xltx、.csv、.tsv（加欄位、寫公式、格式、圖表、清理凌亂資料），從頭建立試算表，或在表格格式之間轉換。使用者提到某個試算表檔案並要對它做事時一定要用。產出不是試算表（例如 Word、HTML 報告、單純的 Python 程式）時不要用。
license: Apache-2.0，完整條款見 LICENSE.txt
tools: [files]
---

# XLSX：建立、編輯與分析試算表

## 在這個環境怎麼執行

- **一律用 `run_python` 在沙盒裡執行。** 下面的 shell 指令也一樣：在
  `run_python` 裡用 `subprocess.run([...], capture_output=True, text=True)`
  執行，並把 stdout、stderr 印出來。不要用 `run_command` 執行這些指令。
- 工作目錄是 `/workspace`（這段對話的工作資料夾）：使用者上傳的檔案在
  `uploads/`，產出的檔案存在 `/workspace` 底下，完成後告訴使用者檔名。
- **中間檔放在這次工作專用的資料夾，不要動別人的檔案。** 同一個人的
  其他對話可能同時在用這個工作資料夾。開始時先建一個專用資料夾，例如
  `W = f".skill-work/xlsx-{secrets.token_hex(3)}"`（`os.makedirs(W)`），
  解壓縮的 `unpacked/`、JSON、腳本、逐頁圖片等中間檔都放在裡面（Python 裡
  `os.chdir(W)`，`subprocess` 傳 `cwd=W`）。每次 `run_python` 都是新的行程，
  把 W 的路徑印出來，之後每次執行都寫明同一個路徑。
  只有要交給使用者的成品（含給他預覽的 PDF）才存到工作資料夾的一般位置，
  並取一個不會和既有檔案撞名的檔名。`rm`、覆寫只能用在 W 裡的檔案；
  `uploads/` 裡的原檔只讀不改，要修改時先複製到 W；切換到 W 之後，上傳檔與
  成品都用絕對路徑（`/workspace/uploads/…`、`/workspace/成品.docx`）。
  完成後刪掉 W。
- 沙盒**沒有網路，也不能安裝套件**。`openpyxl`、`pandas`、`markitdown`
  與 LibreOffice 都已經裝好，直接 import 或執行；萬一 import 失敗，告訴
  使用者缺少哪個套件，不要嘗試 `pip install`。
- 這個 skill 的腳本在 `/opt/skills/xlsx/scripts/`（唯讀）。
- 每次 `run_python` 有時間上限（預設 60 秒），LibreOffice 重算比較慢，
  一次執行只做一件事。

| 工作 | 做法 |
|---|---|
| 用公式、格式**建立**或**編輯** | `openpyxl`，注意下面的陷阱 |
| 大量資料讀入或寫出 | `pandas`（`read_excel`、`to_excel`） |
| **快速看一下**工作表內容 | `markitdown file.xlsx`：每張工作表一個 `## 工作表名稱`，也能讀 `.xlsm`。沒有儲存格座標，不要依它規劃修改 |
| **讀取**模型（公式**和**數值） | `load_workbook` 讀兩次，見下面的陷阱 |

## 每份產出都要做到

- **專業字型**：英數用 Arial 或 Times New Roman；中文用「微軟正黑體」
  （`Microsoft JhengHei`）。使用者另有指定時照他的。
- **零公式錯誤。** `recalc.py` 回報 `errors_found` 時不能交付；唯一的例外
  見下面的 `not_computed`。認為某個錯誤原本就存在時要證明：用
  `data_only=True` 載入**原始檔**看那一格。你造成的錯誤和原本就有的錯誤
  看起來一模一樣。
- **用公式，不要寫死計算結果。** 寫 `sheet['B10'] = '=SUM(B2:B9)'`，不要
  寫 Python 算好的總和。輸入改變時試算表要能重算。
- **照使用者的規格做。** 工作表名稱、欄位標題、他寫出來的公式都要一字
  不差。重新設計成算別的東西，就算再漂亮也是失敗。
- **每個假設與寫死的數字都要註明**，放在讀者看得到的地方：儲存格註解，
  或表格最後旁邊的儲存格。有真實出處就寫出處（`來源：公司 2024 年報第
  45 頁營收附註`）；數字來自使用者就直接寫明。
- **你建立給別人填的活頁簿**要有簡短的圖例，說明哪些儲存格要填，並附一列
  格式正確的範例資料。要你修改的既有檔案**不要**加這種範例列。
- **編輯既有檔案時完全照它的慣例。** 它的慣例優先於這裡的所有建議。先找出
  它指定的輸入儲存格（不同的字色、填滿或網底），只寫在那裡，既有的公式
  一個都不要動。

## 重算（檔案有公式時一定要做）

openpyxl 把公式當字串寫入，**沒有快取值**。重算之前，任何讀快取值的工具
（`pandas`、`load_workbook(data_only=True)` 與大部分預覽）讀到的公式儲存格
都是 `None`。

```bash
python /opt/skills/xlsx/scripts/recalc.py output.xlsx [逾時秒數]   # 預設 30
```

LibreOffice 在**副本**上計算公式，只把數值寫回你的檔案，並輸出 JSON：
`status`（`success` | `errors_found`）、`total_formulas`、`total_errors`，以及
`error_summary`（每種錯誤最多列 100 個儲存格；`locations_truncated` 說明還有
幾個沒列出，以 `total_errors` 為準，不要數清單長度）。修正它列出的問題後
再跑一次。**輸出的 JSON 有 `error` 鍵而沒有 `status`，表示根本沒有重算**，
而且只有這種情況結束代碼不是 0；`errors_found` 的結束代碼也是 0，所以
不能把正常結束當成活頁簿沒問題。

**重算沒有錯誤只代表公式算得出來，不代表算得對。** 範圍差一格或參照錯列，
一樣會得到沒有錯誤但數字錯的檔案。先寫 2～3 個公式，確認取到預期的值，
再擴展成整個表格。

**`not_computed` 列出 LibreOffice 算不了的公式，`success` 時也會有**：它沒有
的函數（`_xlfn.XLOOKUP`、`_xlfn.LET`……）或連到其他活頁簿
（`='[1]Returns Analysis'!$B$2`）。這些儲存格保留原本的值：openpyxl 存檔後
就沒有值，直到用 Excel 開啟。想先拿到它們的數字，用 `data_only=True` 讀
原始檔，公式照樣保留。直接或間接依賴它們的正確公式也會回報 `#NAME?`：
不要改，告訴使用者。檢查它們的儲存格（`IFERROR(B1,0)`）會拿到 LibreOffice
的替代值，保留的值也可能過時，要說明。直接改工作表 XML 之後，刪掉每個
改過的公式的 `<v>`：保留舊值的錯誤只會被列出，不會被回報。

## 選擇經得起驗證的公式

LibreOffice 支援的函數比 Excel 少，算不了的公式要到 Excel 開啟才有值。

- **優先用 Excel 2007 就有的函數**：`SUMIFS`、`INDEX`、`MATCH`、`IFERROR`、
  `SUMPRODUCT`，不需要前綴。
- **有六個 2007 之後的函數可以用，但要加 `_xlfn.` 前綴**，因為 openpyxl
  會原樣寫入公式，而 Excel 儲存新函數時有前綴（介面上看不到）：
  `_xlfn.TEXTJOIN`、`_xlfn.CONCAT`、`_xlfn.IFS`、`_xlfn.SWITCH`、
  `_xlfn.MAXIFS`、`_xlfn.MINIFS`。沒加前綴會變成 `#NAME?`。
- **不要用 `XLOOKUP`、`XMATCH`、`SORT`、`FILTER`、`UNIQUE`、`SEQUENCE`。**
  這裡的 LibreOffice 算不了；就算算得了，也只會填左上角一格，因為 openpyxl
  寫的檔案沒有溢出（spill）資訊。查找用 `INDEX`/`MATCH`，排序、篩選、去除
  重複在 Python 裡做完再寫入。
- 少一個 `)` 會回報 `unbalanced brackets`。參數太少（`=ROUND(A1)`）不會：
  LibreOffice 照樣算出值，Excel 卻可能要求修復檔案。

## openpyxl 的陷阱

- **讀模型要載入兩次。** `data_only=True` 拿到快取值但沒有公式；預設拿到
  公式字串但沒有值。一次拿不到兩者。
- **用 `data_only=True` 載入後存檔會毀掉公式。** 那個活頁簿已經沒有公式，
  存檔會把每個公式永久換成數值。
- **openpyxl 剛寫好的檔案用 `data_only=True` 讀，全部都是 `None`**，先跑
  `recalc.py`。（結果是 `""` 的公式讀回來也是 `None`。）
- **合併儲存格只寫左上角。** 範圍裡其他儲存格是 `MergedCell`，`.value`
  唯讀。
- **`.xlsm` 要在 `load_workbook` 傳 `keep_vba=True`**，否則巨集會不見。
- **工作表名稱有空白時，跨表參照要加引號**：`='Assumptions Inputs'!$B$5`。
  沒加會得到 `#VALUE!`。
- **存檔會弄丟上傳檔案裡的文字方塊、圖案與交叉分析篩選器。** 先在
  `xl/drawings/` 搜尋 `<xdr:sp `（含空白），並看有沒有 `xl/slicers/`；有的話
  告訴使用者，或改成直接編輯工作表 XML。
- **格式錯誤的活頁簿沒有東西會幫你修**：數字格式裡沒關的引號
  （`'0.00 "USD'`）、以 `=` 開頭的名稱定義、重複或空白的表格標題都會原樣
  存檔，Excel 可能要求修復。
- **部分粗體或斜體的儲存格文字會被攤平**，除非用
  `load_workbook(rich_text=True)`；這時 `.value` 是 `CellRichText`，不是
  `str`。
- **每個新公式都要設 `number_format`**（日期、百分比、金額）：沒有東西會
  自動推斷，日期會顯示成 `45337`，30% 會顯示成 `0.3`。
- **每個新圖表都要設 `chart.roundedCorners = False`；圖例與你加的每個標題
  （`chart.legend`、`chart.title`、`chart.x_axis.title`……）設
  `.overlay = False`；有座標軸的圖表（不是圓餅或環圈圖）設
  `chart.x_axis.delete = False` 與 `chart.y_axis.delete = False`**，否則 Excel
  可能把標題或圖例畫在圖上、框線變圓角，或不畫座標軸。
- **用 `DateAxis` 時設 `chart.y_axis.crossAx = 500`**，否則 Excel 可能要求
  修復檔案。

## 財務模型

除非使用者另有指示，或既有檔案已經有不同的做法。

**顏色：** 藍字（`0,0,255`）表示寫死的輸入與情境參數 · 黑字表示公式 ·
綠字（`0,128,0`）表示連到其他工作表 · 紅字（`255,0,0`）表示連到其他檔案 ·
黃色填滿（`255,255,0`）表示關鍵假設與使用者要填的儲存格。

**數字：** 金額 `$#,##0`（新台幣可用 `#,##0`），單位寫在標題（`營收（百萬元）`）
· 零顯示成 `-`，百分比也一樣（`$#,##0;($#,##0);-`） · 負數用括號 · 百分比
`0.0%`，**以小數儲存**（`0.15` 顯示 `15.0%`；存 `15` 會顯示 `1500.0%`）·
倍數 `0.0x` · 年份存成文字（`"2024"`，不要變成 `2,024`）。

**結構：** 每個假設放在自己有標籤的儲存格，用到它的公式都參照它
（`=B5*(1+$B$6)`，不要寫 `=B5*1.05`）· 每個預測期間的公式要一致，因為一列
中間單獨改過的一格是最常見的隱性錯誤 · 分母可能是零時要防護。

## 相依套件

`openpyxl`、`pandas`、`markitdown`（已裝好）· LibreOffice（`soffice`，由
`/opt/skills/xlsx/scripts/office/soffice.py` 自動設定）
