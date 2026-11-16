/**
 * 管理平台 → MCP 工具（Python 版，features.mcpServers）：管理者掛載遠端的
 * MCP 伺服器，連上之後它的工具就和其他工具組一樣，到「群組」決定誰能用。
 *
 * - 只接受遠端伺服器（Streamable HTTP 網址）；在伺服器上啟動程式的
 *   MCP 只能由部署的人寫在 harness.yaml。
 * - 標頭的值（API 金鑰）送出後不會再顯示，修改時留空表示沿用。
 * - 有模型中台（LiteLLM Proxy）時提供 webiq 範本：網址是
 *   <中台>/webiq/mcp，標頭 x-litellm-api-key: Bearer <金鑰>。
 * - 一般成員看不到這一頁，伺服器也會拒絕他們的請求。
 */

import { type FormEvent, useCallback, useEffect, useId, useState } from "react";
import { createPortal } from "react-dom";
import type {
  McpServerInfo,
  McpServerInput,
  McpServerList,
  McpTestResult,
} from "../../../../src/web/protocol.ts";
import { api } from "../../api.ts";
import { refreshProject, useStore } from "../../store.ts";
import {
  AddIcon,
  CheckIcon,
  CloseIcon,
  PlugIcon,
  RetryIcon,
  TrashIcon,
} from "../Icons.tsx";
import { ConfirmDialog, Modal } from "../shell/Dialog.tsx";
import { Field } from "../shell/Field.tsx";
import { showToast } from "../shell/toast.tsx";

const STATUS: Record<McpServerInfo["status"], { label: string; cls: string }> =
  {
    connecting: { label: "連線中", cls: "badge-warn" },
    connected: { label: "已連線", cls: "badge-muted" },
    error: { label: "連線失敗", cls: "badge-danger" },
    disabled: { label: "已停用", cls: "badge-muted" },
  };

/** LiteLLM 上 webiq 的範本。gateway 是模型中台的網址（去掉 /v1）。 */
export function webiqTemplate(gateway: string): Draft {
  return {
    name: "webiq",
    url: `${gateway || "http://litellm:4000"}/webiq/mcp`,
    description: "網頁搜尋（透過模型中台 LiteLLM）",
    headers: [{ name: "x-litellm-api-key", value: "Bearer ", stored: false }],
    agents: null,
  };
}

interface Draft {
  name: string;
  url: string;
  description: string;
  headers: { name: string; value: string; stored: boolean }[];
  agents: string[] | null;
}

const EMPTY: Draft = {
  name: "",
  url: "",
  description: "",
  headers: [],
  agents: null,
};

function toDraft(server: McpServerInfo): Draft {
  return {
    name: server.name,
    url: server.url,
    description: server.description,
    headers: server.headers.map((h) => ({
      name: h.name,
      value: "",
      stored: h.set,
    })),
    agents: server.agents,
  };
}

function toInput(draft: Draft): McpServerInput {
  return {
    name: draft.name.trim(),
    url: draft.url.trim(),
    description: draft.description.trim(),
    headers: draft.headers
      .filter((h) => h.name.trim())
      .map((h) => ({ name: h.name.trim(), value: h.value.trim() })),
    agents: draft.agents,
  };
}

export function McpServers() {
  const project = useStore((s) => s.project);
  const [list, setList] = useState<McpServerList>();
  const [loadError, setLoadError] = useState<string>();
  const [editing, setEditing] = useState<
    { server?: McpServerInfo; draft: Draft } | undefined
  >();
  const [busy, setBusy] = useState<string>();

  const load = useCallback(async () => {
    setLoadError(undefined);
    try {
      setList(await api.mcpServers());
    } catch (error) {
      setLoadError((error as Error).message);
    }
  }, []);

  // 連線狀態改變時伺服器會通知重新讀取專案，這裡跟著重新讀取清單。
  // biome-ignore lint/correctness/useExhaustiveDependencies: project 只當作通知
  useEffect(() => {
    void load();
  }, [load, project]);

  const reconnect = async (server: McpServerInfo) => {
    setBusy(server.name);
    try {
      await api.reconnectMcpServer(server.name);
      await load();
    } catch (error) {
      showToast((error as Error).message);
    }
    setBusy(undefined);
  };

  const hasWebiq =
    list?.servers.some((s) => s.name === "webiq") ||
    list?.configured.some((s) => s.name === "webiq");

  return (
    <section aria-labelledby="h-mcp" className="settings-body">
      <div className="members-head">
        <div>
          <h2 id="h-mcp">MCP 工具</h2>
          <p className="lead">
            {
              "掛載遠端的 MCP 伺服器，例如模型中台（LiteLLM）上的網頁搜尋。連上後它的工具會成為一個工具組，到「群組」決定哪些成員能用；「所有人」沒有限制工具組時，所有成員都能用。只有管理者能新增。"
            }
          </p>
        </div>
        <button
          type="button"
          className="btn btn-accent"
          disabled={!list}
          onClick={() => setEditing({ draft: structuredClone(EMPTY) })}
        >
          <AddIcon size={15} />
          掛載 MCP 伺服器
        </button>
      </div>

      {list && !hasWebiq && (
        <div className="box box-row">
          <div>
            <div style={{ fontWeight: 600 }}>網頁搜尋 webiq（LiteLLM）</div>
            <div className="help" style={{ marginTop: 4 }}>
              {list.gateway
                ? `從模型中台 ${list.gateway} 掛載 webiq，只要填上 LiteLLM 的金鑰。`
                : "套用 LiteLLM 的 webiq 範本，填上中台網址與金鑰。"}
            </div>
          </div>
          <button
            type="button"
            className="btn btn-outline"
            onClick={() => setEditing({ draft: webiqTemplate(list.gateway) })}
          >
            套用範本
          </button>
        </div>
      )}

      {loadError && (
        <div className="box box-row" role="alert">
          <span className="inline-error">讀不到 MCP 伺服器：{loadError}</span>
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

      {list && list.servers.length === 0 && (
        <p className="subtle">還沒有掛載任何 MCP 伺服器。</p>
      )}
      {list && list.servers.length > 0 && (
        <ul className="member-list" aria-label="MCP 伺服器">
          {list.servers.map((server) => (
            <li key={server.name} className="member-row">
              <div className="member-main">
                <div className="member-name">
                  <span className="member-display mono">{server.name}</span>
                  <span className={`badge ${STATUS[server.status].cls}`}>
                    {STATUS[server.status].label}
                  </span>
                </div>
                <div className="member-meta mono">{server.url}</div>
                {server.description && (
                  <div className="member-meta">{server.description}</div>
                )}
                <div className="member-meta">
                  {server.status === "connected"
                    ? `${server.tools.length} 個工具：${server.tools
                        .map((t) => t.name)
                        .join("、")}`
                    : server.status === "error"
                      ? ""
                      : server.status === "connecting"
                        ? "正在連線…"
                        : "停用中，工具不會出現在對話裡。"}
                  {server.status === "connected" &&
                    ` · 加到：${
                      server.agents === null
                        ? "所有 agent"
                        : server.agents.join("、") || "（沒有 agent）"
                    }`}
                </div>
                {server.status === "error" && (
                  <div className="inline-error member-meta">{server.error}</div>
                )}
              </div>
              {busy === server.name && (
                <span className="spinner spin" aria-hidden="true" />
              )}
              {server.enabled && server.status !== "connecting" && (
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  disabled={busy === server.name}
                  onClick={() => reconnect(server)}
                >
                  <RetryIcon size={14} />
                  重新連線
                </button>
              )}
              <button
                type="button"
                className="btn btn-outline btn-sm"
                onClick={() => setEditing({ server, draft: toDraft(server) })}
              >
                編輯
              </button>
            </li>
          ))}
        </ul>
      )}

      {list && list.configured.length > 0 && (
        <div className="form-row">
          <span className="label">部署時設定的伺服器（harness.yaml）</span>
          <ul className="member-list" aria-label="harness.yaml 的 MCP 伺服器">
            {list.configured.map((server) => (
              <li key={server.name} className="member-row">
                <div className="member-main">
                  <div className="member-name">
                    <span className="member-display mono">{server.name}</span>
                    <span className="badge badge-muted">harness.yaml</span>
                  </div>
                  <div className="member-meta mono">
                    {server.command ? "在伺服器上啟動的程式" : server.url}
                  </div>
                  <div className="member-meta">
                    {server.tools.length} 個工具
                    {server.tools.length > 0 && `：${server.tools.join("、")}`}
                  </div>
                </div>
              </li>
            ))}
          </ul>
          <div className="help">
            這些由部署的人寫在 harness.yaml，要修改請改檔案後重新啟動。
          </div>
        </div>
      )}

      {editing &&
        list &&
        createPortal(
          <ServerDialog
            server={editing.server}
            initial={editing.draft}
            agents={list.agents}
            onClose={() => setEditing(undefined)}
            onSaved={async (message) => {
              setEditing(undefined);
              showToast(message);
              await Promise.all([load(), refreshProject()]);
            }}
          />,
          document.body,
        )}
    </section>
  );
}

function ServerDialog({
  server,
  initial,
  agents,
  onClose,
  onSaved,
}: {
  server?: McpServerInfo;
  initial: Draft;
  agents: McpServerList["agents"];
  onClose: () => void;
  onSaved: (message: string) => void | Promise<void>;
}) {
  const titleId = useId();
  const [draft, setDraft] = useState(initial);
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);
  const [test, setTest] = useState<McpTestResult | "testing">();
  const [deleting, setDeleting] = useState(false);
  const editing = server !== undefined;

  const edit = (changes: Partial<Draft>) => {
    setDraft((current) => ({ ...current, ...changes }));
    setError(undefined);
    setTest(undefined);
  };

  const setHeader = (
    index: number,
    changes: Partial<Draft["headers"][number]>,
  ) =>
    edit({
      headers: draft.headers.map((h, i) =>
        i === index ? { ...h, ...changes } : h,
      ),
    });

  const runTest = async () => {
    setTest("testing");
    setTest(
      await api
        .testMcpServer({
          ...toInput(draft),
          ...(editing ? { existing: server.name } : {}),
        })
        .catch(
          (failure: Error): McpTestResult => ({
            ok: false,
            message: failure.message,
          }),
        ),
    );
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    try {
      const input = toInput(draft);
      if (editing) {
        delete input.name;
        await api.updateMcpServer(server.name, input);
        await onSaved(`已更新 ${server.name}，正在重新連線`);
      } else {
        await api.createMcpServer(input);
        await onSaved(`已掛載 ${input.name}，正在連線`);
      }
    } catch (failure) {
      setError((failure as Error).message);
      setBusy(false);
    }
  };

  const toggleEnabled = async () => {
    if (!server) return;
    setBusy(true);
    try {
      await api.updateMcpServer(server.name, { enabled: !server.enabled });
      await onSaved(
        server.enabled ? `已停用 ${server.name}` : `已啟用 ${server.name}`,
      );
    } catch (failure) {
      setError((failure as Error).message);
      setBusy(false);
    }
  };

  const chosen = draft.agents ?? [];
  const toggleAgent = (name: string) =>
    edit({
      agents: chosen.includes(name)
        ? chosen.filter((item) => item !== name)
        : [...chosen, name],
    });

  return (
    <Modal
      onClose={onClose}
      className="confirm-dialog form-dialog mcp-dialog"
      labelledBy={titleId}
    >
      <form onSubmit={submit} noValidate>
        <h2 id={titleId} className="dialog-title">
          {editing ? `編輯 ${server.name}` : "掛載 MCP 伺服器"}
        </h2>
        <div className="dialog-fields">
          <Field
            label="名稱"
            className="mono"
            autoComplete="off"
            value={draft.name}
            disabled={editing}
            placeholder="例如 webiq"
            hint={
              editing
                ? "名稱就是工具組名稱，群組依名稱開放，所以不能修改。"
                : "英文字母開頭，可以用英文、數字、- 與 _。也是群組頁上的工具組名稱。"
            }
            onChange={(event) => edit({ name: event.target.value })}
          />
          <Field
            label="網址（Streamable HTTP）"
            className="mono"
            autoComplete="off"
            value={draft.url}
            placeholder="http://litellm:4000/webiq/mcp"
            hint="LiteLLM 上的伺服器是 <中台網址>/<伺服器名稱>/mcp。不支援舊的 SSE。"
            onChange={(event) => edit({ url: event.target.value })}
          />
          <Field
            label="說明"
            value={draft.description}
            placeholder="選填，例如：網頁搜尋"
            onChange={(event) => edit({ description: event.target.value })}
          />

          <fieldset className="model-choices access-field">
            <legend>標頭（認證）</legend>
            {draft.headers.map((header, index) => (
              <div
                // biome-ignore lint/suspicious/noArrayIndexKey: 標頭沒有固定的識別碼
                key={index}
                className="mcp-header-row"
              >
                <input
                  className="field mono"
                  aria-label="標頭名稱"
                  placeholder="x-litellm-api-key"
                  value={header.name}
                  onChange={(event) =>
                    setHeader(index, { name: event.target.value })
                  }
                />
                <input
                  className="field mono"
                  type="password"
                  autoComplete="new-password"
                  aria-label={`${header.name || "標頭"} 的值`}
                  placeholder={
                    header.stored ? "已設定，留空沿用" : "Bearer sk-…"
                  }
                  value={header.value}
                  onChange={(event) =>
                    setHeader(index, { value: event.target.value })
                  }
                />
                <button
                  type="button"
                  className="icon-btn"
                  aria-label={`移除標頭 ${header.name}`}
                  onClick={() =>
                    edit({
                      headers: draft.headers.filter((_, i) => i !== index),
                    })
                  }
                >
                  <CloseIcon size={14} />
                </button>
              </div>
            ))}
            <div>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() =>
                  edit({
                    headers: [
                      ...draft.headers,
                      { name: "", value: "", stored: false },
                    ],
                  })
                }
              >
                <AddIcon size={14} />
                新增標頭
              </button>
            </div>
            <div className="help">
              {
                "金鑰存在伺服器的 secrets 資料夾，存好後不會再顯示。連模型中台時也可以寫 "
              }
              <code>Bearer ${"{LITELLM_API_KEY}"}</code>
              {"，沿用 .env 的金鑰（其他環境變數只能用 MCP_ 開頭的）。"}
            </div>
          </fieldset>

          {agents.length > 1 && (
            <fieldset className="model-choices access-field">
              <legend>加到哪些 agent</legend>
              <div className="segmented segmented-sm">
                <button
                  type="button"
                  aria-pressed={draft.agents === null}
                  onClick={() => edit({ agents: null })}
                >
                  全部
                </button>
                <button
                  type="button"
                  aria-pressed={draft.agents !== null}
                  onClick={() =>
                    edit({ agents: draft.agents ?? agents.map((a) => a.name) })
                  }
                >
                  指定
                </button>
              </div>
              {draft.agents !== null && (
                <ul className="model-choices-list">
                  {agents.map((agent) => (
                    <li key={agent.name}>
                      <label className="model-choice">
                        <input
                          type="checkbox"
                          checked={chosen.includes(agent.name)}
                          onChange={() => toggleAgent(agent.name)}
                        />
                        <span className="model-choice-label">{agent.name}</span>
                        {agent.description && (
                          <span className="model-choice-name">
                            {agent.description}
                          </span>
                        )}
                      </label>
                    </li>
                  ))}
                </ul>
              )}
              <div className="help">
                成員自建的 agent 可以自己勾選這個工具組。
              </div>
            </fieldset>
          )}

          <div className="mcp-test">
            <button
              type="button"
              className="btn btn-outline btn-sm"
              disabled={test === "testing" || !draft.url.trim()}
              onClick={runTest}
            >
              {test === "testing" ? (
                <span className="spinner spin" aria-hidden="true" />
              ) : (
                <PlugIcon size={14} />
              )}
              測試連線
            </button>
            {test && test !== "testing" && (
              <span
                className={`anim-in ${test.ok ? "ok-text" : "inline-error"}`}
                role="status"
              >
                {test.ok ? (
                  <>
                    <CheckIcon size={14} />
                    連上了，{test.tools.length} 個工具：
                    {test.tools.map((t) => t.name).join("、")}
                  </>
                ) : (
                  test.message
                )}
              </span>
            )}
          </div>
        </div>

        {error && (
          <p className="inline-error" role="alert">
            {error}
          </p>
        )}
        <div className="dialog-actions">
          {editing && (
            <div className="mcp-dialog-extra">
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                disabled={busy}
                onClick={() => setDeleting(true)}
              >
                <TrashIcon size={14} />
                拿掉
              </button>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                disabled={busy}
                onClick={toggleEnabled}
              >
                {server.enabled ? "停用" : "啟用"}
              </button>
            </div>
          )}
          <button type="button" className="btn btn-outline" onClick={onClose}>
            取消
          </button>
          <button type="submit" className="btn btn-accent" disabled={busy}>
            {editing ? "儲存" : "掛載"}
          </button>
        </div>
      </form>

      {deleting &&
        server &&
        createPortal(
          <ConfirmDialog
            title={`拿掉「${server.name}」？`}
            confirmLabel="拿掉"
            danger
            onConfirm={async () => {
              await api.deleteMcpServer(server.name);
              await onSaved(`已拿掉 ${server.name}`);
            }}
            onClose={() => setDeleting(false)}
          >
            它的工具會從所有對話與 agent
            消失，存起來的金鑰也會刪除。群組裡勾選的
            {server.name} 會留著，之後用同樣的名稱重新掛載就會恢復。
          </ConfirmDialog>,
          document.body,
        )}
    </Modal>
  );
}
