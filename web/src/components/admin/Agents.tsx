/**
 * 管理平台 → Agent（Python 版，features.agentAdmin）：管理者新增與修改
 * 公司的 agent，也就是專案的 agents/*.md。成員自建的 agent 在 Agent 頁，
 * 只有建立的人能用；這裡的 agent 是提供給大家的。
 *
 * - 網頁上能改說明、指示、工具、skills 與預設搜尋的知識庫；其他設定
 *   （model、subagents、handoffs…）原樣保留，只能改檔案。
 * - 工具與 skills 可以「不限制」（檔案裡不寫，專案有的都能用），或只勾
 *   選某些。檔案裡寫了工具組以外的名稱（單一工具、ontology）會保留。
 * - 掛載的 MCP 伺服器在「MCP 工具」頁指定 agent，不寫進檔案。
 * - 存檔前伺服器會重新載入檢查，設定有誤時不儲存，原本的檔案不變。
 */

import {
  type FormEvent,
  type ReactNode,
  useCallback,
  useEffect,
  useId,
  useState,
} from "react";
import { createPortal } from "react-dom";
import type {
  AdminAgentInfo,
  AdminAgentList,
} from "../../../../src/web/protocol.ts";
import { toolsetText } from "../../agents.ts";
import { api } from "../../api.ts";
import { refreshProject } from "../../store.ts";
import { CheckList } from "../AgentsView.tsx";
import { AddIcon } from "../Icons.tsx";
import { Modal } from "../shell/Dialog.tsx";
import { Field } from "../shell/Field.tsx";
import { showToast } from "../shell/toast.tsx";

const NAME_PATTERN = /^[A-Za-z][A-Za-z0-9_-]{0,39}$/;

interface Draft {
  name: string;
  description: string;
  instructions: string;
  /** null 表示不限制。 */
  tools: string[] | null;
  skills: string[] | null;
  knowledge: string[];
}

const EMPTY: Draft = {
  name: "",
  description: "",
  instructions: "",
  tools: ["files", "web"],
  skills: null,
  knowledge: [],
};

export function Agents() {
  const [list, setList] = useState<AdminAgentList>();
  const [loadError, setLoadError] = useState<string>();
  const [editing, setEditing] = useState<AdminAgentInfo | "new">();

  const load = useCallback(async () => {
    setLoadError(undefined);
    try {
      setList(await api.adminAgents());
    } catch (error) {
      setLoadError((error as Error).message);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <section aria-labelledby="h-agents" className="settings-body">
      <div className="members-head">
        <div>
          <h2 id="h-agents">Agent</h2>
          <p className="lead">
            {
              "公司提供給大家的 agent（專案的 agents/*.md）。可以改說明、指示、工具、skills 與預設搜尋的知識庫；誰能用哪些工具與知識庫仍由「群組」決定。成員自建的 agent 只有建立的人看得到，不在這裡。"
            }
          </p>
        </div>
        <button
          type="button"
          className="btn btn-accent"
          disabled={!list}
          onClick={() => setEditing("new")}
        >
          <AddIcon size={15} />
          新增 Agent
        </button>
      </div>

      {loadError && (
        <div className="box box-row" role="alert">
          <span className="inline-error">讀不到 agent：{loadError}</span>
          <button type="button" className="btn btn-outline" onClick={load}>
            重試
          </button>
        </div>
      )}
      {!list && !loadError && (
        <p className="subtle" aria-busy="true">
          讀取中…
        </p>
      )}

      {list && (
        <ul className="member-list" aria-label="公司的 Agent">
          {list.agents.map((agent) => (
            <li key={agent.name} className="member-row">
              <div className="member-main">
                <div className="member-name">
                  <span className="member-display">{agent.name}</span>
                  <span className="subtle mono">{agent.file}</span>
                  {agent.default && (
                    <span className="badge badge-accent">預設</span>
                  )}
                </div>
                <div className="member-meta skill-desc">
                  {agent.description || "沒有說明"}
                </div>
                <div className="member-meta">
                  {[
                    agent.tools === null
                      ? "工具不限制"
                      : `工具：${agent.tools.join("、") || "無"}`,
                    agent.skills === null
                      ? "skills 不限制"
                      : `skills：${agent.skills.length} 個`,
                    agent.knowledge.length > 0 &&
                      `知識庫：${agent.knowledge.length} 個`,
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </div>
              </div>
              <button
                type="button"
                className="btn btn-outline btn-sm"
                onClick={() => setEditing(agent)}
              >
                編輯
              </button>
            </li>
          ))}
          {list.agents.length === 0 && (
            <li className="subtle">還沒有公司的 agent。</li>
          )}
        </ul>
      )}

      {list &&
        editing &&
        createPortal(
          <AgentDialog
            agent={editing === "new" ? undefined : editing}
            catalog={list.catalog}
            taken={list.agents.map((agent) => agent.name)}
            onClose={() => setEditing(undefined)}
            onSaved={async (name, created) => {
              setEditing(undefined);
              showToast(created ? `已新增 ${name}` : `已儲存 ${name}`);
              await Promise.all([load(), refreshProject()]);
            }}
          />,
          document.body,
        )}
    </section>
  );
}

function AgentDialog({
  agent,
  catalog,
  taken,
  onClose,
  onSaved,
}: {
  agent?: AdminAgentInfo;
  catalog: AdminAgentList["catalog"];
  taken: string[];
  onClose: () => void;
  onSaved: (name: string, created: boolean) => Promise<void>;
}) {
  const titleId = useId();
  const descriptionId = useId();
  const instructionsId = useId();
  const [draft, setDraft] = useState<Draft>(
    agent
      ? {
          name: agent.name,
          description: agent.description,
          instructions: agent.instructions,
          tools: agent.tools,
          skills: agent.skills,
          knowledge: agent.knowledge,
        }
      : EMPTY,
  );
  const [touched, setTouched] = useState(false);
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);
  const creating = agent === undefined;
  const edit = (change: Partial<Draft>) => {
    setDraft((current) => ({ ...current, ...change }));
    setError(undefined);
  };

  const nameError = !creating
    ? undefined
    : !draft.name.trim()
      ? "請輸入名稱"
      : !NAME_PATTERN.test(draft.name.trim())
        ? "英文字母開頭，只能有英文、數字、底線與連字號，最多 40 個字元"
        : taken.includes(draft.name.trim())
          ? "已經有同名的 agent"
          : undefined;

  const toolsetNames = catalog.toolsets.map((set) => set.name);
  const toolItems = [
    ...catalog.toolsets.map((set) => {
      const text = toolsetText(set.name, set.builtin, set.tools);
      return { name: set.name, label: text.label, hint: text.hint };
    }),
    // 檔案裡寫的單一工具或這裡不列的工具組（例如 ontology）照樣保留。
    ...(draft.tools ?? [])
      .filter((name) => !toolsetNames.includes(name))
      .map((name) => ({
        name,
        label: name,
        hint: "檔案裡寫的工具或工具組",
      })),
  ];
  const skillItems = [
    ...catalog.skills.map((skill) => ({
      name: skill.name,
      label: skill.builtin ? `${skill.name}（內建）` : skill.name,
      hint: skill.description,
    })),
    ...(draft.skills ?? [])
      .filter((name) => !catalog.skills.some((skill) => skill.name === name))
      .map((name) => ({
        name,
        label: name,
        hint: "找不到這個 skill",
        missing: true,
      })),
  ];
  const baseItems = [
    ...catalog.knowledgeBases.map((base) => ({
      name: base.id,
      label: base.name,
      hint: base.description,
    })),
    ...draft.knowledge
      .filter((id) => !catalog.knowledgeBases.some((base) => base.id === id))
      .map((id) => ({
        name: id,
        label: id,
        hint: "找不到這個知識庫",
        missing: true,
      })),
  ];

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setTouched(true);
    if (nameError) return;
    if (!draft.instructions.trim()) {
      setError("請填寫指示");
      return;
    }
    setBusy(true);
    const input = {
      description: draft.description,
      instructions: draft.instructions,
      tools: draft.tools,
      skills: draft.skills,
      knowledge: draft.knowledge,
    };
    try {
      if (creating) {
        const name = draft.name.trim();
        await api.createAdminAgent({ ...input, name });
        await onSaved(name, true);
      } else {
        await api.updateAdminAgent(agent.name, input);
        await onSaved(agent.name, false);
      }
    } catch (failure) {
      setError((failure as Error).message);
      setBusy(false);
    }
  };

  return (
    <Modal
      onClose={onClose}
      className="confirm-dialog form-dialog skill-dialog"
      labelledBy={titleId}
    >
      <form onSubmit={submit} noValidate>
        <h2 id={titleId} className="dialog-title">
          {creating ? "新增公司 Agent" : `編輯 ${agent.name}`}
        </h2>
        {agent && (
          <p className="help skill-note">
            存在 <code>{agent.file}</code>
            。存檔會重寫開頭的設定，檔案裡的註解會消失。
            {agent.otherSettings.length > 0 &&
              ` 這些設定只能改檔案，會原樣保留：${agent.otherSettings.join("、")}。`}
          </p>
        )}
        <div className="dialog-fields">
          <Field
            label="名稱"
            className="mono"
            autoComplete="off"
            value={draft.name}
            disabled={!creating}
            placeholder="例如 hr-helper"
            error={touched ? nameError : undefined}
            hint={
              creating
                ? "英文識別碼，存成 agents/<名稱>.md，建立後不能修改。"
                : "名稱是識別碼，不能修改。"
            }
            onChange={(event) => edit({ name: event.target.value })}
          />
          <div className="form-row field-row">
            <label htmlFor={descriptionId}>說明</label>
            <input
              id={descriptionId}
              className="field"
              value={draft.description}
              maxLength={300}
              placeholder="一句話說明這個 agent 做什麼，顯示在新對話頁與 Agent 頁"
              onChange={(event) => edit({ description: event.target.value })}
            />
          </div>
          <div className="form-row field-row">
            <label htmlFor={instructionsId}>指示</label>
            <textarea
              id={instructionsId}
              className="field agent-instructions skill-instructions"
              rows={12}
              value={draft.instructions}
              placeholder="這個 agent 的角色、要做的事、回答的方式與限制"
              onChange={(event) => edit({ instructions: event.target.value })}
            />
          </div>

          <Limited
            legend="工具"
            value={draft.tools}
            allText="不限制：專案有的工具都能用（成員仍受群組限制）"
            someText="只用勾選的工具組"
            initial={toolsetNames}
            onChange={(tools) => edit({ tools })}
          >
            <CheckList
              legend="工具組"
              help="需要確認的工具照樣會先問使用者。"
              empty="這個專案沒有工具組。"
              items={toolItems}
              value={draft.tools ?? []}
              onChange={(tools) => edit({ tools })}
            />
          </Limited>
          {catalog.mcpServers.length > 0 && (
            <p className="help">
              掛載的 MCP 伺服器（{catalog.mcpServers.join("、")}）在「MCP
              工具」頁指定給哪些 agent，不在這裡設定。
            </p>
          )}

          <Limited
            legend="Skills"
            value={draft.skills}
            allText="不限制：專案的公司 skill 都列給它（不含內建的）"
            someText="只列勾選的 skill"
            initial={catalog.skills.map((skill) => skill.name)}
            onChange={(skills) => edit({ skills })}
          >
            <CheckList
              legend="Skills"
              help="製作 Excel、Word、PowerPoint 與 PDF 的 skill 要搭配「執行 Python」工具。"
              empty="還沒有 skill。"
              items={skillItems}
              value={draft.skills ?? []}
              onChange={(skills) => edit({ skills })}
            />
          </Limited>
          <p className="help">
            另外，Skills 頁設為「預設開啟」的 skill
            每段對話都會加上，使用者也可以在輸入框的 ＋
            選單自己挑；沒開放給他的群組、被關閉的 skill 一律不會給。
          </p>

          <CheckList
            legend="預設搜尋的知識庫"
            help={
              agent?.knowledgeFilter
                ? "回答前先搜尋勾選的知識庫。檔案裡設定的標籤過濾與 topK 會保留。"
                : "回答前先搜尋勾選的知識庫，並標出出處。"
            }
            empty="還沒有知識庫。"
            items={baseItems}
            value={draft.knowledge}
            onChange={(knowledge) => edit({ knowledge })}
          />
        </div>

        {error && (
          <p className="inline-error" role="alert">
            {error}
          </p>
        )}
        <div className="dialog-actions">
          <button type="button" className="btn btn-outline" onClick={onClose}>
            取消
          </button>
          <button type="submit" className="btn btn-accent" disabled={busy}>
            {busy && <span className="spinner spin" aria-hidden="true" />}
            {creating ? "建立" : "儲存"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

/** 「不限制」或「只用勾選的」；選後者時顯示勾選清單。 */
function Limited({
  legend,
  value,
  allText,
  someText,
  onChange,
  initial,
  children,
}: {
  legend: string;
  value: string[] | null;
  allText: string;
  someText: string;
  onChange: (value: string[] | null) => void;
  /** 從「不限制」改成「只用勾選的」時先勾選這些。 */
  initial: string[];
  children: ReactNode;
}) {
  const name = useId();
  return (
    <fieldset className="limited-field">
      <legend>{legend}</legend>
      <label className="limited-choice">
        <input
          type="radio"
          name={name}
          checked={value === null}
          onChange={() => onChange(null)}
        />
        {allText}
      </label>
      <label className="limited-choice">
        <input
          type="radio"
          name={name}
          checked={value !== null}
          onChange={() => onChange(value ?? initial)}
        />
        {someText}
      </label>
      {value !== null && children}
    </fieldset>
  );
}
