/**
 * 新增或編輯一個 skill 的對話框，管理平台的公司 skill 與 Skills 頁的個人
 * skill 共用。也提供上傳 skill 資料夾 zip 的按鈕（同名時問要不要取代）。
 *
 * skill 由三個部分組成，和 Anthropic 的 SKILL.md 一樣：
 * - 名稱：小寫英文、數字與連字號，載入時用這個名稱，建立後不能改。
 * - 說明：agent 平常只看得到這段，靠它判斷什麼時候要載入。
 * - 指示：載入後 agent 照著做的完整內容（Markdown）。
 */

import { type FormEvent, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { SkillDetail } from "../../../src/web/protocol.ts";
import { ApiError, type SkillInput } from "../api.ts";
import { TrashIcon } from "./Icons.tsx";
import { ConfirmDialog, Modal } from "./shell/Dialog.tsx";
import { Field } from "./shell/Field.tsx";

const NAME_PATTERN = /^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$/;

export const DESCRIPTION_PLACEHOLDER =
  "例如：整理會議記錄。使用者貼上會議逐字稿或筆記、要整理成決議與待辦時使用";
export const INSTRUCTIONS_PLACEHOLDER = `例如：
1. 先列出會議的決議，每點一行。
2. 再列出待辦事項，寫出負責人與期限（沒提到就寫「未定」）。
3. 最後補上還沒有結論的議題。`;

/** 名稱不符合規則時的說明；沒問題時為 undefined。 */
export function nameError(name: string): string | undefined {
  if (!name.trim()) return "請輸入名稱";
  if (!NAME_PATTERN.test(name.trim())) {
    return "只能用小寫英文、數字與連字號（-），開頭和結尾不能是連字號";
  }
  return undefined;
}

export function SkillDialog({
  skill,
  title,
  note,
  readOnly = false,
  deleteLabel,
  deleteNote,
  onClose,
  onSave,
  onDelete,
}: {
  /** 編輯時的內容；新增時沒有。 */
  skill?: SkillDetail;
  title: string;
  /** 顯示在欄位上方的說明，例如「儲存後會複製成公司版本」。 */
  note?: string;
  /** 只能看（例如成員看公司 skill）。 */
  readOnly?: boolean;
  /** 有的話顯示刪除按鈕。 */
  deleteLabel?: string;
  deleteNote?: string;
  onClose: () => void;
  onSave: (input: SkillInput) => Promise<void>;
  onDelete?: () => Promise<void>;
}) {
  const titleId = useId();
  const descriptionId = useId();
  const instructionsId = useId();
  const [name, setName] = useState(skill?.name ?? "");
  const [description, setDescription] = useState(skill?.description ?? "");
  const [instructions, setInstructions] = useState(skill?.instructions ?? "");
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const editing = skill !== undefined;
  const checkedName = editing ? undefined : nameError(name);
  const [touched, setTouched] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setTouched(true);
    if (checkedName) return;
    if (!description.trim()) {
      setError("請填寫說明：agent 靠這段說明判斷什麼時候要載入");
      return;
    }
    if (!instructions.trim()) {
      setError("請填寫指示");
      return;
    }
    setBusy(true);
    try {
      await onSave({
        name: name.trim(),
        description: description.trim(),
        instructions,
      });
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
          {title}
        </h2>
        {note && <p className="help skill-note">{note}</p>}
        <div className="dialog-fields">
          <Field
            label="名稱"
            className="mono"
            autoComplete="off"
            value={name}
            disabled={editing || readOnly}
            placeholder="例如 meeting-notes"
            error={touched ? checkedName : undefined}
            hint={
              editing
                ? "名稱是載入時用的識別碼，建立後不能修改。"
                : "小寫英文、數字與連字號，例如 meeting-notes。建立後不能修改。"
            }
            onChange={(event) => {
              setName(event.target.value);
              setError(undefined);
            }}
          />
          <div className="form-row field-row">
            <label htmlFor={descriptionId}>說明（什麼時候用）</label>
            <textarea
              id={descriptionId}
              className="field skill-description"
              rows={3}
              value={description}
              readOnly={readOnly}
              placeholder={DESCRIPTION_PLACEHOLDER}
              aria-describedby={`${descriptionId}-hint`}
              onChange={(event) => {
                setDescription(event.target.value);
                setError(undefined);
              }}
            />
            <div id={`${descriptionId}-hint`} className="help">
              agent
              平常只看得到這段說明，靠它判斷要不要載入；寫清楚做什麼、什麼情況下使用。
            </div>
          </div>
          <div className="form-row field-row">
            <label htmlFor={instructionsId}>指示</label>
            <textarea
              id={instructionsId}
              className="field agent-instructions skill-instructions"
              rows={14}
              value={instructions}
              readOnly={readOnly}
              placeholder={INSTRUCTIONS_PLACEHOLDER}
              aria-describedby={`${instructionsId}-hint`}
              onChange={(event) => {
                setInstructions(event.target.value);
                setError(undefined);
              }}
            />
            <div id={`${instructionsId}-hint`} className="help">
              載入後 agent 照著做的內容，可以用 Markdown。
            </div>
          </div>
          {skill && skill.files.length > 0 && (
            <div className="form-row">
              <span className="label">參考檔案（{skill.files.length}）</span>
              <ul className="skill-files mono">
                {skill.files.slice(0, 30).map((path) => (
                  <li key={path}>{path}</li>
                ))}
                {skill.files.length > 30 && (
                  <li className="subtle">
                    還有 {skill.files.length - 30} 個檔案
                  </li>
                )}
              </ul>
              <div className="help">
                agent 載入後需要時用 read_skill_file 讀取。要換檔案請重新上傳
                zip。
              </div>
            </div>
          )}
          {skill && (skill.requires.length > 0 || skill.tools.length > 0) && (
            <div className="help">
              {skill.requires.length > 0 &&
                `需要這些工具才用得上：${skill.requires.join("、")}。`}
              {skill.tools.length > 0 &&
                ` 載入時一併開啟的工具：${skill.tools.join("、")}。`}
            </div>
          )}
        </div>

        {error && (
          <p className="inline-error" role="alert">
            {error}
          </p>
        )}
        <div className="dialog-actions">
          {onDelete && deleteLabel && (
            <div className="mcp-dialog-extra">
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                disabled={busy}
                onClick={() => setDeleting(true)}
              >
                <TrashIcon size={14} />
                {deleteLabel}
              </button>
            </div>
          )}
          <button type="button" className="btn btn-outline" onClick={onClose}>
            {readOnly ? "關閉" : "取消"}
          </button>
          {!readOnly && (
            <button type="submit" className="btn btn-accent" disabled={busy}>
              {editing ? "儲存" : "建立"}
            </button>
          )}
        </div>
      </form>

      {deleting &&
        onDelete &&
        createPortal(
          <ConfirmDialog
            title={`${deleteLabel}「${name}」？`}
            confirmLabel={deleteLabel ?? "刪除"}
            danger
            onConfirm={async () => {
              try {
                await onDelete();
              } catch (failure) {
                setDeleting(false);
                setError((failure as Error).message);
              }
            }}
            onClose={() => setDeleting(false)}
          >
            {deleteNote}
          </ConfirmDialog>,
          document.body,
        )}
    </Modal>
  );
}

/**
 * 上傳 skill 資料夾的 zip：同名的 skill 已經存在時（409）先問要不要取代。
 * 回傳上傳後的 skill；取消時回傳 undefined。
 */
export function useSkillUpload(
  upload: (file: File, replace: boolean) => Promise<SkillDetail>,
) {
  const input = useRef<HTMLInputElement>(null);
  const [pending, setPending] = useState<{ file: File; message: string }>();
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);
  const resolver = useRef<(value: SkillDetail | undefined) => void>(undefined);

  const send = async (file: File, replace: boolean) => {
    setBusy(true);
    setError(undefined);
    try {
      const result = await upload(file, replace);
      resolver.current?.(result);
    } catch (failure) {
      if (failure instanceof ApiError && failure.status === 409 && !replace) {
        setPending({ file, message: failure.message });
      } else {
        setError((failure as Error).message);
        resolver.current?.(undefined);
      }
    }
    setBusy(false);
  };

  const choose = (): Promise<SkillDetail | undefined> =>
    new Promise((resolve) => {
      resolver.current = resolve;
      input.current?.click();
    });

  const element = (
    <>
      <input
        ref={input}
        type="file"
        accept=".zip,application/zip"
        hidden
        onChange={(event) => {
          const file = event.target.files?.[0];
          event.target.value = "";
          if (file) void send(file, false);
        }}
      />
      {pending &&
        createPortal(
          <ConfirmDialog
            title="取代同名的 skill？"
            confirmLabel="取代"
            onConfirm={async () => {
              const { file } = pending;
              setPending(undefined);
              await send(file, true);
            }}
            onClose={() => {
              setPending(undefined);
              resolver.current?.(undefined);
            }}
          >
            {pending.message} 取代後原本的指示與參考檔案會換成 zip 裡的內容。
          </ConfirmDialog>,
          document.body,
        )}
    </>
  );
  return {
    choose,
    element,
    error,
    busy,
    clearError: () => setError(undefined),
  };
}
