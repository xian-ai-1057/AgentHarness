/**
 * 知識庫頁（網址 /knowledge、/knowledge/<id>）：每個人都看得到。
 *
 * - 我的知識庫：自己建立、只有自己能用的知識庫。可以上傳文件（拖曳或
 *   選檔）、刪除文件、改名稱與說明，按「用這個知識庫開新對話」就會在
 *   新對話裡勾好它。不能分享；要給別人用的資料請管理者建成公司知識庫。
 * - 公司知識庫：管理者在管理平台建立、用群組開放給這個人的知識庫，這裡
 *   只能看說明與文件數；是維護者或管理者時多一個「到管理平台管理」。
 *
 * 參考 Claude 的 Projects 知識、ChatGPT 的專案檔案與 MaiAgent、Dify 的
 * 知識庫頁：清單用卡片，進去後是文件清單與上傳區。
 */

import {
  type DragEvent,
  type FormEvent,
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";
import type {
  CompanyKnowledgeBase,
  KnowledgeDocuments,
  MyKnowledge,
  PersonalKnowledgeBase,
} from "../../../src/web/protocol.ts";
import { api } from "../api.ts";
import { formatBytes } from "../format.ts";
import { navigate } from "../router.ts";
import {
  AddIcon,
  ArrowLeftIcon,
  BookIcon,
  ChatsIcon,
  FileIcon,
  PenIcon,
  RetryIcon,
  ShieldIcon,
  TrashIcon,
} from "./Icons.tsx";
import { Link } from "./Sidebar.tsx";
import { ConfirmDialog, Modal } from "./shell/Dialog.tsx";
import { Field } from "./shell/Field.tsx";
import { showToast } from "./shell/toast.tsx";

const CHUNKING_LABELS: Record<PersonalKnowledgeBase["chunking"], string> = {
  paragraph: "一般文件",
  regulation: "法規、內規",
};

/** 用這個知識庫開新對話：新對話頁會把它勾好。 */
export function chatWith(id: string): string {
  return `/?knowledge=${encodeURIComponent(id)}`;
}

export function KnowledgeView({ id }: { id?: string }) {
  const [data, setData] = useState<MyKnowledge>();
  const [loadError, setLoadError] = useState<string>();
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    setLoadError(undefined);
    try {
      setData(await api.myKnowledge());
    } catch (error) {
      setLoadError((error as Error).message);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    document.title = "知識庫 · Harness";
  }, []);

  const current = id ? data?.mine.find((item) => item.id === id) : undefined;

  return (
    <main className="main">
      <header className="main-header">
        <div className="main-title">
          <h1>{current?.name ?? "知識庫"}</h1>
        </div>
      </header>
      <div className="scroll">
        <div className="page kb-page">
          {loadError && (
            <div className="box box-row" role="alert">
              <span className="inline-error">讀不到知識庫：{loadError}</span>
              <button type="button" className="btn btn-outline" onClick={load}>
                重試
              </button>
            </div>
          )}
          {!data && !loadError && (
            <p className="subtle" aria-busy="true">
              讀取中…
            </p>
          )}
          {data && id && !current && (
            <div className="box">
              <p style={{ margin: 0 }}>
                找不到這個知識庫，可能已經刪除了。{" "}
                <Link to="/knowledge">回到所有知識庫</Link>
              </p>
            </div>
          )}
          {data && current && (
            <PersonalDetail
              key={current.id}
              base={current}
              data={data}
              onChanged={load}
            />
          )}
          {data && !id && (
            <Overview data={data} onCreate={() => setCreating(true)} />
          )}
        </div>
      </div>
      {creating &&
        data &&
        createPortal(
          <BaseDialog
            onClose={() => setCreating(false)}
            onSaved={async (base) => {
              setCreating(false);
              await load();
              navigate(`/knowledge/${base.id}`);
            }}
          />,
          document.body,
        )}
    </main>
  );
}

function Overview({
  data,
  onCreate,
}: {
  data: MyKnowledge;
  onCreate: () => void;
}) {
  const { limits, mine, company } = data;
  const full = mine.length >= limits.maxBases;
  return (
    <>
      <div className="page-head">
        <div>
          <h2>知識庫</h2>
          <p>
            對話時勾選知識庫，agent
            會先搜尋裡面的文件再回答，並標出資料來自哪一份文件。
          </p>
        </div>
        {limits.enabled && (
          <button
            type="button"
            className="btn btn-accent"
            disabled={full}
            title={full ? `每個人最多 ${limits.maxBases} 個知識庫` : undefined}
            onClick={onCreate}
          >
            <AddIcon size={15} />
            新增知識庫
          </button>
        )}
      </div>

      {limits.enabled && (
        <section className="kb-group" aria-labelledby="h-kb-mine">
          <div className="kb-group-head">
            <h3 id="h-kb-mine">我的知識庫</h3>
            <span className="subtle">
              只有你看得到 · {mine.length}/{limits.maxBases} 個 · 已用{" "}
              {formatBytes(data.usedBytes)} /{" "}
              {formatBytes(limits.maxTotalBytes)}
            </span>
          </div>
          {mine.length === 0 ? (
            <div className="kb-empty">
              <span className="kb-empty-icon" aria-hidden="true">
                <BookIcon size={20} />
              </span>
              <div>
                <p className="kb-empty-title">還沒有自己的知識庫</p>
                <p className="subtle">
                  把常查的文件（手冊、規章、會議紀錄）放進來，對話時就能直接引用。
                </p>
              </div>
              <button
                type="button"
                className="btn btn-outline"
                onClick={onCreate}
              >
                <AddIcon size={15} />
                建立第一個
              </button>
            </div>
          ) : (
            <ul className="kb-grid">
              {mine.map((base) => (
                <li key={base.id}>
                  <Link to={`/knowledge/${base.id}`} className="kb-card">
                    <span className="kb-card-title">
                      <span className="kb-icon" aria-hidden="true">
                        <BookIcon size={16} />
                      </span>
                      <span className="kb-card-name">{base.name}</span>
                    </span>
                    <span className="kb-card-desc">
                      {base.description || "沒有說明"}
                    </span>
                    <span className="kb-card-meta">
                      {base.documents} 份文件 · {formatBytes(base.bytes)}
                      {base.chunking === "regulation" && (
                        <span className="badge badge-muted">依條文</span>
                      )}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      <section className="kb-group" aria-labelledby="h-kb-company">
        <div className="kb-group-head">
          <h3 id="h-kb-company">公司知識庫</h3>
          <span className="subtle">由管理者提供，依你所屬的群組開放</span>
        </div>
        {company.length === 0 ? (
          <p className="subtle kb-none">目前沒有開放給你的公司知識庫。</p>
        ) : (
          <ul className="kb-grid">
            {company.map((base) => (
              <li key={base.id}>
                <CompanyCard base={base} />
              </li>
            ))}
          </ul>
        )}
      </section>
    </>
  );
}

function CompanyCard({ base }: { base: CompanyKnowledgeBase }) {
  return (
    <div className="kb-card kb-card-static">
      <span className="kb-card-title">
        <span className="kb-icon" aria-hidden="true">
          <BookIcon size={16} />
        </span>
        <span className="kb-card-name">{base.name}</span>
      </span>
      <span className="kb-card-desc">{base.description || "沒有說明"}</span>
      <span className="kb-card-meta">{base.documents} 份文件</span>
      <span className="kb-card-actions">
        <Link to={chatWith(base.id)} className="btn btn-ghost btn-sm">
          <ChatsIcon size={14} />
          開新對話
        </Link>
        {base.manage && (
          <Link to="/admin/knowledge" className="btn btn-ghost btn-sm">
            <ShieldIcon size={14} />
            到管理平台管理
          </Link>
        )}
      </span>
    </div>
  );
}

function PersonalDetail({
  base,
  data,
  onChanged,
}: {
  base: PersonalKnowledgeBase;
  data: MyKnowledge;
  onChanged: () => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [deleting, setDeleting] = useState(false);
  return (
    <>
      <div className="kb-detail-head">
        <Link to="/knowledge" className="btn btn-ghost group-back">
          <ArrowLeftIcon size={15} />
          所有知識庫
        </Link>
        <div className="page-head">
          <div style={{ minWidth: 0 }}>
            <h2 className="kb-detail-title">{base.name}</h2>
            <p>
              {base.description || "沒有說明。"}
              <span className="badge badge-muted kb-type">
                {CHUNKING_LABELS[base.chunking]}
              </span>
            </p>
          </div>
          <div className="kb-detail-actions">
            <button
              type="button"
              className="btn btn-outline"
              onClick={() => setEditing(true)}
            >
              <PenIcon size={14} />
              編輯
            </button>
            <Link to={chatWith(base.id)} className="btn btn-accent">
              <ChatsIcon size={15} />
              用這個知識庫開新對話
            </Link>
          </div>
        </div>
      </div>

      <Documents base={base} data={data} onChanged={onChanged} />

      <div className="group-danger">
        <button
          type="button"
          className="btn btn-outline"
          onClick={() => setDeleting(true)}
        >
          <TrashIcon size={15} />
          刪除知識庫
        </button>
      </div>

      {editing &&
        createPortal(
          <BaseDialog
            base={base}
            onClose={() => setEditing(false)}
            onSaved={async () => {
              setEditing(false);
              await onChanged();
              showToast("已儲存");
            }}
          />,
          document.body,
        )}
      {deleting &&
        createPortal(
          <ConfirmDialog
            title={`刪除「${base.name}」？`}
            confirmLabel="刪除知識庫"
            danger
            onConfirm={async () => {
              await api.deleteMyKnowledge(base.id);
              showToast("已刪除知識庫");
              navigate("/knowledge");
              await onChanged();
            }}
            onClose={() => setDeleting(false)}
          >
            裡面的 {base.documents}{" "}
            份文件會一起刪除，不能復原。之前的對話裡的引用將打不開原文。
          </ConfirmDialog>,
          document.body,
        )}
    </>
  );
}

function Documents({
  base,
  data,
  onChanged,
}: {
  base: PersonalKnowledgeBase;
  data: MyKnowledge;
  onChanged: () => Promise<void>;
}) {
  const { limits, formats } = data;
  const [docs, setDocs] = useState<KnowledgeDocuments>();
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState<string>();
  const [dragging, setDragging] = useState(false);
  const [removing, setRemoving] = useState<string>();
  const input = useRef<HTMLInputElement>(null);
  const replaceInput = useRef<HTMLInputElement>(null);
  const replacing = useRef<string>(undefined);

  const load = useCallback(async () => {
    try {
      setDocs(await api.myKnowledgeDocuments(base.id));
    } catch (failure) {
      setError((failure as Error).message);
    }
  }, [base.id]);

  useEffect(() => {
    void load();
  }, [load]);

  const upload = async (files: File[], replace?: string) => {
    if (files.length === 0) return;
    setError(undefined);
    const failed: string[] = [];
    let done = 0;
    for (const file of files) {
      setBusy(`正在上傳 ${file.name}（${done + 1}/${files.length}）…`);
      const suffix = `.${file.name.split(".").pop()?.toLowerCase()}`;
      if (!formats.includes(suffix)) {
        failed.push(`${file.name}：不支援這種格式`);
        continue;
      }
      if (file.size > limits.maxFileBytes) {
        failed.push(
          `${file.name}：超過單檔上限 ${formatBytes(limits.maxFileBytes)}`,
        );
        continue;
      }
      try {
        await api.uploadMyKnowledge(base.id, file, replace);
        done += 1;
      } catch (failure) {
        failed.push(`${file.name}：${(failure as Error).message}`);
      }
    }
    setBusy("正在更新索引…");
    await Promise.all([load(), onChanged()]);
    setBusy(undefined);
    if (failed.length > 0) setError(failed.join("\n"));
    if (done > 0) {
      showToast(replace ? "已更新文件" : `已上傳 ${done} 份文件`);
    }
  };

  const onDrop = (event: DragEvent<HTMLElement>) => {
    event.preventDefault();
    setDragging(false);
    if (busy) return;
    void upload(Array.from(event.dataTransfer.files));
  };

  const index = docs?.index;
  const list = docs?.documents ?? [];
  const full = list.length >= limits.maxDocuments;
  return (
    <section className="kb-section kb-docs" aria-labelledby="h-kb-docs">
      <div className="box-row">
        <h3 id="h-kb-docs" className="kb-heading">
          文件
          <span className="subtle kb-count">
            {list.length}/{limits.maxDocuments} 份
          </span>
        </h3>
        <button
          type="button"
          className="btn btn-ghost"
          aria-label="重新讀取"
          title="重新讀取"
          onClick={load}
        >
          <RetryIcon size={15} />
        </button>
      </div>

      <button
        type="button"
        className={`kb-drop${dragging ? " dragging" : ""}`}
        disabled={Boolean(busy) || full}
        onClick={() => input.current?.click()}
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
      >
        <span className="kb-drop-icon" aria-hidden="true">
          <FileIcon size={20} />
        </span>
        <span className="kb-drop-title">
          {busy ??
            (full
              ? `已經有 ${limits.maxDocuments} 份文件，請先刪除不用的`
              : "把檔案拖到這裡，或點一下選擇檔案")}
        </span>
        <span className="subtle">
          支援 {formats.join("、")} · 每份最多{" "}
          {formatBytes(limits.maxFileBytes)} · 所有個人知識庫合計{" "}
          {formatBytes(limits.maxTotalBytes)}
        </span>
      </button>
      <input
        ref={input}
        type="file"
        multiple
        hidden
        accept={formats.join(",")}
        onChange={(event) => {
          const files = Array.from(event.target.files ?? []);
          event.target.value = "";
          void upload(files);
        }}
      />
      <input
        ref={replaceInput}
        type="file"
        hidden
        accept={formats.join(",")}
        onChange={(event) => {
          const files = Array.from(event.target.files ?? []).slice(0, 1);
          event.target.value = "";
          void upload(files, replacing.current);
        }}
      />

      {error && (
        <div className="inline-error kb-error" role="alert">
          {error}
        </div>
      )}
      {index && "error" in index && (
        <div className="box" role="alert">
          <span className="inline-error">建立索引失敗：{index.error}</span>
        </div>
      )}
      {index && !("error" in index) && index.warnings.length > 0 && (
        <ul className="kb-warnings">
          {index.warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      )}
      {!docs && !error && (
        <p className="subtle" aria-busy="true">
          讀取中…
        </p>
      )}
      {docs && list.length === 0 && (
        <p className="subtle kb-none">還沒有文件，上傳後就能在對話裡搜尋。</p>
      )}
      {list.length > 0 && (
        <ul className="member-list" aria-label="文件">
          {list.map((doc) => (
            <li key={doc.path} className="member-row">
              <span className="kb-icon" aria-hidden="true">
                <FileIcon size={15} />
              </span>
              <span className="member-main">
                <span className="member-name">
                  <span className="member-display kb-path">{doc.path}</span>
                  {!doc.supported && (
                    <span className="badge badge-muted">不支援的格式</span>
                  )}
                  {doc.note && (
                    <span className="badge badge-warn">搜尋不到</span>
                  )}
                </span>
                <span className="member-meta">
                  {formatBytes(doc.size)} · {doc.chunks} 個片段 ·{" "}
                  {new Date(doc.modifiedAt * 1000).toLocaleString()}
                </span>
                {doc.note && <span className="kb-note">{doc.note}</span>}
              </span>
              <button
                type="button"
                className="btn btn-ghost"
                disabled={Boolean(busy)}
                onClick={() => {
                  replacing.current = doc.path;
                  replaceInput.current?.click();
                }}
              >
                更新
              </button>
              <button
                type="button"
                className="btn btn-ghost"
                aria-label={`刪除 ${doc.path}`}
                title="刪除"
                disabled={Boolean(busy)}
                onClick={() => setRemoving(doc.path)}
              >
                <TrashIcon size={15} />
              </button>
            </li>
          ))}
        </ul>
      )}
      {removing &&
        createPortal(
          <ConfirmDialog
            title={`刪除「${removing}」？`}
            confirmLabel="刪除文件"
            danger
            onConfirm={async () => {
              await api.deleteMyKnowledgeDocument(base.id, removing);
              showToast("已刪除文件");
              await Promise.all([load(), onChanged()]);
            }}
            onClose={() => setRemoving(undefined)}
          >
            之後的對話搜尋不到這份文件。
          </ConfirmDialog>,
          document.body,
        )}
    </section>
  );
}

/** 新增（沒有 base）或編輯個人知識庫的對話框。 */
function BaseDialog({
  base,
  onClose,
  onSaved,
}: {
  base?: PersonalKnowledgeBase;
  onClose: () => void;
  onSaved: (base: PersonalKnowledgeBase) => void | Promise<void>;
}) {
  const titleId = useId();
  const nameRef = useRef<HTMLInputElement>(null);
  const [name, setName] = useState(base?.name ?? "");
  const [description, setDescription] = useState(base?.description ?? "");
  const [chunking, setChunking] = useState<PersonalKnowledgeBase["chunking"]>(
    base?.chunking ?? "paragraph",
  );
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!name.trim()) {
      setError("請輸入名稱");
      return;
    }
    setBusy(true);
    try {
      const fields = {
        name: name.trim(),
        description: description.trim(),
        chunking,
      };
      const saved = base
        ? await api.updateMyKnowledge(base.id, fields)
        : await api.createMyKnowledge(fields);
      await onSaved(saved);
    } catch (failure) {
      setError((failure as Error).message);
      setBusy(false);
    }
  };

  return (
    <Modal
      onClose={onClose}
      className="confirm-dialog form-dialog"
      labelledBy={titleId}
      initialFocus={nameRef}
    >
      <form onSubmit={submit} noValidate>
        <h2 id={titleId} className="dialog-title">
          {base ? "編輯知識庫" : "新增知識庫"}
        </h2>
        <div className="dialog-fields">
          <Field
            ref={nameRef}
            label="名稱"
            autoComplete="off"
            maxLength={40}
            placeholder="例如：專案 A 會議紀錄"
            value={name}
            error={error}
            onChange={(event) => {
              setName(event.target.value);
              setError(undefined);
            }}
          />
          <Field
            label="說明"
            autoComplete="off"
            maxLength={300}
            placeholder="選填：裡面有什麼文件，agent 會依說明判斷要不要搜尋"
            value={description}
            onChange={(event) => setDescription(event.target.value)}
          />
          <fieldset className="kb-type-choice">
            <legend>文件類型</legend>
            <label className="kb-radio">
              <input
                type="radio"
                name="chunking"
                checked={chunking === "paragraph"}
                onChange={() => setChunking("paragraph")}
              />
              <span>
                <strong>一般文件</strong>
                <span className="subtle">依段落切開，適合手冊、報告、筆記</span>
              </span>
            </label>
            <label className="kb-radio">
              <input
                type="radio"
                name="chunking"
                checked={chunking === "regulation"}
                onChange={() => setChunking("regulation")}
              />
              <span>
                <strong>法規、內規</strong>
                <span className="subtle">
                  「第 N 條」一條一段，引用時標出條號
                </span>
              </span>
            </label>
          </fieldset>
          {!base && (
            <p className="help">
              只有你自己看得到、用得到。要給同事一起用的資料，請管理者建成公司知識庫。
            </p>
          )}
        </div>
        <div className="dialog-actions">
          <button type="button" className="btn btn-outline" onClick={onClose}>
            取消
          </button>
          <button type="submit" className="btn btn-accent" disabled={busy}>
            {base ? "儲存" : "建立"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
