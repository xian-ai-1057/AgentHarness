#!/bin/bash
# Agent Harness 新增的離線版 bundle-artifact.sh（不是 Anthropic 官方的腳本）。
#
# 和官方的 scripts/bundle-artifact.sh 做一樣的事（Parcel 打包、html-inline
# 內嵌成單一 HTML），但打包工具已經裝在專案範本裡，不再執行 pnpm add。
#
# 用法：在專案資料夾裡執行
#   bash /opt/skills/web-artifacts-builder/offline/bundle-artifact.sh
set -e

if [ ! -f "package.json" ]; then
  echo "❌ 找不到 package.json，請在專案資料夾裡執行。"
  exit 1
fi
if [ ! -f "index.html" ]; then
  echo "❌ 專案根目錄沒有 index.html。"
  exit 1
fi

if [ ! -f ".parcelrc" ]; then
  cat > .parcelrc << 'JSON'
{
  "extends": "@parcel/config-default",
  "resolvers": ["parcel-resolver-tspaths", "..."]
}
JSON
fi

rm -rf dist bundle.html
echo "🔨 Parcel 打包中..."
./node_modules/.bin/parcel build index.html --dist-dir dist --no-source-maps \
  --cache-dir "${TMPDIR:-/tmp}/parcel-cache-$(basename "$PWD")" --log-level warn
echo "🎯 內嵌成單一 HTML..."
./node_modules/.bin/html-inline dist/index.html > bundle.html

echo "✅ 完成：bundle.html（$(du -h bundle.html | cut -f1)）"
