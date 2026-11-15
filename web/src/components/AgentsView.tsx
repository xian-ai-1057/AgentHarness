/**
 * 自建 Agent（features.userAgents，Python 版）。
 *
 * /agents 列出「我的 Agent」與「管理者提供的」agent，按「開始對話」用它開
 * 新對話（/?agent=<名稱>）。/agents/new 建立、/agents/:id 編輯自己的
 * agent：名稱、說明、指示、開場建議、預設模型、工具、知識庫與技能。
 *
 * 做法參考 ChatGPT 的 GPTs、Claude 的 Projects 與 MaiAgent 的建立 Agent。
 * 工具、知識庫與模型只列出這個人能用的（所屬群組開放的、模型選單裡的），
 * 伺服器存檔時與每一輪執行時都會再檢查。只有建立的人看得到。
 */

import { type ReactNode, useEffect, useId, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import type {
  AgentInfo,
  ProjectInfo,
  UserAgentInfo,
  UserAgentInput,
  UserAgentList,
} from "../../../src/web/protocol.ts";
import {
  agentInitial,
  agentLabel,
  isUserAgent,
  toolsetText,
} from "../agents.ts";
import { api } from "../api.ts";
import { navigate } from "../router.ts";
import { useStore } from "../store.ts";
import {
  AddIcon,
  AgentIcon,
  ArrowLeftIcon,
  CloseIcon,
  GearIcon,
  PenIcon,
  TrashIcon,
  WarnIcon,
} from "./Icons.tsx";
import { Link } from "./Sidebar.tsx";
import { ConfirmDialog } from "./shell/Dialog.tsx";
import { Field } from "./shell/Field.tsx";
import { showToast } from "./shell/toast.tsx";

/** 腳本要在沙盒裡執行的 skills（伺服器 user_agents.SANDBOX_SKILLS）。 */
const SANDBOX_SKILLS = new Set(["xlsx", "docx", "pptx", "pdf"]);
const SANDBOX_TOOLSET = "sandbox";

function sandboxWarning(project: ProjectInfo): string {
  return project.toolsets.some((set) => set.name === SANDBOX_TOOLSET)
    ? "勾選的技能要用「執行 Python」才能產生檔案，請在上面的工具勾選「執行 Python」。"
    : "勾選的技能要用「執行 Python」才能產生檔案，但管理者沒有開放這個工具給你，Agent 只能說明做法、做不出檔案。";
}

const DEFAULT_LIMITS: UserAgentList["limits"] = {
  name: 40,
  description: 200,
  instructions: 8000,
  starter: 100,
  starters: 4,
};

const INSTRUCTIONS_PLACEHOLDER = `例如：
你是法遵小幫手，協助同仁檢查文件是否符合內部規範。
- 回答前先搜尋知識庫，引用時標出條號。
- 找不到依據時直接說找不到，不要猜。
- 用條列整理重點，最後附上建議的下一步。`;

/** 新對話用這個 agent 的網址。 */
function chatWith(name: string): string {
  return `/?agent=${encodeURIComponent(name)}`;
}

function Page({
  title,
  actions,
  children,
}: {
  title: string;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <main className="main">
      <header className="main-header">
        <div className="main-title">
          <h1>{title}</h1>
        </div>
      </header>
      <div className="scroll">
        <div className="page agents-page">{children}</div>
      </div>
      {actions}
    </main>
  );
}

/** /agents：我的 Agent 與管理者提供的 agent。 */
export function AgentsView() {
  const project = useStore((s) => s.project);

  useEffect(() => {
    document.title = "Agent · Harness";
  }, []);

  if (!project) return <main className="main" aria-busy="true" />;
  if (!project.features?.userAgents) {
    return (
      <Page title="Agent">
        <p className="empty-state">這個版本沒有自建 Agent 的功能。</p>
      </Page>
    );
  }

  const mine = project.agents.filter((item) => item.custom);
  const provided = project.agents.filter((item) => !isUserAgent(item.name));

  return (
    <Page title="Agent">
      <div className="page-head anim-in">
        <div>
          <h2>Agent</h2>
          <p>
            把常用的指示、工具與知識庫存成自己的 Agent，開新對話時直接選用。
            只有你自己看得到。
          </p>
        </div>
        <Link to="/agents/new" className="btn btn-accent">
          <AddIcon size={15} />
          建立 Agent
        </Link>
      </div>

      <section aria-labelledby="h-mine" className="agents-section anim-in">
        <h3 id="h-mine" className="agents-heading">
          我的 Agent
          <span className="hint">{mine.length}</span>
        </h3>
        {mine.length === 0 ? (
          <div className="agents-empty">
            <span className="agent-avatar agent-avatar-lg" aria-hidden="true">
              <AgentIcon size={22} />
            </span>
            <div>
              <p className="agents-empty-title">還沒有自己的 Agent</p>
              <p className="subtle">
                例如「週報小幫手」：寫好格式與語氣，勾選要用的知識庫，之後每週開新對話就能直接用。
              </p>
            </div>
            <Link to="/agents/new" className="btn btn-outline">
              <AddIcon size={15} />
              建立第一個 Agent
            </Link>
          </div>
        ) : (
          <ul className="agent-grid" aria-label="我的 Agent">
            {mine.map((agent) => (
              <AgentCard key={agent.name} agent={agent} project={project} />
            ))}
          </ul>
        )}
      </section>

      {provided.length > 0 && (
        <section
          aria-labelledby="h-provided"
          className="agents-section anim-in"
          style={{ animationDelay: "0.06s" }}
        >
          <h3 id="h-provided" className="agents-heading">
            管理者提供的
            <span className="hint">{provided.length}</span>
          </h3>
          <ul className="agent-grid" aria-label="管理者提供的 Agent">
            {provided.map((agent) => (
              <AgentCard key={agent.name} agent={agent} project={project} />
            ))}
          </ul>
        </section>
      )}
    </Page>
  );
}

function AgentCard({
  agent,
  project,
}: {
  agent: AgentInfo;
  project: ProjectInfo;
}) {
  const label = agentLabel(agent);
  const bases = (agent.knowledge ?? [])
    .map((id) => project.knowledgeBases?.find((base) => base.id === id)?.name)
    .filter(Boolean);
  const facts = [
    agent.tools.length > 0 ? `${agent.tools.length} 個工具` : "不用工具",
    bases.length > 0 ? `知識庫：${bases.join("、")}` : "",
  ].filter(Boolean);
  return (
    <li className="agent-card">
      <div className="agent-card-head">
        <span
          className={`agent-avatar ${agent.custom ? "" : "agent-avatar-muted"}`}
          aria-hidden="true"
        >
          {agent.custom ? agentInitial(label) : <AgentIcon size={18} />}
        </span>
        <div className="agent-card-title">
          <span className="agent-card-name">{label}</span>
          {!agent.custom && agent.name === project.defaultAgent && (
            <span className="badge badge-muted">預設</span>
          )}
        </div>
      </div>
      <p className="agent-card-desc">{agent.description || "沒有說明"}</p>
      <p className="agent-card-facts">{facts.join(" · ")}</p>
      <div className="agent-card-actions">
        <Link to={chatWith(agent.name)} className="btn btn-outline btn-sm">
          <PenIcon size={14} />
          開始對話
        </Link>
        {agent.custom && (
          <Link
            to={`/agents/${agent.custom.id}`}
            className="btn btn-outline btn-sm"
            aria-label={`編輯「${label}」的設定`}
          >
            <GearIcon size={14} />
            編輯設定
          </Link>
        )}
      </div>
    </li>
  );
}

/** 表單裡的值；開場建議多留一格空白讓人直接輸入。 */
type Draft = UserAgentInput;

const EMPTY_DRAFT: Draft = {
  name: "",
  description: "",
  instructions: "",
  starters: [],
  model: null,
  toolsets: [],
  knowledgeBases: [],
  skills: [],
};

/**
 * 新的 agent 一開始勾的工具與 skills（伺服器依群組算好：工具和一般對話
 * 一樣，skills 全勾）。舊版伺服器沒有提供時只勾「讀寫檔案」。
 */
function startDraft(project: ProjectInfo, list: UserAgentList): Draft {
  if (list.defaults) {
    return {
      ...EMPTY_DRAFT,
      toolsets: list.defaults.toolsets,
      skills: list.defaults.skills,
    };
  }
  return {
    ...EMPTY_DRAFT,
    toolsets: project.toolsets
      .filter((set) => set.builtin && set.name === "files")
      .map((set) => set.name),
  };
}

/** /agents/new 與 /agents/:id。 */
export function AgentEditor({ id }: { id: string }) {
  const project = useStore((s) => s.project);
  const creating = id === "new";
  const [saved, setSaved] = useState<UserAgentInfo>();
  const [draft, setDraft] = useState<Draft>();
  // 建立時一開始的表單（預設勾的工具）；和它一樣就不算有變更。
  const [initial, setInitial] = useState<Draft>();
  const [limits, setLimits] = useState(DEFAULT_LIMITS);
  const [loadError, setLoadError] = useState<string>();
  const [error, setError] = useState<string>();
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const instructionsId = useId();

  useEffect(() => {
    document.title = `${creating ? "建立 Agent" : "編輯 Agent"} · Harness`;
  }, [creating]);

  // 只在打開頁面（與專案資訊第一次讀到）時讀一次；之後專案資訊更新
  // （例如存檔後）不要蓋掉正在編輯的內容。
  const ready = Boolean(project);
  // biome-ignore lint/correctness/useExhaustiveDependencies: 見上方說明
  useEffect(() => {
    if (!project) return;
    let cancelled = false;
    api
      .userAgents()
      .then((list) => {
        if (cancelled) return;
        setLimits(list.limits);
        if (creating) {
          const start = startDraft(project, list);
          setInitial(start);
          setDraft(start);
          return;
        }
        const found = list.agents.find((item) => item.id === id);
        if (!found) {
          setLoadError("找不到這個 Agent，可能已經被刪除。");
          return;
        }
        setSaved(found);
        setDraft(toDraft(found));
      })
      .catch((failure: Error) => {
        if (!cancelled) setLoadError(failure.message);
      });
    return () => {
      cancelled = true;
    };
  }, [id, creating, ready]);

  const options = useMemo(() => {
    if (!project) return undefined;
    return {
      toolsets: project.toolsets.map((set) => ({
        name: set.name,
        ...toolsetText(
          set.name,
          set.builtin,
          set.tools.map((item) => item.name),
        ),
      })),
      knowledgeBases: (project.knowledgeBases ?? []).map((base) => ({
        name: base.id,
        label: base.name,
        hint: base.description,
      })),
      skills: (project.skills ?? []).map((skill) => ({
        name: skill.name,
        label: skill.name,
        hint: skill.description,
      })),
    };
  }, [project]);

  if (!project || (!draft && !loadError)) {
    return (
      <Page title="Agent">
        <p className="subtle" aria-busy="true">
          讀取中…
        </p>
      </Page>
    );
  }
  if (loadError || !draft || !options) {
    return (
      <Page title="Agent">
        <p className="empty-state">
          {loadError} <Link to="/agents">回到所有 Agent</Link>
        </p>
      </Page>
    );
  }

  const edit = (change: Partial<Draft>) => {
    setDraft({ ...draft, ...change });
    setError(undefined);
  };
  const baseline = saved ? toDraft(saved) : (initial ?? EMPTY_DRAFT);
  const dirty =
    JSON.stringify(cleaned(baseline)) !== JSON.stringify(cleaned(draft));
  const tooLong = overflow(draft, limits);
  const status =
    error ??
    (dirty
      ? "有未儲存的變更"
      : saved
        ? "所有變更都已儲存"
        : "填好名稱就可以建立");
  // 之前選的東西後來被收回（群組改了）時，仍然顯示出來讓人取消勾選。
  const withMissing = (
    items: { name: string; label: string; hint?: string }[],
    chosen: string[],
    labelOf: (name: string) => string = (name) => name,
  ) => [
    ...items,
    ...chosen
      .filter((name) => !items.some((item) => item.name === name))
      .map((name) => ({
        name,
        label: labelOf(name),
        hint: "目前不能使用",
        missing: true,
      })),
  ];

  const save = async (thenChat: boolean) => {
    if (!draft.name.trim()) {
      setError("請輸入名稱");
      return;
    }
    const message = firstOverflow(tooLong);
    if (message) {
      setError(message);
      return;
    }
    setSaving(true);
    setError(undefined);
    try {
      const body = cleaned(draft);
      const result = saved
        ? await api.updateUserAgent(saved.id, body)
        : await api.createUserAgent(body);
      setSaved(result);
      setDraft(toDraft(result));
      showToast(saved ? "已儲存" : `已建立「${result.name}」`);
      if (thenChat) navigate(chatWith(result.key));
      else if (!saved) navigate(`/agents/${result.id}`, { replace: true });
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const starters =
    draft.starters.length < limits.starters
      ? [...draft.starters, ""]
      : draft.starters;

  return (
    <Page
      title={creating ? "建立 Agent" : "編輯 Agent"}
      actions={
        <footer className="agent-editor-bar">
          <span
            className={error ? "inline-error" : "subtle"}
            role={error ? "alert" : undefined}
          >
            {status}
          </span>
          <div className="agent-editor-buttons">
            {saved && !dirty && (
              <Link to={chatWith(saved.key)} className="btn btn-outline">
                <PenIcon size={15} />
                開始對話
              </Link>
            )}
            {(dirty || !saved) && (
              <>
                <button
                  type="button"
                  className="btn btn-outline"
                  disabled={saving}
                  onClick={() => save(true)}
                >
                  {saved ? "儲存並開始對話" : "建立並開始對話"}
                </button>
                <button
                  type="button"
                  className="btn btn-accent"
                  disabled={saving}
                  onClick={() => save(false)}
                >
                  {saved ? "儲存" : "建立"}
                </button>
              </>
            )}
          </div>
        </footer>
      }
    >
      <div className="agent-editor anim-in">
        <div className="agent-editor-form">
          <div>
            <Link to="/agents" className="btn btn-ghost group-back">
              <ArrowLeftIcon size={15} />
              所有 Agent
            </Link>
            <h2 className="agent-editor-title">
              {creating ? "建立 Agent" : saved?.name}
            </h2>
            <p className="lead">
              只有你自己看得到。工具、知識庫與模型只列出管理者開放給你的。
            </p>
          </div>

          <section className="agent-fields" aria-label="基本資料">
            <Field
              label="名稱"
              value={draft.name}
              error={tooLong.name}
              placeholder="例如：週報小幫手"
              onChange={(event) => edit({ name: event.target.value })}
            />
            <Field
              label="說明"
              value={draft.description}
              error={tooLong.description}
              placeholder="一句話說明它能幫你做什麼"
              onChange={(event) => edit({ description: event.target.value })}
            />
            <div className="form-row field-row">
              <label htmlFor={instructionsId}>指示</label>
              <textarea
                id={instructionsId}
                className="field agent-instructions"
                value={draft.instructions}
                aria-invalid={tooLong.instructions ? true : undefined}
                rows={9}
                placeholder={INSTRUCTIONS_PLACEHOLDER}
                aria-describedby={`${instructionsId}-hint`}
                onChange={(event) => edit({ instructions: event.target.value })}
              />
              <div id={`${instructionsId}-hint`} className="help agent-count">
                <span>
                  它扮演什麼角色、要遵守哪些規則、回答的格式。大量的參考資料請放進知識庫。
                </span>
                <span
                  className={
                    tooLong.instructions ? "mono agent-count-over" : "mono"
                  }
                >
                  {length(draft.instructions)} / {limits.instructions}
                </span>
              </div>
              {tooLong.instructions && (
                <div className="inline-error field-error" role="alert">
                  {tooLong.instructions}
                </div>
              )}
            </div>
          </section>

          <fieldset className="model-choices access-field">
            <legend>開場建議</legend>
            <div className="help">
              新對話頁會顯示成按鈕，點了直接填進輸入框。最多 {limits.starters}{" "}
              個。
            </div>
            <ul className="agent-starters">
              {starters.map((text, index) => (
                // biome-ignore lint/suspicious/noArrayIndexKey: 依位置編輯的欄位
                <li key={index}>
                  <input
                    className="field"
                    value={text}
                    aria-invalid={tooLong.starters[index] ? true : undefined}
                    title={tooLong.starters[index]}
                    aria-label={`開場建議 ${index + 1}`}
                    placeholder={
                      index === 0
                        ? "例如：幫我把這週的進度整理成週報"
                        : "再加一個"
                    }
                    onChange={(event) => {
                      const next = [...draft.starters];
                      next[index] = event.target.value;
                      edit({ starters: next });
                    }}
                  />
                  {index < draft.starters.length && (
                    <button
                      type="button"
                      className="icon-btn"
                      aria-label={`刪除開場建議 ${index + 1}`}
                      onClick={() =>
                        edit({
                          starters: draft.starters.filter(
                            (_, i) => i !== index,
                          ),
                        })
                      }
                    >
                      <CloseIcon size={14} />
                    </button>
                  )}
                </li>
              ))}
            </ul>
            {Object.values(tooLong.starters)[0] && (
              <div className="inline-error field-error" role="alert">
                {Object.values(tooLong.starters)[0]}
              </div>
            )}
          </fieldset>

          <ModelField
            project={project}
            value={draft.model}
            onChange={(model) => edit({ model })}
          />

          <CheckList
            legend="工具"
            help="勾選這個 Agent 可以使用的工具。需要確認的工具照樣會先問你。"
            empty="管理者還沒有開放工具給你。"
            items={withMissing(
              options.toolsets,
              draft.toolsets,
              (name) => toolsetText(name, true, []).label,
            )}
            value={draft.toolsets}
            onChange={(toolsets) => edit({ toolsets })}
          />
          <CheckList
            legend="知識庫"
            help="回答前會先搜尋勾選的知識庫，並標出出處。"
            empty="目前沒有開放給你的知識庫。"
            items={withMissing(options.knowledgeBases, draft.knowledgeBases)}
            value={draft.knowledgeBases}
            onChange={(knowledgeBases) => edit({ knowledgeBases })}
          />
          {(options.skills.length > 0 || draft.skills.length > 0) && (
            <CheckList
              legend="技能"
              help="遇到相關的工作時，Agent 會載入技能，照著裡面的步驟做。製作 Excel、Word、PowerPoint 與 PDF 檔的技能要搭配「執行 Python」工具。"
              empty="這個專案沒有技能。"
              warning={
                draft.skills.some((name) => SANDBOX_SKILLS.has(name)) &&
                !draft.toolsets.includes(SANDBOX_TOOLSET)
                  ? sandboxWarning(project)
                  : undefined
              }
              items={withMissing(options.skills, draft.skills)}
              value={draft.skills}
              onChange={(skills) => edit({ skills })}
            />
          )}

          {saved && (
            <div className="group-danger">
              <button
                type="button"
                className="btn btn-outline"
                onClick={() => setDeleting(true)}
              >
                <TrashIcon size={15} />
                刪除 Agent
              </button>
            </div>
          )}
        </div>

        <aside className="agent-preview" aria-label="預覽">
          <div className="agent-preview-label">新對話頁的樣子</div>
          <div className="agent-preview-card">
            <span className="agent-avatar agent-avatar-lg" aria-hidden="true">
              {agentInitial(draft.name || "A")}
            </span>
            <p className="agent-preview-name">
              {draft.name.trim() || "未命名的 Agent"}
            </p>
            <p className="agent-preview-desc">
              {draft.description.trim() || "說明會顯示在這裡"}
            </p>
            {draft.starters.some((item) => item.trim()) && (
              <ul className="ch-suggestions agent-preview-starters">
                {draft.starters
                  .filter((item) => item.trim())
                  .map((item) => (
                    <li key={item}>
                      <span className="ch-suggestion">{item}</span>
                    </li>
                  ))}
              </ul>
            )}
          </div>
        </aside>
      </div>

      {deleting &&
        saved &&
        createPortal(
          <ConfirmDialog
            title={`刪除「${saved.name}」？`}
            confirmLabel="刪除 Agent"
            danger
            onConfirm={async () => {
              await api.deleteUserAgent(saved.id);
              showToast(`已刪除「${saved.name}」`);
              navigate("/agents", { replace: true });
            }}
            onClose={() => setDeleting(false)}
          >
            用它開始的對話還留著，可以看，但不能再接著聊。
          </ConfirmDialog>,
          document.body,
        )}
    </Page>
  );
}

function toDraft(agent: UserAgentInfo): Draft {
  return {
    name: agent.name,
    description: agent.description,
    instructions: agent.instructions,
    starters: agent.starters,
    model: agent.model,
    toolsets: agent.toolsets,
    knowledgeBases: agent.knowledgeBases,
    skills: agent.skills,
  };
}

/** 送出前整理：去掉空白的開場建議。 */
function cleaned(draft: Draft): Draft {
  return {
    ...draft,
    name: draft.name.trim(),
    description: draft.description.trim(),
    instructions: draft.instructions.trim(),
    starters: draft.starters.map((item) => item.trim()).filter(Boolean),
  };
}

/** 字數：和伺服器一樣用字元算（中文、表情符號都算一個字），頭尾空白不算。 */
function length(text: string): number {
  return Array.from(text.trim()).length;
}

type Overflow = {
  name?: string;
  description?: string;
  instructions?: string;
  starters: Record<number, string>;
};

/** 超過上限的欄位與提示。輸入框不擋字數，免得貼上長文時尾巴默默不見。 */
function overflow(draft: Draft, limits: UserAgentList["limits"]): Overflow {
  const over = (label: string, text: string, limit: number) => {
    const count = length(text);
    return count > limit
      ? `${label}最多 ${limit} 個字，現在 ${count} 個字`
      : undefined;
  };
  const starters: Record<number, string> = {};
  draft.starters.forEach((text, index) => {
    const message = over("開場建議", text, limits.starter);
    if (message) starters[index] = message;
  });
  return {
    name: over("名稱", draft.name, limits.name),
    description: over("說明", draft.description, limits.description),
    instructions: over("指示", draft.instructions, limits.instructions),
    starters,
  };
}

/** 第一個超過上限的提示，沒有就是 undefined。 */
function firstOverflow(found: Overflow): string | undefined {
  return (
    found.name ??
    found.description ??
    found.instructions ??
    Object.values(found.starters)[0]
  );
}

function ModelField({
  project,
  value,
  onChange,
}: {
  project: ProjectInfo;
  value: string | null;
  onChange: (value: string | null) => void;
}) {
  const id = useId();
  const models = project.models ?? [];
  const fallback = models.find((item) => item.isDefault) ?? models[0];
  const known = value === null || models.some((item) => item.name === value);
  return (
    <div className="form-row field-row">
      <label htmlFor={id}>預設模型</label>
      <select
        id={id}
        className="field"
        value={value ?? ""}
        onChange={(event) => onChange(event.target.value || null)}
      >
        <option value="">
          跟著預設{fallback ? `（${fallback.label}）` : ""}
        </option>
        {models.map((item) => (
          <option key={item.name} value={item.name}>
            {item.label}
          </option>
        ))}
        {!known && value && (
          <option value={value}>{value}（目前不能使用）</option>
        )}
      </select>
      <div className="help">開始對話後，一樣可以在輸入框換模型。</div>
    </div>
  );
}

function CheckList({
  legend,
  help,
  empty,
  warning,
  items,
  value,
  onChange,
}: {
  legend: string;
  help: string;
  empty: string;
  /** 目前的勾選有問題時顯示的提醒。 */
  warning?: string;
  items: { name: string; label: string; hint?: string; missing?: boolean }[];
  value: string[];
  onChange: (value: string[]) => void;
}) {
  const toggle = (name: string) =>
    onChange(
      value.includes(name)
        ? value.filter((item) => item !== name)
        : [...value, name],
    );
  return (
    <fieldset className="model-choices access-field">
      <legend>{legend}</legend>
      <div className="help">{help}</div>
      {warning && (
        <p className="agent-warning" role="status">
          <WarnIcon size={14} />
          {warning}
        </p>
      )}
      {items.length === 0 ? (
        <p className="subtle">{empty}</p>
      ) : (
        <ul className="model-choices-list agent-checklist">
          {items.map((item) => (
            <li key={item.name}>
              <label
                className={`model-choice ${item.missing ? "is-missing" : ""}`}
              >
                <input
                  type="checkbox"
                  checked={value.includes(item.name)}
                  onChange={() => toggle(item.name)}
                />
                <span className="model-choice-label">{item.label}</span>
                {item.hint && (
                  <span className="model-choice-name" title={item.hint}>
                    {item.hint}
                  </span>
                )}
              </label>
            </li>
          ))}
        </ul>
      )}
    </fieldset>
  );
}
