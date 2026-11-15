#!/bin/bash
# Agent Harness 新增的離線版 init-artifact.sh（不是 Anthropic 官方的腳本）。
#
# 官方的 scripts/init-artifact.sh 會用 pnpm 從網路下載套件；沙盒沒有網路，
# 所以建置映像檔時已經用官方腳本建好範本（/opt/web-artifact，含 Parcel 與
# html-inline）。這裡複製範本的原始碼，node_modules 則連結到範本的（唯讀），
# 不用下載任何東西。
#
# 用法：bash /opt/skills/web-artifacts-builder/offline/init-artifact.sh <專案名稱>
set -e

TEMPLATE="${WEB_ARTIFACT_TEMPLATE:-/opt/web-artifact}"

if [ -z "$1" ]; then
  echo "用法：bash $0 <專案名稱>"
  exit 1
fi
if [ ! -d "$TEMPLATE/node_modules" ]; then
  echo "找不到專案範本 $TEMPLATE（沙盒映像檔要用 docker/sandbox.Dockerfile 建置）"
  exit 1
fi
if [ -e "$1" ]; then
  echo "$1 已經存在，換一個名稱"
  exit 1
fi

mkdir -p "$1"
# 複製範本（不含 node_modules 與快取），再連結範本的 node_modules。
tar -C "$TEMPLATE" --exclude=./node_modules --exclude=./.parcel-cache \
  --exclude=./dist -cf - . | tar -C "$1" -xf -
ln -s "$TEMPLATE/node_modules" "$1/node_modules"
sed -i 's#<title>.*</title>#<title>'"$(basename "$1")"'</title>#' "$1/index.html"
# 新版 Vite 範本的圖示（favicon.svg 等）用絕對路徑，Parcel 打包單一 HTML 時
# 找不到，和官方腳本拿掉 vite.svg 一樣拿掉。
sed -i '/<link rel="icon"/d' "$1/index.html"

echo "✅ 已建立 $1（React + TypeScript + Tailwind CSS + shadcn/ui，40 多個元件在 src/components/ui/）"
echo "   之後在 $1 裡執行：bash /opt/skills/web-artifacts-builder/offline/bundle-artifact.sh"
