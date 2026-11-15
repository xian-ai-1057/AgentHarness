"""把 HTML 裡從 CDN 載入的 p5.js 換成內嵌的版本，讓檔案不用上網也能開。

Agent Harness 新增的輔助腳本（不是 Anthropic 官方 skill 的一部分）。銀行等
內部網路常常連不到 cdnjs 與 Google Fonts，所以：

- `<script src="...p5...js">` 換成沙盒映像檔裡 p5 1.7.0 的內容；
- 拿掉 Google Fonts 的 `<link>`，字型改用 CSS 裡寫好的備援字體。

用法：python /opt/skills/algorithmic-art/offline/inline_p5.py art.html
"""

import pathlib
import re
import sys

P5 = pathlib.Path("/usr/local/lib/node_modules/p5/lib/p5.min.js")
SCRIPT = re.compile(
    r'<script\s+src="[^"]*p5(?:\.min)?\.js"\s*>\s*</script>', re.I
)
FONTS = re.compile(
    r"<link[^>]+(?:fonts\.googleapis\.com|fonts\.gstatic\.com)[^>]*>\s*", re.I
)


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    path = pathlib.Path(sys.argv[1])
    html = path.read_text(encoding="utf-8")
    if not SCRIPT.search(html):
        print("找不到載入 p5.js 的 <script src=...>，沒有修改。")
        return 1
    library = P5.read_text(encoding="utf-8").replace("</script", "<\\/script")
    html = SCRIPT.sub(
        lambda _: f"<script>\n{library}\n</script>", html, count=1
    )
    html, removed = FONTS.subn("", html)
    path.write_text(html, encoding="utf-8")
    size = path.stat().st_size / 1024
    print(f"已內嵌 p5.js，移除 {removed} 個 Google Fonts 連結：{path}")
    print(f"檔案大小 {size:.0f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
