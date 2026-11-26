/**
 * 新對話：打招呼、輸入框，以及幾個建議。
 *
 * 送出後先在畫面上顯示訊息與「思考中」，建立好對話再切到對話頁。
 * 第一次使用、還沒連接模型時，改成顯示說明：模型在管理平台設定，管理
 * 者多一個前往管理平台的按鈕。
 *
 * 伺服器支援工作資料夾時，輸入框可以選資料夾：上傳的檔案放進那個
 * 資料夾，建立對話時一起送出（SessionOptions.folder）。
 *
 * ?agent=<名稱> 預先選好 agent（Agent 頁的「開始對話」）。選了自己建立的
 * agent 時，上方顯示它的名稱與說明，建議換成它的開場建議。
 */

import { useEffect, useMemo, useRef, useState } from "react";
import type { SessionOptions } from "../../../src/web/protocol.ts";
import { agentInitial, agentLabel } from "../agents.ts";
import { api } from "../api.ts";
import { isAdmin } from "../auth.ts";
import { activeFolder, foldersEnabled } from "../folders.ts";
import { navigate, useSearchParam } from "../router.ts";
import { upsertSummary, useStore } from "../store.ts";
import "./chat/chat.css";
import { Composer } from "./Composer.tsx";
import { PendingView } from "./Conversation.tsx";
import { FolderContext } from "./chat/folder.ts";
import {
  agentDefaultSkills,
  agentKnowledge,
  agentTools,
  type ComposerOptions,
  choosableSkills,
  EMPTY_OPTIONS,
  optionsEnabled,
} from "./chat/options.ts";
import { handOff } from "./chat/pending.ts";
import { Thinking } from "./chat/Thinking.tsx";
import {
  AlertIcon,
  ChevronDownIcon,
  CloseIcon,
  FolderIcon,
  GearIcon,
} from "./Icons.tsx";
import { Link } from "./Sidebar.tsx";

/** 輸入框底下的建議：點了把文字填進輸入框。 */
const SUGGESTIONS = [
  { label: "分析檔案", text: "幫我分析這個檔案，整理出重點與值得注意的地方：" },
  { label: "寫一份文件", text: "幫我寫一份文件，主題是：" },
  { label: "整理重點", text: "幫我把下面的內容整理成條列重點：\n\n" },
  { label: "上網查資料", text: "幫我上網查一下：" },
];

export function NewChat() {
  const project = useStore((s) => s.project);
  const agentParam = useSearchParam("agent");
  const [agentName, setAgentName] = useState<string | undefined>(
    agentParam ?? undefined,
  );
  const [error, setError] = useState<string>();
  const [draft, setDraft] = useState<{ text: string }>();
  const [sending, setSending] = useState<{
    text: string;
    attachments: string[];
  }>();
  const [options, setOptions] = useState<SessionOptions>(EMPTY_OPTIONS);
  const [chosenFolder, setChosenFolder] = useState<string>();
  // 從專案頁開的新對話（?category=）放進那個專案。
  const categoryId = useSearchParam("category");
  const category = useStore((s) =>
    categoryId
      ? s.categories.find((item) => item.id === categoryId)
      : undefined,
  );

  useEffect(() => {
    document.title = project ? `${project.name} · Harness` : "Harness";
  }, [project]);

  // 從 Agent 頁換了一個 agent 開新對話（網址的 ?agent= 變了）。
  useEffect(() => {
    if (!agentParam) return;
    setAgentName(agentParam);
    setOptions((current) => ({ ...current, tools: null }));
  }, [agentParam]);
  // 從知識庫頁開的新對話（?knowledge=）：在 agent 預設的知識庫之外再勾
  // 選那個知識庫。每個知識庫只套用一次，之後使用者自己改的不會被蓋掉。
  const knowledgeId = useSearchParam("knowledge");
  const appliedKnowledge = useRef<string>(undefined);
  useEffect(() => {
    if (!project || !knowledgeId || appliedKnowledge.current === knowledgeId)
      return;
    if (!project.knowledgeBases?.some((base) => base.id === knowledgeId))
      return;
    appliedKnowledge.current = knowledgeId;
    const first =
      project.agents.find((item) => item.name === project.defaultAgent) ??
      project.agents[0];
    const defaults = agentKnowledge(project, first);
    setOptions((current) => ({
      ...current,
      knowledge: [...defaults.filter((id) => id !== knowledgeId), knowledgeId],
    }));
  }, [project, knowledgeId]);

  const agent = useMemo(
    () =>
      project?.agents.find((item) => item.name === agentName) ??
      project?.agents.find((item) => item.name === project.defaultAgent) ??
      project?.agents[0],
    [project, agentName],
  );

  if (!project) return <main className="main" aria-busy="true" />;
  // 存取群組沒有開放任何 agent 或模型給這個人：說明原因，不顯示輸入框。
  const nothingOpen =
    !agent ||
    (project.features?.groups === true &&
      !isAdmin(project) &&
      (project.models?.length ?? 0) === 0);
  if (nothingOpen) {
    return (
      <main className="main">
        <div className="new-chat ch-new">
          <div className="new-chat-inner ch-new-inner anim-in">
            <section className="error-card ch-interrupted" role="status">
              <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
                <span className="ch-error-icon">
                  <AlertIcon />
                </span>
                <p className="body" style={{ margin: 0 }}>
                  管理者還沒有開放可以使用的{agent ? "模型" : " agent"}
                  給你，請聯絡管理者。
                </p>
              </div>
            </section>
          </div>
        </div>
      </main>
    );
  }

  const { connection } = project.model;
  if (connection && !connection.ready) {
    // 每個人看到同一張說明卡；管理者多一個前往管理平台的按鈕。
    const admin = isAdmin(project);
    return (
      <main className="main">
        <div className="new-chat ch-new">
          <div className="new-chat-inner ch-new-inner anim-in">
            <section className="error-card ch-interrupted" role="status">
              <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
                <span className="ch-error-icon">
                  <AlertIcon />
                </span>
                <p className="body" style={{ margin: 0 }}>
                  {admin
                    ? "還沒有連接模型。到管理平台選一家模型供應商並填上金鑰，就可以開始使用。"
                    : "還沒有連接模型，請管理者到管理平台完成設定。"}
                </p>
              </div>
              {admin && (
                <div className="actions">
                  <Link to="/admin/model" className="btn btn-accent">
                    前往管理平台
                  </Link>
                </div>
              )}
            </section>
          </div>
        </div>
      </main>
    );
  }

  const enabled = optionsEnabled(project);
  const folder = activeFolder(project, chosenFolder);
  const sessionOptions: Partial<SessionOptions> | undefined = enabled
    ? { ...options, ...(folder ? { folder } : {}) }
    : folder
      ? { folder }
      : undefined;
  const composerOptions: ComposerOptions | undefined = enabled
    ? {
        models: project.models ?? [],
        skills: choosableSkills(project, agent),
        defaultSkills: agentDefaultSkills(project, agent),
        tools: agentTools(project, agent),
        knowledgeBases: project.knowledgeBases ?? [],
        defaultKnowledge: agentKnowledge(project, agent),
        value: options,
        fallbackModel: agent.model,
        onChange: (change) =>
          setOptions((current) => ({ ...current, ...change })),
      }
    : undefined;

  const start = async (text: string, attachments: string[]) => {
    setError(undefined);
    setSending({ text, attachments });
    try {
      const summary = await api.createSession(
        text,
        agent.name,
        attachments,
        sessionOptions,
        category?.id,
      );
      upsertSummary(summary);
      handOff(summary.id, { text, attachments, base: 0, folder });
      navigate(`/s/${summary.id}`);
      return true;
    } catch (failure) {
      setSending(undefined);
      setError(`沒有開始對話：${(failure as Error).message}`);
      return false;
    }
  };

  const provided = project.agents.filter((item) => !item.custom);
  const mine = project.agents.filter((item) => item.custom);
  const agentOption = (item: (typeof project.agents)[number]) => (
    <option key={item.name} value={item.name}>
      {agentLabel(item)}
      {item.description ? ` — ${item.description}` : ""}
    </option>
  );
  const agentPicker =
    project.agents.length > 1 ? (
      <label className="select-chip">
        <span className="ch-hide-narrow">agent：</span>
        {agentLabel(agent)}
        <ChevronDownIcon />
        <select
          aria-label="選擇 agent"
          value={agent.name}
          onChange={(event) => {
            setAgentName(event.target.value);
            // 換 agent 後工具清單不同，工具選擇重新來過。
            setOptions((current) => ({ ...current, tools: null }));
          }}
        >
          {mine.length > 0 ? (
            <>
              <optgroup label="我的 Agent">{mine.map(agentOption)}</optgroup>
              <optgroup label="管理者提供的">
                {provided.map(agentOption)}
              </optgroup>
            </>
          ) : (
            project.agents.map(agentOption)
          )}
        </select>
      </label>
    ) : composerOptions ? undefined : (
      <span className="select-chip">agent：{agentLabel(agent)}</span>
    );
  // 自建的 agent 有開場建議時，取代一般的建議。
  const starters = agent.custom?.starters.length
    ? agent.custom.starters.map((text) => ({ label: text, text }))
    : SUGGESTIONS;

  return (
    <FolderContext.Provider value={folder}>
      <main className="main">
        <div className={`new-chat ch-new${sending ? " sending" : ""}`}>
          <div className="new-chat-inner ch-new-inner">
            {sending ? (
              <div className="thread ch-thread ch-new-thread">
                <PendingView pending={sending} />
                <Thinking />
              </div>
            ) : (
              <>
                {category && (
                  <div className="new-category anim-in">
                    <FolderIcon size={14} />
                    <span>在專案「{category.name}」開新對話</span>
                    <button
                      type="button"
                      className="icon-btn"
                      aria-label="不要放進專案"
                      onClick={() => navigate("/", { replace: true })}
                    >
                      <CloseIcon size={13} />
                    </button>
                  </div>
                )}
                {agent.custom ? (
                  <div className="ch-agent-intro anim-in">
                    <span
                      className="agent-avatar agent-avatar-lg"
                      aria-hidden="true"
                    >
                      {agentInitial(agentLabel(agent))}
                    </span>
                    <h1 className="ch-agent-name">{agentLabel(agent)}</h1>
                    {agent.description && (
                      <p className="ch-agent-desc">{agent.description}</p>
                    )}
                    <Link
                      to={`/agents/${agent.custom.id}`}
                      className="btn btn-ghost btn-sm ch-agent-edit"
                    >
                      <GearIcon size={14} />
                      編輯這個 Agent
                    </Link>
                  </div>
                ) : (
                  <h1 className="ch-greeting anim-in">今天要做什麼？</h1>
                )}
              </>
            )}

            <div className="anim-in" style={{ animationDelay: "0.06s" }}>
              <Composer
                placeholder="問點什麼，或交代一件工作"
                busy={Boolean(sending)}
                rows={3}
                autoFocus
                draft={draft}
                onSubmit={start}
                onUpload={
                  project.uploads
                    ? (file) => api.upload(file, folder)
                    : undefined
                }
                maxUploadBytes={project.uploads?.maxBytes}
                options={composerOptions}
                folder={
                  folder && foldersEnabled(project)
                    ? {
                        folders: project.folders ?? [],
                        value: folder,
                        onChange: setChosenFolder,
                      }
                    : undefined
                }
                controls={agentPicker}
              />
              {error && (
                <p className="inline-error" role="alert">
                  {error}
                </p>
              )}
            </div>

            {!sending && (
              <ul
                className="ch-suggestions anim-in"
                style={{ animationDelay: "0.12s" }}
                aria-label="建議"
              >
                {starters.map((item) => (
                  <li key={item.label}>
                    <button
                      type="button"
                      className="ch-suggestion"
                      onClick={() => setDraft({ text: item.text })}
                    >
                      {item.label}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </main>
    </FolderContext.Provider>
  );
}
