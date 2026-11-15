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
位置前面，例如「第二章 › 第五條」；「附錄」「附件」「參考資料」這類
標題會結束前面的章節，後面的內容記在它們底下。單一條文超過字數上限時，
先依「（一）」這類款目、再依句號切成幾片，每片的頁碼是那一片開始的
那一頁。
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
# 結束正文章節的標題：附錄、附件、附表、參考資料等。
_APPENDIX = re.compile(r"^(附\s*[錄件表圖則]|參考(?:資料|文獻))")
# 目錄的引導點，例如「第一章 總則 ........ 3」。
_LEADER = re.compile(r"(?:\.{4,}|…{2,}|[‧·•．]{4,})")
# 一頁有這麼多行帶引導點就當成目錄頁，裡面的章節標題不算數。
_TOC_LINES = 3
# 頁尾的頁碼，例如「附件 3-1」「附表 2-ii」。
_PAGE_FOOTER = re.compile(
    r"^附\s*[錄件表圖]\s*[0-9A-Za-z一二三四五六七八九十]*\s*[-－–]\s*[0-9ivxIVX]+$"
)
# 條文、要點底下的款目，例如「（一）」「(四)原則四：…」，要在行首。
_SUB_ITEM = re.compile(r"(?m)^[（(]\s*[一二三四五六七八九十]+\s*[)）]")
# 同一行出現在這麼多頁以上就是頁首頁尾，不當章節標題。
_REPEATED_PAGES = 3
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
        chunk_size: 每片的字數上限；超過時依款目、句號再切。

    Returns:
        (位置, 文字) 的列表；位置是「第二章 › 第五條（第 3 頁）」這種
        格式，頁碼是這一條開始的那一頁。不像法規類文件時回傳 None。
    """
    # 目錄頁（有頁碼的位置才看得出一頁）、帶引導點的行、頁首頁尾只當
    # 內文，不當章節標題或新的一條。
    toc = {
        location
        for location, text in sections
        if _PAGE.search(location)
        and sum(bool(_LEADER.search(line)) for line in text.splitlines())
        >= _TOC_LINES
    }
    pages_of: dict[str, set[str]] = {}
    for location, text in sections:
        for line in text.splitlines():
            pages_of.setdefault(_normal(line.strip()), set()).add(location)
    lines = [
        (
            location,
            line.strip(),
            location in toc
            or bool(_LEADER.search(line))
            or bool(_PAGE_FOOTER.match(_normal(line.strip())))
            or (
                _heading(line.strip())
                and len(pages_of.get(_normal(line.strip()), ()))
                >= _REPEATED_PAGES
            ),
        )
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


def _heading(line: str) -> bool:
    """章節標題（第一章）或附錄、附件、參考資料這類標題。"""
    if len(line) > _CHAPTER_CHARS or _LEADER.search(line):
        return False
    normal = _normal(line)
    # 結尾是頁碼的是目錄，例如「第六章 雲端服務維運控管 24」。
    if re.search(r"\s\d{1,3}$", normal):
        return False
    if _CHAPTER.match(normal):
        return True
    return bool(_APPENDIX.match(normal)) and "。" not in normal


def _count(lines: list[tuple[str, str, bool]], kind: str) -> int:
    last, found = 0, 0
    for _, line, toc in lines:
        if toc:
            continue
        if kind == "point" and _heading(line):
            last = 0
            continue
        hit = _boundary(line, kind, last)
        if hit:
            last = hit[1]
            found += 1
    return found


def _units(
    lines: list[tuple[str, str, bool]], kind: str
) -> list[tuple[str, list[tuple[str, str]]]]:
    """切成一條一段：(標籤, [(頁碼, 一行)…])。第一條之前的前言自成一段。"""
    units: list[tuple[str, list[tuple[str, str]]]] = []
    chapter, last = "", 0
    label: str = ""
    buffer: list[tuple[str, str]] = []

    def flush() -> None:
        if buffer:
            units.append((label, list(buffer)))
        buffer.clear()

    for location, line, toc in lines:
        page = _page_of(location)
        normal = _normal(line)
        if toc:
            buffer.append((page, line))
            continue
        if _heading(line):
            flush()
            if kind == "point":
                # 要點常常每章從「一、」重新編號。
                last = 0
            chapter = re.sub(r"\s+", " ", normal).rstrip("—－-：: ")
            label = chapter
            buffer.append((page, line))
            continue
        hit = _boundary(line, kind, last)
        if hit:
            last = hit[1]
            # 章節標題後面緊接著第一條：標題併進這一條。
            heading_only = len(buffer) == 1 and chapter and label == chapter
            if not heading_only:
                flush()
            label = f"{chapter} › {hit[0]}" if chapter else hit[0]
        buffer.append((page, line))
    flush()
    return units


def _page_of(location: str) -> str:
    match = _PAGE.search(location)
    return f"第 {match.group(1)} 頁" if match else ""


def _location(label: str, page: str) -> str:
    if label and page:
        return f"{label}（{page}）"
    return label or page


def _pieces(
    units: list[tuple[str, list[tuple[str, str]]]], chunk_size: int
) -> list[tuple[str, str]]:
    """組成 (位置, 文字)；超過字數上限的條文依句號、分號或換行再切，
    還是太長就硬切。每片的頁碼是那一片開始的那一頁。"""
    out: list[tuple[str, str]] = []
    for label, body in units:
        text = "\n".join(line for _, line in body)
        # 每一行在 text 裡開始的位置，用來查一片從哪一頁開始。
        starts, at = [], 0
        for page, line in body:
            starts.append((at, page))
            at += len(line) + 1
        for offset, piece in _split_text(text, chunk_size):
            stripped = piece.strip()
            if stripped:
                begin = offset + len(piece) - len(piece.lstrip())
                out.append(
                    (_location(label, _page_at(starts, begin)), stripped)
                )
    return out


def _split_text(text: str, chunk_size: int) -> list[tuple[int, str]]:
    """切成不超過 chunk_size 的片段：(開始位置, 文字)。

    先依「（一）」「(二)」這類款目分段，整段放得下就不拆開，讓每片盡量
    從一個款目開頭；單一款目太長時再依句號、分號或換行切。
    """
    if len(text) <= chunk_size:
        return [(0, text)]
    starts = [0] + [
        match.start() for match in _SUB_ITEM.finditer(text) if match.start() > 0
    ]
    blocks = [
        (start, text[start:end])
        for start, end in zip(starts, [*starts[1:], len(text)], strict=True)
    ]
    out: list[tuple[int, str]] = []
    buffer, buffer_at = "", 0
    for start, block in blocks:
        if buffer and len(buffer) + len(block) > chunk_size:
            out.append((buffer_at, buffer))
            buffer = ""
        if len(block) > chunk_size:
            out += [
                (start + offset, piece)
                for offset, piece in _split_sentences(block, chunk_size)
            ]
            continue
        if not buffer:
            buffer_at = start
        buffer += block
    if buffer:
        out.append((buffer_at, buffer))
    return out


def _split_sentences(text: str, chunk_size: int) -> list[tuple[int, str]]:
    """依句號、分號或換行切成不超過 chunk_size 的片段；還是太長就硬切。"""
    out: list[tuple[int, str]] = []
    buffer, buffer_at, offset = "", 0, 0
    for sentence in re.split(r"(?<=[。；;\n])", text):
        while len(sentence) > chunk_size:
            if buffer:
                out.append((buffer_at, buffer))
                buffer = ""
            out.append((offset, sentence[:chunk_size]))
            sentence = sentence[chunk_size:]
            offset += chunk_size
        if buffer and len(buffer) + len(sentence) > chunk_size:
            out.append((buffer_at, buffer))
            buffer = ""
        if not buffer:
            buffer_at = offset
        buffer += sentence
        offset += len(sentence)
    if buffer:
        out.append((buffer_at, buffer))
    return out


def _page_at(starts: list[tuple[int, str]], offset: int) -> str:
    """text 裡 offset 這個位置所在的頁碼（starts 是每一行的開始位置）。"""
    found = ""
    for start, page in starts:
        if start > offset:
            break
        found = page or found
    return found
