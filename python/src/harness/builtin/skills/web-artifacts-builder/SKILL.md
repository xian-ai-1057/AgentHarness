---
# 改寫自 Anthropic 官方 skills 的 web-artifacts-builder（https://github.com/anthropics/skills
# ，commit 1780c5e），授權 Apache License 2.0，完整條款見 LICENSE.txt。
# 修改內容：說明翻成繁體中文；沙盒沒有網路，改用建置映像檔時就建好的專案
# 範本（/opt/web-artifact），新增 offline/init-artifact.sh 與
# offline/bundle-artifact.sh 取代需要下載套件的步驟；成品是交給使用者下載的
# HTML 檔；描述寫清楚和 frontend-design 的分工。scripts/ 未修改（建置映像檔時用它建立範本）。
name: web-artifacts-builder
description: 用 React、TypeScript、Tailwind CSS 與 shadcn/ui 建構多元件、較複雜的網頁應用，最後打包成單一 HTML 檔。使用者要用 React 或 shadcn/ui，或頁面需要多個畫面共用的複雜狀態、路由時使用（例如多步驟的小工具、可編輯資料的應用）；單一 HTML 就做得到的頁面（包括有分頁、篩選、圖表的儀表板）不要用，改用 frontend-design。
license: Apache-2.0，完整條款見 LICENSE.txt
tools: [files]
requires: [run_python]
---

# 網頁應用建構器

要建構功能強大的前端網頁應用，照這些步驟：

1. 用 `offline/init-artifact.sh` 建立前端專案
2. 編輯產生的程式碼，開發你的應用
3. 用 `offline/bundle-artifact.sh` 把所有程式碼打包成單一 HTML 檔
4. 把檔案交給使用者
5. （選用）測試

**技術組合**：React + TypeScript + Vite + Parcel（打包）+ Tailwind CSS +
shadcn/ui

## 在這個環境怎麼執行

- **一律用 `run_python` 在沙盒裡執行**，指令用
  `subprocess.run(..., capture_output=True, text=True)` 執行並印出 stdout、
  stderr；需要 `cd` 時傳 `cwd=`。不要用 `run_command`。
- 沙盒**沒有網路，不能安裝套件**。官方的 `scripts/init-artifact.sh` 與
  `scripts/bundle-artifact.sh` 會用 pnpm 下載，**在這裡不能用**；改用
  `/opt/skills/web-artifacts-builder/offline/` 裡的同名腳本。專案範本
  （React、Tailwind CSS、40 多個 shadcn/ui 元件與 Radix UI、lucide-react
  圖示、date-fns、react-hook-form、zod、sonner 等，以及 Parcel）在建置映像檔
  時就裝好了，
  `node_modules` 是連到範本的唯讀連結。**只能使用範本裡已經有的套件**：
  用 `os.listdir("node_modules")` 或看 `package.json` 確認；沒有的套件
  不要 import，改用已有的元件自己寫。
- 專案建在 `.skill-work/web-artifacts-<隨機碼>/` 底下（同一個人的其他
  對話可能同時在用工作資料夾），完成後把 `bundle.html` 複製到工作資料夾的
  一般位置、取一個不會和既有檔案撞名的檔名，再刪掉專案資料夾。
- 每次 `run_python` 有時間上限（預設 60 秒）。打包通常要 20 到 40 秒，
  一次執行只做打包這件事；超時的話告訴使用者，可以請管理者調高沙盒的
  時間上限。
- 使用者下載 HTML 後用瀏覽器開啟（網頁的檔案預覽只會顯示原始碼）。打包後
  的檔案不需要網路。
- 用 Playwright 自我檢查時，截圖寫在 `/tmp` 或專案資料夾裡，不要存在工作
  資料夾的一般位置（那裡的檔案都會顯示給使用者）。

## 設計與樣式準則

**非常重要**：為了避免常被稱為「AI 罐頭設計（AI slop）」的東西，避免過度
置中的版面、紫色漸層、千篇一律的圓角，以及 Inter 字型。

## 快速開始

### 第 1 步：建立專案

執行初始化腳本建立新的 React 專案（在 `run_python` 裡）：

```python
import os, secrets, subprocess
W = f"/workspace/.skill-work/web-artifacts-{secrets.token_hex(3)}"
os.makedirs(W)
r = subprocess.run(
    ["bash", "/opt/skills/web-artifacts-builder/offline/init-artifact.sh", "app"],
    cwd=W, capture_output=True, text=True)
print(W, r.stdout, r.stderr)
```

這會建立一個設定完整的專案：

- ✅ React + TypeScript（透過 Vite 範本）
- ✅ Tailwind CSS 3.4.1 與 shadcn/ui 主題系統
- ✅ 設定好路徑別名（`@/`）
- ✅ 預先放好 40 多個 shadcn/ui 元件
- ✅ 包含所有 Radix UI 相依套件
- ✅ 設定好 Parcel 打包（透過 .parcelrc）

### 第 2 步：開發應用

編輯產生的檔案來建構應用（入口是 `src/App.tsx`、`src/main.tsx`，樣式在
`src/index.css`）。元件這樣匯入：

```tsx
import { Button } from '@/components/ui/button'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Dialog, DialogContent, DialogTrigger } from '@/components/ui/dialog'
```

### 第 3 步：打包成單一 HTML 檔

把 React 應用打包成單一 HTML 檔（在專案資料夾執行）：

```python
r = subprocess.run(
    ["bash", "/opt/skills/web-artifacts-builder/offline/bundle-artifact.sh"],
    cwd=f"{W}/app", capture_output=True, text=True)
print(r.stdout[-3000:], r.stderr[-3000:])
```

這會產生 `bundle.html`：所有 JavaScript、CSS 與相依套件都內嵌在裡面的
獨立檔案。

**需求**：專案根目錄必須有 `index.html`。

**腳本做的事**：

- 建立支援路徑別名的 `.parcelrc` 設定
- 用 Parcel 打包（不產生 source map）
- 用 html-inline 把所有資源內嵌成單一 HTML

打包失敗時，錯誤訊息通常是 TypeScript 型別或 import 路徑的問題，修正後
再打包一次。

### 第 4 步：交給使用者

把 `bundle.html` 複製到工作資料夾（例如 `/workspace/銷售儀表板.html`），
告訴使用者檔名，請他下載後用瀏覽器開啟。

### 第 5 步：測試與檢視（選用）

注意：這是完全選用的步驟，只有必要或使用者要求時才做。

可以用其他 skill（例如 webapp-testing 的 Playwright）測試。一般來說不要先
測試，因為會拉長使用者拿到成品的時間；交付之後，使用者要求或出現問題時
再測。

## 參考

- **shadcn/ui 元件**：https://ui.shadcn.com/docs/components （沙盒裡沒有
  網路，元件原始碼在專案的 `src/components/ui/`，直接讀檔案確認用法）
