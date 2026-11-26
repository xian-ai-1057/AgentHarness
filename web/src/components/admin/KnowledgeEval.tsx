/**
 * 管理平台 → 知識庫 → 評測：題庫回歸評測。
 *
 * 每一題寫下問題、應該找到的文件與應該出現的關鍵字（也可以寫參考答案）。
 * 按「執行評測」用知識庫目前的設定搜尋每一題，算出通過率、命中率與
 * MRR，並和上一次比較列出退步的題目；文件、版本資訊或檢索設定改動後，
 * 伺服器也會自動評測一次（只評測檢索，不花模型費用）。
 */

import {
  type FormEvent,
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";
import type {
  KnowledgeAdminBase,
  KnowledgeEval,
  KnowledgeEvalQuestion,
  KnowledgeEvalRun,
  KnowledgeEvalSummary,
} from "../../../../src/web/protocol.ts";
import { api } from "../../api.ts";
import { AddIcon, DownloadIcon, RetryIcon, TrashIcon } from "../Icons.tsx";
import { ConfirmDialog, Modal } from "../shell/Dialog.tsx";
import { Field } from "../shell/Field.tsx";
import { showToast } from "../shell/toast.tsx";

/** 檢索方式的名稱（知識庫設定與評測紀錄共用）。 */
export const SEARCH_LABELS: Record<string, string> = {
  keyword: "關鍵字（精確比對）",
  bm25: "演算法（BM25）",
  hybrid: "BM25 + 語意（embedding）",
};

/** 執行中時多久重新讀一次。 */
const POLL_MS = 1500;

type QuestionDraft = {
  question: string;
  sources: string;
  keywords: string;
  answer: string;
};

const EMPTY: QuestionDraft = {
  question: "",
  sources: "",
  keywords: "",
  answer: "",
};

export function percent(value: number | null | undefined): string {
  return value === null || value === undefined
    ? "—"
    : `${Math.round(value * 100)}%`;
}

function when(seconds: number): string {
  return new Date(seconds * 1000).toLocaleString();
}

export function KnowledgeEvalSection({
  base,
  onChanged,
}: {
  base: KnowledgeAdminBase;
  onChanged: () => Promise<void>;
}) {
  const [data, setData] = useState<KnowledgeEval>();
  const [error, setError] = useState<string>();
  const [editing, setEditing] = useState<KnowledgeEvalQuestion | "new">();
  const [removing, setRemoving] = useState<KnowledgeEvalQuestion>();
  const [importing, setImporting] = useState(false);
  const [starting, setStarting] = useState(false);
  const [viewing, setViewing] = useState<string>();

  const load = useCallback(async () => {
    try {
      setData(await api.knowledgeEval(base.id));
      setError(undefined);
    } catch (failure) {
      setError((failure as Error).message);
    }
  }, [base.id]);

  useEffect(() => {
    void load();
  }, [load]);

  // 執行中時定期重新讀取，結束後更新知識庫清單上的概況。
  const running = data?.running;
  useEffect(() => {
    if (!running) return;
    const timer = setInterval(async () => {
      const next = await api.knowledgeEval(base.id).catch(() => undefined);
      if (!next) return;
      setData(next);
      if (!next.running) {
        setViewing(running);
        void onChanged();
      }
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [running, base.id, onChanged]);

  const latest = data?.runs.find((run) => run.status !== "running");
  const shown = viewing ?? latest?.id;

  return (
    <section className="access-field kb-section" aria-labelledby="h-kb-eval">
      <div className="box-row">
        <h3 id="h-kb-eval" className="kb-heading">
          題庫評測
        </h3>
        <div className="kb-actions">
          <button
            type="button"
            className="btn btn-ghost"
            aria-label="重新讀取"
            onClick={load}
          >
            <RetryIcon size={15} />
          </button>
          <button
            type="button"
            className="btn btn-accent"
            disabled={!data || data.questions.length === 0 || Boolean(running)}
            onClick={() => setStarting(true)}
          >
            {running ? "評測中…" : "執行評測"}
          </button>
        </div>
      </div>
      <p className="help">
        {
          "寫下使用者會問的問題、應該找到的文件與應該出現的字詞。改了文件、版本資訊或檢索設定後會自動評測一次（只評測檢索，不花模型費用），退步的題目會標出來。"
        }
      </p>
      {error && (
        <div className="inline-error" role="alert">
          {error}
        </div>
      )}
      {!data && !error && (
        <p className="subtle" aria-busy="true">
          讀取中…
        </p>
      )}

      {data && data.runs.length > 0 && (
        <RunHistory runs={data.runs} selected={shown} onSelect={setViewing} />
      )}
      {data && shown && (
        <RunDetail
          key={shown}
          baseId={base.id}
          runId={shown}
          questions={data.questions}
        />
      )}

      {data && (
        <div className="kb-eval-questions">
          <div className="box-row">
            <h4 className="kb-subheading">
              題目（{data.questions.length} / {data.limit}）
            </h4>
            <div className="kb-actions">
              <a
                className="btn btn-ghost"
                href={api.evalExportUrl(base.id)}
                download
              >
                <DownloadIcon size={15} />
                匯出
              </a>
              <button
                type="button"
                className="btn btn-outline"
                onClick={() => setImporting(true)}
              >
                匯入
              </button>
              <button
                type="button"
                className="btn btn-outline"
                onClick={() => setEditing("new")}
              >
                <AddIcon size={15} />
                新增題目
              </button>
            </div>
          </div>
          {data.questions.length === 0 && (
            <p className="subtle">
              還沒有題目。可以一題一題新增，或從 Excel／CSV
              匯入（欄位：問題、應該找到的文件、關鍵字、參考答案）。
            </p>
          )}
          {data.questions.length > 0 && (
            <ol className="member-list kb-question-list" aria-label="題目">
              {data.questions.map((item) => (
                <li key={item.id} className="member-row">
                  <span className="member-main">
                    <span className="member-display">{item.question}</span>
                    <span className="member-meta">
                      {item.sources.length > 0 &&
                        `應該找到：${item.sources.join("、")}`}
                      {item.sources.length > 0 && item.keywords.length > 0
                        ? " · "
                        : ""}
                      {item.keywords.length > 0 &&
                        `關鍵字：${item.keywords.join("、")}`}
                    </span>
                    {item.answer && (
                      <span className="member-meta">
                        參考答案：{item.answer}
                      </span>
                    )}
                  </span>
                  <button
                    type="button"
                    className="btn btn-ghost"
                    onClick={() => setEditing(item)}
                  >
                    編輯
                  </button>
                  <button
                    type="button"
                    className="btn btn-ghost"
                    aria-label={`刪除「${item.question}」`}
                    onClick={() => setRemoving(item)}
                  >
                    <TrashIcon size={15} />
                  </button>
                </li>
              ))}
            </ol>
          )}
        </div>
      )}

      {editing &&
        createPortal(
          <QuestionDialog
            baseId={base.id}
            question={editing === "new" ? undefined : editing}
            onClose={() => setEditing(undefined)}
            onSaved={async () => {
              setEditing(undefined);
              await load();
              void onChanged();
            }}
          />,
          document.body,
        )}
      {removing &&
        createPortal(
          <ConfirmDialog
            title="刪除這一題？"
            confirmLabel="刪除"
            danger
            onConfirm={async () => {
              await api.deleteEvalQuestion(base.id, removing.id);
              showToast("已刪除");
              await load();
              void onChanged();
            }}
            onClose={() => setRemoving(undefined)}
          >
            {removing.question}
          </ConfirmDialog>,
          document.body,
        )}
      {importing &&
        createPortal(
          <ImportDialog
            baseId={base.id}
            hasQuestions={(data?.questions.length ?? 0) > 0}
            onClose={() => setImporting(false)}
            onImported={async (added) => {
              setImporting(false);
              showToast(`已匯入 ${added} 題`);
              await load();
              void onChanged();
            }}
          />,
          document.body,
        )}
      {starting &&
        data &&
        createPortal(
          <RunDialog
            baseId={base.id}
            models={data.models}
            onClose={() => setStarting(false)}
            onStarted={async (id) => {
              setStarting(false);
              setViewing(id);
              await load();
            }}
          />,
          document.body,
        )}
    </section>
  );
}

function SummaryLine({
  summary,
  run,
}: {
  summary: KnowledgeEvalSummary;
  run: KnowledgeEvalRun;
}) {
  return (
    <span className="member-meta">
      通過 {summary.passed}/{summary.total}（{percent(summary.passRate)}）·
      命中率 {percent(summary.hitRate)} · MRR{" "}
      {summary.mrr === null ? "—" : summary.mrr.toFixed(2)}
      {run.mode === "answer" && ` · 評測回答（${run.settings.answerModel}）`}
    </span>
  );
}

function RunHistory({
  runs,
  selected,
  onSelect,
}: {
  runs: KnowledgeEvalRun[];
  selected?: string;
  onSelect: (id: string) => void;
}) {
  return (
    <details className="kb-eval-history" open={runs.length <= 3}>
      <summary>評測紀錄（最近 {runs.length} 次）</summary>
      <ul className="member-list" aria-label="評測紀錄">
        {runs.map((run) => (
          <li key={run.id} className="member-row">
            <button
              type="button"
              className={`group-open kb-eval-run ${
                run.id === selected ? "selected" : ""
              }`}
              aria-current={run.id === selected ? "true" : undefined}
              onClick={() => onSelect(run.id)}
            >
              <span className="member-main">
                <span className="member-name">
                  <span className="member-display">{when(run.startedAt)}</span>
                  <span className="badge badge-muted">
                    {run.trigger === "手動" ? "手動" : `自動：${run.trigger}`}
                  </span>
                  {run.status === "running" && (
                    <span className="badge badge-muted">執行中</span>
                  )}
                  {run.status === "error" && (
                    <span className="badge badge-danger">失敗</span>
                  )}
                  {run.regressions.length > 0 && (
                    <span className="badge badge-warn">
                      退步 {run.regressions.length} 題
                    </span>
                  )}
                  {run.fixed.length > 0 && (
                    <span className="badge badge-ok">
                      改善 {run.fixed.length} 題
                    </span>
                  )}
                </span>
                {run.summary && <SummaryLine summary={run.summary} run={run} />}
                {run.error && <span className="kb-note">{run.error}</span>}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </details>
  );
}

function RunDetail({
  baseId,
  runId,
  questions,
}: {
  baseId: string;
  runId: string;
  questions: KnowledgeEvalQuestion[];
}) {
  const [run, setRun] = useState<KnowledgeEvalRun>();
  const [error, setError] = useState<string>();
  const [onlyFailed, setOnlyFailed] = useState(true);

  useEffect(() => {
    let alive = true;
    const read = async () => {
      try {
        const found = await api.evalRun(baseId, runId);
        if (!alive) return;
        setRun(found);
        if (found.status === "running") setTimeout(read, POLL_MS);
      } catch (failure) {
        if (alive) setError((failure as Error).message);
      }
    };
    void read();
    return () => {
      alive = false;
    };
  }, [baseId, runId]);

  if (error) {
    return (
      <div className="inline-error" role="alert">
        {error}
      </div>
    );
  }
  if (!run) return null;
  if (run.status === "running") {
    return (
      <p className="subtle" aria-busy="true">
        評測中…（{questions.length} 題）
      </p>
    );
  }
  const regressions = new Set(run.regressions);
  const results = run.results ?? [];
  const failed = results.filter((item) => !item.passed);
  const listed = onlyFailed ? failed : results;
  const settings = run.settings;
  return (
    <div className="box kb-eval-detail">
      <dl className="kb-eval-stats" aria-label="評測結果">
        <Stat
          label="通過"
          value={
            run.summary ? `${run.summary.passed}/${run.summary.total}` : "—"
          }
        />
        <Stat label="通過率" value={percent(run.summary?.passRate)} />
        <Stat
          label={`命中率（前 ${settings.topK} 筆）`}
          value={percent(run.summary?.hitRate)}
        />
        <Stat
          label="MRR"
          value={
            run.summary?.mrr === null || run.summary?.mrr === undefined
              ? "—"
              : run.summary.mrr.toFixed(2)
          }
        />
        <Stat
          label="退步"
          value={String(run.regressions.length)}
          tone={run.regressions.length > 0 ? "warn" : undefined}
        />
      </dl>
      <p className="member-meta">
        {when(run.startedAt)} · {run.startedBy} · 檢索方式{" "}
        {SEARCH_LABELS[settings.searchMode ?? ""] ?? settings.searchMode}
        {settings.embeddingModel ? `（${settings.embeddingModel}）` : ""}
        {settings.reranker ? ` · reranker ${settings.reranker}` : ""} · 切片{" "}
        {settings.chunking === "regulation" ? "依條文" : "依段落"}{" "}
        {settings.chunkSize} 字 · {settings.documents} 份文件
      </p>
      {run.error && (
        <div className="inline-error" role="alert">
          {run.error}
        </div>
      )}
      {results.length > 0 && (
        <label className="kb-check">
          <input
            type="checkbox"
            checked={onlyFailed}
            onChange={(event) => setOnlyFailed(event.target.checked)}
          />
          只看沒通過的（{failed.length} 題）
        </label>
      )}
      {listed.length === 0 && results.length > 0 && (
        <p className="subtle">全部通過。</p>
      )}
      <ol className="kb-eval-results">
        {listed.map((item) => (
          <li
            key={item.id}
            className={`kb-eval-result ${item.passed ? "pass" : "fail"}`}
          >
            <div className="member-name">
              <span
                className={`badge ${item.passed ? "badge-ok" : "badge-danger"}`}
              >
                {item.passed ? "通過" : "沒過"}
              </span>
              {regressions.has(item.id) && (
                <span className="badge badge-warn">退步</span>
              )}
              <span className="member-display">{item.question}</span>
            </div>
            {item.rank !== null && (
              <div className="member-meta">
                應該找到的文件排第 {item.rank} 名
              </div>
            )}
            {item.reasons.length > 0 && (
              <ul className="kb-warnings">
                {item.reasons.map((reason) => (
                  <li key={reason}>{reason}</li>
                ))}
              </ul>
            )}
            {item.answer && <p className="kb-hit-text">回答：{item.answer}</p>}
            {item.hits.length > 0 && (
              <details>
                <summary className="member-meta">
                  找到的 {item.hits.length} 筆
                </summary>
                <ol className="kb-eval-hits mono">
                  {item.hits.map((hit, index) => (
                    // biome-ignore lint/suspicious/noArrayIndexKey: 同一份文件可能出現兩次，順序固定
                    <li key={`${index}-${hit}`}>{hit}</li>
                  ))}
                </ol>
              </details>
            )}
          </li>
        ))}
      </ol>
    </div>
  );
}

function Stat({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "warn";
}) {
  return (
    <div className={`kb-stat ${tone ?? ""}`}>
      <dt className="kb-stat-label">{label}</dt>
      <dd className="kb-stat-value">{value}</dd>
    </div>
  );
}

function QuestionDialog({
  baseId,
  question,
  onClose,
  onSaved,
}: {
  baseId: string;
  question?: KnowledgeEvalQuestion;
  onClose: () => void;
  onSaved: () => void;
}) {
  const titleId = useId();
  const answerId = useId();
  const first = useRef<HTMLInputElement>(null);
  const [draft, setDraft] = useState<QuestionDraft>(
    question
      ? {
          question: question.question,
          sources: question.sources.join("\n"),
          keywords: question.keywords.join("、"),
          answer: question.answer,
        }
      : EMPTY,
  );
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);

  const split = (text: string) =>
    text
      .split(/[\n,，、;；]+/)
      .map((item) => item.trim())
      .filter(Boolean);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    const body = {
      question: draft.question.trim(),
      sources: split(draft.sources),
      keywords: split(draft.keywords),
      answer: draft.answer.trim(),
    };
    try {
      if (question) await api.updateEvalQuestion(baseId, question.id, body);
      else await api.addEvalQuestion(baseId, body);
      onSaved();
    } catch (failure) {
      setError((failure as Error).message);
      setBusy(false);
    }
  };

  const edit = (changes: Partial<QuestionDraft>) => {
    setDraft((current) => ({ ...current, ...changes }));
    setError(undefined);
  };

  return (
    <Modal
      onClose={onClose}
      className="confirm-dialog form-dialog"
      labelledBy={titleId}
      initialFocus={first}
    >
      <form onSubmit={submit} noValidate>
        <h2 id={titleId} className="dialog-title">
          {question ? "編輯題目" : "新增題目"}
        </h2>
        <div className="dialog-fields">
          <Field
            ref={first}
            label="問題"
            placeholder="例如：特休假怎麼計算？"
            value={draft.question}
            onChange={(event) => edit({ question: event.target.value })}
          />
          <Field
            label="應該找到的文件"
            placeholder="例如：hr/leave.pdf、leave.md › 第 3 條"
            hint="檔名或路徑，可以用 * 樣式；加上「› 位置」時位置也要對。好幾份用逗號分開，任一份出現在前幾筆就算找到。"
            value={draft.sources}
            onChange={(event) => edit({ sources: event.target.value })}
          />
          <Field
            label="應該出現的關鍵字"
            placeholder="例如：七天、滿一年"
            hint="全部出現在找到的片段裡才算通過（評測回答時看回答）。"
            value={draft.keywords}
            onChange={(event) => edit({ keywords: event.target.value })}
          />
          <div className="form-row field-row">
            <label htmlFor={answerId}>參考答案（選填）</label>
            <textarea
              id={answerId}
              className="field"
              rows={3}
              placeholder="用模型評測回答時，請模型比對重點是否一致"
              value={draft.answer}
              onChange={(event) => edit({ answer: event.target.value })}
            />
          </div>
          {error && (
            <div className="inline-error" role="alert">
              {error}
            </div>
          )}
        </div>
        <div className="dialog-actions">
          <button type="button" className="btn btn-outline" onClick={onClose}>
            取消
          </button>
          <button type="submit" className="btn btn-accent" disabled={busy}>
            儲存
          </button>
        </div>
      </form>
    </Modal>
  );
}

function ImportDialog({
  baseId,
  hasQuestions,
  onClose,
  onImported,
}: {
  baseId: string;
  hasQuestions: boolean;
  onClose: () => void;
  onImported: (added: number) => void;
}) {
  const titleId = useId();
  const input = useRef<HTMLInputElement>(null);
  const [replace, setReplace] = useState(false);
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);

  const choose = async (file: File | undefined) => {
    if (!file) return;
    setBusy(true);
    setError(undefined);
    try {
      const result = await api.importEvalQuestions(baseId, file, replace);
      onImported(result.added);
    } catch (failure) {
      setError((failure as Error).message);
      setBusy(false);
    }
  };

  return (
    <Modal
      onClose={onClose}
      className="confirm-dialog form-dialog"
      labelledBy={titleId}
    >
      <h2 id={titleId} className="dialog-title">
        匯入題庫
      </h2>
      <div className="dialog-fields">
        <p className="help">
          Excel（.xlsx）或 CSV，第一列是欄位名稱：
          <strong>問題</strong>
          （必填）、應該找到的文件、關鍵字、參考答案。文件與關鍵字有好幾個時用逗號、頓號或換行分開。可以先「匯出」一份當範本。
        </p>
        {hasQuestions && (
          <label className="kb-check">
            <input
              type="checkbox"
              checked={replace}
              onChange={(event) => setReplace(event.target.checked)}
            />
            取代原本的題目（不勾的話加在後面）
          </label>
        )}
        {error && (
          <div className="inline-error kb-error" role="alert">
            {error}
          </div>
        )}
        <input
          ref={input}
          type="file"
          hidden
          accept=".xlsx,.csv"
          onChange={(event) => {
            const file = event.target.files?.[0];
            event.target.value = "";
            void choose(file);
          }}
        />
      </div>
      <div className="dialog-actions">
        <button type="button" className="btn btn-outline" onClick={onClose}>
          取消
        </button>
        <button
          type="button"
          className="btn btn-accent"
          disabled={busy}
          onClick={() => input.current?.click()}
        >
          {busy ? "匯入中…" : "選擇檔案"}
        </button>
      </div>
    </Modal>
  );
}

function RunDialog({
  baseId,
  models,
  onClose,
  onStarted,
}: {
  baseId: string;
  models: string[];
  onClose: () => void;
  onStarted: (id: string) => void;
}) {
  const titleId = useId();
  const topKId = useId();
  const [withAnswers, setWithAnswers] = useState(false);
  const [model, setModel] = useState(models[0] ?? "");
  const [topK, setTopK] = useState("5");
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);

  const start = async () => {
    const k = Number(topK);
    if (!Number.isInteger(k) || k < 1 || k > 20) {
      setError("前幾筆必須是 1 到 20 的整數");
      return;
    }
    setBusy(true);
    try {
      const started = await api.runEval(baseId, {
        topK: k,
        ...(withAnswers && model && { answerModel: model }),
      });
      onStarted(started.id);
    } catch (failure) {
      setError((failure as Error).message);
      setBusy(false);
    }
  };

  return (
    <Modal
      onClose={onClose}
      className="confirm-dialog form-dialog"
      labelledBy={titleId}
    >
      <h2 id={titleId} className="dialog-title">
        執行評測
      </h2>
      <div className="dialog-fields">
        <div className="form-row field-row">
          <label htmlFor={topKId}>看前幾筆結果</label>
          <input
            id={topKId}
            className="field"
            inputMode="numeric"
            value={topK}
            onChange={(event) => setTopK(event.target.value)}
          />
          <div className="help">
            和 agent 每次搜尋拿到的筆數一樣比較準（預設 5）。
          </div>
        </div>
        <label className="kb-check">
          <input
            type="checkbox"
            checked={withAnswers}
            onChange={(event) => setWithAnswers(event.target.checked)}
          />
          也請模型回答並評分（每題會呼叫模型一到兩次）
        </label>
        {withAnswers && (
          <div className="form-row field-row">
            <label htmlFor={`${titleId}-model`}>回答用的模型</label>
            <select
              id={`${titleId}-model`}
              className="field"
              value={model}
              onChange={(event) => setModel(event.target.value)}
            >
              {models.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
            <div className="help">
              知識庫有資料分級時，會自動改用可以處理這個等級的模型。
            </div>
          </div>
        )}
        {error && (
          <div className="inline-error" role="alert">
            {error}
          </div>
        )}
      </div>
      <div className="dialog-actions">
        <button type="button" className="btn btn-outline" onClick={onClose}>
          取消
        </button>
        <button
          type="button"
          className="btn btn-accent"
          disabled={busy}
          onClick={start}
        >
          開始
        </button>
      </div>
    </Modal>
  );
}
