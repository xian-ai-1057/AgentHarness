---
# 改寫自 Anthropic 官方 skills 的 pdf（https://github.com/anthropics/skills
# ，commit 1780c5e），授權 Apache License 2.0，完整條款見 LICENSE.txt。
# 修改內容：SKILL.md 翻成繁體中文；改成在 Agent Harness 的沙盒裡執行（腳本
# 在 /opt/skills/pdf/scripts/，沒有網路、不安裝套件）；補上中文字型與中文
# OCR 的做法。REFERENCE.md、FORMS.md 與 scripts/ 未修改。
name: pdf
description: 處理 PDF 檔案時使用：讀取或擷取文字與表格、合併或分割 PDF、旋轉頁面、加浮水印、建立新的 PDF、填寫 PDF 表單、加密或解密、擷取圖片，以及對掃描檔做 OCR。使用者提到 .pdf 檔或要產出 PDF 時都用。
license: Apache-2.0，完整條款見 LICENSE.txt
tools: [files]
---

# PDF 處理指南

## 在這個環境怎麼執行

- **一律用 `run_python` 在沙盒裡執行。** 下面的命令列工具（`qpdf`、
  `pdftotext`、`pdfimages`、`node`……）也一樣：在 `run_python` 裡用
  `subprocess.run([...], capture_output=True, text=True)` 執行並印出 stdout、
  stderr。不要用 `run_command` 執行這些指令。
- 工作目錄是 `/workspace`（這段對話的工作資料夾）：使用者上傳的檔案在
  `uploads/`，產出的檔案存在 `/workspace` 底下，完成後告訴使用者檔名。
- 沙盒**沒有網路，也不能安裝套件**。下面提到的 Python 套件（pypdf、
  pdfplumber、reportlab、pypdfium2、pytesseract、pdf2image）、命令列工具
  （qpdf、poppler-utils、tesseract 含繁中與簡中）與 npm 套件（pdf-lib、
  pdfjs-dist）都已經裝好；萬一 import 失敗，告訴使用者缺少什麼，不要嘗試
  `pip install` 或 `npm install`。`pdftk` 沒有安裝，改用 qpdf 或 pypdf。
- 這個 skill 的腳本在 `/opt/skills/pdf/scripts/`（唯讀）。REFERENCE.md 與
  FORMS.md 裡寫的 `scripts/...` 都指這個資料夾，例如
  `python /opt/skills/pdf/scripts/check_fillable_fields.py uploads/form.pdf`。
- **你看不到圖片**（工具結果只有文字）。FORMS.md 裡要看頁面圖片判斷欄位
  的步驟，優先改用 `extract_form_structure.py` 的座標（Approach A）；只能靠
  看圖估計位置的掃描表單，先告訴使用者這個限制，填完後請他預覽確認。
  `convert_pdf_to_images.py` 的輸出資料夾要先建立。
- **表單要填中文時**，見下面的〈填寫中文表單〉：`fill_fillable_fields.py`
  會存入中文值，但表單欄位的字型通常沒有中文字，很多檢視器會顯示空白。

## 填寫中文表單

照 FORMS.md 用 `extract_form_field_info.py` 取得 `field_info.json` 之後，值裡
有中文時，改成把文字直接畫在頁面上，並拿掉原本的表單欄位（填好的檔案就
不能再當表單編輯）。先跟使用者說明這個差異。

```python
import io, json
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, NameObject
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

pdfmetrics.registerFont(
    TTFont("UMing", "/usr/share/fonts/truetype/arphic/uming.ttc", subfontIndex=2)
)
fields = {f["field_id"]: f for f in json.load(open("field_info.json"))}
values = {"name": "王小明", "agree": True}   # field_id → 文字，勾選框用 True/False

writer = PdfWriter(clone_from=PdfReader("uploads/form.pdf"))
for number, page in enumerate(writer.pages, start=1):
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=(float(page.mediabox.width), float(page.mediabox.height)))
    for field_id, value in values.items():
        field = fields[field_id]
        if field["page"] != number:
            continue
        left, bottom, right, top = field["rect"]
        if field["type"] == "checkbox":
            if value:  # 畫一個勾（字型裡沒有 ✓）
                c.setLineWidth(1.5)
                c.line(left + 2, (bottom + top) / 2, (left + right) / 2, bottom + 2)
                c.line((left + right) / 2, bottom + 2, right - 2, top - 2)
        else:
            size = min(12, (top - bottom) * 0.7)
            c.setFont("UMing", size)
            c.drawString(left + 2, bottom + (top - bottom - size) / 2 + 1, str(value))
    c.save()
    page.merge_page(PdfReader(buffer).pages[0])
    if "/Annots" in page:  # 拿掉表單欄位，否則欄位的底色會蓋住文字
        kept = [a for a in page["/Annots"] if a.get_object().get("/Subtype") != "/Widget"]
        if kept:
            page[NameObject("/Annots")] = ArrayObject(kept)
        else:
            del page["/Annots"]
if "/AcroForm" in writer._root_object:
    del writer._root_object["/AcroForm"]
writer.write("filled.pdf")
```

完成後用 `pdftotext filled.pdf -` 確認文字都在，再請使用者預覽確認位置。

## 概覽

這份指南說明用 Python 套件與命令列工具處理 PDF 的常見做法。進階功能、
JavaScript 套件與更多範例見 REFERENCE.md（用 `read_skill_file` 讀取）。要填寫
PDF 表單時，讀 FORMS.md 並照它的步驟做。

## 快速開始

```python
from pypdf import PdfReader, PdfWriter

# 讀取 PDF
reader = PdfReader("document.pdf")
print(f"頁數：{len(reader.pages)}")

# 擷取文字
text = ""
for page in reader.pages:
    text += page.extract_text()
```

## Python 套件

### pypdf：基本操作

#### 合併 PDF
```python
from pypdf import PdfWriter, PdfReader

writer = PdfWriter()
for pdf_file in ["doc1.pdf", "doc2.pdf", "doc3.pdf"]:
    reader = PdfReader(pdf_file)
    for page in reader.pages:
        writer.add_page(page)

with open("merged.pdf", "wb") as output:
    writer.write(output)
```

#### 分割 PDF
```python
reader = PdfReader("input.pdf")
for i, page in enumerate(reader.pages):
    writer = PdfWriter()
    writer.add_page(page)
    with open(f"page_{i+1}.pdf", "wb") as output:
        writer.write(output)
```

#### 擷取中繼資料
```python
reader = PdfReader("document.pdf")
meta = reader.metadata
print(f"標題：{meta.title}")
print(f"作者：{meta.author}")
print(f"主旨：{meta.subject}")
print(f"建立工具：{meta.creator}")
```

#### 旋轉頁面
```python
reader = PdfReader("input.pdf")
writer = PdfWriter()

page = reader.pages[0]
page.rotate(90)  # 順時針轉 90 度
writer.add_page(page)

with open("rotated.pdf", "wb") as output:
    writer.write(output)
```

### pdfplumber：擷取文字與表格

#### 保留版面擷取文字
```python
import pdfplumber

with pdfplumber.open("document.pdf") as pdf:
    for page in pdf.pages:
        text = page.extract_text()
        print(text)
```

#### 擷取表格
```python
with pdfplumber.open("document.pdf") as pdf:
    for i, page in enumerate(pdf.pages):
        tables = page.extract_tables()
        for j, table in enumerate(tables):
            print(f"第 {i+1} 頁的表格 {j+1}：")
            for row in table:
                print(row)
```

#### 進階表格擷取
```python
import pandas as pd

with pdfplumber.open("document.pdf") as pdf:
    all_tables = []
    for page in pdf.pages:
        tables = page.extract_tables()
        for table in tables:
            if table:  # 略過空表格
                df = pd.DataFrame(table[1:], columns=table[0])
                all_tables.append(df)

# 合併所有表格
if all_tables:
    combined_df = pd.concat(all_tables, ignore_index=True)
    combined_df.to_excel("extracted_tables.xlsx", index=False)
```

### reportlab：建立 PDF

#### 基本做法
```python
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

c = canvas.Canvas("hello.pdf", pagesize=letter)
width, height = letter

# 加入文字
c.drawString(100, height - 100, "Hello World!")
c.drawString(100, height - 120, "This is a PDF created with reportlab")

# 加一條線
c.line(100, height - 140, 400, height - 140)

# 存檔
c.save()
```

#### 多頁 PDF
```python
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
from reportlab.lib.styles import getSampleStyleSheet

doc = SimpleDocTemplate("report.pdf", pagesize=letter)
styles = getSampleStyleSheet()
story = []

# 加入內容
title = Paragraph("Report Title", styles['Title'])
story.append(title)
story.append(Spacer(1, 12))

body = Paragraph("This is the body of the report. " * 20, styles['Normal'])
story.append(body)
story.append(PageBreak())

# 第 2 頁
story.append(Paragraph("Page 2", styles['Heading1']))
story.append(Paragraph("Content for page 2", styles['Normal']))

# 產生 PDF
doc.build(story)
```

#### 中文字型（重要）

reportlab 內建的字型沒有中文字，直接寫中文會變成黑色方塊。先註冊沙盒裡
的 TrueType 中文字型（AR PL UMing，明體），再讓樣式使用它：

```python
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.styles import getSampleStyleSheet

pdfmetrics.registerFont(
    TTFont("UMing", "/usr/share/fonts/truetype/arphic/uming.ttc", subfontIndex=2)
)  # subfontIndex=2 是台灣字形（AR PL UMing TW）
styles = getSampleStyleSheet()
for name in ("Normal", "Title", "Heading1", "Heading2", "BodyText"):
    styles[name].fontName = "UMing"
styles["Normal"].wordWrap = "CJK"   # 中文沒有空格，要用 CJK 斷行
styles["BodyText"].wordWrap = "CJK"
# canvas 直接畫字時：c.setFont("UMing", 12)
```

#### 上標與下標

**重要：** reportlab 的 PDF 不要用 Unicode 上下標字元（₀₁₂₃₄₅₆₇₈₉、
⁰¹²³⁴⁵⁶⁷⁸⁹）。內建字型沒有這些字，會變成黑色方塊。

改在 Paragraph 裡用 reportlab 的 XML 標記：
```python
from reportlab.platypus import Paragraph
from reportlab.lib.styles import getSampleStyleSheet

styles = getSampleStyleSheet()

# 下標：<sub>
chemical = Paragraph("H<sub>2</sub>O", styles['Normal'])

# 上標：<super>
squared = Paragraph("x<super>2</super> + y<super>2</super>", styles['Normal'])
```

用 canvas 直接畫的文字（不是 Paragraph），手動調整字型大小與位置，不要用
Unicode 上下標字元。

## 命令列工具

### pdftotext（poppler-utils）
```bash
# 擷取文字
pdftotext input.pdf output.txt

# 保留版面
pdftotext -layout input.pdf output.txt

# 只擷取部分頁面
pdftotext -f 1 -l 5 input.pdf output.txt  # 第 1–5 頁
```

### qpdf
```bash
# 合併
qpdf --empty --pages file1.pdf file2.pdf -- merged.pdf

# 分割
qpdf input.pdf --pages . 1-5 -- pages1-5.pdf
qpdf input.pdf --pages . 6-10 -- pages6-10.pdf

# 旋轉
qpdf input.pdf output.pdf --rotate=+90:1  # 第 1 頁轉 90 度

# 移除密碼
qpdf --password=mypassword --decrypt encrypted.pdf decrypted.pdf
```

## 常見工作

### 掃描檔的文字（OCR）
```python
import pytesseract
from pdf2image import convert_from_path

# PDF 轉成圖片
images = convert_from_path('scanned.pdf')

# 逐頁 OCR；繁體中文用 chi_tra，中英混合用 chi_tra+eng，簡體用 chi_sim
text = ""
for i, image in enumerate(images):
    text += f"第 {i+1} 頁：\n"
    text += pytesseract.image_to_string(image, lang="chi_tra+eng")
    text += "\n\n"

print(text)
```

頁數多時分批處理，避免超過 `run_python` 的時間上限。

### 加浮水印
```python
from pypdf import PdfReader, PdfWriter

# 建立或載入浮水印
watermark = PdfReader("watermark.pdf").pages[0]

# 套用到每一頁
reader = PdfReader("document.pdf")
writer = PdfWriter()

for page in reader.pages:
    page.merge_page(watermark)
    writer.add_page(page)

with open("watermarked.pdf", "wb") as output:
    writer.write(output)
```

### 擷取圖片
```bash
# 用 pdfimages（poppler-utils）
pdfimages -j input.pdf output_prefix

# 圖片會存成 output_prefix-000.jpg、output_prefix-001.jpg……
```

### 設定密碼
```python
from pypdf import PdfReader, PdfWriter

reader = PdfReader("input.pdf")
writer = PdfWriter()

for page in reader.pages:
    writer.add_page(page)

# 加上密碼
writer.encrypt("userpassword", "ownerpassword")

with open("encrypted.pdf", "wb") as output:
    writer.write(output)
```

## 速查表

| 工作 | 最適合的工具 | 指令或程式 |
|------|-----------|--------------|
| 合併 PDF | pypdf | `writer.add_page(page)` |
| 分割 PDF | pypdf | 每頁一個檔案 |
| 擷取文字 | pdfplumber | `page.extract_text()` |
| 擷取表格 | pdfplumber | `page.extract_tables()` |
| 建立 PDF | reportlab | Canvas 或 Platypus（中文要先註冊字型） |
| 命令列合併 | qpdf | `qpdf --empty --pages ...` |
| 掃描檔 OCR | pytesseract | 先轉成圖片，`lang="chi_tra+eng"` |
| 填寫 PDF 表單 | pdf-lib 或 pypdf（見 FORMS.md） | 見 FORMS.md |

## 接下來

- 進階的 pypdfium2 用法見 REFERENCE.md
- JavaScript 套件（pdf-lib）見 REFERENCE.md
- 要填寫 PDF 表單，照 FORMS.md 的步驟做
- 疑難排解見 REFERENCE.md
