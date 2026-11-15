/**
 * 自建 Agent 的共用小工具：顯示名稱、工具組的白話說明。
 *
 * 自建的 agent 在對話裡的名稱是 user:<識別碼>，畫面上一律顯示它的名稱
 * （AgentInfo.label）；刪掉之後顯示建立對話時記下的名稱。
 */

import type {
  AgentInfo,
  ProjectInfo,
  SessionSummary,
} from "../../src/web/protocol.ts";

export const USER_AGENT_PREFIX = "user:";

export function isUserAgent(name: string | undefined): boolean {
  return Boolean(name?.startsWith(USER_AGENT_PREFIX));
}

/** agent 在畫面上的名稱。 */
export function agentLabel(agent: AgentInfo): string {
  return agent.label ?? agent.name;
}

/** 一段對話的 agent 在畫面上的名稱。 */
export function sessionAgentLabel(
  project: ProjectInfo | undefined,
  summary: Pick<SessionSummary, "agent" | "agentLabel">,
): string {
  const found = project?.agents.find((item) => item.name === summary.agent);
  if (found) return agentLabel(found);
  if (summary.agentLabel) return summary.agentLabel;
  return isUserAgent(summary.agent) ? "已刪除的 Agent" : summary.agent;
}

/** 這段對話用的自建 agent 已經被刪掉了（專案資訊還沒載入時不算）。 */
export function isDeletedAgent(
  project: ProjectInfo | undefined,
  agent: string | undefined,
): boolean {
  if (!project || !isUserAgent(agent)) return false;
  return !project.agents.some((item) => item.name === agent);
}

/** 內建工具組的白話說明；專案自己的工具組顯示名稱與工具。 */
const BUILTIN_TOOLSETS: Record<string, { label: string; hint: string }> = {
  files: {
    label: "讀寫檔案",
    hint: "讀取、搜尋、建立與修改工作資料夾裡的檔案",
  },
  shell: { label: "執行指令", hint: "在工作資料夾執行終端機指令" },
  web: { label: "上網查資料", hint: "搜尋網路、讀取網頁" },
  plan: { label: "計畫清單", hint: "做事前列出步驟，邊做邊打勾" },
  sandbox: { label: "執行 Python", hint: "在隔離的沙盒裡執行 Python 程式" },
};

export function toolsetText(
  name: string,
  builtin: boolean,
  tools: string[],
): { label: string; hint: string } {
  const known = BUILTIN_TOOLSETS[name];
  if (known && (builtin || name === "sandbox")) return known;
  return { label: name, hint: tools.join("、") };
}

/** 頭像上的字：名稱的第一個字（英文轉大寫）。 */
export function agentInitial(name: string): string {
  const first = Array.from(name.trim())[0] ?? "A";
  return first.toUpperCase();
}
