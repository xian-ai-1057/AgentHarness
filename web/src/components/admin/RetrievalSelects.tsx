/**
 * 知識庫設定的兩個下拉選單：「Embedding 模型」（檢索方式）與「Reranker」。
 *
 * 選項來自模型連線上的模型（GET /api/knowledge/models，LiteLLM Proxy 會
 * 標明哪些是 embedding、哪些是 rerank 模型）；清單裡沒有的可以選「其他」
 * 自行輸入。
 */

import { useEffect, useId, useState } from "react";
import type {
  KnowledgeModelChoices,
  ModelChoice,
} from "../../../../src/web/protocol.ts";
import { api } from "../../api.ts";
import { Field } from "../shell/Field.tsx";
import {
  applySearchChoice,
  CUSTOM_CHOICE,
  embeddingWarning,
  MODEL_PREFIX,
  type SettingsDraft,
  searchChoice,
} from "./knowledgeForm.ts";

type Loaded = KnowledgeModelChoices | { loading: true };

// 同一頁的兩個選單、新增與編輯共用一次查詢；重新整理頁面才重查。
let cached: Promise<KnowledgeModelChoices> | undefined;

/** 模型連線上的 embedding 與 rerank 模型；查詢失敗時 source 是 error。 */
export function useKnowledgeModels(): Loaded {
  const [found, setFound] = useState<Loaded>({ loading: true });
  useEffect(() => {
    let alive = true;
    cached ??= api.knowledgeModels().catch(
      (error: Error): KnowledgeModelChoices => ({
        embedding: [],
        rerank: [],
        source: "error",
        error: error.message,
      }),
    );
    void cached.then((value) => {
      if (alive) setFound(value);
      // 查詢失敗時下次打開再試一次。
      if (value.source === "error") cached = undefined;
    });
    return () => {
      alive = false;
    };
  }, []);
  return found;
}

function listNote(found: Loaded): string {
  if ("loading" in found) return "正在查詢模型連線上的模型…";
  // 查詢失敗另外用醒目的提醒顯示（見 embeddingWarning）。
  if (found.source === "error") return "";
  if (found.source === "none") {
    return "沒有設定模型端點，列不出模型；可以選「其他」自行輸入。";
  }
  if (found.source === "names") {
    return "依模型名稱判斷用途，清單裡沒有的請選「其他」自行輸入。";
  }
  return "";
}

function rerankNote(found: Loaded): string {
  if ("loading" in found) return listNote(found);
  if (found.source === "error") {
    return `列不出模型網址上的 rerank 模型（${found.error ?? "查詢失敗"}），可以選「其他」自行輸入。`;
  }
  if (found.source !== "none" && found.rerank.length === 0) {
    return "這個模型網址上沒有 rerank 模型。";
  }
  return listNote(found);
}

function ModelOptions({
  models,
  current,
  group,
}: {
  models: ModelChoice[];
  current: string;
  group: string;
}) {
  const listed = models.some((model) => model.name === current);
  if (models.length === 0 && (!current || listed)) return null;
  return (
    <optgroup label={group}>
      {models.map((model) => (
        <option key={model.name} value={MODEL_PREFIX + model.name}>
          {model.label === model.name
            ? model.name
            : `${model.label}（${model.name}）`}
        </option>
      ))}
      {current && !listed && (
        <option value={MODEL_PREFIX + current}>{current}（目前設定）</option>
      )}
    </optgroup>
  );
}

function SelectRow({
  label,
  value,
  hint,
  warning = "",
  onChange,
  children,
}: {
  label: string;
  value: string;
  hint: string;
  /** 醒目的提醒，例如模型網址上沒有可以選的模型。 */
  warning?: string;
  onChange: (value: string) => void;
  children: React.ReactNode;
}) {
  const id = useId();
  return (
    <div className="form-row field-row">
      <label htmlFor={id}>{label}</label>
      <select
        id={id}
        className="field"
        value={value}
        aria-describedby={
          [warning ? `${id}-warning` : "", hint ? `${id}-hint` : ""]
            .filter(Boolean)
            .join(" ") || undefined
        }
        onChange={(event) => onChange(event.target.value)}
      >
        {children}
      </select>
      {warning && (
        <div id={`${id}-warning`} className="field-warning" role="status">
          {warning}
        </div>
      )}
      {hint && (
        <div id={`${id}-hint`} className="help">
          {hint}
        </div>
      )}
    </div>
  );
}

const SEARCH_HINTS: Record<string, string> = {
  keyword:
    "精確比對：只看查詢的字詞有沒有出現、出現幾次，不用任何模型。適合查編號、專有名詞。",
  bm25: "BM25 演算法：依字詞的稀有度與段落長度排序，不用任何模型。",
  model: "BM25 加上這個 embedding 模型的語意檢索，換模型後會重新計算向量。",
};

/**
 * 「Embedding 模型」：關鍵字、演算法（BM25）、模型連線上的 embedding
 * 模型、其他（自行輸入）；不是預設知識庫時最後還有「沿用預設知識庫」。
 */
export function EmbeddingSelect({
  builtin,
  inherited,
  fields,
  models,
  onChange,
}: {
  builtin: boolean;
  /** 沿用時實際的檢索方式（顯示在「沿用預設知識庫」後面）。 */
  inherited?: string;
  fields: Pick<SettingsDraft, "searchMode" | "embeddingModel">;
  models: Loaded;
  onChange: (
    fields: Pick<SettingsDraft, "searchMode" | "embeddingModel">,
  ) => void;
}) {
  const [custom, setCustom] = useState(false);
  const choice = searchChoice(fields, builtin, custom);
  const list = "loading" in models ? [] : models.embedding;
  const kind =
    choice.startsWith(MODEL_PREFIX) || choice === CUSTOM_CHOICE
      ? "model"
      : choice;
  const note = listNote(models);
  const hint = [SEARCH_HINTS[kind] ?? "", note].filter(Boolean).join(" ");
  return (
    <>
      <SelectRow
        label="Embedding 模型"
        value={choice}
        hint={hint}
        warning={embeddingWarning(
          "loading" in models ? undefined : models,
          custom ? "" : fields.embeddingModel,
        )}
        onChange={(value) => {
          setCustom(value === CUSTOM_CHOICE);
          onChange(applySearchChoice(value, builtin));
        }}
      >
        <option value="keyword">關鍵字（精確比對）</option>
        <option value="bm25">演算法（BM25）</option>
        <ModelOptions
          models={list}
          current={custom ? "" : fields.embeddingModel}
          group="Embedding 模型（BM25 + 語意檢索）"
        />
        <option value={CUSTOM_CHOICE}>其他（自行輸入模型名稱）</option>
        {!builtin && (
          <option value="">
            沿用預設知識庫{inherited ? `（目前：${inherited}）` : ""}
          </option>
        )}
      </SelectRow>
      {custom && (
        <Field
          label="Embedding 模型名稱"
          autoComplete="off"
          className="mono"
          placeholder="例如：openai/text-embedding-3-small"
          value={fields.embeddingModel}
          onChange={(event) =>
            onChange({ searchMode: "", embeddingModel: event.target.value })
          }
        />
      )}
    </>
  );
}

/**
 * 「Reranker」：不重新排序（其他知識庫是「沿用預設知識庫」）、模型連線上
 * 的 rerank 模型、其他（自行輸入）。
 */
export function RerankerSelect({
  builtin,
  inherited,
  value,
  models,
  onChange,
}: {
  builtin: boolean;
  /** 沿用時實際的 reranker；null 是不重新排序。 */
  inherited?: string | null;
  value: string;
  models: Loaded;
  onChange: (value: string) => void;
}) {
  const [custom, setCustom] = useState(false);
  const list = "loading" in models ? [] : models.rerank;
  const choice = custom ? CUSTOM_CHOICE : value ? MODEL_PREFIX + value : "";
  const empty = builtin
    ? "不重新排序"
    : `沿用預設知識庫（目前：${inherited || "不重新排序"}）`;
  const hint = [
    "用 rerank 模型重新評估前幾名候選的相關度，選填。",
    rerankNote(models),
  ]
    .filter(Boolean)
    .join(" ");
  return (
    <>
      <SelectRow
        label="Reranker"
        value={choice}
        hint={hint}
        onChange={(next) => {
          setCustom(next === CUSTOM_CHOICE);
          onChange(
            next.startsWith(MODEL_PREFIX)
              ? next.slice(MODEL_PREFIX.length)
              : "",
          );
        }}
      >
        <option value="">{empty}</option>
        <ModelOptions
          models={list}
          current={custom ? "" : value}
          group="Rerank 模型"
        />
        <option value={CUSTOM_CHOICE}>其他（自行輸入模型名稱）</option>
      </SelectRow>
      {custom && (
        <Field
          label="Reranker 模型名稱"
          autoComplete="off"
          className="mono"
          placeholder="例如：cohere/rerank-v3.5"
          value={value}
          onChange={(event) => onChange(event.target.value)}
        />
      )}
    </>
  );
}
