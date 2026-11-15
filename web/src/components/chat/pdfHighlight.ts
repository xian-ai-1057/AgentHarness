/**
 * 在 PDF 的文字裡找出引用的段落，算出要螢光標示的範圍。
 *
 * PDF.js 讀出的文字是一段一段的（通常一行一段，見 getTextContent 的
 * items），知識庫的片段則是 pypdf 讀出來的文字，兩邊的空白、換行和
 * 全形半形不一定相同，所以比對前都先做 NFKC 並去掉空白。
 *
 * 片段的開頭可能不在這一頁（條文從上一頁開始），中間也可能夾著頁首頁尾，
 * 所以不要求整段完全相同：從片段前面找第一個對得到的小段（錨點）當起點，
 * 從後面找最後一個對得到的當終點，兩者之間就是要標示的範圍。片段的後半
 * 不在這一頁時，回傳還沒對到的部分，由呼叫端拿去下一頁繼續找。
 *
 * 純函式，不碰 PDF.js，測試可以直接引用。
 */

/** 一頁的文字，每個字記著來自哪一段、在那一段裡的位置。 */
export interface PageText {
  /** 正規化後的文字（NFKC、沒有空白）。 */
  text: string;
  /** text 每個字來自第幾段。 */
  item: number[];
  /** text 每個字在那一段原文裡的位置。 */
  offset: number[];
  /** 每一段原文的字數。 */
  lengths: number[];
}

/** 一段文字裡要標示的部分：from、to 是佔這段寬度的比例（0～1）。 */
export interface ItemMark {
  item: number;
  from: number;
  to: number;
}

export interface PageMatch {
  marks: ItemMark[];
  /** 片段裡還沒對到的部分（已正規化）；整段都對到時是空字串。 */
  rest: string;
  /** 第一個錨點在片段裡的位置，越小表示片段的開頭越可能在這一頁。 */
  firstAnchor: number;
}

/** 錨點的長度：太短容易對到別的地方（例如「第一條」），太長容易對不到。 */
const ANCHOR = 16;
/** 找錨點時每次往後移幾個字。 */
const STEP = 4;
/** 剩下不到這麼多字就當作整段都對到了（頁尾的小差異）。 */
const TAIL = 12;

/** 比對用：NFKC 並去掉空白。 */
export function normalizeForMatch(text: string): string {
  return text.normalize("NFKC").replace(/\s+/g, "");
}

/** 把一頁的文字段落（PDF.js 的 item.str）整理成可以比對的形式。 */
export function pageText(items: readonly string[]): PageText {
  const page: PageText = { text: "", item: [], offset: [], lengths: [] };
  const parts: string[] = [];
  items.forEach((str, index) => {
    page.lengths.push(str.length);
    for (let at = 0; at < str.length; ) {
      const code = str.codePointAt(at) ?? 0;
      const char = String.fromCodePoint(code);
      for (const normal of normalizeForMatch(char)) {
        parts.push(normal);
        page.item.push(index);
        page.offset.push(at);
      }
      at += char.length;
    }
  });
  // 用 parts 而不是逐字串接，避免長文件時一直複製字串。
  page.text = parts.join("");
  return page;
}

/**
 * 在一頁裡找引用的段落。
 *
 * @param page pageText 的結果。
 * @param excerpt 引用的片段（已用 normalizeForMatch 正規化）。
 * @returns 要標示的部分；這一頁完全對不到時是 null。
 */
export function matchPage(page: PageText, excerpt: string): PageMatch | null {
  if (!excerpt || !page.text) return null;
  const size = Math.min(ANCHOR, excerpt.length);
  const offsets: number[] = [];
  for (let at = 0; at + size <= excerpt.length; at += STEP) offsets.push(at);
  const last = excerpt.length - size;
  if (offsets.at(-1) !== last) offsets.push(last);

  // 起點：片段裡最前面、在這一頁找得到的錨點。
  let first = -1;
  let start = -1;
  for (const at of offsets) {
    const found = page.text.indexOf(excerpt.slice(at, at + size));
    if (found >= 0) {
      first = at;
      start = found;
      break;
    }
  }
  if (start < 0) return null;

  // 終點：片段裡最後面、在起點之後找得到的錨點。範圍太長表示對到了
  // 別的地方，改用片段的長度估計。
  let end = start + size;
  let reached = first + size;
  for (let index = offsets.length - 1; index >= 0; index--) {
    const at = offsets[index] ?? 0;
    if (at <= first) break;
    const found = page.text.indexOf(excerpt.slice(at, at + size), start);
    if (found < 0) continue;
    const span = found + size - start;
    if (span <= (at + size - first) * 1.5 + 40) {
      end = found + size;
      reached = at + size;
    }
    break;
  }
  if (end === start + size && reached === first + size) {
    // 只對到一個錨點：照片段剩下的長度往後標，最多到這一頁結束。
    end = Math.min(page.text.length, start + excerpt.length - first);
    reached = first + (end - start);
  }
  // 錨點是固定長度的，頭尾不滿一個錨點的字逐字往外延伸。
  while (
    first > 0 &&
    start > 0 &&
    page.text[start - 1] === excerpt[first - 1]
  ) {
    start--;
    first--;
  }
  while (
    reached < excerpt.length &&
    end < page.text.length &&
    page.text[end] === excerpt[reached]
  ) {
    end++;
    reached++;
  }
  const rest = excerpt.length - reached <= TAIL ? "" : excerpt.slice(reached);
  return { marks: marksFor(page, start, end), rest, firstAnchor: first };
}

/** 把 text 裡 [start, end) 的範圍換成每一段要標示的比例。 */
function marksFor(page: PageText, start: number, end: number): ItemMark[] {
  const marks: ItemMark[] = [];
  for (let at = start; at < end; at++) {
    const item = page.item[at] ?? 0;
    const length = page.lengths[item] || 1;
    const from = (page.offset[at] ?? 0) / length;
    const to = ((page.offset[at] ?? 0) + 1) / length;
    const current = marks.at(-1);
    if (current && current.item === item) {
      current.from = Math.min(current.from, from);
      current.to = Math.min(1, Math.max(current.to, to));
    } else {
      marks.push({ item, from, to: Math.min(1, to) });
    }
  }
  return marks;
}

/**
 * 決定從哪一頁開始標示。
 *
 * 有頁碼而且那一頁對得到時用那一頁；否則用片段開頭最可能在的那一頁
 * （第一個錨點最前面的，一樣時取前面的頁）。
 *
 * @param pages 每一頁的文字（索引 0 是第 1 頁），還沒讀的頁可以是 undefined。
 * @param page 出處的頁碼（從 1 開始）。
 * @returns 頁碼（從 1 開始）；都對不到時是 undefined。
 */
export function startPage(
  pages: readonly (PageText | undefined)[],
  excerpt: string,
  page?: number,
): number | undefined {
  if (page !== undefined) {
    const cited = pages[page - 1];
    if (cited && matchPage(cited, excerpt)) return page;
  }
  let best: number | undefined;
  let bestAnchor = Number.POSITIVE_INFINITY;
  pages.forEach((text, index) => {
    if (!text) return;
    const match = matchPage(text, excerpt);
    if (match && match.firstAnchor < bestAnchor) {
      best = index + 1;
      bestAnchor = match.firstAnchor;
    }
  });
  return best;
}

/**
 * 從 first 這一頁開始標示整段引用；片段跨頁時繼續標下一頁。
 *
 * @returns 頁碼（從 1 開始）→ 那一頁要標示的部分。
 */
export function matchFrom(
  pages: readonly (PageText | undefined)[],
  excerpt: string,
  first: number,
): Map<number, ItemMark[]> {
  const result = new Map<number, ItemMark[]>();
  let rest = excerpt;
  // 一段引用頂多跨幾頁；避免頁首頁尾對到時一路標到文件結尾。
  for (let page = first; rest && page < first + 4; page++) {
    const text = pages[page - 1];
    if (!text) break;
    const match = matchPage(text, rest);
    if (!match) break;
    result.set(page, match.marks);
    rest = match.rest;
  }
  return result;
}
