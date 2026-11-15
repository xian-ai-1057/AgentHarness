/** 預設開啟的 skills：對話裡顯示與關閉。 */

import { describe, expect, it } from "vitest";
import type {
  AgentInfo,
  ProjectInfo,
  SessionOptions,
} from "../../src/web/protocol.ts";
import {
  activeDefaultSkills,
  agentDefaultSkills,
  type ComposerOptions,
  toggleSkill,
} from "../../web/src/components/chat/options.ts";

const skill = (name: string) => ({ name, description: "", builtin: true });

const project = {
  skills: ["xlsx", "docx", "pdf", "planning"].map(skill),
  defaultSkills: ["xlsx", "docx", "pptx", "pdf"],
} as unknown as ProjectInfo;

const agent = (tools: string[]) => ({ name: "main", tools }) as AgentInfo;

const composer = (
  value: Partial<SessionOptions>,
  defaults = ["xlsx", "docx", "pdf"],
): ComposerOptions => ({
  models: [],
  skills: project.skills ?? [],
  defaultSkills: defaults,
  tools: [],
  knowledgeBases: [],
  defaultKnowledge: [],
  value: { model: null, tools: null, skills: [], ...value },
  onChange: () => {},
});

describe("預設開啟的 skills", () => {
  it("agent 能執行程式時才有，只留伺服器有的 skill", () => {
    expect(agentDefaultSkills(project, agent(["run_python"]))).toEqual([
      "xlsx",
      "docx",
      "pdf",
    ]);
    expect(agentDefaultSkills(project, agent(["read_file"]))).toEqual([]);
    expect(agentDefaultSkills(project, undefined)).toEqual([]);
  });

  it("扣掉關掉的；工具取消 run_python 時一個都沒有", () => {
    expect(activeDefaultSkills(composer({ disabledSkills: ["docx"] }))).toEqual(
      ["xlsx", "pdf"],
    );
    expect(activeDefaultSkills(composer({ tools: ["read_file"] }))).toEqual([]);
  });

  it("預設 skill 切換的是 disabledSkills，其他 skill 切換一定要用的", () => {
    expect(toggleSkill(composer({ skills: ["pdf"] }), "pdf")).toEqual({
      disabledSkills: ["pdf"],
      skills: [],
    });
    expect(
      toggleSkill(composer({ disabledSkills: ["pdf", "docx"] }), "pdf"),
    ).toEqual({ disabledSkills: ["docx"] });
    expect(toggleSkill(composer({}), "planning")).toEqual({
      skills: ["planning"],
    });
    expect(toggleSkill(composer({ skills: ["planning"] }), "planning")).toEqual(
      { skills: [] },
    );
  });
});
