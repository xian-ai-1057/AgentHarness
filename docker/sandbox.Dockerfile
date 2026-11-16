# 沙盒的映像檔：agent 寫的程式在這個映像檔的容器裡執行。
#
# `docker compose up -d` 會一併建置（建置目錄是 repo 根目錄）。要加裝套件
# 時改這個檔案，再執行 `docker compose build sandbox-image`，並更新
# docker-compose.yml 裡的 HARNESS_SANDBOX_NOTES，模型才知道有哪些套件可以用。
#
# 沙盒執行時沒有網路，所以內建 skills（xlsx、docx、pptx、pdf、
# web-artifacts-builder、webapp-testing、mcp-builder 等）需要的工具都在這裡
# 一次裝好，執行時不會、也無法再下載套件。

# Node 套件（pptxgenjs、docx 等）先在 Node 的映像檔裡裝好，再整包複製過去。
# p5 給 algorithmic-art 內嵌進 HTML；@modelcontextprotocol/*、express、zod、
# typescript、tsx 讓 mcp-builder 在沙盒裡編譯、測試 MCP 伺服器。
FROM node:22-bookworm-slim AS node
RUN npm install -g --no-fund --no-audit \
      pptxgenjs@4 docx@9 pdf-lib@1 pdfjs-dist@6 \
      react-icons@5 react@19 react-dom@19 sharp@0.35 \
      p5@1.7.0 \
      @modelcontextprotocol/server@2 @modelcontextprotocol/node@2 \
      @modelcontextprotocol/express@2 @modelcontextprotocol/client@2 \
      @modelcontextprotocol/sdk@1 express@5 zod@4 \
      typescript@5 tsx@4 @types/node@22 @types/express@5 \
 && npm cache clean --force

# web-artifacts-builder 的 React + Tailwind + shadcn/ui 專案範本：用官方的
# init-artifact.sh 建好並裝好打包工具（Parcel、html-inline）。沙盒裡的
# offline/init-artifact.sh 複製這個範本、連結它的 node_modules，不用上網。
# @swc/core 固定在 1.15：1.16 起原生模組要先解壓到可執行的快取資料夾，
# 沙盒的 /tmp 不能執行程式、其他地方又是唯讀，會載入失敗。packageExports
# 讓 Parcel 認得新版 Radix UI 用 package.json exports 宣告的子路徑。
FROM node:22-bookworm-slim AS webapp
RUN npm install -g --no-fund --no-audit pnpm@9 && npm cache clean --force
COPY python/src/harness/builtin/skills/web-artifacts-builder/scripts /tmp/wab
WORKDIR /opt
ENV CI=1
RUN bash /tmp/wab/init-artifact.sh web-artifact \
 && cd web-artifact \
 && pnpm add -D parcel @parcel/config-default parcel-resolver-tspaths \
      html-inline \
 && printf '%s\n' '{' '  "extends": "@parcel/config-default",' \
      '  "resolvers": ["parcel-resolver-tspaths", "..."]' '}' > .parcelrc \
 && node -e "const f='package.json',p=require('./'+f);p.pnpm={overrides:{'@swc/core':'1.15.47'}};p['@parcel/resolver-default']={packageExports:true};require('fs').writeFileSync(f,JSON.stringify(p,null,2))" \
 && pnpm install --no-frozen-lockfile \
 && pnpm store prune

FROM python:3.12-slim

# LibreOffice 讓網頁把 Word、PowerPoint 轉成 PDF 預覽（見
# harness.web.office），xlsx skill 也用它重算公式。fonts-liberation 的字型
# 和 Arial、Times New Roman 等寬，版面才不會跑掉；fonts-arphic-uming 是
# TrueType 的中文字型，reportlab 產生中文 PDF 時用它（Noto CJK 是
# reportlab 不支援的 OpenType 格式）。
# pandoc（讀 Word）、qpdf 與 poppler-utils（pdftoppm、pdftotext）、
# tesseract（掃描檔 OCR，含繁中與簡中）、zip、unzip 給文件 skills 使用。
# libatomic1 是 Playwright 附帶的 Node 需要的函式庫。
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      fonts-noto-cjk fonts-liberation fonts-arphic-uming \
      libreoffice-writer-nogui libreoffice-impress-nogui \
      libreoffice-calc-nogui \
      pandoc qpdf poppler-utils zip unzip \
      tesseract-ocr tesseract-ocr-chi-tra tesseract-ocr-chi-sim \
      libatomic1 \
 && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir \
      pandas numpy openpyxl pdfplumber python-docx python-pptx matplotlib \
      pypdf pypdfium2 reportlab pillow lxml defusedxml \
      pytesseract pdf2image \
      "markitdown[docx,pptx,xlsx,xls,pdf]" \
      "mcp>=1.25,<2" httpx pydantic playwright

# webapp-testing 用的無頭 Chromium（Playwright 下載的版本，含系統相依
# 套件），放在固定位置，沙盒裡的使用者也讀得到。
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright
RUN playwright install --with-deps --only-shell chromium \
 && rm -rf /var/lib/apt/lists/*

COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
# 讓 agent 寫在 /workspace 的腳本直接 require('pptxgenjs') 或
# import 'pdfjs-dist'，不用 npm install：ES module 不看 NODE_PATH，而是往上層
# 資料夾找 node_modules，所以根目錄也放一個連結。
ENV NODE_PATH=/usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules /node_modules \
 && ln -s ../lib/node_modules/typescript/bin/tsc /usr/local/bin/tsc \
 && ln -s ../lib/node_modules/tsx/dist/cli.mjs /usr/local/bin/tsx

# 內建 skills 附帶的腳本（例如 xlsx 的 recalc.py、pptx 的 validate.py）。
# 映像檔的系統目錄在沙盒裡是唯讀的，容器裡的程式改不到它們。
COPY python/src/harness/builtin/skills /opt/skills
COPY --from=webapp /opt/web-artifact /opt/web-artifact

# canvas-design 附帶的字型（SIL OFL）也給 LibreOffice、matplotlib 等使用。
RUN mkdir -p /usr/local/share/fonts \
 && ln -s /opt/skills/canvas-design/canvas-fonts \
      /usr/local/share/fonts/canvas-fonts \
 && fc-cache -f

# 圖表預設用中文字型，否則中文會變成方框。
RUN printf 'font.family: Noto Sans CJK JP\naxes.unicode_minus: False\n' \
      > /etc/matplotlibrc
ENV MATPLOTLIBRC=/etc/matplotlibrc
