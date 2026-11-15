---
# 改寫自 Anthropic 官方 skills 的 brand-guidelines（https://github.com/anthropics/skills
# ，commit 1780c5e），授權 Apache License 2.0，完整條款見 LICENSE.txt。
# 修改內容：說明翻成繁體中文；註明這是 Anthropic 的品牌規範；補上 Agent
# Harness 沙盒裡的字型位置與 Office、網頁的套用方式。色碼與字型照原樣。
name: brand-guidelines
description: 把 Anthropic 官方的品牌色彩與字型套用到簡報、文件、網頁、圖表等產出，讓它有 Anthropic 的外觀。使用者要求 Anthropic 風格、Anthropic 品牌色或字型時使用；要套用其他公司（例如自己公司）的品牌規範時不要用。
license: Apache-2.0，完整條款見 LICENSE.txt
tools: [files]
---

# Anthropic 品牌樣式

## 概要

這份是 **Anthropic** 的品牌識別與樣式資源。要套用自己公司的品牌時，請
使用者提供規範，或請管理者把這個 skill 複製到專案的 `skills/` 改成自己
公司的版本。

**關鍵字**：品牌、企業識別、視覺識別、後製、樣式、品牌色、字型、
Anthropic 品牌、視覺格式、視覺設計

## 品牌規範

### 色彩

**主色：**

- 深色：`#141413`：主要文字與深色背景
- 淺色：`#faf9f5`：淺色背景與深色底上的文字
- 中灰：`#b0aea5`：次要元素
- 淺灰：`#e8e6dc`：淡色背景

**強調色：**

- 橘：`#d97757`：主要強調色
- 藍：`#6a9bcc`：次要強調色
- 綠：`#788c5d`：第三強調色

### 字型

- **標題**：Poppins（備援 Arial）
- **內文**：Lora（備援 Georgia）
- **注意**：最好在環境裡事先裝好這些字型。

## 功能

### 自動套用字型

- 標題（24pt 以上）用 Poppins
- 內文用 Lora
- 沒有自訂字型時自動改用 Arial／Georgia
- 在各種系統上都維持可讀性

### 文字樣式

- 標題（24pt 以上）：Poppins
- 內文：Lora
- 依背景自動選擇文字顏色
- 保留文字的層級與格式

### 圖形與強調色

- 非文字的圖形使用強調色
- 依序輪流使用橘、藍、綠三個強調色
- 保持視覺變化，同時不偏離品牌

## 技術細節

### 字型管理

- 有安裝 Poppins、Lora 時直接使用
- 沒有時自動改用 Arial（標題）與 Georgia（內文）
- 不需要另外安裝字型，現有的系統字型就能運作
- 想要最好的效果，在環境裡裝好 Poppins 與 Lora

**在 Agent Harness 的沙盒裡：** Lora 在 `/opt/skills/canvas-design/canvas-fonts/`
（已登記到系統字型，LibreOffice、matplotlib 都找得到）；沙盒裡沒有
Poppins，標題用 Arial（沙盒裡由等寬的 Liberation Sans 代替）。Word、
PowerPoint 檔在使用者的電腦上開啟，沒有這些字型時 Office 會自動替換。
中文字不在這兩套字型裡，中文用微軟正黑體（Office）或 Noto Sans CJK
（網頁、圖片）。

### 色彩套用

- 用 RGB 值精準對應品牌色
- 透過 python-pptx 的 `RGBColor` 類別套用（pptxgenjs 用不含 `#` 的色碼，
  例如 `"d97757"`）
- 在不同系統上維持顏色一致
