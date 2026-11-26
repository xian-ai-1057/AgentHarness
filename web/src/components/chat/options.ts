/** 輸入框的模型、工具、skills、知識庫選項（Python 版才有）。 */

import type {
  AgentInfo,
  KnowledgeBaseInfo,
  ModelOption,
  ProjectInfo,
  SessionOptions,
  SkillInfo,
} from "../../../../src/web/protocol.ts";

/** ＋ 選單與模型選單需要的資料。 */
export interface ComposerOptions {
  models: ModelOption[];
  skills: SkillInfo[];
  /** 這個 agent 預設開啟的 skills（只有它用得上的）。 */
  defaultSkills?: string[];
  /** 這個 agent 可以用的工具名稱與說明。 */
  tools: { name: string; description: string }[];
  /** 可以勾選的知識庫（群組開放的）。 */
  knowledgeBases: KnowledgeBaseInfo[];
  /** 沒有另外勾選時，agent 預設搜尋的知識庫。 */
  defaultKnowledge: string[];
  value: SessionOptions;
  /** 沒選模型時實際會用的模型名稱（agent 或專案的設定）。 */
  fallbackModel?: string | null;
  onChange: (change: Partial<SessionOptions>) => void;
  /** 在對話裡改的選項要等下一則訊息才生效，選單裡要說明。 */
  nextTurn?: boolean;
}

export const EMPTY_OPTIONS: SessionOptions = {
  model: null,
  tools: null,
  skills: [],
};

/** 伺服器支援而且有模型可以選時，才顯示這些選項。 */
export function optionsEnabled(project: ProjectInfo | undefined): boolean {
  return Boolean(
    project?.features?.sessionOptions && (project.models?.length ?? 0) > 0,
  );
}

/** agent 可以用的工具，附上 toolsets 裡的說明。 */
export function agentTools(
  project: ProjectInfo,
  agent: AgentInfo,
): ComposerOptions["tools"] {
  const known = new Map(
    project.toolsets.flatMap((set) => set.tools).map((t) => [t.name, t]),
  );
  return agent.tools.map((name) => ({
    name,
    description: known.get(name)?.description ?? "",
  }));
}

/** agent 預設搜尋的知識庫，只留可以勾選的。 */
export function agentKnowledge(
  project: ProjectInfo,
  agent: AgentInfo | undefined,
): string[] {
  const open = new Set((project.knowledgeBases ?? []).map((base) => base.id));
  return (agent?.knowledge ?? []).filter((id) => open.has(id));
}

/** 這段對話實際會搜尋的知識庫：自己勾選的，或 agent 的預設。 */
export function chosenKnowledge(
  value: SessionOptions,
  defaults: string[],
): string[] {
  return value.knowledge ?? defaults;
}

/**
 * 勾選或取消一個知識庫後要存的值：和 agent 的預設一樣時存 null（跟著
 * agent），否則存勾選的清單（照知識庫的順序）。
 */
export function toggleKnowledge(
  value: SessionOptions,
  defaults: string[],
  bases: KnowledgeBaseInfo[],
  id: string,
): string[] | null {
  const current = new Set(chosenKnowledge(value, defaults));
  if (current.has(id)) current.delete(id);
  else current.add(id);
  const next = bases.map((base) => base.id).filter((key) => current.has(key));
  const same =
    next.length === defaults.length &&
    next.every((key) => defaults.includes(key));
  return same ? null : next;
}

/** 目前實際使用的模型名稱。 */
export function effectiveModel(
  value: SessionOptions,
  fallback: string | null | undefined,
  models: ModelOption[],
): string | undefined {
  return (
    value.model ??
    fallback ??
    models.find((model) => model.isDefault)?.name ??
    models[0]?.name
  );
}

/** 模型的顯示名稱；不在清單裡時用原本的名稱。 */
export function modelLabel(
  name: string | null | undefined,
  models: ModelOption[] | undefined,
): string | undefined {
  if (!name) return undefined;
  return models?.find((model) => model.name === name)?.label || name;
}

/**
 * agent 用得上的 skills：requires 的工具 agent 都有（群組沒開放或專案
 * 沒有沙盒時，agent 的工具裡就沒有 run_python）。
 */
export function agentSkills(
  project: ProjectInfo,
  agent: AgentInfo | undefined,
): SkillInfo[] {
  const tools = agent?.tools ?? [];
  return (project.skills ?? []).filter((skill) =>
    (skill.requires ?? []).every((name) => tools.includes(name)),
  );
}

/**
 * 每段對話自動開啟的公司與內建 skill（例如 docx、xlsx），不含個人的。
 * 和 Claude 一樣，這些能力自動可用，使用者端不逐一列出；要調整請管理者
 * 到管理平台的 Skills 頁。
 */
export function automaticSkills(project: ProjectInfo): Set<string> {
  const personal = new Set(
    (project.skills ?? []).filter((s) => s.personal).map((s) => s.name),
  );
  return new Set(
    (project.defaultSkills ?? []).filter((name) => !personal.has(name)),
  );
}

/** ＋ 選單列出、讓使用者自己挑的 skills：扣掉自動開啟的。 */
export function choosableSkills(
  project: ProjectInfo,
  agent: AgentInfo | undefined,
): SkillInfo[] {
  const automatic = automaticSkills(project);
  return agentSkills(project, agent).filter(
    (skill) => !automatic.has(skill.name),
  );
}

/** agent 預設開啟的 skills（只留它用得上的）。 */
export function agentDefaultSkills(
  project: ProjectInfo,
  agent: AgentInfo | undefined,
): string[] {
  const usable = new Set(agentSkills(project, agent).map((s) => s.name));
  return (project.defaultSkills ?? []).filter((name) => usable.has(name));
}

/**
 * 這段對話取消了 skill 需要的哪個工具；沒有取消時為 undefined。這時
 * skill 用不到，也不能勾選（和伺服器的判斷一樣）。
 */
export function missingTool(
  options: ComposerOptions,
  name: string,
): string | undefined {
  const tools = options.value.tools;
  if (!tools) return undefined;
  const skill = options.skills.find((item) => item.name === name);
  return (skill?.requires ?? []).find((tool) => !tools.includes(tool));
}

/** 這段對話實際開著的預設 skills：扣掉關掉的與需要的工具被取消的。 */
export function activeDefaultSkills(options: ComposerOptions): string[] {
  const off = options.value.disabledSkills ?? [];
  return (options.defaultSkills ?? []).filter(
    (name) => !off.includes(name) && !missingTool(options, name),
  );
}

/**
 * 在 ＋ 選單勾選或取消一個 skill 後要存的值。預設 skill 改的是
 * disabledSkills；其他 skill 改的是一定要用的 skills。
 */
export function toggleSkill(
  options: ComposerOptions,
  name: string,
): Partial<SessionOptions> {
  const { value } = options;
  if ((options.defaultSkills ?? []).includes(name)) {
    const off = value.disabledSkills ?? [];
    return off.includes(name)
      ? { disabledSkills: off.filter((item) => item !== name) }
      : {
          disabledSkills: [...off, name],
          skills: value.skills.filter((item) => item !== name),
        };
  }
  return {
    skills: value.skills.includes(name)
      ? value.skills.filter((item) => item !== name)
      : [...value.skills, name],
  };
}
