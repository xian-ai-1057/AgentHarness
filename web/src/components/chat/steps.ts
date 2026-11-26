/**
 * 把工具呼叫寫成一句看得懂的話，例如「讀取 `src/app.ts`」。
 *
 * 畫面上的步驟列只顯示這句話；原始的參數與結果展開後才看得到。
 */

/** 一句話：動詞加上對象。對象依 style 決定怎麼排版。 */
export interface StepSentence {
  verb: string;
  target?: string;
  /** code：等寬字；quote：放進「」；plain：一般文字。 */
  style?: "code" | "quote" | "plain";
}

const SUBAGENT_PREFIX = "ask_";
const HANDOFF_PREFIX = "transfer_to_";
const TARGET_LIMIT = 80;

/** 只看路徑的工具：動詞與預設路徑。 */
const PATH_TOOLS: Record<string, { verb: string; fallback?: string }> = {
  read_file: { verb: "讀取" },
  list_dir: { verb: "列出", fallback: "." },
  write_file: { verb: "寫入" },
  edit_file: { verb: "修改" },
};

export function describeStep(step: {
  name: string;
  args: Record<string, unknown>;
}): StepSentence {
  const { name, args } = step;
  const path = PATH_TOOLS[name];
  if (path) {
    const target = text(args.path) ?? path.fallback;
    return target
      ? { verb: path.verb, target: clip(target), style: "code" }
      : { verb: path.verb };
  }
  switch (name) {
    case "find_files":
      return withTarget("尋找", args.pattern, "code");
    case "search_files":
      return withTarget("搜尋", args.pattern, "quote");
    case "run_command":
      return withTarget("執行", firstLine(args.command), "code");
    case "web_search":
      return withTarget("搜尋網路", args.query, "quote");
    case "web_fetch":
      return withTarget("讀取網頁", hostOf(args.url), "plain");
    case "load_skill":
      return withTarget("載入 skill", args.name, "code");
    case "read_skill_file":
      return withTarget(
        "讀取 skill 參考檔",
        [text(args.name), text(args.path)].filter(Boolean).join("/"),
        "code",
      );
    case "update_plan":
      return { verb: "更新計畫" };
    case "sandbox":
    case "run_python":
      return { verb: "執行 Python 程式" };
    case "find_entity":
      return withTarget(
        "查詢",
        [text(args.entity_type), text(args.query)].filter(Boolean).join(" "),
        "plain",
      );
    case "get_related":
      return withTarget(
        "查關係",
        [text(args.entity_type), text(args.entity_id)]
          .filter(Boolean)
          .join(" "),
        "plain",
      );
    case "search_knowledge":
      return withTarget("搜尋知識庫", args.query, "quote");
    case "remember":
      return withTarget("記住", firstLine(args.content), "quote");
    case "forget":
      return { verb: "刪除一則記憶" };
    case "search_documents":
      return withTarget("搜尋文件", args.query, "quote");
    case "get_metric":
      return withTarget("查指標", args.metric, "code");
    case "run_action":
      return withTarget("執行動作", args.action, "code");
  }
  const delegated = delegation(name);
  if (delegated) return { ...delegated, style: "plain" };
  const summary = shortArgs(args);
  return summary
    ? { verb: name, target: summary, style: "code" }
    : { verb: name };
}

/** 工具的白話名稱，例如 edit_file 是「修改檔案」；不認識的工具回傳 undefined。 */
const TOOL_LABELS: Record<string, string> = {
  read_file: "讀取檔案",
  list_dir: "列出資料夾",
  write_file: "寫入檔案",
  edit_file: "修改檔案",
  find_files: "尋找檔案",
  search_files: "搜尋檔案內容",
  run_command: "執行指令",
  web_search: "搜尋網路",
  web_fetch: "讀取網頁",
  update_plan: "更新計畫",
  load_skill: "載入 skill",
  read_skill_file: "讀取 skill 參考檔",
  sandbox: "執行 Python 程式",
  run_python: "執行 Python 程式",
  find_entity: "查詢業務物件",
  get_related: "查詢物件關係",
  search_documents: "搜尋文件",
  get_metric: "查詢指標",
  run_action: "執行動作",
  search_knowledge: "搜尋知識庫",
  remember: "記住一件事",
  forget: "刪除一則記憶",
};

export function toolLabel(name: string): string | undefined {
  const label = TOOL_LABELS[name];
  if (label) return label;
  const delegated = delegation(name);
  return delegated ? `${delegated.verb} ${delegated.target}` : undefined;
}

/** ask_researcher 是交給 subagent，transfer_to_billing 是把對話轉交出去。 */
function delegation(
  name: string,
): { verb: string; target: string } | undefined {
  for (const [prefix, verb] of [
    [SUBAGENT_PREFIX, "交給"],
    [HANDOFF_PREFIX, "轉交給"],
  ] as const) {
    if (name.startsWith(prefix) && name.length > prefix.length) {
      return { verb, target: name.slice(prefix.length) };
    }
  }
  return undefined;
}

/** 整句的純文字，給標題、aria-label 與測試用。 */
export function sentenceText(sentence: StepSentence): string {
  if (!sentence.target) return sentence.verb;
  if (sentence.style === "quote")
    return `${sentence.verb}「${sentence.target}」`;
  return `${sentence.verb} ${sentence.target}`;
}

function withTarget(
  verb: string,
  value: unknown,
  style: StepSentence["style"],
): StepSentence {
  const target = text(value);
  return target ? { verb, target: clip(target), style } : { verb };
}

function text(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() !== ""
    ? value.trim()
    : undefined;
}

function firstLine(value: unknown): string | undefined {
  const full = text(value);
  if (!full) return undefined;
  const [line = ""] = full.split("\n");
  return full.includes("\n") ? `${line} …` : line;
}

function hostOf(value: unknown): string | undefined {
  const url = text(value);
  if (!url) return undefined;
  try {
    return new URL(url).host || url;
  } catch {
    return url;
  }
}

function clip(value: string): string {
  return value.length > TARGET_LIMIT
    ? `${value.slice(0, TARGET_LIMIT)}…`
    : value;
}

/** 不認識的工具：把參數縮成一小段，例如 `query="天氣", limit=3`。 */
function shortArgs(args: Record<string, unknown>): string {
  const parts = Object.entries(args).map(([key, value]) => {
    if (typeof value === "string") {
      const line = value.split("\n")[0] ?? "";
      const more = value.includes("\n") || line.length > 30;
      return `${key}=${JSON.stringify(more ? `${line.slice(0, 30)}…` : line)}`;
    }
    return `${key}=${JSON.stringify(value)}`;
  });
  return clip(parts.join(", "));
}
