import { describe, expect, it } from "vitest";
import type { SessionDetail } from "../src/web/protocol.ts";
import { buildTurns, resultPreview } from "../web/src/transcript.ts";

describe("resultPreview", () => {
  it("把排版過的 JSON 物件壓成一行", () => {
    const text = JSON.stringify({ month: "2026-10", total: 192000 }, null, 2);
    expect(resultPreview(text)).toBe('{"month":"2026-10","total":192000}');
  });

  it("把排版過的 JSON 陣列壓成一行", () => {
    const text = JSON.stringify(["2026-09", "2026-10"], null, 2);
    expect(resultPreview(text)).toBe('["2026-09","2026-10"]');
  });

  it("一般文字取第一個非空白的行", () => {
    expect(resultPreview("\n\n  # 2026-10 銷售報告\n\n內容")).toBe(
      "# 2026-10 銷售報告",
    );
  });

  it("看起來像 JSON 但解析不了時當成一般文字", () => {
    expect(resultPreview("{ 不是 JSON\n第二行")).toBe("{ 不是 JSON");
  });

  it("太長時截斷", () => {
    const text = JSON.stringify({ items: "字".repeat(200) }, null, 2);
    const preview = resultPreview(text, 20);
    expect(preview).toHaveLength(21);
    expect(preview.endsWith("…")).toBe(true);
  });

  it("沒有結果時回傳空字串", () => {
    expect(resultPreview(undefined)).toBe("");
    expect(resultPreview("   ")).toBe("");
  });
});

describe("壓縮標記", () => {
  const detail = (messages: unknown[]) =>
    ({
      summary: { status: "idle" },
      approvals: [],
      messages,
      partial: "",
    }) as unknown as SessionDetail;
  const kinds = (messages: unknown[]) =>
    buildTurns(detail(messages), {}).map((turn) => [
      turn.user ?? "",
      ...turn.blocks.map((block) => block.kind),
    ]);
  const record = (keepFrom: number) => ({
    role: "harness",
    type: "compaction",
    keep_from: keepFrom,
    summary: "摘要",
    reason: "threshold",
  });

  it("顯示在保留的第一則訊息前面，而不是紀錄寫入的位置", () => {
    const messages = [
      { role: "user", content: "一" },
      { role: "assistant", content: "答一" },
      { role: "user", content: "二" },
      { role: "assistant", content: "答二" },
      record(3),
      { role: "harness", type: "usage", tokens: 100, estimate: 90 },
    ];
    expect(kinds(messages)).toEqual([
      ["一", "text"],
      ["二", "compaction", "text"],
    ]);
  });

  it("全部摘要時顯示在最後", () => {
    const messages = [
      { role: "user", content: "一" },
      { role: "assistant", content: "答一" },
      record(2),
      { role: "user", content: "二" },
      { role: "assistant", content: "答二" },
    ];
    expect(kinds(messages)).toEqual([
      ["一", "text", "compaction"],
      ["二", "text"],
    ]);
  });
});
