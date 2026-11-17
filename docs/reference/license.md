# 授權

Agent Harness 以 [Apache License 2.0](https://github.com/xian-ai-1057/AgentHarness/blob/main/LICENSE)
授權，Copyright 2026 [xian-ai-1057](https://github.com/xian-ai-1057)。

## 可以做什麼

- 自由使用、修改、商用、再散布，不需要另外取得同意，也不用付費。
- 可以把它嵌進自己的產品，自己的程式碼可以用其他授權（包含不開源）。
- 授權包含專利授權：貢獻者對自己貢獻的部分授予專利使用權；對本專案提起
  專利訴訟的人，專利授權會終止。

## 散布或改作時要做的事

Apache 2.0 要求保留署名。把 Agent Harness（原樣或改過的版本）給別人時：

1. **附上 `LICENSE`。**
2. **保留署名。** 原始碼裡的著作權、專利、商標與署名聲明不能拿掉。
3. **附上 `NOTICE` 的內容。** repo 根目錄的
   [`NOTICE`](https://github.com/xian-ai-1057/AgentHarness/blob/main/NOTICE)
   記載原作者與第三方元件，散布時要在 NOTICE 檔、文件或產品裡平常顯示
   第三方聲明的地方附上它的內容。可以在後面加上自己的署名。
4. **註明修改。** 修改過的檔案要有明顯的說明，表示你改過它。

授權不包含商標：不能用原作者的名義替改作的版本背書。

Python 套件（`python/`）與 npm 套件各自附上 `LICENSE`、`NOTICE`：
`python/LICENSE`、`python/NOTICE` 是根目錄檔案的複本（測試會檢查兩者一致），
建置 wheel 時會一起打包。

## 第三方元件

| 元件 | 位置 | 授權 |
|---|---|---|
| 改寫自 [anthropics/skills](https://github.com/anthropics/skills) 的 skills（xlsx、docx、pptx、pdf 與其他範例 skills） | `python/src/harness/builtin/skills/` | Apache 2.0，每個資料夾保留官方 `LICENSE.txt`，`SKILL.md` 開頭註明修改內容 |
| canvas-design 用的字型 | `skills/canvas-design/canvas-fonts/` | SIL Open Font License 1.1，見各字型的 `*-OFL.txt` |
| PDF.js 的字元對照表與標準字型 | `python/src/harness/web/static/pdfjs/` | Apache 2.0；CMaps 為 Adobe 的 BSD-3-Clause，字型見 `LICENSE_FOXIT`、`LICENSE_LIBERATION` |
| 網頁版打包的 JavaScript 套件（React、KaTeX、highlight.js、PDF.js 等） | `python/src/harness/web/static/assets/` | MIT、ISC、BSD、0BSD、Apache 2.0，完整清單與條文見 `static/THIRD_PARTY_LICENSES.md` |

`THIRD_PARTY_LICENSES.md` 由 `npm run build` 自動產生（Vite 的
`build.license`），加入或升級前端套件後重新建置就會更新。

`skills/` 底下沒有 `LICENSE.txt` 的 skills（`code-review`、`debugging`、
`doc-coauthoring`、`git-commit`、`planning`、`web-research`）是本專案自己寫
的，和其他程式碼一樣以 Apache 2.0 授權。

**Docker 映像檔：** 沙盒映像檔（`docker/sandbox.Dockerfile`）建置時會從
Debian、PyPI、npm 安裝 LibreOffice、pandoc、Poppler、Tesseract、Playwright 等工具，它們各自有
自己的授權（部分是 GPL、MPL）。只散布原始碼時不受影響；如果要公開散布建置
好的映像檔，請一併提供這些套件的授權資訊（Debian 套件的授權在映像檔的
`/usr/share/doc/*/copyright`）。

## 貢獻

依 Apache 2.0 第 5 條，送進本專案的貢獻（pull request 等）除非另外聲明，
都以同樣的 Apache 2.0 授權。
