/**
 * 回覆用的 remark 外掛（單獨一個檔，測試也用同一份設定）。
 *
 * remark-cjk-friendly：CommonMark 的規則下，`**` 內側緊接中文標點
 * （「」、（）、。）而外側是中文字時不算粗體，例如
 * `一套**「風險對稱」**的`，畫面上會留下星號。這個外掛放寬中日韓文字
 * 旁邊的規則；刪除線（~~）用另一個外掛。
 *
 * remark-math 只認 $$…$$，單一 $ 由 math.ts 先挑出 LaTeX 再改寫。
 */

import type { Options } from "react-markdown";
import remarkCjkFriendly from "remark-cjk-friendly";
import remarkCjkFriendlyGfmStrikethrough from "remark-cjk-friendly-gfm-strikethrough";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";

export type RemarkPlugins = NonNullable<Options["remarkPlugins"]>;

export const remarkPlugins: RemarkPlugins = [
  remarkGfm,
  remarkCjkFriendly,
  remarkCjkFriendlyGfmStrikethrough,
  [remarkMath, { singleDollarTextMath: false }],
];
