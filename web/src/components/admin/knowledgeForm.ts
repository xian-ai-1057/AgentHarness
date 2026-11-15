/** 知識庫設定表單的純函式：草稿與要送出的修改。不碰 window，測試可以直接引用。 */

import type {
  KnowledgeAdminBase,
  KnowledgeModelChoices,
  KnowledgeSearchMode,
  KnowledgeSettings,
} from "../../../../src/web/protocol.ts";

/** 表單裡每一欄都是文字，維護者是 MemberInfo.id 的清單。 */
export interface SettingsDraft {
  name: string;
  description: string;
  /** "" 表示沒有設定：有 embeddingModel 就是 hybrid，沒有就是 bm25。 */
  searchMode: "" | KnowledgeSearchMode;
  embeddingModel: string;
  chunkSize: string;
  /** "" 表示沒有設定（沿用預設或 knowledge 區塊）。 */
  chunking: "" | "paragraph" | "regulation";
  reranker: string;
  rerankCandidates: string;
  minSimilarity: string;
  minRerankScore: string;
  maintainers: string[];
}

const TEXT_KEYS = ["embeddingModel", "reranker"] as const;
const INT_KEYS = ["chunkSize", "rerankCandidates"] as const;
const FLOAT_KEYS = ["minSimilarity", "minRerankScore"] as const;

const LABELS: Record<string, string> = {
  chunkSize: "切片長度",
  chunking: "切片方式",
  rerankCandidates: "候選數",
  minSimilarity: "相似度門檻",
  minRerankScore: "Rerank 分數門檻",
};

export function toSettingsDraft(base: KnowledgeAdminBase): SettingsDraft {
  const own = base.settings;
  const text = (value: unknown) =>
    value === undefined || value === null ? "" : String(value);
  return {
    name: base.name,
    description: base.description,
    searchMode: own.searchMode ?? "",
    embeddingModel: text(own.embeddingModel),
    chunkSize: text(own.chunkSize),
    chunking: own.chunking ?? "",
    reranker: text(own.reranker),
    rerankCandidates: text(own.rerankCandidates),
    minSimilarity: text(own.minSimilarity),
    minRerankScore: text(own.minRerankScore),
    maintainers: base.maintainers ?? [],
  };
}

type Changes = KnowledgeSettings & { maintainers?: string[] };

/**
 * 和原本的設定比較，算出要送給 PATCH /api/knowledge/:id 的欄位。清空的
 * 檢索設定送 null（刪掉，沿用預設）；數字格式不對時回傳錯誤。
 */
export function settingsChanges(
  base: KnowledgeAdminBase,
  draft: SettingsDraft,
): { changes: Changes } | { error: string } {
  const initial = toSettingsDraft(base);
  const changes: Changes = {};
  if (draft.name.trim() !== initial.name) {
    if (!draft.name.trim()) return { error: "請輸入名稱" };
    changes.name = draft.name.trim();
  }
  if (draft.description.trim() !== initial.description) {
    changes.description = draft.description.trim();
  }
  if (draft.chunking !== initial.chunking) {
    changes.chunking = draft.chunking || null;
  }
  if (draft.searchMode !== initial.searchMode) {
    changes.searchMode = draft.searchMode || null;
  }
  for (const key of TEXT_KEYS) {
    const value = draft[key].trim();
    if (value !== initial[key]) changes[key] = value || null;
  }
  for (const key of [...INT_KEYS, ...FLOAT_KEYS]) {
    const value = draft[key].trim();
    if (value === initial[key]) continue;
    if (!value) {
      changes[key] = null;
      continue;
    }
    const number = Number(value);
    const integer = (INT_KEYS as readonly string[]).includes(key);
    if (!Number.isFinite(number) || (integer && !Number.isInteger(number))) {
      return {
        error: `${LABELS[key]}必須是${integer ? "整數" : "數字"}`,
      };
    }
    changes[key] = number;
  }
  if (!sameMembers(draft.maintainers, initial.maintainers)) {
    changes.maintainers = draft.maintainers;
  }
  return { changes };
}

/** 草稿和原本的不一樣嗎（維護者不管順序）。 */
export function draftDirty(
  base: KnowledgeAdminBase,
  draft: SettingsDraft,
): boolean {
  const initial = toSettingsDraft(base);
  return (
    !sameMembers(draft.maintainers, initial.maintainers) ||
    (Object.keys(initial) as (keyof SettingsDraft)[]).some(
      (key) => key !== "maintainers" && draft[key] !== initial[key],
    )
  );
}

function sameMembers(a: string[], b: string[]): boolean {
  if (a.length !== b.length) return false;
  const set = new Set(a);
  return b.every((item) => set.has(item));
}

/**
 * 「Embedding 模型」下拉選單的值：keyword（關鍵字，精確比對）、bm25
 * （演算法）、model:<名稱>、custom（自行輸入），或 ""（沿用預設知識庫，
 * 只有其他知識庫有）。預設知識庫沒有設定時就是 bm25。
 */
export const CUSTOM_CHOICE = "custom";
export const MODEL_PREFIX = "model:";

type SearchFields = Pick<SettingsDraft, "searchMode" | "embeddingModel">;

export function searchChoice(
  fields: SearchFields,
  builtin: boolean,
  custom: boolean,
): string {
  if (fields.searchMode === "keyword" || fields.searchMode === "bm25") {
    return fields.searchMode;
  }
  if (custom) return CUSTOM_CHOICE;
  if (fields.embeddingModel) return MODEL_PREFIX + fields.embeddingModel;
  return builtin ? "bm25" : "";
}

/**
 * 選了下拉選單的某一項後，草稿裡的 searchMode 與 embeddingModel。
 *
 * 選模型時不寫 searchMode（有模型就是 hybrid）。預設知識庫選演算法時
 * 兩個都清掉（本來就是 BM25）；其他知識庫要寫明 bm25，才不會沿用預設
 * 知識庫的 embedding 模型。
 */
export function applySearchChoice(
  choice: string,
  builtin: boolean,
): SearchFields {
  if (choice === "keyword")
    return { searchMode: "keyword", embeddingModel: "" };
  if (choice === "bm25") {
    return { searchMode: builtin ? "" : "bm25", embeddingModel: "" };
  }
  if (choice.startsWith(MODEL_PREFIX)) {
    return {
      searchMode: "",
      embeddingModel: choice.slice(MODEL_PREFIX.length),
    };
  }
  return { searchMode: "", embeddingModel: "" };
}

/** 實際生效的檢索方式，給「沿用預設知識庫（目前：…）」用。 */
export function describeSearch(retrieval: {
  searchMode: KnowledgeSearchMode | null;
  embeddingModel: string | null;
}): string {
  if (retrieval.searchMode === "keyword") return "關鍵字";
  if (retrieval.searchMode === "hybrid" || retrieval.embeddingModel) {
    return retrieval.embeddingModel ?? "embedding";
  }
  return "演算法（BM25）";
}

/**
 * 「Embedding 模型」下方的提醒：模型網址上沒有 embedding 模型、查詢失敗，
 * 或目前設定的模型不在網址上。沒有要提醒的時候回傳 ""。
 */
export function embeddingWarning(
  found: KnowledgeModelChoices | undefined,
  current: string,
): string {
  if (!found || found.source === "none") return "";
  if (found.source === "error") {
    return `列不出模型網址上的 embedding 模型（${found.error ?? "查詢失敗"}），目前只能選關鍵字或演算法，或選「其他」自行輸入模型名稱。`;
  }
  if (found.embedding.length === 0) {
    return "這個模型網址上沒有 embedding 模型，只能選關鍵字或演算法（BM25）。要用語意檢索，請先在模型中台加上 embedding 模型（LiteLLM 請在 model_info 標明 mode: embedding），或選「其他」自行輸入。";
  }
  // 依名稱猜的清單可能漏掉，只有 LiteLLM 標明用途時才提醒不在清單上。
  if (
    found.source === "model_info" &&
    current &&
    !found.embedding.some((model) => model.name === current)
  ) {
    return `目前設定的「${current}」不在這個模型網址上，搜尋時可能會失敗，請改選清單裡的模型。`;
  }
  return "";
}
