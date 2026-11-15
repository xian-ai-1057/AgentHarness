---
# 改寫自 Anthropic 官方 skills 的 webapp-testing（https://github.com/anthropics/skills
# ，commit 1780c5e），授權 Apache License 2.0，完整條款見 LICENSE.txt。
# 修改內容：說明翻成繁體中文；改成在 Agent Harness 的沙盒裡執行
# （Playwright 與無頭 Chromium 建置時裝好，腳本在
# /opt/skills/webapp-testing/）；註明沙盒沒有網路，只能測沙盒裡啟動的伺服器
# 或本機 HTML 檔；沒有看圖工具，截圖交給使用者預覽。scripts/、examples/
# 未修改。
name: webapp-testing
description: 用 Playwright 與無頭瀏覽器操作、測試網頁應用：驗證前端功能、除錯 UI 行為、擷取畫面截圖、讀取瀏覽器主控台訊息。使用者要測試或檢查自己寫的網頁、HTML 檔或在沙盒裡跑的網站時使用。沙盒沒有網路，不能測試外部或公司內部的網站。
license: Apache-2.0，完整條款見 LICENSE.txt
tools: [files]
---

# 網頁應用測試

測試網頁應用時，寫原生的 Python Playwright 腳本。

## 在這個環境怎麼執行

- **一律用 `run_python` 在沙盒裡執行。** Playwright（Python）與無頭
  Chromium 已經裝好，直接 `from playwright.sync_api import sync_playwright`；
  不要執行 `playwright install` 或 `pip install`。
- **沙盒沒有網路。** 能測的只有：工作資料夾裡的 HTML 檔（`file:///workspace/…`）、
  在同一次 `run_python` 裡啟動的伺服器（`localhost`），例如用
  `with_server.py` 啟動的 `python -m http.server` 或 Node 程式。外部網站、
  公司內部網站、使用者電腦上的 `localhost` 都連不到；使用者要測那些時，
  說明這個限制。
- 腳本在 `/opt/skills/webapp-testing/scripts/`，範例在
  `/opt/skills/webapp-testing/examples/`（唯讀）。shell 指令用
  `subprocess.run(..., capture_output=True, text=True)` 執行並印出結果。
- 每次 `run_python` 有時間上限（預設 60 秒），沙盒的記憶體也有限：一次
  開一個瀏覽器、一個分頁，用完就關；`--timeout` 不要設太長。
- **你看不到截圖。** 檢查畫面用文字：`page.content()`、
  `page.locator(...).inner_text()`、元素的 `bounding_box()`、主控台訊息。
  截圖存到 `.skill-work/webapp-testing-<隨機碼>/`，需要給使用者看的才複製到
  工作資料夾的一般位置（網頁會顯示成可預覽的圖片），做完刪掉專用資料夾。

**附帶的輔助腳本**：

- `scripts/with_server.py`：管理伺服器的生命週期（支援多個伺服器）

**一律先用 `--help` 執行腳本**看用法。除非先試過、確定真的需要客製化，
否則不要讀原始碼。這些腳本可能很長，會塞滿你的上下文；它們是設計成直接
呼叫的黑盒子，而不是讀進上下文裡。

## 決策樹：選擇做法

```
使用者的工作 → 是靜態 HTML 嗎？
    ├─ 是 → 直接讀 HTML 檔找出選擇器
    │         ├─ 成功 → 用這些選擇器寫 Playwright 腳本
    │         └─ 失敗或不完整 → 當成動態網頁處理（如下）
    │
    └─ 否（動態網頁應用）→ 伺服器已經在跑了嗎？
        ├─ 否 → 執行：python /opt/skills/webapp-testing/scripts/with_server.py --help
        │        然後用這個輔助腳本 + 寫簡化的 Playwright 腳本
        │
        └─ 是 → 先偵察、再行動：
            1. 開啟頁面並等待 networkidle
            2. 截圖或檢查 DOM
            3. 從渲染後的狀態找出選擇器
            4. 用找到的選擇器執行動作
```

（在沙盒裡，每次 `run_python` 結束時它啟動的伺服器也會停止，所以動態
網頁一律用 `with_server.py` 在同一次執行裡啟動伺服器並跑測試。）

## 範例：使用 with_server.py

要啟動伺服器，先執行 `--help`，再使用輔助腳本：

**單一伺服器：**

```bash
python /opt/skills/webapp-testing/scripts/with_server.py --server "npm run dev" --port 5173 -- python your_automation.py
```

**多個伺服器（例如後端 + 前端）：**

```bash
python /opt/skills/webapp-testing/scripts/with_server.py \
  --server "cd backend && python server.py" --port 3000 \
  --server "cd frontend && npm run dev" --port 5173 \
  -- python your_automation.py
```

（沙盒裡不能 `npm install`；前端專案要用已經裝好的套件，或先打包成靜態
檔案再用 `python -m http.server` 提供。）

自動化腳本只要包含 Playwright 的邏輯（伺服器會自動管理）：

```python
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)  # 一律用無頭模式啟動 chromium
    page = browser.new_page()
    page.goto('http://localhost:5173')  # 伺服器已經在跑、準備好了
    page.wait_for_load_state('networkidle')  # 關鍵：等 JS 執行完
    # ……你的自動化邏輯
    browser.close()
```

## 先偵察、再行動

1. **檢查渲染後的 DOM**：

   ```python
   page.screenshot(path=f'{W}/inspect.png', full_page=True)  # 給使用者看
   content = page.content()
   page.locator('button').all()
   ```

2. 從檢查結果**找出選擇器**

3. 用找到的選擇器**執行動作**

## 常見陷阱

❌ **不要**在動態網頁的 `networkidle` 之前就檢查 DOM
✅ **要**先 `page.wait_for_load_state('networkidle')` 再檢查

## 最佳做法

- **把附帶的腳本當黑盒子使用**：要完成工作時，先想想 `scripts/` 裡有沒有
  能幫上忙的。這些腳本可靠地處理常見的複雜流程，又不會塞滿上下文。先用
  `--help` 看用法，再直接呼叫。
- 同步腳本用 `sync_playwright()`
- 用完一定要關閉瀏覽器
- 用描述性的選擇器：`text=`、`role=`、CSS 選擇器或 ID
- 加上適當的等待：`page.wait_for_selector()` 或 `page.wait_for_timeout()`

## 參考檔案

- **examples/**：示範常見模式的範例（用 `read_skill_file` 讀取）：
  - `element_discovery.py`：找出頁面上的按鈕、連結與輸入框
  - `static_html_automation.py`：用 file:// 網址開啟本機 HTML
  - `console_logging.py`：在自動化過程中擷取主控台訊息
