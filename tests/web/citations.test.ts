import { describe, expect, it } from "vitest";
import {
  citationsByBlock,
  parseCitation,
  parseSearchResult,
  sourceUrl,
  splitCitations,
} from "../../web/src/components/chat/citations.ts";
import type { Block, Step } from "../../web/src/transcript.ts";

const RESULT = [
  "[1] 來源：行內規範 / R03_分級辦法.pdf › 第五點（第 2 頁）\n高風險 AI 系統應經 AI 專責主管核准。",
  "[2] 來源：公開規範 / FSC-01.txt\n第十九條 委外應簽訂書面契約。",
].join("\n\n---\n\n");

function search(result: string, id = "s1"): Step {
  return {
    id,
    name: "search_knowledge",
    args: { query: "x" },
    rawArgs: "",
    result,
    status: "done",
  };
}

describe("知識庫出處", () => {
  it("拆開出處文字", () => {
    expect(parseCitation("行內規範 / sub/R03.pdf › 第五點（第 2 頁）")).toEqual(
      {
        base: "行內規範",
        path: "sub/R03.pdf",
        location: "第五點（第 2 頁）",
      },
    );
    expect(parseCitation("hr/leave.md")).toEqual({
      base: "",
      path: "hr/leave.md",
      location: "",
    });
  });

  it("讀出 search_knowledge 的每一筆與頁碼", () => {
    const hits = parseSearchResult(RESULT);
    expect(
      hits.map((hit) => [hit.number, hit.base, hit.path, hit.page]),
    ).toEqual([
      [1, "行內規範", "R03_分級辦法.pdf", 2],
      [2, "公開規範", "FSC-01.txt", undefined],
    ]);
    expect(hits[1]?.excerpt).toBe("第十九條 委外應簽訂書面契約。");
    expect(parseSearchResult("知識庫裡沒有找到相關的內容。")).toEqual([]);
  });

  it("每段文字對照同一輪之前最近一次搜尋；還沒搜尋過的文字不處理", () => {
    const blocks: Block[] = [
      { kind: "text", key: "t0", text: "先查一下", streaming: false },
      { kind: "steps", key: "s", steps: [search(RESULT)] },
      { kind: "text", key: "t1", text: "依 [1]", streaming: false },
      {
        kind: "steps",
        key: "s2",
        steps: [search("[1] 來源：別的.md\n內容", "s2")],
      },
      { kind: "text", key: "t2", text: "依 [1][2]", streaming: false },
    ];
    const found = citationsByBlock(blocks);
    expect(found.has("t0")).toBe(false);
    expect(found.get("t1")?.get(1)?.path).toBe("R03_分級辦法.pdf");
    expect(found.get("t2")?.get(1)?.path).toBe("別的.md");
    expect(found.get("t2")?.get(2)?.path).toBe("FSC-01.txt");
  });

  it("拆出文字裡的引用編號", () => {
    expect(splitCitations("見 [1, 3] 與 [2]。")).toEqual([
      "見 ",
      [1, 3],
      " 與 ",
      [2],
      "。",
    ]);
    expect(splitCitations("沒有引用")).toEqual(["沒有引用"]);
  });

  it("原文網址帶知識庫名稱與路徑", () => {
    const [hit] = parseSearchResult(RESULT);
    expect(hit && sourceUrl(hit)).toBe(
      `/api/knowledge/source?base=${encodeURIComponent("行內規範")}&path=${encodeURIComponent("R03_分級辦法.pdf")}`,
    );
  });
});
