/**
 * 管理平台 → 成員（多人帳號模式，只有管理者看得到）：列出成員，新增成員、
 * 重設密碼、換角色、調整所屬群組、停用或啟用，以及刪除成員。
 *
 * 刪除會連同這個人的對話、記憶、「我的檔案」、個人知識庫與自建 agent 一起
 * 清掉，無法復原，所以要輸入帳號名稱確認；想保留資料請用停用。
 *
 * 密碼由伺服器產生，新增或重設後只顯示這一次，請管理者交給對方。
 * 伺服器拒絕的動作（例如停用最後一位管理者）把原因顯示在那一列。
 */

import {
  type FormEvent,
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";
import type {
  AccessGroup,
  CurrentUser,
  IssuedPassword,
  MemberInfo,
} from "../../../src/web/protocol.ts";
import { api } from "../api.ts";
import { currentUser, memberFormErrors, ROLE_LABELS } from "../auth.ts";
import { formatAgo, useNow } from "../format.ts";
import { refreshProject, useStore } from "../store.ts";
import { COPY_LABELS, useCopy } from "./chat/copy.ts";
import { CopyIcon } from "./chat/icons.tsx";
import {
  CheckIcon,
  CrossIcon,
  KeyIcon,
  MoreIcon,
  ShieldIcon,
  TrashIcon,
  UserPlusIcon,
  UsersIcon,
} from "./Icons.tsx";
import { ConfirmDialog, Modal } from "./shell/Dialog.tsx";
import { Field } from "./shell/Field.tsx";
import { FloatingMenu } from "./shell/FloatingMenu.tsx";
import { Avatar } from "./shell/UserMenu.tsx";

type Pending =
  | { kind: "disable"; member: MemberInfo }
  | { kind: "reset"; member: MemberInfo }
  | { kind: "delete"; member: MemberInfo }
  | { kind: "groups"; member: MemberInfo };

export function Members() {
  const me = useStore((s) => currentUser(s.project));
  const hasGroups = useStore((s) => s.project?.features?.groups === true);
  const [members, setMembers] = useState<MemberInfo[]>();
  // 可以加入的群組（不含「所有人」）；沒有群組功能時是空的。
  const [groups, setGroups] = useState<AccessGroup[]>([]);
  const [loadError, setLoadError] = useState<string>();
  const [adding, setAdding] = useState(false);
  const [issued, setIssued] = useState<{
    title: string;
    password: string;
  }>();
  const [menu, setMenu] = useState<{ id: string; anchor: HTMLElement }>();
  const [pending, setPending] = useState<Pending>();
  const [rowError, setRowError] = useState<{ id: string; message: string }>();
  const [busy, setBusy] = useState<string>();
  const now = useNow(true, 60_000);
  const closeMenu = useCallback(() => setMenu(undefined), []);

  const load = useCallback(() => {
    setLoadError(undefined);
    api.members().then(setMembers, (error: Error) => {
      setLoadError(error.message);
    });
    if (hasGroups) {
      // 讀不到群組時只是不顯示群組，成員照常管理。
      api.groups().then(
        (list) => setGroups(list.groups.filter((item) => !item.builtin)),
        () => setGroups([]),
      );
    }
  }, [hasGroups]);
  useEffect(load, [load]);

  const replace = (updated: MemberInfo) =>
    setMembers((list) =>
      list?.map((item) => (item.id === updated.id ? updated : item)),
    );

  const update = async (
    member: MemberInfo,
    changes: Parameters<typeof api.updateMember>[1],
  ) => {
    setRowError(undefined);
    setBusy(member.id);
    try {
      replace(await api.updateMember(member.id, changes));
      // 改了自己的角色：帳號選單與管理平台看得到的東西跟著變。
      if (member.id === me?.id) void refreshProject();
    } catch (error) {
      setRowError({ id: member.id, message: (error as Error).message });
    }
    setBusy(undefined);
  };

  const showIssued = (title: string, result: IssuedPassword) => {
    replace(result.user);
    setIssued({ title, password: result.password });
  };

  const menuMember = members?.find((item) => item.id === menu?.id);
  const groupNames = (member: MemberInfo) =>
    (member.groups ?? [])
      .map((id) => groups.find((item) => item.id === id)?.name)
      .filter(Boolean)
      .join("、");

  return (
    <section aria-labelledby="h-members" className="settings-body">
      <div className="members-head">
        <div>
          <h2 id="h-members">成員</h2>
          <p className="lead">
            每位成員用自己的帳號登入，只看得到自己的對話、檔案與記憶。
          </p>
        </div>
        <button
          type="button"
          className="btn btn-accent"
          onClick={() => setAdding(true)}
        >
          <UserPlusIcon size={15} />
          新增成員
        </button>
      </div>

      {loadError && (
        <div className="box box-row" role="alert">
          <span className="inline-error">讀不到成員：{loadError}</span>
          <button type="button" className="btn btn-outline" onClick={load}>
            重試
          </button>
        </div>
      )}
      {!members && !loadError && (
        <p className="subtle" aria-busy="true">
          讀取中…
        </p>
      )}
      {members && (
        <ul className="member-list" aria-label="成員">
          {members.map((member) => (
            <li
              key={member.id}
              className={`member-row${member.disabled ? " disabled" : ""}`}
            >
              <Avatar name={member} />
              <div className="member-main">
                <div className="member-name">
                  <span className="member-display">{member.displayName}</span>
                  {member.id === me?.id && (
                    <span className="subtle">（你）</span>
                  )}
                  {member.role === "admin" && (
                    <span className="badge badge-muted">管理者</span>
                  )}
                  {member.disabled && (
                    <span className="badge badge-danger">停用</span>
                  )}
                </div>
                <div className="member-meta">
                  <span className="mono">{member.username}</span>
                  {" · "}
                  {member.lastSeenAt
                    ? `最後使用 ${formatAgo(member.lastSeenAt, now)}`
                    : "還沒登入過"}
                  {groupNames(member) && ` · 群組：${groupNames(member)}`}
                </div>
              </div>
              {busy === member.id && (
                <>
                  <span className="spinner spin" aria-hidden="true" />
                  <span className="sr-only">處理中</span>
                </>
              )}
              <button
                type="button"
                className="icon-btn"
                aria-label={`「${member.displayName}」的選項`}
                aria-haspopup="menu"
                aria-expanded={menu?.id === member.id}
                onClick={(event) =>
                  setMenu(
                    menu?.id === member.id
                      ? undefined
                      : { id: member.id, anchor: event.currentTarget },
                  )
                }
              >
                <MoreIcon />
              </button>
              {rowError?.id === member.id && (
                <p className="inline-error member-error" role="alert">
                  {rowError.message}
                </p>
              )}
            </li>
          ))}
        </ul>
      )}

      {menu && menuMember && (
        <FloatingMenu anchor={menu.anchor} label="成員選項" onClose={closeMenu}>
          {/* 自己的密碼到使用者選單的「修改密碼」改。 */}
          {menuMember.id !== me?.id && (
            <button
              type="button"
              role="menuitem"
              className="menu-item"
              onClick={() => {
                closeMenu();
                setPending({ kind: "reset", member: menuMember });
              }}
            >
              <KeyIcon size={15} />
              重設密碼
            </button>
          )}
          <button
            type="button"
            role="menuitem"
            className="menu-item"
            onClick={() => {
              closeMenu();
              void update(menuMember, {
                role: menuMember.role === "admin" ? "member" : "admin",
              });
            }}
          >
            <ShieldIcon size={15} />
            {menuMember.role === "admin" ? "設為成員" : "設為管理者"}
          </button>
          {hasGroups && (
            <button
              type="button"
              role="menuitem"
              className="menu-item"
              onClick={() => {
                closeMenu();
                setPending({ kind: "groups", member: menuMember });
              }}
            >
              <UsersIcon size={15} />
              調整群組
            </button>
          )}
          {/* 不能停用自己，不然會把自己鎖在外面。 */}
          {menuMember.id !== me?.id && (
            <button
              type="button"
              role="menuitem"
              className={`menu-item${menuMember.disabled ? "" : " danger"}`}
              onClick={() => {
                closeMenu();
                if (menuMember.disabled) {
                  void update(menuMember, { disabled: false });
                } else {
                  setPending({ kind: "disable", member: menuMember });
                }
              }}
            >
              {menuMember.disabled ? (
                <CheckIcon size={15} />
              ) : (
                <CrossIcon size={15} />
              )}
              {menuMember.disabled ? "啟用" : "停用"}
            </button>
          )}
          {/* 不能刪除自己。 */}
          {menuMember.id !== me?.id && (
            <button
              type="button"
              role="menuitem"
              className="menu-item danger"
              onClick={() => {
                closeMenu();
                setPending({ kind: "delete", member: menuMember });
              }}
            >
              <TrashIcon size={15} />
              刪除成員
            </button>
          )}
        </FloatingMenu>
      )}

      {pending?.kind === "disable" &&
        createPortal(
          <ConfirmDialog
            title={`停用「${pending.member.displayName}」？`}
            confirmLabel="停用"
            onConfirm={async () => {
              replace(
                await api.updateMember(pending.member.id, { disabled: true }),
              );
            }}
            onClose={() => setPending(undefined)}
          >
            <p>
              停用後 {pending.member.username}{" "}
              就不能登入，對話與檔案會保留，之後可以再啟用。
            </p>
          </ConfirmDialog>,
          document.body,
        )}
      {pending?.kind === "reset" &&
        createPortal(
          <ConfirmDialog
            title={`重設「${pending.member.displayName}」的密碼？`}
            confirmLabel="重設密碼"
            onConfirm={async () => {
              const result = await api.resetPassword(pending.member.id);
              showIssued(`${pending.member.displayName} 的新密碼`, result);
            }}
            onClose={() => setPending(undefined)}
          >
            <p>原本的密碼會馬上失效，會產生一組新的密碼。</p>
          </ConfirmDialog>,
          document.body,
        )}
      {pending?.kind === "delete" &&
        createPortal(
          <DeleteMemberDialog
            member={pending.member}
            onDeleted={() =>
              setMembers((list) =>
                list?.filter((item) => item.id !== pending.member.id),
              )
            }
            onClose={() => setPending(undefined)}
          />,
          document.body,
        )}
      {pending?.kind === "groups" &&
        createPortal(
          <MemberGroupsDialog
            member={pending.member}
            groups={groups}
            onSaved={replace}
            onClose={() => setPending(undefined)}
          />,
          document.body,
        )}
      {adding &&
        createPortal(
          <AddMemberDialog
            groups={groups}
            onClose={() => setAdding(false)}
            onAdded={(result) => {
              setMembers((list) => [...(list ?? []), result.user]);
              setAdding(false);
              setIssued({
                title: `已新增 ${result.user.displayName}`,
                password: result.password,
              });
            }}
          />,
          document.body,
        )}
      {issued &&
        createPortal(
          <PasswordDialog
            title={issued.title}
            password={issued.password}
            onClose={() => setIssued(undefined)}
          />,
          document.body,
        )}
    </section>
  );
}

function AddMemberDialog({
  groups,
  onClose,
  onAdded,
}: {
  groups: AccessGroup[];
  onClose: () => void;
  onAdded: (result: IssuedPassword) => void;
}) {
  const [chosen, setChosen] = useState<string[]>([]);
  const titleId = useId();
  const formRef = useRef<HTMLFormElement>(null);
  const firstRef = useRef<HTMLInputElement>(null);
  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [role, setRole] = useState<CurrentUser["role"]>("member");
  const [errors, setErrors] = useState<ReturnType<typeof memberFormErrors>>({});
  const [failure, setFailure] = useState<string>();
  const [busy, setBusy] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (attempt === 0) return;
    formRef.current
      ?.querySelector<HTMLInputElement>("[aria-invalid='true']")
      ?.focus();
  }, [attempt]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const found = memberFormErrors({ username, displayName });
    setErrors(found);
    setAttempt((count) => count + 1);
    if (Object.keys(found).length > 0) return;
    setBusy(true);
    setFailure(undefined);
    try {
      onAdded(
        await api.addMember(
          username.trim(),
          displayName.trim(),
          role,
          role === "member" ? chosen : [],
        ),
      );
    } catch (error) {
      setFailure((error as Error).message);
      setBusy(false);
    }
  };

  return (
    <Modal
      onClose={onClose}
      className="confirm-dialog form-dialog"
      labelledBy={titleId}
      initialFocus={firstRef}
    >
      <form ref={formRef} onSubmit={submit} noValidate>
        <h2 id={titleId} className="dialog-title">
          新增成員
        </h2>
        <div className="dialog-fields">
          <Field
            ref={firstRef}
            label="帳號"
            className="mono"
            autoComplete="off"
            autoCapitalize="none"
            spellCheck={false}
            value={username}
            error={errors.username}
            hint={
              errors.username ? undefined : "登入時輸入的名稱，建立後不能改"
            }
            onChange={(event) => {
              setUsername(event.target.value);
              setErrors((current) => ({ ...current, username: undefined }));
            }}
          />
          <Field
            label="顯示名稱"
            autoComplete="off"
            value={displayName}
            error={errors.displayName}
            onChange={(event) => {
              setDisplayName(event.target.value);
              setErrors((current) => ({ ...current, displayName: undefined }));
            }}
          />
          <fieldset className="form-row role-field">
            <legend className="label">角色</legend>
            <div className="segmented segmented-sm">
              {(["member", "admin"] as const).map((item) => (
                <button
                  key={item}
                  type="button"
                  aria-pressed={role === item}
                  onClick={() => setRole(item)}
                >
                  {ROLE_LABELS[item]}
                </button>
              ))}
            </div>
            <div className="help">
              {role === "admin"
                ? "管理者可以管理成員、模型連線、權限與工作資料夾。"
                : "成員只能使用自己的對話、檔案與記憶。"}
            </div>
          </fieldset>
          {role === "member" && groups.length > 0 && (
            <GroupChecklist
              groups={groups}
              value={chosen}
              onChange={setChosen}
            />
          )}
        </div>
        {failure && (
          <p className="inline-error" role="alert">
            {failure}
          </p>
        )}
        <div className="dialog-actions">
          <button type="button" className="btn btn-outline" onClick={onClose}>
            取消
          </button>
          <button type="submit" className="btn btn-accent" disabled={busy}>
            {busy && <span className="spinner spin" aria-hidden="true" />}
            新增
          </button>
        </div>
      </form>
    </Modal>
  );
}

/** 勾選要加入的群組（不含「所有人」，每位成員都自動屬於它）。 */
function GroupChecklist({
  groups,
  value,
  onChange,
}: {
  groups: AccessGroup[];
  value: string[];
  onChange: (value: string[]) => void;
}) {
  const toggle = (id: string) =>
    onChange(
      value.includes(id) ? value.filter((item) => item !== id) : [...value, id],
    );
  return (
    <fieldset className="model-choices access-field">
      <legend>群組</legend>
      <div className="help">
        每位成員都屬於「所有人」；另外勾選的群組開放的資源也能使用。
      </div>
      <ul className="model-choices-list">
        {groups.map((group) => (
          <li key={group.id}>
            <label className="model-choice">
              <input
                type="checkbox"
                checked={value.includes(group.id)}
                onChange={() => toggle(group.id)}
              />
              <span className="model-choice-label">{group.name}</span>
              {group.description && (
                <span className="model-choice-name">{group.description}</span>
              )}
            </label>
          </li>
        ))}
      </ul>
    </fieldset>
  );
}

/** 從成員這一邊調整他屬於哪些群組。 */
function MemberGroupsDialog({
  member,
  groups,
  onSaved,
  onClose,
}: {
  member: MemberInfo;
  groups: AccessGroup[];
  onSaved: (member: MemberInfo) => void;
  onClose: () => void;
}) {
  const titleId = useId();
  const [chosen, setChosen] = useState<string[]>(member.groups ?? []);
  const [failure, setFailure] = useState<string>();
  const [busy, setBusy] = useState(false);

  const save = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setFailure(undefined);
    try {
      onSaved(await api.setMemberGroups(member.id, chosen));
      onClose();
    } catch (error) {
      setFailure((error as Error).message);
      setBusy(false);
    }
  };

  return (
    <Modal
      onClose={onClose}
      className="confirm-dialog form-dialog"
      labelledBy={titleId}
    >
      <form onSubmit={save}>
        <h2 id={titleId} className="dialog-title">
          「{member.displayName}」的群組
        </h2>
        <div className="dialog-fields">
          {member.role === "admin" && (
            <p className="help">
              管理者不受群組限制，加入與否都能使用全部資源。
            </p>
          )}
          {groups.length > 0 ? (
            <GroupChecklist
              groups={groups}
              value={chosen}
              onChange={setChosen}
            />
          ) : (
            <p className="help">
              還沒有其他群組。到「群組」頁新增群組後，就能在這裡把成員加進去。
            </p>
          )}
        </div>
        {failure && (
          <p className="inline-error" role="alert">
            {failure}
          </p>
        )}
        <div className="dialog-actions">
          <button type="button" className="btn btn-outline" onClick={onClose}>
            取消
          </button>
          <button
            type="submit"
            className="btn btn-accent"
            disabled={busy || groups.length === 0}
          >
            {busy && <span className="spinner spin" aria-hidden="true" />}
            儲存
          </button>
        </div>
      </form>
    </Modal>
  );
}

/** 刪除成員：無法復原，要輸入帳號名稱才能確認。 */
function DeleteMemberDialog({
  member,
  onDeleted,
  onClose,
}: {
  member: MemberInfo;
  onDeleted: () => void;
  onClose: () => void;
}) {
  const [typed, setTyped] = useState("");
  const matches = typed.trim().toLowerCase() === member.username.toLowerCase();
  return (
    <ConfirmDialog
      title={`刪除「${member.displayName}」？`}
      confirmLabel="刪除成員"
      danger
      disabled={!matches}
      onConfirm={async () => {
        await api.deleteMember(member.id);
        onDeleted();
      }}
      onClose={onClose}
    >
      <p>
        帳號會被刪除，連同他的對話、記憶、我的檔案、個人知識庫與自建 Agent
        一起清掉，<strong>無法復原</strong>。稽核紀錄會保留。
      </p>
      <p>只是暫時不讓他登入、想保留資料的話，請改用「停用」。</p>
      <Field
        label={`輸入帳號 ${member.username} 確認`}
        className="mono"
        autoComplete="off"
        autoCapitalize="none"
        spellCheck={false}
        value={typed}
        onChange={(event) => setTyped(event.target.value)}
      />
    </ConfirmDialog>
  );
}

/** 只顯示一次的密碼，附複製按鈕。 */
function PasswordDialog({
  title,
  password,
  onClose,
}: {
  title: string;
  password: string;
  onClose: () => void;
}) {
  const titleId = useId();
  const copyRef = useRef<HTMLButtonElement>(null);
  const [state, copy] = useCopy();
  return (
    <Modal
      onClose={onClose}
      className="confirm-dialog"
      labelledBy={titleId}
      initialFocus={copyRef}
    >
      <h2 id={titleId} className="dialog-title">
        {title}
      </h2>
      <div className="dialog-body">
        <div className="issued-password">
          <span className="sr-only">密碼：</span>
          <code className="mono issued-code">{password}</code>
          <button
            ref={copyRef}
            type="button"
            className="btn btn-outline ch-btn-small"
            onClick={() => copy(password)}
          >
            {state === "copied" ? (
              <CheckIcon size={14} />
            ) : (
              <CopyIcon size={14} />
            )}
            <span aria-live="polite">{COPY_LABELS[state]}</span>
          </button>
        </div>
        <p className="help issued-note">
          這組密碼只會顯示這一次，請交給對方，登入後可以自己修改。
        </p>
      </div>
      <div className="dialog-actions">
        <button type="button" className="btn btn-accent" onClick={onClose}>
          完成
        </button>
      </div>
    </Modal>
  );
}
