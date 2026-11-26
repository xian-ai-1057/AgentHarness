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
  agentSkills,
  automaticSkills,
  type ComposerOptions,
  choosableSkills,
  missingTool,
  toggleSkill,
} from "../../web/src/components/chat/options.ts";

const skill = (name: string, requires: string[] = []) => ({
  name,
  description: "",
  builtin: true,
  requires,
});

const project = {
  skills: [
    skill("xlsx", ["run_python"]),
    skill("docx", ["run_python"]),
    skill("pdf", ["run_python"]),
    skill("internal-comms"),
    skill("planning"),
  ],
  defaultSkills: ["xlsx", "docx", "pptx", "pdf", "internal-comms"],
} as unknown as ProjectInfo;

const agent = (tools: string[]) => ({ name: "main", tools }) as AgentInfo;

const composer = (
  value: Partial<SessionOptions>,
  defaults = ["xlsx", "docx", "pdf", "internal-comms"],
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
  it("需要 run_python 的只在 agent 能執行程式時才有", () => {
    expect(agentDefaultSkills(project, agent(["run_python"]))).toEqual([
      "xlsx",
      "docx",
      "pdf",
      "internal-comms",
    ]);
    expect(agentDefaultSkills(project, agent(["read_file"]))).toEqual([
      "internal-comms",
    ]);
    expect(agentDefaultSkills(project, undefined)).toEqual(["internal-comms"]);
  });

  it("agent 沒有需要的工具時，＋ 選單不列出那些 skill", () => {
    const names = (tools: string[]) =>
      agentSkills(project, agent(tools)).map((item) => item.name);

    expect(names(["read_file"])).toEqual(["internal-comms", "planning"]);
    expect(names(["run_python"])).toHaveLength(5);
  });

  it("扣掉關掉的；工具取消 run_python 時只剩不需要它的", () => {
    expect(activeDefaultSkills(composer({ disabledSkills: ["docx"] }))).toEqual(
      ["xlsx", "pdf", "internal-comms"],
    );
    expect(activeDefaultSkills(composer({ tools: ["read_file"] }))).toEqual([
      "internal-comms",
    ]);
  });

  it("工具取消 run_python 時說明缺哪個工具", () => {
    const options = composer({ tools: ["read_file"] });

    expect(missingTool(options, "xlsx")).toBe("run_python");
    expect(missingTool(options, "internal-comms")).toBeUndefined();
    expect(missingTool(composer({}), "xlsx")).toBeUndefined();
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

describe("自動開啟的 skills 不列給使用者", () => {
  const withMine = {
    ...project,
    skills: [
      ...(project.skills ?? []),
      { ...skill("my-report"), builtin: false, personal: true },
    ],
    defaultSkills: [...(project.defaultSkills ?? []), "my-report"],
  } as unknown as ProjectInfo;

  it("自動開啟的是公司與內建的預設 skill，不含自己的", () => {
    expect([...automaticSkills(withMine)]).toEqual([
      "xlsx",
      "docx",
      "pptx",
      "pdf",
      "internal-comms",
    ]);
    expect(automaticSkills({} as ProjectInfo).size).toBe(0);
  });

  it("＋ 選單只列可以自己挑的與自己的 skill", () => {
    const names = choosableSkills(withMine, agent(["run_python"])).map(
      (item) => item.name,
    );
    expect(names).toEqual(["planning", "my-report"]);
  });
});
