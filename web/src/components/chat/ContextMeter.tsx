/**
 * 輸入框旁的上下文用量（Python 版，見對話壓縮）。
 *
 * 用量過半才出現，平常不佔位置；點一下會在輸入框填入 /compact，讓使用者
 * 補上要保留的重點後送出。快到自動壓縮的門檻時改用提醒的顏色。
 */

import type { ContextUsage } from "../../../../src/web/protocol.ts";
import { formatTokens } from "../../format.ts";

/** 用量超過上限的這個比例才顯示。 */
const SHOW_RATIO = 0.5;
/** 用量到自動壓縮門檻的這個比例時改用提醒的顏色。 */
const WARN_RATIO = 0.9;

export function ContextMeter({
  usage,
  onCompact,
}: {
  usage: ContextUsage | undefined;
  /** 點了之後要做的事（在輸入框填入 /compact）；沒有時只顯示。 */
  onCompact?: () => void;
}) {
  if (!usage?.window) return null;
  const ratio = usage.tokens / usage.window;
  if (ratio < SHOW_RATIO) return null;
  const percent = Math.min(100, Math.round(ratio * 100));
  const warn =
    usage.threshold !== null && usage.tokens >= usage.threshold * WARN_RATIO;
  const title = contextTitle(usage);
  return (
    <button
      type="button"
      className={`select-chip ch-context${warn ? " warn" : ""}`}
      title={title}
      aria-label={title}
      onClick={onCompact}
      disabled={!onCompact}
    >
      <svg
        className="ch-context-ring"
        viewBox="0 0 20 20"
        width="16"
        height="16"
        aria-hidden="true"
      >
        <circle cx="10" cy="10" r="8" />
        <circle
          cx="10"
          cy="10"
          r="8"
          className="ch-context-used"
          strokeDasharray={`${(percent / 100) * 50.27} 50.27`}
        />
      </svg>
      <span>上下文 {percent}%</span>
    </button>
  );
}

/** 滑鼠移上去時的說明。 */
export function contextTitle(usage: ContextUsage): string {
  const used = `這段對話大約用了 ${formatTokens(usage.tokens)} / ${formatTokens(
    usage.window ?? 0,
  )} tokens 的上下文。`;
  const auto =
    usage.auto && usage.threshold
      ? `到 ${formatTokens(usage.threshold)} 時會自動把較早的內容壓縮成摘要；`
      : "自動壓縮已關閉；";
  return `${used}${auto}點這裡（或輸入 /compact）可以立刻壓縮。`;
}
