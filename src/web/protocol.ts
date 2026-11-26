/**
 * 網頁版伺服器與瀏覽器之間傳遞的資料格式。
 *
 * 這個檔案只有型別，前端也直接 import 它，兩邊的格式才不會走樣。
 */

import type { PermissionMode } from "../permissions.ts";
import type { Message, ToolResult } from "../types.ts";

export type { Message, PermissionMode, ToolResult };

/**
 * 對話目前的狀態。
 *   idle     這次啟動伺服器後還沒跑過
 *   running  正在跑
 *   waiting  等使用者確認工具呼叫
 *   done     跑完了
 *   error    出錯停下來（例如連不上模型）
 *   stopped  使用者按了停止
 */
export type SessionStatus =
  | "idle"
  | "running"
  | "waiting"
  | "done"
  | "error"
  | "stopped";

/** 正在跑的對話此刻在做什麼。 */
export interface Activity {
  /** compacting：正在壓縮對話（Python 版，摘要要多呼叫一次模型）。 */
  kind: "thinking" | "tool" | "writing" | "waiting" | "compacting";
  /** kind 為 tool 或 waiting 時，相關的工具名稱。 */
  tool?: string;
  /**
   * 正在工作的 subagent（Python 版）；有多層時由外到內以 › 連接。
   * 沒有時表示是直接和使用者對話的 agent。
   */
  agent?: string;
}

/** 上下文用量（Python 版，見對話壓縮）。 */
export interface ContextUsage {
  /** 下一次請求大約的 token 數（以模型上次回報的用量為準）。 */
  tokens: number;
  /** 模型的上下文上限；查不到時為 null。 */
  window: number | null;
  /** 超過這個 token 數會自動壓縮；不知道上限時為 null。 */
  threshold: number | null;
  /** 是否開啟自動壓縮。 */
  auto: boolean;
}

/** 管理平台「對話壓縮」裡一個模型的上下文上限。 */
export interface CompactionModel {
  name: string;
  label: string;
  /** 實際使用的上限；查不到時為 null（不會主動壓縮）。 */
  window: number | null;
  /** 上限從哪裡來：管理者設定、端點查到、harness.yaml 的預設值或 litellm。 */
  source: "config" | "detected" | "default" | "litellm" | null;
  /** 管理者另外設定的值。 */
  configured: number | null;
  /** 從端點（vLLM、LiteLLM Proxy）查到的值。 */
  detected: number | null;
}

/** 管理平台「對話壓縮」的設定（Python 版）。 */
export interface CompactionSettings {
  /** harness.yaml 寫了 compaction: false 時為 false。 */
  enabled: boolean;
  auto: boolean;
  thresholdRatio: number;
  /** harness.yaml 的 compaction.contextWindow（套用到所有模型）。 */
  defaultWindow: number | null;
  models: CompactionModel[];
}

/** subagent 內部呼叫的一個工具（Python 版）。 */
export interface SubagentStep {
  /** 畫面用的識別碼，在同一次 ask_<名稱> 呼叫裡不重複。 */
  id: string;
  /** subagent 自己的工具呼叫 id，用來對應權限確認。 */
  callId: string;
  /** 呼叫這個工具的 subagent。 */
  agent: string;
  /** 由外到內經過的 agent。 */
  path: string[];
  name: string;
  arguments: Record<string, unknown>;
  status: "running" | "done" | "error";
  result?: string;
}

/** 側欄與「工作中」列表需要的對話摘要。 */
export interface SessionSummary {
  id: string;
  /** 第一則使用者訊息的開頭，或使用者改過的名稱。 */
  title: string;
  agent: string;
  /**
   * 這段對話自己選的模型（Python 版）；沒有時跟著 agent 或專案的設定。
   * 下一輪開始時生效。
   */
  model?: string | null;
  /** 這段對話放在哪個專案（ChatCategory.id，Python 版）；沒有時是未分類。 */
  category?: string;
  status: SessionStatus;
  activity?: Activity;
  /** 這一輪開始的時間（毫秒）。 */
  startedAt?: number;
  endedAt?: number;
  /** 最後一次有動靜的時間（毫秒），用來排序。 */
  updatedAt: number;
  /** 出錯時的說明。 */
  error?: string;
  /** 最近一輪裡回報錯誤的工具呼叫數。 */
  toolErrors: number;
  /** 最近一輪正常結束的原因（end_turn、max_turns、blocked…）。 */
  stopReason?: string;
  /** 被防護規則擋下時的說明（Python 版；擋下的內容不會存進紀錄）。 */
  notice?: string;
  /** 正在等使用者決定的工具呼叫，讓列表可以直接允許或拒絕。 */
  approval?: Approval;
  /** 自建 agent 的名稱（Python 版）；agent 刪掉後仍然保留。 */
  agentLabel?: string;
  /** 最近一次的上下文用量（Python 版）。 */
  context?: ContextUsage;
  /** 這段對話碰過分級的資料（Python 版，見 SessionClassification）。 */
  classification?: SessionClassification;
}

/**
 * 資料分級（Python 版）：這段對話碰過的最高等級。資料超過目前模型能處理的
 * 等級時，伺服器自動改用可以處理的模型（例如地端模型），之後每一輪都
 * 繼續用它。
 */
export interface SessionClassification {
  /** 等級識別碼，例如 confidential。 */
  level: string;
  /** 等級名稱，例如「機密」。 */
  name: string;
  /** 資料來自哪裡，例如「知識庫「人資規章」」。 */
  sources: string[];
  /** 因此改用的模型；沒有改用時是 null。 */
  model: string | null;
}

/** 寫檔類工具執行前，給使用者看的內容。 */
export interface FilePreview {
  path: string;
  /** 檔案原本的內容，新檔案時為 null。 */
  before: string | null;
  after: string;
}

/** 一個等使用者決定的工具呼叫。 */
export interface Approval {
  id: string;
  sessionId: string;
  callId: string;
  tool: string;
  arguments: Record<string, unknown>;
  preview?: FilePreview;
  /** 每次都要核准（ontology 的 run_action）：只能允許這一次或拒絕。 */
  onceOnly?: boolean;
  /** run_action 要執行的動作，給人看的內容。 */
  action?: ApprovalAction;
}

/** 核准卡片上的 ontology 動作。 */
export interface ApprovalAction {
  name: string;
  label: string;
  effects: string;
  /** 對象，例如「合約 C-2024-007」；動作沒有對象時是 null。 */
  target: string | null;
  reason: string;
  params: { name: string; label: string; value: unknown }[];
}

/**
 * 使用者對工具呼叫的決定。
 *   once     只允許這一次
 *   session  這段對話之後都允許這個工具（Python 版；不寫進 harness.yaml）
 *   always   加進 harness.yaml 的 allow 規則，以後都允許
 *   deny     拒絕
 */
export type ApprovalDecision = "once" | "session" | "always" | "deny";

/** 一段對話的完整內容。 */
export interface SessionDetail {
  summary: SessionSummary;
  messages: Message[];
  /** 模型還在產生、尚未存進紀錄的文字。 */
  partial: string;
  approvals: Approval[];
  /** 這段對話自己的權限模式；null 表示跟著專案設定。 */
  mode: PermissionMode | null;
  /**
   * subagent 內部呼叫的工具，依上層 ask_<名稱> 呼叫的 id 分組（Python 版）。
   * subagent 的對話不存檔，伺服器重新啟動後就沒有了。
   */
  subagentSteps?: Record<string, SubagentStep[]>;
  /** 這段對話的選項（Python 版），見 SessionOptions。 */
  options?: SessionOptions;
  /**
   * 使用者對回覆的評價（Python 版），以 assistant 訊息在 messages 裡的
   * 索引為鍵。
   */
  feedback?: Record<string, Feedback>;
  /**
   * 產生每則回覆的模型（Python 版），以 assistant 訊息在 messages 裡的索引
   * 為鍵；這個功能加入之前的回覆沒有記錄。
   */
  replyModels?: Record<string, string>;
}

/**
 * 一段對話自己的選項（Python 版）。每一項都是 null 時跟著 agent 的設定。
 * PUT /api/sessions/:id/options 可以只送要改的欄位；建立對話時也可以帶。
 */
export interface SessionOptions {
  /** 這段對話用的模型，必須是 ProjectInfo.models 裡的名稱。 */
  model: string | null;
  /** 這段對話可以用的工具名稱；只能是 agent 原本就有的工具。null 表示全部。 */
  tools: string[] | null;
  /** 這段對話一定要用的 skill 名稱，會在送給模型的訊息裡提示它先讀取。 */
  skills: string[];
  /**
   * 這段對話關掉的預設 skill（ProjectInfo.defaultSkills 裡的名稱）。沒有或
   * 空陣列時，預設 skill 全部開著。
   */
  disabledSkills?: string[];
  /**
   * 這段對話要搜尋的知識庫（KnowledgeBaseInfo.id）；null 或沒有時跟著 agent
   * 的設定（AgentInfo.knowledge）。只能選 ProjectInfo.knowledgeBases 裡的。
   * 空陣列表示這段對話不搜尋知識庫。
   */
  knowledge?: string[] | null;
  /**
   * 這段對話的工作資料夾（FolderInfo.id）；沒有時是自己的「我的檔案」。
   * 訊息裡的附件、工具參數與 PRODUCED_MARKER 的路徑都相對於這個資料夾。
   */
  folder?: string | null;
}

/** 使用者對一則回覆的評價。 */
export interface Feedback {
  rating: "up" | "down";
  /** 倒讚時勾選的原因。 */
  reasons?: string[];
  comment?: string;
}

/** 對話搜尋的一筆結果（Python 版）。 */
export interface SearchResult {
  id: string;
  title: string;
  /** 命中訊息內容時，含關鍵字的一小段文字；只命中標題時沒有。 */
  snippet?: string;
  updatedAt: number;
}

/** 工作資料夾裡的一個檔案或資料夾（Python 版）。 */
export interface FileEntry {
  /** 相對於工作資料夾的路徑，用 / 分隔。 */
  path: string;
  name: string;
  kind: "file" | "dir";
  /** 檔案大小（位元組）；資料夾沒有。 */
  size?: number;
  /** 最後修改時間（毫秒）。 */
  modifiedAt: number;
}

/** 可以在輸入框選的一個模型（Python 版）。 */
export interface ModelOption {
  /** 交給 litellm 的模型名稱。 */
  name: string;
  /** 顯示用的名稱。 */
  label: string;
  /** 供應商名稱，例如 Anthropic、公司自架。 */
  provider: string;
  /** 是否看得懂圖片；不知道時沒有。 */
  vision?: boolean;
  /** 是否為專案預設的模型。 */
  isDefault?: boolean;
}

/** 可以在 ＋ 選單選的一個 skill（Python 版）。 */
export interface SkillInfo {
  name: string;
  description: string;
  /** 內建 skill 或專案 skills/ 裡的。 */
  builtin: boolean;
  /** 自己建立的個人 skill（只有自己看得到，預設開啟）。 */
  personal?: boolean;
  /**
   * agent 要有這些工具才用得上（例如 run_python）。沒有時 ＋ 選單不列出；
   * 這段對話取消了這些工具時不能勾選（Python 版）。
   */
  requires?: string[];
}

/**
 * 伺服器支援哪些功能（Python 版才有）。沒有這個欄位或某一項是 false 時，
 * 前端要把對應的介面藏起來，TypeScript 版的伺服器才不會壞掉。
 */
export interface ServerFeatures {
  /** GET /api/files、/api/files/list：預覽與列出工作資料夾的檔案。 */
  files: boolean;
  /** PATCH /api/sessions/:id（改名）、DELETE /api/sessions/:id。 */
  sessionAdmin: boolean;
  /** GET /api/sessions/search?q=。 */
  search: boolean;
  /** PUT /api/sessions/:id/options：每段對話自己選模型、工具、skills。 */
  sessionOptions: boolean;
  /** PUT /api/sessions/:id/feedback：對回覆按讚或倒讚。 */
  feedback: boolean;
  /** 權限確認可以選「這段對話都允許」（ApprovalDecision 的 session）。 */
  sessionApproval?: boolean;
  /** 多人帳號：登入、成員管理、每個人的資料分開（見 CurrentUser）。 */
  accounts?: boolean;
  /** 每段對話選工作資料夾（見 FolderInfo、SessionOptions.folder）。 */
  folders?: boolean;
  /**
   * GET /api/files/pdf?path=…&folder=…：把 Word、PowerPoint 檔轉成 PDF 送出
   * （伺服器用 LibreOffice 轉換並快取）。回 501 表示這台伺服器不能轉換，
   * 網頁改用瀏覽器裡的簡易預覽。
   */
  officePdf?: boolean;
  /**
   * 專案（對話的分類，見 ChatCategory）：GET/POST /api/categories、
   * PATCH/DELETE /api/categories/:id、PATCH /api/sessions/:id 的 category、
   * POST /api/sessions 的 category、POST /api/sessions/bulk（見 BulkRequest）。
   */
  categories?: boolean;
  /**
   * 存取群組（帳號模式）：管理者決定每位成員可以用哪些 agent、工具組、
   * 知識庫與知識庫標籤（見 AccessGroup）。成員拿到的 ProjectInfo 已經只列出開放
   * 給他的部分。模型不歸群組管，見 ProjectInfo.models。
   */
  groups?: boolean;
  /**
   * 多個知識庫（見 KnowledgeBaseInfo）：ProjectInfo.knowledgeBases、
   * SessionOptions.knowledge 與管理平台的知識庫頁（/api/knowledge）。
   */
  knowledgeBases?: boolean;
  /**
   * GET /api/knowledge/source?base=&path=（Python 版）：回覆裡的知識庫出處
   * 可以點，打開原文（PDF 跳到出處的頁碼）。只送得出這個人搜尋得到的文件。
   */
  knowledgeSources?: boolean;
  /**
   * 個人知識庫（Python 版）：側欄的「知識庫」頁可以瀏覽可以用的知識庫，
   * 也能建立只有自己能用的知識庫（見 MyKnowledge）。false 表示管理者在
   * harness.yaml 關掉了建立個人知識庫（頁面仍然列出公司知識庫）。
   */
  personalKnowledge?: boolean;
  /**
   * 稽核紀錄（Python 版）：管理平台可以查詢與匯出登入、成員、群組、設定
   * 與工具核准的紀錄（見 AuditEntry）。
   */
  audit?: boolean;
  /**
   * 自建 Agent（Python 版）：每個人在 /agents 建立自己的 agent，只能挑
   * 所屬群組開放的工具組與知識庫（見 UserAgentInfo）。
   */
  userAgents?: boolean;
  /**
   * 管理者掛載的 MCP 伺服器（Python 版）：管理平台的「MCP」頁可以新增
   * 遠端 MCP 伺服器，工具和其他工具組一樣依存取群組開放（見 McpServerInfo）。
   */
  mcpServers?: boolean;
  /** 管理平台的「Skills」頁：新增、修改、刪除、上傳、關閉公司 skill。 */
  skillAdmin?: boolean;
  /** 管理平台的「Agent」頁：新增與修改公司的 agent（agents/*.md）。 */
  agentAdmin?: boolean;
  /** 個人 skill（帳號模式）：每個人在 /skills 建立自己的 skill。 */
  personalSkills?: boolean;
  /** 知識庫的文件版本、生效期間與題庫回歸評測（Python 版）。 */
  knowledgeGovernance?: boolean;
  /** 管理平台的「資料分級」頁：機密資料自動改用核可的模型。 */
  classification?: boolean;
}

/**
 * 使用者自己建立的專案，用來把對話分類整理（和 ChatGPT、Claude 的專案
 * 一樣；和 harness 的專案資料夾無關）。每個人只看得到自己的專案。刪除
 * 專案不會刪除裡面的對話，對話改成未分類。
 */
export interface ChatCategory {
  id: string;
  /** 1 到 50 個字，同一個人的專案名稱不能重複（不分大小寫）。 */
  name: string;
  createdAt: number;
  /** 裡面有幾段對話。 */
  sessionCount: number;
}

/**
 * POST /api/sessions/bulk：一次刪除或移動好幾段對話（最多 500 段）。
 * move 時 category 是目標專案，null 表示移出專案。
 */
export interface BulkRequest {
  action: "delete" | "move";
  ids: string[];
  category?: string | null;
}

/** 處理好的對話，以及略過的對話與原因（例如還在執行的對話不能刪除）。 */
export interface BulkResult {
  done: string[];
  skipped: { id: string; reason: string }[];
}

/**
 * 登入的人（Python 版）。
 *   admin   管理者：管理成員、模型連線、全站權限與工作資料夾
 *   member  成員：只能使用自己的對話、檔案與記憶
 */
export interface CurrentUser {
  id: string;
  username: string;
  displayName: string;
  role: "admin" | "member";
}

/**
 * 登入方式（Python 版）。
 *   local     只在本機使用、沒有建立任何帳號：不必登入，視為一位本機管理者
 *   accounts  要用帳號密碼登入；沒有登入時 API 一律回 401
 * POST /api/auth/login {username, password} 成功時設定 HttpOnly cookie 並回傳
 * CurrentUser；POST /api/auth/logout 登出；GET /api/auth/me 回傳 CurrentUser。
 * PUT /api/auth/password {current, next} 改自己的密碼。
 */
export type AuthMode = "local" | "accounts";

/** 成員管理頁看到的一位成員（只有管理者能讀，GET /api/admin/users）。 */
export interface MemberInfo extends CurrentUser {
  disabled: boolean;
  /** 建立時間（毫秒）。 */
  createdAt: number;
  /** 最後一次使用的時間（毫秒）；沒有登入過時沒有。 */
  lastSeenAt?: number;
  /**
   * 另外加入的存取群組（AccessGroup.id，不含「所有人」）；只有 Python 版
   * 帳號模式才有。
   */
  groups?: string[];
}

/**
 * 新增成員或重設密碼的結果。密碼由伺服器產生，只會回傳這一次，
 * 請管理者交給成員；成員第一次登入後可以自己改。
 *   POST  /api/admin/users {username, displayName, role, groups?}
 *   PATCH /api/admin/users/:id {displayName?, role?, disabled?} → MemberInfo
 *   POST  /api/admin/users/:id/password
 *   DELETE /api/admin/users/:id（Python 版：刪除帳號與這個人的所有資料）
 *   PUT   /api/admin/users/:id/groups {groups} → MemberInfo（Python 版）
 */
export interface IssuedPassword {
  user: MemberInfo;
  password: string;
}

/**
 * 存取群組可以控制的資源類別。knowledgeBases 是知識庫（KnowledgeBaseInfo.id），
 * knowledge 是知識庫裡的標籤（細部過濾）。模型不在這裡：誰能用哪些模型、
 * 額度與限流由模型中台（LiteLLM Proxy）決定。
 */
export type AccessKind =
  | "agents"
  | "toolsets"
  | "knowledgeBases"
  | "knowledge"
  | "skills";

/**
 * 存取群組（Python 版帳號模式，只有管理者能讀寫）。每一類資源是名稱清單，
 * 或 null 表示全部。每位成員自動屬於內建的「所有人」（id 為 "everyone"，
 * members 是空的、不能刪除或改名），能用的資源是所屬群組的聯集；管理者
 * 不受限制。新建的群組沒有給的類別是空的（什麼都不能用）。
 *   GET    /api/admin/groups → {groups: AccessGroup[], catalog: GroupCatalog}
 *   POST   /api/admin/groups {name, description?, members?, agents?, …}
 *   PATCH  /api/admin/groups/:id {name?, description?, members?, agents?, …}
 *   DELETE /api/admin/groups/:id
 */
export interface AccessGroup {
  id: string;
  name: string;
  description: string;
  builtin: boolean;
  /** 成員的 id（MemberInfo.id）。 */
  members: string[];
  agents: string[] | null;
  toolsets: string[] | null;
  /** 可以搜尋的知識庫（KnowledgeBaseInfo.id）。 */
  knowledgeBases: string[] | null;
  /** 可以搜尋的知識庫標籤；沒有標籤的文件所有人都搜尋得到。 */
  knowledge: string[] | null;
  /**
   * 可以用的 skill（內建與公司的；個人 skill 不歸群組管）。Python 版才有，
   * TypeScript 版沒有這一類。
   */
  skills?: string[] | null;
}

/**
 * 管理者在管理平台掛載的 MCP 伺服器（Python 版，features.mcpServers）。
 *   GET    /api/admin/mcp → McpServerList
 *   POST   /api/admin/mcp McpServerInput → McpServerInfo
 *   PATCH  /api/admin/mcp/:name McpServerInput → McpServerInfo
 *   DELETE /api/admin/mcp/:name
 *   POST   /api/admin/mcp/:name/reconnect → McpServerInfo
 *   POST   /api/admin/mcp/test McpServerInput & {existing?} → McpTestResult
 * 只接受遠端（Streamable HTTP）伺服器。標頭的值（API 金鑰）存在伺服器的
 * secrets 裡，API 只回傳名稱。伺服器名稱就是工具組名稱。
 */
export type McpStatus = "connecting" | "connected" | "error" | "disabled";

export interface McpToolInfo {
  name: string;
  description: string;
}

export interface McpServerInfo {
  name: string;
  url: string;
  description: string;
  /** 只有名稱；值不會送回瀏覽器。 */
  headers: { name: string; set: boolean }[];
  /** 工具加到哪些專案 agent；null 表示全部。 */
  agents: string[] | null;
  enabled: boolean;
  createdAt: number;
  updatedAt: number;
  status: McpStatus;
  /** status 為 error 時的原因。 */
  error: string;
  tools: McpToolInfo[];
}

export interface McpServerInput {
  name?: string;
  url?: string;
  description?: string;
  /** value 留空表示沿用已經存的值（修改時）。 */
  headers?: { name: string; value: string }[];
  agents?: string[] | null;
  enabled?: boolean;
}

export interface McpServerList {
  servers: McpServerInfo[];
  /** harness.yaml 的 mcpServers：部署時設定，網頁上只能看。 */
  configured: {
    name: string;
    url: string;
    command: boolean;
    tools: string[];
  }[];
  /** 可以選的專案 agent。 */
  agents: { name: string; description: string }[];
  /** 模型中台（HARNESS_BASE_URL 去掉 /v1），LiteLLM 範本用；沒有時是空字串。 */
  gateway: string;
}

export type McpTestResult =
  | { ok: true; tools: McpToolInfo[] }
  | { ok: false; message: string };

/** 群組頁可以勾選的資源。 */
export interface GroupCatalog {
  agents: { name: string; description: string }[];
  toolsets: { name: string; tools: string[] }[];
  knowledgeBases: KnowledgeBaseInfo[];
  /** 所有知識庫裡用到的標籤。 */
  knowledge: string[];
  /** 專案有沒有知識庫。 */
  hasKnowledge: boolean;
  /** 內建與公司的 skill（Python 版）。 */
  skills?: { name: string; description: string; builtin: boolean }[];
}

export interface GroupList {
  groups: AccessGroup[];
  catalog: GroupCatalog;
}

/**
 * 一個知識庫（Python 版）。預設知識庫的 id 是 "default"（harness.yaml 的
 * knowledge 區塊或 knowledge/ 資料夾），其他的寫在 harness.yaml 的
 * knowledgeBases，資料夾預設是 knowledge/<id>/。
 */
export interface KnowledgeBaseInfo {
  id: string;
  name: string;
  description: string;
  /** 使用者自己建立的個人知識庫（id 以 my- 開頭，只有自己看得到）。 */
  personal?: boolean;
}

/**
 * 一般使用者的知識庫頁（Python 版，features.personalKnowledge）。
 *   GET    /api/my/knowledge → MyKnowledge
 *   POST   /api/my/knowledge {name, description?, chunking?}
 *          → PersonalKnowledgeBase
 *   PATCH  /api/my/knowledge/:id {name?, description?, chunking?}
 *   DELETE /api/my/knowledge/:id（連同文件一起刪除）
 *   GET    /api/my/knowledge/:id/documents → KnowledgeDocuments
 *   POST   /api/my/knowledge/:id/documents?replace=（multipart，要帶
 *          X-Harness-Upload: 1）→ {files: {path, size}[]}
 *   DELETE /api/my/knowledge/:id/documents?path=
 * 個人知識庫只有建立的人能看、能用，不經過存取群組，也不能分享。
 */
export interface MyKnowledge {
  /** 群組開放給這個人的公司知識庫（管理者在管理平台建立的）。 */
  company: CompanyKnowledgeBase[];
  /** 自己建立的知識庫，依建立時間排序。 */
  mine: PersonalKnowledgeBase[];
  limits: PersonalKnowledgeLimits;
  /** 個人知識庫的文件加起來的大小（位元組）。 */
  usedBytes: number;
  /** 支援的副檔名，例如 [".docx", ".md", …]。 */
  formats: string[];
}

export interface CompanyKnowledgeBase extends KnowledgeBaseInfo {
  documents: number;
  /** 這個人能不能在管理平台管理它（管理者或維護者）。 */
  manage: boolean;
}

export interface PersonalKnowledgeBase extends KnowledgeBaseInfo {
  /** 切片方式：paragraph（依段落）或 regulation（法規一條一片）。 */
  chunking: "paragraph" | "regulation";
  documents: number;
  /** 文件加起來的大小（位元組）。 */
  bytes: number;
  /** 秒（Unix time）。 */
  createdAt: number;
}

/** harness.yaml 的 personalKnowledge 區塊（大小已換算成位元組）。 */
export interface PersonalKnowledgeLimits {
  enabled: boolean;
  maxBases: number;
  maxDocuments: number;
  maxFileBytes: number;
  maxTotalBytes: number;
}

/**
 * 檢索方式：keyword 精確比對（只看字詞有沒有出現、出現幾次）、bm25 用
 * BM25 演算法排序、hybrid 是 BM25 加上 embedding 模型的語意檢索。沒寫時
 * 有 embeddingModel 就是 hybrid，沒有就是 bm25。
 */
export type KnowledgeSearchMode = "keyword" | "bm25" | "hybrid";

/** 知識庫的檢索設定（和 harness.yaml 的鍵相同）。 */
export interface KnowledgeSettings {
  name?: string;
  description?: string;
  searchMode?: KnowledgeSearchMode | null;
  embeddingModel?: string | null;
  chunkSize?: number | null;
  /** 切片方式：paragraph（依段落，預設）或 regulation（法規一條一片）。 */
  chunking?: "paragraph" | "regulation" | null;
  reranker?: string | null;
  rerankCandidates?: number | null;
  minSimilarity?: number | null;
  minRerankScore?: number | null;
}

/**
 * 管理平台的一個知識庫。管理者看到全部，維護者只看到自己維護的（沒有
 * maintainers 欄位）。
 *   GET    /api/knowledge → KnowledgeAdminList
 *   POST   /api/knowledge {id, name, description?, …KnowledgeSettings}（管理者）
 *   PATCH  /api/knowledge/:id {…KnowledgeSettings, maintainers?}（管理者；
 *          值是 null 表示刪掉這個設定）
 *   DELETE /api/knowledge/:id（管理者；只從 harness.yaml 拿掉，文件留著）
 *   GET    /api/knowledge/:id/documents → KnowledgeDocuments
 *   POST   /api/knowledge/:id/documents?dir=&replace=（multipart，要帶
 *          X-Harness-Upload: 1）→ {files: {path, size}[]}
 *   DELETE /api/knowledge/:id/documents?path=
 *   POST   /api/knowledge/:id/search {query, topK?, asOf?, allVersions?}
 *          → {hits: KnowledgeHit[]}
 */
export interface KnowledgeAdminBase extends KnowledgeBaseInfo {
  /** 預設知識庫（不能刪除）。 */
  builtin: boolean;
  /** 資料夾，相對於專案根目錄。 */
  path: string;
  /** 文件數（含不支援的格式）。 */
  documents: number;
  /** harness.yaml 裡這個知識庫自己寫的設定。 */
  settings: KnowledgeSettings;
  /** 實際生效的檢索設定（含沿用 knowledge 區塊與預設值的）。 */
  retrieval: Required<Omit<KnowledgeSettings, "name" | "description">>;
  /** 預設會搜尋這個知識庫的 agent。 */
  agents: string[];
  /** 維護者的 id（MemberInfo.id）；只有管理者看得到。 */
  maintainers?: string[];
  /** 資料分級（ClassificationSettings 的等級識別碼）；沒有分級時是 null。 */
  classification?: string | null;
  /** 資料分級的名稱，例如「機密」。 */
  classificationName?: string;
  /** 題庫評測的概況。 */
  evaluation?: KnowledgeEvalBrief;
}

/** 知識庫清單上的評測概況。 */
export interface KnowledgeEvalBrief {
  questions: number;
  running: boolean;
  latest: {
    id: string;
    mode: KnowledgeEvalMode;
    /** 秒（Unix time）。 */
    startedAt: number;
    summary: KnowledgeEvalSummary | null;
    regressions: number;
  } | null;
}

/**
 * 知識庫的題庫回歸評測（管理者或維護者）：
 *   GET    /api/knowledge/:id/eval → KnowledgeEval
 *   POST   /api/knowledge/:id/eval/questions {question, sources?, keywords?,
 *          answer?} → KnowledgeEvalQuestion
 *   PATCH  /api/knowledge/:id/eval/questions/:qid → KnowledgeEvalQuestion
 *   DELETE /api/knowledge/:id/eval/questions/:qid
 *   POST   /api/knowledge/:id/eval/import?replace=1（multipart CSV/.xlsx）
 *          → {added}
 *   GET    /api/knowledge/:id/eval/export → CSV
 *   POST   /api/knowledge/:id/eval/run {answerModel?, topK?} → {id}
 *   GET    /api/knowledge/:id/eval/runs/:runId → KnowledgeEvalRun（含 results）
 * 文件、版本資訊或檢索設定改動後，伺服器會自動評測檢索（trigger 寫原因，
 * startedBy 是「自動」）。
 */
export type KnowledgeEvalMode = "retrieval" | "answer";

export interface KnowledgeEvalQuestion {
  id: string;
  question: string;
  /** 應該找到的文件（路徑、檔名或樣式，可以加「› 位置」）。 */
  sources: string[];
  /** 應該出現的字詞。 */
  keywords: string[];
  /** 參考答案（用模型評測回答時比對）。 */
  answer: string;
}

export interface KnowledgeEvalSummary {
  total: number;
  passed: number;
  passRate: number | null;
  /** 有寫應該找到的文件的題目裡，找到的比例。 */
  hitRate: number | null;
  /** 第一個正確結果名次的倒數平均。 */
  mrr: number | null;
  topK: number;
  errors: number;
}

export interface KnowledgeEvalResult {
  id: string;
  question: string;
  passed: boolean;
  rank: number | null;
  missing_keywords: string[];
  hits: string[];
  answer: string | null;
  judge: string | null;
  reasons: string[];
  error: string | null;
}

export interface KnowledgeEvalRun {
  id: string;
  mode: KnowledgeEvalMode;
  status: "running" | "done" | "error";
  /** 手動，或自動評測的原因（例如「上傳文件」）。 */
  trigger: string;
  startedBy: string;
  /** 秒（Unix time）。 */
  startedAt: number;
  finishedAt: number | null;
  /** 評測當時的檢索設定。 */
  settings: Record<string, string | number | null>;
  summary: KnowledgeEvalSummary | null;
  /** 上次（同類型）通過、這次沒過的題目 id。 */
  regressions: string[];
  fixed: string[];
  error: string | null;
  results?: KnowledgeEvalResult[];
}

export interface KnowledgeEval {
  questions: KnowledgeEvalQuestion[];
  runs: KnowledgeEvalRun[];
  /** 執行中的評測 id。 */
  running: string | null;
  /** 評測回答可以選的模型。 */
  models: string[];
  limit: number;
}

/**
 * 管理平台 → 資料分級（管理者）：
 *   GET /api/admin/classification → ClassificationSettings
 *   PUT /api/admin/classification ClassificationSettings → ClassificationSettings
 * 寫進 harness.yaml 的 dataClassification 與每個知識庫的 classification。
 */
export interface ClassificationSettings {
  enabled: boolean;
  /** 由低到高。 */
  levels: { id: string; name: string }[];
  /** 沒列在 models 的模型最高能處理的等級；null 表示不限制。 */
  defaultClearance: string | null;
  /** 每個模型最高能處理的等級。 */
  models: Record<string, string>;
  /** 資料超過模型等級時自動改用的模型。 */
  routeTo: string | null;
  /** 所有個人知識庫的等級。 */
  personalKnowledge: string | null;
  /** 工具組的等級。 */
  toolsets: Record<string, string>;
  /** 知識庫的等級。 */
  knowledgeBases: Record<string, string>;
  /** 以下只在 GET 回傳：畫面用的選項。 */
  modelNames?: string[];
  toolsetNames?: string[];
  bases?: { id: string; name: string }[];
  personalEnabled?: boolean;
}

/**
 * 知識庫設定的下拉選單：模型連線上的 embedding 與 rerank 模型（管理者）。
 *   GET /api/knowledge/models → KnowledgeModelChoices
 * source：model_info 是 LiteLLM 的 /model/info 標明了用途；names 是依
 * 模型名稱判斷；none 是沒有可以查的端點；error 是查詢失敗（看 error）。
 */
export interface KnowledgeModelChoices {
  embedding: ModelChoice[];
  rerank: ModelChoice[];
  source: "model_info" | "names" | "none" | "error";
  error?: string;
}

export interface KnowledgeAdminList {
  bases: KnowledgeAdminBase[];
  /** 能不能新增、刪除知識庫與修改設定（管理者）。 */
  canCreate: boolean;
  /** 能不能指定維護者（帳號模式）。 */
  maintainers: boolean;
  /** 支援的副檔名，例如 [".docx", ".md", …]。 */
  formats: string[];
}

export interface KnowledgeDocument {
  /** 相對於知識庫資料夾的路徑。 */
  path: string;
  size: number;
  /** 秒（Unix time）。 */
  modifiedAt: number;
  /** 是不是支援的格式（不支援的不會被搜尋到）。 */
  supported: boolean;
  /** 切成幾個片段（索引建立失敗時是 0）。 */
  chunks: number;
  labels: string[];
  /** 支援的格式卻搜尋不到時的原因，例如掃描的 PDF 沒有文字。 */
  note?: string;
  /** 版本與生效期間（documents.yaml 或 frontmatter），沒有設定時是 {}。 */
  version?: KnowledgeDocumentVersion;
  /** 今天的狀態：有效、還沒生效、已失效、被新版取代。 */
  status?: KnowledgeDocumentStatus;
  /** 取代這份文件的新版（已生效的）。 */
  supersededBy?: string[];
}

/**
 * 文件的版本資訊（Python 版）：
 *   PUT /api/knowledge/:id/documents/info?path= KnowledgeDocumentVersion
 *       → {path, version, status}
 * 日期是 YYYY-MM-DD。搜尋時只找今天有效的文件。
 */
export interface KnowledgeDocumentVersion {
  version?: string;
  effective?: string;
  expires?: string;
  supersedes?: string[];
  note?: string;
}

export type KnowledgeDocumentStatus =
  | "active"
  | "pending"
  | "expired"
  | "superseded";

export interface KnowledgeDocuments {
  documents: KnowledgeDocument[];
  index:
    | {
        chunks: number;
        /** 實際的檢索方式（見 KnowledgeSearchMode）。 */
        searchMode: KnowledgeSearchMode;
        embedding: boolean;
        reranker: boolean;
        /** 略過的檔案與原因。 */
        warnings: string[];
      }
    | { error: string };
}

/**
 * 出處文件讀出來的文字，依索引的片段排列（Python 版）：
 *   GET /api/knowledge/source/text?base&path → KnowledgeSourceText
 * 網頁在裡面標出引用的片段。只有搜尋得到這份文件的人拿得到。
 */
export interface KnowledgeSourceText {
  path: string;
  sections: { location: string; text: string }[];
}

export interface KnowledgeHit {
  source: string;
  location: string;
  text: string;
  labels: string[];
  similarity: number | null;
  rerankScore: number | null;
  /** 文件的版本說明，例如「2026 年版，2026-01-01 起生效」。 */
  version?: string;
  /** 文件在查詢日期的狀態（勾選「包含舊版」時可能不是 active）。 */
  status?: KnowledgeDocumentStatus;
}

/**
 * 一筆稽核紀錄（Python 版，只有管理者能讀）。紀錄只能新增，不能修改或
 * 刪除；每一筆有前一筆的雜湊，串成一條鏈（匯出的檔案裡有雜湊）。
 *   GET /api/admin/audit?category&actor&since&until&before&limit → AuditPage
 *   GET /api/admin/audit/verify → AuditVerification
 *   GET /api/admin/audit/export?format=csv|jsonl&… → 下載檔案（匯出本身也會記一筆）
 */
export interface AuditEntry {
  /** 流水號，從 1 開始，越新越大。 */
  seq: number;
  /** 時間（毫秒）。 */
  at: number;
  /** 做這件事的人；登入失敗等不知道是誰時都是空字串。 */
  actor: { id: string; username: string };
  /** 動作代碼，例如 auth.login、member.update、approval.decide。 */
  action: string;
  /** 動作的中文名稱。 */
  label: string;
  /** 對象：帳號、群組名稱或工具名稱。 */
  target: string;
  /** 其他資訊，內容依動作而不同。 */
  detail: Record<string, unknown>;
  /** 請求的來源 IP。 */
  address: string;
}

/** 稽核紀錄的查詢條件；時間是毫秒，until 不包含。 */
export interface AuditFilters {
  /** 分類：auth、member、group、settings、knowledge、approval、audit。 */
  category?: string;
  /** 帳號名稱（做這件事的人或對象），部分符合即可。 */
  actor?: string;
  since?: number;
  until?: number;
}

export interface AuditPage {
  /** 新的在前；下一頁用最後一筆的 seq 當 before。 */
  entries: AuditEntry[];
  /** 符合條件的總筆數。 */
  total: number;
  /** 分類代碼 → 中文名稱。 */
  categories: Record<string, string>;
}

/** 從第一筆開始檢查雜湊鏈的結果；brokenAt 是第一筆對不上的流水號。 */
export interface AuditVerification {
  ok: boolean;
  checked: number;
  brokenAt?: number;
}

/**
 * 一個工作資料夾（Python 版）。agent 的檔案工具、執行指令與沙盒都只看得到
 * 這段對話選的資料夾；上傳的檔案也存在裡面。
 *   private  每個人自己的「我的檔案」，只有本人看得到。本機模式（AuthMode
 *            為 local）沒有帳號，只有這一個，路徑是專案資料夾本身，而且
 *            ServerFeatures.folders 為 false。
 *   shared   管理者在 harness.yaml 的 workspaces 開放的資料夾；升級前的舊
 *            對話另有一個 id 為 "legacy" 的「舊資料」資料夾，只有接手舊資料
 *            的管理者看得到。
 * 資料夾在對話開始時決定；之後 PUT /options 改 folder 會被拒絕（400）。
 */
export interface FolderInfo {
  id: string;
  name: string;
  kind: "private" | "shared";
  /** false 時 agent 只能讀，不能寫入或修改。 */
  writable: boolean;
}

export interface ToolInfo {
  name: string;
  description: string;
  needsApproval: boolean;
}

export interface ToolsetInfo {
  name: string;
  builtin: boolean;
  tools: ToolInfo[];
}

/** 設定值從哪裡來：agent 檔案、harness.yaml、環境變數或預設值。 */
export type SettingSource = "agent" | "config" | "env" | "default";

export interface AgentInfo {
  /** 對話裡用的名稱；自建的 agent 是 user:<識別碼>。 */
  name: string;
  /** 顯示的名稱（自建的 agent）；沒有時顯示 name。 */
  label?: string;
  /** 這個人自己建立的 agent 才有。 */
  custom?: { id: string; starters: string[] };
  description: string;
  tools: string[];
  /** 實際使用的模型名稱；都沒設定時為 null。 */
  model: string | null;
  modelSource: SettingSource;
  maxTurns: number;
  maxTurnsSource: SettingSource;
  /**
   * 預設搜尋的知識庫（Python 版，只列這個人可以用的）；null 或沒有表示
   * 這個 agent 沒有設定知識庫。
   */
  knowledge?: string[] | null;
}

export interface PermissionSettings {
  mode: PermissionMode;
  allow: string[];
  ask: string[];
  deny: string[];
}

export interface ProjectInfo {
  name: string;
  root: string;
  /** 伺服器是哪個版本，沒有時視為 typescript。 */
  runtime?: "typescript" | "python";
  defaultAgent: string;
  agents: AgentInfo[];
  toolsets: ToolsetInfo[];
  permissions: PermissionSettings;
  /**
   * 可以上傳檔案時才有（Python 版）。上傳用 POST /api/uploads
   * （multipart/form-data，要帶 X-Harness-Upload: 1 標頭），送出訊息時
   * 把回傳的 path 放進 attachments。
   */
  uploads?: { maxBytes: number };
  /** 伺服器支援哪些功能；TypeScript 版沒有這個欄位。 */
  features?: ServerFeatures;
  /** 登入方式與目前登入的人（Python 版）。 */
  auth?: { mode: AuthMode; user: CurrentUser };
  /** 這個人可以使用的工作資料夾，預設的（自己的「我的檔案」）排第一個。 */
  folders?: FolderInfo[];
  /** 輸入框可以選的模型（Python 版），預設模型排第一個。 */
  models?: ModelOption[];
  /** ＋ 選單可以選的 skills（Python 版）。 */
  skills?: SkillInfo[];
  /**
   * 每段對話預設開啟的 skills（Python 版），使用者可以在 ＋ 選單逐一
   * 關閉。SkillInfo.requires 的工具 agent 沒有時不會套用。
   */
  defaultSkills?: string[];
  /** 這個人在對話裡可以勾選的知識庫（Python 版，群組開放的）。 */
  knowledgeBases?: KnowledgeBaseInfo[];
  /** 這個人能不能打開管理平台的知識庫頁（管理者或知識庫的維護者）。 */
  manageKnowledge?: boolean;
  model: {
    /** harness.yaml 裡的值，沒寫時為 null。 */
    config: { model: string | null; maxTurns: number | null };
    env: {
      model: string | null;
      baseURL: string | null;
      apiKeySet: boolean;
      /** 有設定的 *_API_KEY 環境變數名稱（Python 版直接連供應商時用）。 */
      keyVars?: string[];
      /** 都沒設定模型時使用的預設模型（Python 版）。 */
      fallbackModel?: string;
    };
    /**
     * 可以在網頁上設定連線時才有（Python 版）：選供應商、填金鑰與模型，
     * 用 PUT /api/settings/connection 儲存。
     */
    connection?: ConnectionInfo;
  };
}

/** 一家可以直接連線的模型供應商。 */
export interface ProviderInfo {
  /** 代號，也是模型名稱的開頭（anthropic/...）。 */
  id: string;
  label: string;
  defaultModel: string;
  needsKey: boolean;
  /** 金鑰的環境變數名稱；不需要金鑰時為 null。 */
  keyVar: string | null;
  /** 金鑰是否已經設定（不會送出金鑰的內容）。 */
  keySet: boolean;
  /** 可以自訂伺服器位址時（Ollama），目前的位址；否則為 null。 */
  baseURL: string | null;
}

/** 連線設定的狀態。 */
export interface ConnectionInfo {
  /** 預設 agent 的模型需要的金鑰或端點是否已經設定。 */
  ready: boolean;
  /** 目前使用的供應商代號、"endpoint"（OpenAI 相容端點），或清單以外時為 null。 */
  provider: string | null;
  providers: ProviderInfo[];
  /**
   * POST /api/settings/models/discover {provider, baseURL, apiKey} 可以列出
   * 供應商或端點的模型（Python 版，見 ModelChoice）。換成別的端點網址時
   * 伺服器不會送出存好的金鑰。
   */
  canDiscover?: boolean;
  /**
   * harness.yaml 的 models：開放在對話中切換的模型名稱（Python 版）。
   * PUT /api/settings/models {models: string[]} 整份換掉。
   */
  choices?: string[];
}

/** 供應商或端點提供的一個模型（POST /api/settings/models/discover）。 */
export interface ModelChoice {
  /** 寫進設定的模型名稱（litellm 格式；端點則是端點上的名稱）。 */
  name: string;
  label: string;
}

/** 連 OpenAI 相容端點時，連線設定裡的供應商代號。 */
export const ENDPOINT_PROVIDER = "endpoint";

/** PUT /api/settings/connection 的內容；apiKey、baseURL 留空表示沿用目前的值。 */
export interface ConnectionSettings {
  provider: string;
  apiKey: string;
  baseURL: string;
  model: string;
}

/** 上傳完成的檔案。 */
export interface UploadedFile {
  name: string;
  /** 相對於專案根目錄的路徑，送出訊息時放進 attachments。 */
  path: string;
  size: number;
}

/**
 * 訊息附件的說明行：伺服器把附件接在使用者訊息後面，每個一行，
 * 開頭是這個標記，接著是路徑（不含空白），後面可能還有給模型的說明。
 */
export const ATTACHMENT_MARKER = "[附件] ";

/**
 * 沙盒產生檔案的說明行（Python 版）：run_python 執行後新增或修改的檔案，
 * 伺服器接在工具結果後面，每個一行，開頭是這個標記，接著是相對於專案
 * 根目錄的路徑。網頁用它顯示檔案卡片與縮圖。
 */
export const PRODUCED_MARKER = "[產生的檔案] ";

/**
 * 不必登入的本機模式（Python 版）每次啟動會產生一把鑰匙，放在終端機顯示
 * 的網址上（?key=…）。沒有帶鑰匙時 API 回 401，錯誤內容的 code 是這個
 * 值：要請使用者重新打開終端機上的網址，而不是顯示登入畫面。
 */
export const LOCAL_KEY_REQUIRED = "local_key_required";

/** 使用者拒絕工具呼叫時，交給模型的工具結果（網頁上改顯示「你拒絕了這個動作」）。 */
export const DENIED_RESULT = "使用者沒有同意這次呼叫，請不要重試同樣的操作";

/**
 * 伺服器重新啟動時，正在跑或等待確認的那一輪會中斷（Python 版）：
 * 摘要的 status 為 stopped、stopReason 為這個值，notice 說明原因；
 * POST /api/sessions/:id/retry 可以接著做。
 */
export const INTERRUPTED_STOP_REASON = "interrupted";

/** 測試模型連線的結果。 */
export interface ModelTestResult {
  ok: boolean;
  model?: string;
  message?: string;
}

/** 伺服器透過 SSE 推給瀏覽器的事件。 */
export type ServerEvent =
  | { type: "hello" }
  | { type: "session"; summary: SessionSummary }
  | { type: "run_start"; sessionId: string; text: string | null }
  | { type: "text_delta"; sessionId: string; text: string }
  | { type: "message"; sessionId: string; message: Message }
  | {
      type: "tool_result";
      sessionId: string;
      result: ToolResult;
      message: Message;
    }
  | { type: "approval"; sessionId: string; approval: Approval }
  /** subagent 呼叫了工具或拿到結果（Python 版）；依 step.id 新增或更新。 */
  | {
      type: "subagent_step";
      sessionId: string;
      /** 上層 ask_<名稱> 工具呼叫的 id。 */
      callId: string;
      step: SubagentStep;
    }
  | {
      type: "approval_resolved";
      sessionId: string;
      approvalId: string;
      decision: ApprovalDecision;
    }
  | { type: "run_end"; sessionId: string; stopReason: string }
  | { type: "run_error"; sessionId: string; message: string }
  | { type: "run_stopped"; sessionId: string }
  /** 對話紀錄被改寫（例如 Python 版壓縮對話），要重新讀取。 */
  | { type: "session_reload"; sessionId: string }
  /** 對話被刪除（Python 版）。 */
  | { type: "session_deleted"; sessionId: string }
  | { type: "project" }
  /** 專案（ChatCategory）有變動：重新讀取 GET /api/categories。 */
  | { type: "categories" };

/**
 * 自己建立的 agent（Python 版，features.userAgents）。只有建立的人看得到。
 *
 *   GET    /api/agents             → UserAgentList
 *   POST   /api/agents             UserAgentInput → UserAgentInfo
 *   PATCH  /api/agents/:id         Partial<UserAgentInput> → UserAgentInfo
 *   DELETE /api/agents/:id
 *
 * 工具組、知識庫與模型只能挑這個人能用的（群組開放的、模型選單裡的），
 * 執行時再依群組限制一次。開新對話時 agent 填 key。
 */
export interface UserAgentInput {
  name: string;
  description: string;
  /** 指示（角色指令）。 */
  instructions: string;
  /** 開場建議，最多 limits.starters 個。 */
  starters: string[];
  /** 預設模型；null 表示跟著專案的預設模型。 */
  model: string | null;
  /** 工具組名稱（ToolsetInfo.name）。 */
  toolsets: string[];
  /** 知識庫識別碼（KnowledgeBaseInfo.id）。 */
  knowledgeBases: string[];
  /** 技能名稱（SkillInfo.name）。 */
  skills: string[];
}

export interface UserAgentInfo extends UserAgentInput {
  id: string;
  /** 對話裡的 agent 名稱（user:<id>）。 */
  key: string;
  createdAt: number;
  updatedAt: number;
}

export interface UserAgentList {
  agents: UserAgentInfo[];
  /**
   * 建立表單預設勾選的工具組與 skills：工具組和一般對話的預設 agent 一樣
   * （只留群組開放的）；skills 全部勾選，但沒有沙盒時不勾要在沙盒裡跑的。
   */
  defaults?: { toolsets: string[]; skills: string[] };
  limits: {
    name: number;
    description: number;
    instructions: number;
    starter: number;
    starters: number;
  };
}

/**
 * 管理平台的 Skills 頁（Python 版，features.skillAdmin，只有管理者能用）。
 *   GET    /api/admin/skills → AdminSkillList
 *   GET    /api/admin/skills/:name → SkillDetail
 *   POST   /api/admin/skills {name, description, instructions} → SkillDetail
 *   PATCH  /api/admin/skills/:name {description?, instructions?, enabled?,
 *          default?} → SkillDetail（改內建 skill 的內容會複製成公司版本）
 *   DELETE /api/admin/skills/:name（公司 skill；取代內建的刪掉後還原）
 *   POST   /api/admin/skills/upload?replace=1 multipart（skill 資料夾的 zip）
 */
export type SkillSource = "builtin" | "company" | "personal";

export interface AdminSkillInfo {
  name: string;
  description: string;
  source: SkillSource;
  /** 公司版本取代了同名的內建 skill。 */
  overridesBuiltin: boolean;
  /** 管理者沒有關掉（harness.yaml 的 web.disabledSkills）。 */
  enabled: boolean;
  /** 每段對話預設開啟（web.defaultSkills）。 */
  default: boolean;
  requires: string[];
  /** skill 的專屬工具。 */
  tools: string[];
  /** 參考檔案與腳本的數量。 */
  files: number;
  /** 明確列出它的公司 agent。 */
  usedBy: string[];
}

export interface SkillLimits {
  maxSkills: number | null;
  maxZipBytes: number;
  maxFiles: number;
  descriptionLimit: number;
  instructionsLimit: number;
}

export interface AdminSkillList {
  skills: AdminSkillInfo[];
  limits: SkillLimits;
}

/** 一個 skill 的完整內容（編輯頁）。管理平台的另外有 AdminSkillInfo 的欄位。 */
export interface SkillDetail extends Partial<Omit<AdminSkillInfo, "files">> {
  name: string;
  description: string;
  instructions: string;
  requires: string[];
  tools: string[];
  /** 參考檔案的路徑。 */
  files: string[];
}

/**
 * 個人 skill（features.personalSkills）。只有建立的人看得到、用得到，
 * 不能分享，預設在自己的對話開啟。
 *   GET    /api/my/skills → MySkillList
 *   GET    /api/my/skills/:name → SkillDetail
 *   POST   /api/my/skills {name, description, instructions} → SkillDetail
 *   PATCH  /api/my/skills/:name {description?, instructions?} → SkillDetail
 *   DELETE /api/my/skills/:name
 *   POST   /api/my/skills/upload?replace=1 multipart（zip）
 */
export interface MySkillInfo {
  name: string;
  description: string;
  requires: string[];
  files: number;
  /** 管理者後來新增了同名的公司 skill，對話裡用公司的。 */
  shadowed: boolean;
}

export interface MySkillList {
  enabled: boolean;
  skills: MySkillInfo[];
  /** 可以用的公司與內建 skill。 */
  shared: { name: string; description: string; builtin: boolean }[];
  limits: SkillLimits;
}

/**
 * 管理平台的 Agent 頁（features.agentAdmin，只有管理者能用）：公司的
 * agent，也就是專案的 agents/*.md。
 *   GET    /api/admin/agents → AdminAgentList
 *   GET    /api/admin/agents/:name → AdminAgentInfo
 *   POST   /api/admin/agents AdminAgentInput & {name} → AdminAgentInfo
 *   PATCH  /api/admin/agents/:name AdminAgentInput → AdminAgentInfo
 * 存檔前會重新載入檢查，設定有誤時不儲存。其他設定（model、subagents、
 * handoffs、ontology…）原樣保留，只能改檔案。
 */
export interface AdminAgentInfo {
  name: string;
  /** 例如 agents/main.md。 */
  file: string;
  description: string;
  instructions: string;
  /** 工具組或工具名稱；null 表示沒有設定（可以用專案所有的工具）。 */
  tools: string[] | null;
  /** null 表示沒有設定（可以用專案所有的公司 skill）。 */
  skills: string[] | null;
  /** 預設搜尋的知識庫。 */
  knowledge: string[];
  /** knowledge 還設定了標籤或 topK（會保留）。 */
  knowledgeFilter: boolean;
  /** 網頁上不能改、原樣保留的設定名稱。 */
  otherSettings: string[];
  /** 是不是專案的預設 agent。 */
  default: boolean;
}

export interface AdminAgentInput {
  description?: string;
  instructions?: string;
  tools?: string[] | null;
  skills?: string[] | null;
  knowledge?: string[];
}

export interface AdminAgentList {
  agents: AdminAgentInfo[];
  catalog: {
    toolsets: { name: string; builtin: boolean; tools: string[] }[];
    skills: { name: string; description: string; builtin: boolean }[];
    knowledgeBases: KnowledgeBaseInfo[];
    /** 管理平台掛載的 MCP 伺服器（在「MCP 工具」頁指定 agent）。 */
    mcpServers: string[];
  };
}
