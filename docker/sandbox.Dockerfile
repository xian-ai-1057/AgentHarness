# 沙盒的映像檔：agent 寫的程式在這個映像檔的容器裡執行。
#
# `docker compose up -d` 會一併建置（建置目錄是 repo 根目錄）。要加裝套件
# 時改這個檔案，再執行 `docker compose build sandbox-image`，並更新
# docker-compose.yml 裡的 HARNESS_SANDBOX_NOTES，模型才知道有哪些套件可以用。
#
# 沙盒執行時沒有網路，所以內建 skills（xlsx、docx、pptx、pdf）需要的工具
# 都在這裡一次裝好，執行時不會、也無法再下載套件。

# Node 套件（pptxgenjs、docx 等）先在 Node 的映像檔裡裝好，再整包複製過去。
FROM node:22-bookworm-slim AS node
RUN npm install -g --no-fund --no-audit \
      pptxgenjs@4 docx@9 pdf-lib@1 pdfjs-dist@6 \
      react-icons@5 react@19 react-dom@19 sharp@0.35 \
 && npm cache clean --force

FROM python:3.12-slim

# LibreOffice 讓網頁把 Word、PowerPoint 轉成 PDF 預覽（見
# harness.web.office），xlsx skill 也用它重算公式。fonts-liberation 的字型
# 和 Arial、Times New Roman 等寬，版面才不會跑掉；fonts-arphic-uming 是
# TrueType 的中文字型，reportlab 產生中文 PDF 時用它（Noto CJK 是
# reportlab 不支援的 OpenType 格式）。
# pandoc（讀 Word）、qpdf 與 poppler-utils（pdftoppm、pdftotext）、
# tesseract（掃描檔 OCR，含繁中與簡中）、zip、unzip 給文件 skills 使用。
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      fonts-noto-cjk fonts-liberation fonts-arphic-uming \
      libreoffice-writer-nogui libreoffice-impress-nogui \
      libreoffice-calc-nogui \
      pandoc qpdf poppler-utils zip unzip \
      tesseract-ocr tesseract-ocr-chi-tra tesseract-ocr-chi-sim \
 && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir \
      pandas numpy openpyxl pdfplumber python-docx python-pptx matplotlib \
      pypdf pypdfium2 reportlab pillow lxml defusedxml \
      pytesseract pdf2image \
      "markitdown[docx,pptx,xlsx,xls,pdf]"

COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
# 讓 agent 寫在 /workspace 的腳本直接 require('pptxgenjs') 或
# import 'pdfjs-dist'，不用 npm install：ES module 不看 NODE_PATH，而是往上層
# 資料夾找 node_modules，所以根目錄也放一個連結。
ENV NODE_PATH=/usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules /node_modules

# 內建 skills 附帶的腳本（例如 xlsx 的 recalc.py、pptx 的 validate.py）。
# 映像檔的系統目錄在沙盒裡是唯讀的，容器裡的程式改不到它們。
COPY python/src/harness/builtin/skills /opt/skills

# 圖表預設用中文字型，否則中文會變成方框。
RUN printf 'font.family: Noto Sans CJK JP\naxes.unicode_minus: False\n' \
      > /etc/matplotlibrc
ENV MATPLOTLIBRC=/etc/matplotlibrc
