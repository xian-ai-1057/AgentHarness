---
# 改寫自 Anthropic 官方 skills 的 internal-comms（https://github.com/anthropics/skills
# ，commit 1780c5e），授權 Apache License 2.0，完整條款見 LICENSE.txt。
# 修改內容：說明翻成繁體中文；補上在 Agent Harness 裡找資料的方式（知識庫、
# 上傳檔案、網頁搜尋，沒有 Slack、Google Drive、Email 等連接器）。
# examples/ 未修改。
name: internal-comms
description: 依公司慣用的格式撰寫各種內部溝通文字：狀態報告、主管更新、3P 更新（進度、計畫、問題）、公司電子報、FAQ、事件報告、專案更新等。使用者要寫週報、進度更新、內部公告、電子報、常見問答或事故說明時使用。
license: Apache-2.0，完整條款見 LICENSE.txt
tools: [files]
---

## 什麼時候使用

撰寫下列內部溝通時使用這個 skill：

- 3P 更新（Progress 進度、Plans 計畫、Problems 問題）
- 公司電子報
- FAQ 回覆
- 狀態報告
- 主管更新
- 專案更新
- 事件報告

## 怎麼使用

撰寫任何內部溝通時：

1. **從需求判斷溝通的類型**
2. **用 `read_skill_file` 讀取 `examples/` 裡對應的指引：**
    - `examples/3p-updates.md`：團隊的進度、計畫、問題更新
    - `examples/company-newsletter.md`：全公司的電子報
    - `examples/faq-answers.md`：回答常見問題
    - `examples/general-comms.md`：不屬於上面任何一種的其他溝通
3. **照該檔案的指示**處理格式、語氣與要蒐集的內容

類型不符合任何既有指引時，先問使用者想要的格式，或請他提供更多背景。

## 在這個環境找資料

指引檔是英文寫的，提到用 Slack、Google Drive、Email、行事曆等工具蒐集
資料。這裡沒有這些連接器，改用：

- 使用者上傳的檔案（工作資料夾的 `uploads/`）與貼上的內容
- 有知識庫工具時，搜尋公司的知識庫
- 有網頁工具時，查詢公開資料
- 資料不夠時直接問使用者；不要編造數字、人名或進度

用使用者的語言撰寫（預設繁體中文），格式與語氣照指引。

## 關鍵字

3P 更新、公司電子報、公司溝通、週報、FAQ、常見問題、更新、內部溝通
