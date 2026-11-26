/** 數學式的前處理（純函式，方便測試）。 */

const MATH = /\$\$/;
const FENCE = /^[ \t>]*(`{3,}|~{3,})/;

/**
 * 模型常把整行公式寫成 `$$…$$` 放在同一行；Markdown 會把它當成行內
 * 公式而縮得很小。整行只有一個 $$…$$ 時改成獨立的區塊公式。程式碼
 * 區塊裡的內容不動。
 */
export function displayMath(text: string): string {
  if (!MATH.test(text)) return text;
  let fence: string | null = null;
  return text
    .split("\n")
    .map((line) => {
      const marker = line.match(FENCE)?.[1];
      if (marker) {
        if (fence === null) fence = marker;
        else if (marker.startsWith(fence)) fence = null;
        return line;
      }
      if (fence !== null) return line;
      const match = line.match(/^(\s*)\$\$([^$]+)\$\$\s*$/);
      if (!match) return line;
      const indent = match[1] ?? "";
      return `${indent}$$\n${indent}${(match[2] ?? "").trim()}\n${indent}$$`;
    })
    .join("\n");
}

// 看起來是 LaTeX：有 \指令，或上下標（x^2、a_1、x_{i}）。
// HOME_DIR 這種底線後面接一串字母的不算。
const LATEX = /\\[A-Za-z]+|[\^_](?:\{|[A-Za-z0-9](?![A-Za-z0-9]))/;
// 整段只是 \text{…}：模型拿數學式包一般文字，直接當文字顯示。
const TEXT_ONLY = /^\\text\{([^{}\\$]*)\}$/;
const WORD = /[A-Za-z0-9]/;
const SPACE = /\s/;
const DIGIT = /[0-9]/;

/** line[start] 是 $ 時，回傳成對的單一 $ 行內公式的結尾位置（後一個 $）。 */
function closingDollar(line: string, start: number): number | undefined {
  // 前面緊接英數字是金額（NT$、US$），後面是空白也不算。
  if (start > 0 && WORD.test(line[start - 1] ?? "")) return undefined;
  const first = line[start + 1];
  if (first === undefined || SPACE.test(first)) return undefined;
  for (let j = start + 1; j < line.length; j++) {
    const ch = line[j];
    if (ch === "\\") {
      j++;
      continue;
    }
    if (ch !== "$") continue;
    // 結尾前面不能是空白，後面不能緊接數字（NT$1,000 到 NT$2,000）。
    if (SPACE.test(line[j - 1] ?? "")) return undefined;
    if (DIGIT.test(line[j + 1] ?? "") || line[j + 1] === "$") return undefined;
    return j;
  }
  return undefined;
}

/** 行內程式碼的結尾位置：長度一樣的一串反引號；沒有就只跳過開頭這串。 */
function codeSpanEnd(line: string, start: number): number {
  const run = line.slice(start).match(/^`+/)?.[0] ?? "`";
  const pattern = /`+/g;
  pattern.lastIndex = start + run.length;
  for (let next = pattern.exec(line); next; next = pattern.exec(line)) {
    if (next[0].length === run.length) return next.index + run.length;
  }
  return start + run.length;
}

/** 一行文字裡的單一 $ 公式；行內程式碼與 $$…$$ 不動。 */
function inlineLine(line: string): string {
  if (!line.includes("$")) return line;
  let out = "";
  let i = 0;
  while (i < line.length) {
    const ch = line[i] as string;
    let stop = i + 1;
    if (ch === "\\") {
      stop = i + 2;
    } else if (ch === "`") {
      stop = codeSpanEnd(line, i);
    } else if (ch === "$" && line[i + 1] === "$") {
      // 已經是 $$…$$，整段照抄。
      const end = line.indexOf("$$", i + 2);
      stop = end === -1 ? line.length : end + 2;
    } else if (ch === "$") {
      const end = closingDollar(line, i);
      const content = end === undefined ? "" : line.slice(i + 1, end);
      if (end !== undefined && LATEX.test(content)) {
        out += content.match(TEXT_ONLY)?.[1] ?? `$$${content}$$`;
        i = end + 1;
        continue;
      }
    }
    out += line.slice(i, stop);
    i = stop;
  }
  return out;
}

/**
 * 單一個 $ 包起來的 LaTeX（$\rightarrow$、$x^2$）改寫成行內的 $$…$$。
 * remark-math 關掉了單一 $，因為回覆裡常有 NT$1,000 到 NT$2,000 這種
 * 金額；這裡只挑內容看起來是 LaTeX 的，而且 $ 前面不是英數字、結尾
 * 後面不是數字。只包了 \text{…} 的直接改成一般文字。程式碼區塊、
 * 行內程式碼、區塊公式裡的內容不動。
 */
export function inlineMath(text: string): string {
  if (!text.includes("$")) return text;
  let fence: string | null = null;
  let block = false;
  return text
    .split("\n")
    .map((line) => {
      const marker = block ? undefined : line.match(FENCE)?.[1];
      if (marker) {
        if (fence === null) fence = marker;
        else if (marker.startsWith(fence)) fence = null;
        return line;
      }
      if (fence !== null) return line;
      if (/^[ \t>]*\$\$/.test(line) && !/\$\$.*\$\$/.test(line)) {
        // 區塊公式的開頭或結尾（$$ 自己一行）。
        block = !block;
        return line;
      }
      if (block) return line;
      return inlineLine(line);
    })
    .join("\n");
}

/** 送進 Markdown 之前的數學式前處理。 */
export function prepareMath(text: string): string {
  return inlineMath(displayMath(text));
}
