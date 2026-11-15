/** 知識庫的純函式：對話裡勾選知識庫、管理平台的設定表單。 */

import { describe, expect, it } from "vitest";
import type {
  KnowledgeAdminBase,
  KnowledgeBaseInfo,
  SessionOptions,
} from "../../src/web/protocol.ts";
import {
  applySearchChoice,
  describeSearch,
  draftDirty,
  searchChoice,
  settingsChanges,
  toSettingsDraft,
} from "../../web/src/components/admin/knowledgeForm.ts";
import {
  agentKnowledge,
  chosenKnowledge,
  toggleKnowledge,
} from "../../web/src/components/chat/options.ts";

const BASES: KnowledgeBaseInfo[] = [
  { id: "default", name: "預設知識庫", description: "" },
  { id: "hr", name: "人資規章", description: "" },
  { id: "it", name: "資訊手冊", description: "" },
];

const options = (knowledge?: string[] | null): SessionOptions => ({
  model: null,
  tools: null,
  skills: [],
  knowledge,
});

describe("對話裡勾選知識庫", () => {
  it("沒有另外勾選時跟著 agent 的預設", () => {
    expect(chosenKnowledge(options(), ["default"])).toEqual(["default"]);
    expect(chosenKnowledge(options(["it"]), ["default"])).toEqual(["it"]);
  });

  it("勾回 agent 的預設時存成 null，其他照知識庫的順序", () => {
    expect(toggleKnowledge(options(), ["default"], BASES, "it")).toEqual([
      "default",
      "it",
    ]);
    expect(
      toggleKnowledge(options(["it", "default"]), ["default"], BASES, "it"),
    ).toBeNull();
    expect(toggleKnowledge(options(), ["default"], BASES, "default")).toEqual(
      [],
    );
  });

  it("agent 的預設只留這個人可以用的", () => {
    const project = { knowledgeBases: BASES.slice(0, 2) };
    expect(
      agentKnowledge(project as never, { knowledge: ["hr", "it"] } as never),
    ).toEqual(["hr"]);
    expect(agentKnowledge(project as never, undefined)).toEqual([]);
  });
});

const BASE: KnowledgeAdminBase = {
  id: "hr",
  name: "人資規章",
  description: "",
  builtin: false,
  path: "knowledge/hr",
  documents: 2,
  settings: { name: "人資規章", chunkSize: 500 },
  retrieval: {
    searchMode: "bm25",
    embeddingModel: null,
    chunkSize: 500,
    chunking: "paragraph",
    reranker: null,
    rerankCandidates: 20,
    minSimilarity: null,
    minRerankScore: null,
  },
  agents: [],
  maintainers: ["u1"],
};

describe("知識庫設定表單", () => {
  it("沒改時不算改過，也沒有要送出的欄位", () => {
    const draft = toSettingsDraft(BASE);
    expect(draftDirty(BASE, draft)).toBe(false);
    expect(settingsChanges(BASE, draft)).toEqual({ changes: {} });
  });

  it("清空的設定送 null，數字轉成數字", () => {
    const draft = {
      ...toSettingsDraft(BASE),
      chunkSize: "",
      minSimilarity: "0.3",
      reranker: " cohere/rerank-v3.5 ",
      maintainers: ["u2"],
    };
    expect(settingsChanges(BASE, draft)).toEqual({
      changes: {
        chunkSize: null,
        minSimilarity: 0.3,
        reranker: "cohere/rerank-v3.5",
        maintainers: ["u2"],
      },
    });
  });

  it("切片方式：選了送出值，改回沒有設定送 null", () => {
    expect(
      settingsChanges(BASE, {
        ...toSettingsDraft(BASE),
        chunking: "regulation",
      }),
    ).toEqual({ changes: { chunking: "regulation" } });
    const base = {
      ...BASE,
      settings: { ...BASE.settings, chunking: "regulation" as const },
    };
    expect(
      settingsChanges(base, { ...toSettingsDraft(base), chunking: "" }),
    ).toEqual({ changes: { chunking: null } });
  });

  it("名稱不能空白，整數欄位不能有小數", () => {
    expect(
      settingsChanges(BASE, { ...toSettingsDraft(BASE), name: " " }),
    ).toEqual({ error: "請輸入名稱" });
    expect(
      settingsChanges(BASE, { ...toSettingsDraft(BASE), chunkSize: "1.5" }),
    ).toEqual({ error: "切片長度必須是整數" });
  });

  it("維護者順序不同不算改過", () => {
    const base = { ...BASE, maintainers: ["u1", "u2"] };
    expect(
      draftDirty(base, { ...toSettingsDraft(base), maintainers: ["u2", "u1"] }),
    ).toBe(false);
  });
});

describe("Embedding 模型下拉選單", () => {
  const empty = { searchMode: "" as const, embeddingModel: "" };

  it("沒有設定時：預設知識庫是演算法，其他知識庫是沿用", () => {
    expect(searchChoice(empty, true, false)).toBe("bm25");
    expect(searchChoice(empty, false, false)).toBe("");
    expect(
      searchChoice({ searchMode: "", embeddingModel: "bge-m3" }, false, false),
    ).toBe("model:bge-m3");
    expect(
      searchChoice({ searchMode: "keyword", embeddingModel: "" }, true, false),
    ).toBe("keyword");
    expect(searchChoice(empty, false, true)).toBe("custom");
  });

  it("選了之後的 searchMode 與 embeddingModel", () => {
    expect(applySearchChoice("keyword", true)).toEqual({
      searchMode: "keyword",
      embeddingModel: "",
    });
    // 預設知識庫本來就是 BM25；其他知識庫要寫明，才不會沿用預設的模型。
    expect(applySearchChoice("bm25", true)).toEqual(empty);
    expect(applySearchChoice("bm25", false)).toEqual({
      searchMode: "bm25",
      embeddingModel: "",
    });
    expect(applySearchChoice("model:text-embedding-3-small", false)).toEqual({
      searchMode: "",
      embeddingModel: "text-embedding-3-small",
    });
    expect(applySearchChoice("", false)).toEqual(empty);
  });

  it("選模型時送出模型、清掉檢索方式", () => {
    const base = {
      ...BASE,
      settings: { ...BASE.settings, searchMode: "keyword" as const },
    };
    const draft = {
      ...toSettingsDraft(base),
      ...applySearchChoice("model:bge-m3", false),
    };
    expect(settingsChanges(base, draft)).toEqual({
      changes: { searchMode: null, embeddingModel: "bge-m3" },
    });
  });

  it("沿用時顯示預設知識庫實際的檢索方式", () => {
    expect(
      describeSearch({ searchMode: "keyword", embeddingModel: null }),
    ).toBe("關鍵字");
    expect(describeSearch({ searchMode: "bm25", embeddingModel: null })).toBe(
      "演算法（BM25）",
    );
    expect(
      describeSearch({ searchMode: "hybrid", embeddingModel: "bge-m3" }),
    ).toBe("bge-m3");
  });
});
