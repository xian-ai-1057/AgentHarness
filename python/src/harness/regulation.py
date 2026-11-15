"""依條文切開法規類文件（知識庫的 chunking: regulation）。

法規、自律規範與公司內規通常一條（或一點）講一件事；依段落與字數切片
時，一條可能被切成兩半，或和下一條黏在一起，回答時就引不準是哪一條。
這裡改成一條一片：

- **條文**：文件裡有 3 條以上依序出現的「第 N 條」（法律、法規命令、
  自律規範），每條一片，位置記成「第五條」。
- **要點**：沒有條文、但有 3 點以上依序出現的「一、」「二、」（行政規則、
  公司內規的「要點」「辦法」），每點一片，位置記成「第五點」。
- 兩種都不是時回傳 None，由呼叫端改用一般的段落切片。

條號必須不倒退、一次最多跳 5 條（要點必須剛好是下一點），條文內文引用
「第三條規定」不會被當成新的一條。「第一章 總則」這類章節標題會記在
位置前面，例如「第二章 › 第五條」。單一條文超過字數上限時，依句號再
切成幾片，位置相同。
"""

import re
import unicodedata

# 一般的阿拉伯數字或中文數字（到「百」）。
_NUMERAL = "0-9一二三四五六七八九十百零〇"
_ARTICLE = re.compile(
    rf"^第\s*([{_NUMERAL}]+)\s*條(?:\s*之\s*([{_NUMERAL}]+))?"
    r"(?=\s|$|[^第規定、及至所])"
)
_POINT = re.compile(r"^([一二三四五六七八九十百]+)\s*、")
_CHAPTER = re.compile(rf"^第\s*[{_NUMERAL}]+\s*[章節編](?=\s|、|$|[^\s第])")
_PAGE = re.compile(r"第\s*(\d+)\s*頁")
_DIGITS = {char: value for value, char in enumerate("零一二三四五六七八九")}
# 至少要有幾條（點）才當成法規類文件。
_MIN_UNITS = 3
# 條號一次最多往後跳幾條（中間有刪除的條文）。
_MAX_JUMP = 5
# 章節標題最多幾個字；更長的多半是內文。
_CHAPTER_CHARS = 40


def numeral(text: str) -> int:
    """阿拉伯數字或中文數字（到百位）轉成整數；看不懂時回傳 -1。

    Args:
        text: 例如「12」「十二」「一百零五」。

    Returns:
        數值，或 -1。
    """
    if text.isdigit():
        return int(text)
    total, current = 0, 0
    for char in text.replace("〇", "零"):
        if char in _DIGITS:
            current = _DIGITS[char]
        elif char in "十百":
            total += (current or 1) * (10 if char == "十" else 100)
            current = 0
        else:
            return -1
    return total + current


def split_regulation(
    sections: list[tuple[str, str]], chunk_size: int
) -> list[tuple[str, str]] | None:
    """把一份文件依條文或要點切開。

    Args:
        sections: 解析器讀出的 (位置, 文字)，例如 PDF 每一頁是
            ("第 3 頁", 該頁文字)。條文可以跨頁。
        chunk_size: 每片的字數上限；超過時依句號再切。

    Returns:
        (位置, 文字) 的列表；位置是「第二章 › 第五條（第 3 頁）」這種
        格式，頁碼是這一條開始的那一頁。不像法規類文件時回傳 None。
    """
    lines = [
        (location, line.strip())
        for location, text in sections
        for line in text.splitlines()
        if line.strip()
    ]
    for kind in ("article", "point"):
        if _count(lines, kind) >= _MIN_UNITS:
            return _pieces(_units(lines, kind), chunk_size)
    return None


def _normal(line: str) -> str:
    """比對用：全形數字、空白轉半形（存進片段的還是原文）。"""
    return unicodedata.normalize("NFKC", line)


def _boundary(line: str, kind: str, last: int) -> tuple[str, int] | None:
    """這一行是新的一條（點）時，回傳 (名稱, 編號)。"""
    line = _normal(line)
    if kind == "article":
        match = _ARTICLE.match(line)
        if not match:
            return None
        number = numeral(match.group(1))
        if not last <= number <= last + _MAX_JUMP or number < 1:
            return None
        name = f"第{match.group(1)}條"
        if match.group(2):
            name += f"之{match.group(2)}"
        return name, number
    match = _POINT.match(line)
    if not match:
        return None
    number = numeral(match.group(1))
    if number != last + 1:
        return None
    return f"第{match.group(1)}點", number


def _count(lines: list[tuple[str, str]], kind: str) -> int:
    last, found = 0, 0
    for _, line in lines:
        hit = _boundary(line, kind, last)
        if hit:
            last = hit[1]
            found += 1
    return found


def _units(lines: list[tuple[str, str]], kind: str) -> list[tuple[str, str]]:
    """切成一條一段：(位置, 文字)。第一條之前的前言自成一段。"""
    units: list[tuple[str, str, list[str]]] = []
    chapter, last = "", 0
    current_label, current_page, buffer = "", "", []

    def flush() -> None:
        if buffer:
            units.append((current_label, current_page, list(buffer)))
        buffer.clear()

    for location, line in lines:
        page = _page_of(location)
        if _CHAPTER.match(_normal(line)) and len(line) <= _CHAPTER_CHARS:
            flush()
            chapter = re.sub(r"\s+", " ", _normal(line))
            current_label, current_page = chapter, page
            buffer.append(line)
            continue
        hit = _boundary(line, kind, last)
        if hit:
            last = hit[1]
            # 章節標題後面緊接著第一條：標題併進這一條。
            heading_only = (
                len(buffer) == 1 and chapter and current_label == chapter
            )
            if not heading_only:
                flush()
                current_page = page
            current_label = f"{chapter} › {hit[0]}" if chapter else hit[0]
        elif not buffer:
            current_page = page
        buffer.append(line)
    flush()
    return [
        (_location(label, page), "\n".join(body)) for label, page, body in units
    ]


def _page_of(location: str) -> str:
    match = _PAGE.search(location)
    return f"第 {match.group(1)} 頁" if match else ""


def _location(label: str, page: str) -> str:
    if label and page:
        return f"{label}（{page}）"
    return label or page


def _pieces(
    units: list[tuple[str, str]], chunk_size: int
) -> list[tuple[str, str]]:
    """超過字數上限的條文依句號、分號或換行再切；還是太長就硬切。"""
    out: list[tuple[str, str]] = []
    for location, text in units:
        if len(text) <= chunk_size:
            out.append((location, text))
            continue
        buffer = ""
        for sentence in re.split(r"(?<=[。；;\n])", text):
            while len(sentence) > chunk_size:
                if buffer:
                    out.append((location, buffer.strip()))
                    buffer = ""
                out.append((location, sentence[:chunk_size].strip()))
                sentence = sentence[chunk_size:]
            if buffer and len(buffer) + len(sentence) > chunk_size:
                out.append((location, buffer.strip()))
                buffer = ""
            buffer += sentence
        if buffer.strip():
            out.append((location, buffer.strip()))
    return [(location, text) for location, text in out if text]
