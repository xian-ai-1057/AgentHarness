# 參與開發

歡迎回報問題、改進文件或送 Pull Request。完整的說明在 repo 根目錄的
[`CONTRIBUTING.md`](https://github.com/xian-ai-1057/AgentHarness/blob/main/CONTRIBUTING.md)，
這裡列出重點。

## 回報問題

- 錯誤與功能建議開在 [Issues](https://github.com/xian-ai-1057/AgentHarness/issues)，
  寫下用的版本（`harness` 或 `pyharness`、網頁版或命令列）、重現步驟、預期與
  實際的結果。新功能先開 Issue 討論方向再動手。
- 安全性問題不要在公開的 Issue 寫出細節，見 `CONTRIBUTING.md` 的回報方式。
- 回報時拿掉 API 金鑰、密碼、內部網址與個人資料。

## 授權

送出的貢獻依照 [Apache License 2.0](/reference/license) 第 5 條，以同一個授權
提供，不需要另外簽署貢獻者協議。加入第三方程式碼時要確認授權相容，並更新
`NOTICE`（`python/NOTICE` 也要一起改）與[授權](/reference/license)頁。

## 開發環境與檢查

需要 Node.js 22.18 以上、Python 3.11 以上。

```bash
npm install                                   # TypeScript 版與網頁前端
cd python && pip install -e ".[dev,pdf,vectors]"   # Python 版
```

修改網頁版：先執行 `pyharness web`（或 `harness web`），再在 repo 執行
`npm run dev:web`。改完前端要 `npm run build`，並提交
`python/src/harness/web/static/` 的變動（CI 會檢查）。

送 PR 前在本機跑過 CI 會跑的檢查：

```bash
npm run lint && npm run typecheck && npm test && npm run build
cd python && ruff check . && ruff format --check . && pytest
```

## 送 PR 的原則

- 一個 PR 只做一件事；修錯誤先寫會重現錯誤的測試。
- 測試不能需要真的 API 金鑰或網路，用假的模型。
- **新功能或行為改變時，同一個 PR 裡一起更新 `docs/` 與相關的 README。**
- 註解、畫面文字與說明文件用繁體中文；Python 照 Google Python Style Guide
  （每行 80 字），TypeScript 照 Biome 的設定。
