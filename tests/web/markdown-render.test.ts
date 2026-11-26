/**
 * 回覆的 Markdown：中文標點旁的粗體、單一 $ 的行內公式。
 * 用和畫面一樣的 remark 外掛解析，檢查得到的節點。
 */

import remarkParse from "remark-parse";
import { unified } from "unified";
import { describe, expect, it } from "vitest";
import { inlineMath, prepareMath } from "../../web/src/components/chat/math.ts";
import { remarkPlugins } from "../../web/src/components/chat/remark.ts";

interface Node {
  type: string;
  value?: string;
  children?: Node[];
}

function parse(text: string): Node {
  const processor = unified().use(remarkParse);
  for (const plugin of remarkPlugins) {
    if (Array.isArray(plugin)) processor.use(plugin[0], plugin[1]);
    else processor.use(plugin as never);
  }
  return processor.runSync(processor.parse(prepareMath(text))) as Node;
}

/** 某種節點裡的文字。 */
function collect(node: Node, type: string, out: string[] = []): string[] {
  if (node.type === type) out.push(flatten(node));
  for (const child of node.children ?? []) collect(child, type, out);
  return out;
}

function flatten(node: Node): string {
  return node.value ?? (node.children ?? []).map(flatten).join("");
}

describe("中文標點旁的粗體", () => {
  it("**「…」** 夾在中文字中間也是粗體", () => {
    const tree = parse("是一套**「風險對稱」**的治理體系");
    expect(collect(tree, "strong")).toEqual(["「風險對稱」"]);
    expect(flatten(tree)).not.toContain("**");
  });

  it("結尾是全形括號、句號時也是粗體", () => {
    const tree = parse(
      "進行了**細粒度（Fine-grained）**的解析，**重點。**接著",
    );
    expect(collect(tree, "strong")).toEqual([
      "細粒度（Fine-grained）",
      "重點。",
    ]);
  });

  it("刪除線也一樣", () => {
    expect(collect(parse("這是~~「舊的」~~說法"), "delete")).toEqual([
      "「舊的」",
    ]);
  });

  it("英文的粗體照舊", () => {
    expect(collect(parse("a **bold** word"), "strong")).toEqual(["bold"]);
  });
});

describe("單一 $ 的行內公式", () => {
  it("$\\rightarrow$ 緊貼中文也排版", () => {
    const tree = parse(
      "**風險越高 $\\rightarrow$ 控制越嚴$\\rightarrow$證據鏈**",
    );
    expect(collect(tree, "inlineMath")).toEqual([
      "\\rightarrow",
      "\\rightarrow",
    ]);
  });

  it("只包 \\text{…} 的改成一般文字", () => {
    expect(inlineMath("$\\text{基本對齊}$，行內流程")).toBe(
      "基本對齊，行內流程",
    );
    const tree = parse(
      "這份文件 $\\text{Guidelines on AI}$ (以下簡稱「指南」)",
    );
    expect(collect(tree, "inlineMath")).toEqual([]);
    expect(flatten(tree)).toBe("這份文件 Guidelines on AI (以下簡稱「指南」)");
  });

  it("上下標也算", () => {
    expect(collect(parse("面積是 $x^2$，第 $a_{i}$ 項"), "inlineMath")).toEqual(
      ["x^2", "a_{i}"],
    );
  });

  it("金額不算數學式", () => {
    for (const text of [
      "費用 NT$1,000 到 NT$2,000",
      "US$5 and US$10",
      "costs $5 or $10",
      "從 $100 漲到 $\\approx 200",
      "路徑 $HOME_DIR/$USER",
    ]) {
      expect(inlineMath(text)).toBe(text);
    }
  });

  it("程式碼與 $$ 區塊裡的不動", () => {
    for (const text of [
      "指令 `echo $\\alpha$` 照抄",
      "```\n$\\alpha$\n```",
      "$$\n\\alpha + $\\beta$\n$$",
      "行內 $$\\alpha$$ 不變",
      "跳脫 \\$\\alpha$ 不算",
    ]) {
      expect(inlineMath(text)).toBe(text);
    }
  });

  it("整行的 $$…$$ 照舊變成區塊公式", () => {
    expect(prepareMath("$$r = \\frac{b}{a}$$\n比例 $r$ 和 $\\beta$")).toBe(
      "$$\nr = \\frac{b}{a}\n$$\n比例 $r$ 和 $$\\beta$$",
    );
  });
});
