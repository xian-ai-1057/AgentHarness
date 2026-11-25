/**
 * 管理平台 → Skills（Python 版，features.skillAdmin）：管理者新增、修改、
 * 刪除公司的 skill，或上傳 skill 資料夾的 zip。
 *
 * - 內建的 skill（改寫自 Anthropic 官方的等）不能刪，但可以關閉；修改內容
 *   會複製成公司版本取代內建的，刪掉公司版本就還原。
 * - 「預設開啟」的 skill 每段對話都會列給 agent（agent 用得上時才載入）；
 *   沒有預設開啟的，成員可以在 ＋ 選單自己勾選。
 * - 誰能用哪些 skill 由「群組」決定；成員也可以在 Skills 頁建立只有自己
 *   能用的個人 skill。
 */

import { useCallback, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import type {
  AdminSkillInfo,
  AdminSkillList,
  SkillDetail,
} from "../../../../src/web/protocol.ts";
import { api } from "../../api.ts";
import { refreshProject } from "../../store.ts";
import { UploadIcon } from "../chat/icons.tsx";
import { AddIcon } from "../Icons.tsx";
import { SkillDialog, useSkillUpload } from "../SkillDialog.tsx";
import { showToast } from "../shell/toast.tsx";

type Editing = { skill?: SkillDetail; info?: AdminSkillInfo };

const SOURCE_LABELS: Record<AdminSkillInfo["source"], string> = {
  builtin: "內建",
  company: "公司",
  personal: "個人",
};

export function Skills() {
  const [list, setList] = useState<AdminSkillList>();
  const [loadError, setLoadError] = useState<string>();
  const [editing, setEditing] = useState<Editing>();
  const [busy, setBusy] = useState<string>();
  const [filter, setFilter] = useState("");

  const load = useCallback(async () => {
    setLoadError(undefined);
    try {
      setList(await api.adminSkills());
    } catch (error) {
      setLoadError((error as Error).message);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const changed = async (message: string) => {
    showToast(message);
    await Promise.all([load(), refreshProject()]);
  };

  const upload = useSkillUpload((file, replace) =>
    api.uploadAdminSkill(file, replace),
  );

  const open = async (info: AdminSkillInfo) => {
    setBusy(info.name);
    try {
      setEditing({ info, skill: await api.adminSkill(info.name) });
    } catch (error) {
      showToast((error as Error).message);
    }
    setBusy(undefined);
  };

  const toggle = async (
    info: AdminSkillInfo,
    key: "enabled" | "default",
    value: boolean,
  ) => {
    setBusy(info.name);
    try {
      await api.updateAdminSkill(info.name, { [key]: value });
      await changed(
        key === "enabled"
          ? `${value ? "已啟用" : "已關閉"} ${info.name}`
          : `${info.name} ${value ? "改成預設開啟" : "不再預設開啟"}`,
      );
    } catch (error) {
      showToast((error as Error).message);
    }
    setBusy(undefined);
  };

  const query = filter.trim().toLowerCase();
  const shown = (list?.skills ?? []).filter(
    (item) =>
      !query ||
      item.name.includes(query) ||
      item.description.toLowerCase().includes(query),
  );

  return (
    <section aria-labelledby="h-skills" className="settings-body">
      <div className="members-head">
        <div>
          <h2 id="h-skills">Skills</h2>
          <p className="lead">
            {
              "Skill 是一段任務指示（可以附參考檔案），agent 判斷用得上時才載入。這裡管理公司的 skill：內建的可以關閉或改成公司版本；誰能用由「群組」決定。成員也可以在 Skills 頁建立只有自己能用的 skill。"
            }
          </p>
        </div>
        <div className="skill-head-actions">
          <button
            type="button"
            className="btn btn-outline"
            disabled={!list || upload.busy}
            onClick={async () => {
              upload.clearError();
              const result = await upload.choose();
              if (result) await changed(`已上傳 ${result.name}`);
            }}
          >
            <UploadIcon size={15} />
            上傳 zip
          </button>
          <button
            type="button"
            className="btn btn-accent"
            disabled={!list}
            onClick={() => setEditing({})}
          >
            <AddIcon size={15} />
            新增 skill
          </button>
        </div>
      </div>
      {upload.element}
      {upload.error && (
        <p className="inline-error" role="alert">
          上傳失敗：{upload.error}
        </p>
      )}

      {loadError && (
        <div className="box box-row" role="alert">
          <span className="inline-error">讀不到 skills：{loadError}</span>
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

      {list && (
        <>
          <input
            type="search"
            className="field skill-filter"
            placeholder="搜尋名稱或說明"
            aria-label="搜尋 skill"
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
          />
          <ul className="member-list" aria-label="Skills">
            {shown.map((item) => (
              <li key={item.name} className="member-row skill-row">
                <div className="member-main">
                  <div className="member-name">
                    <span className="member-display mono">{item.name}</span>
                    <span
                      className={`badge ${
                        item.source === "company"
                          ? "badge-accent"
                          : "badge-muted"
                      }`}
                    >
                      {item.overridesBuiltin
                        ? "公司版（取代內建）"
                        : SOURCE_LABELS[item.source]}
                    </span>
                    {!item.enabled && (
                      <span className="badge badge-warn">已關閉</span>
                    )}
                  </div>
                  <div className="member-meta skill-desc">
                    {item.description}
                  </div>
                  <div className="member-meta">
                    {[
                      item.requires.includes("run_python") && "需要沙盒",
                      item.files > 0 && `${item.files} 個參考檔案`,
                      item.usedBy.length > 0 &&
                        `Agent：${item.usedBy.join("、")}`,
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </div>
                </div>
                {busy === item.name && (
                  <span className="spinner spin" aria-hidden="true" />
                )}
                <label className="skill-switch">
                  <input
                    type="checkbox"
                    checked={item.enabled}
                    disabled={busy === item.name}
                    onChange={(event) =>
                      toggle(item, "enabled", event.target.checked)
                    }
                  />
                  啟用
                </label>
                <label className="skill-switch">
                  <input
                    type="checkbox"
                    checked={item.default}
                    disabled={busy === item.name || !item.enabled}
                    onChange={(event) =>
                      toggle(item, "default", event.target.checked)
                    }
                  />
                  預設開啟
                </label>
                <button
                  type="button"
                  className="btn btn-outline btn-sm"
                  disabled={busy === item.name}
                  onClick={() => open(item)}
                >
                  編輯
                </button>
              </li>
            ))}
            {shown.length === 0 && (
              <li className="subtle">沒有符合的 skill。</li>
            )}
          </ul>
        </>
      )}

      {editing &&
        createPortal(
          <SkillDialog
            skill={editing.skill}
            title={
              editing.skill ? `編輯 ${editing.skill.name}` : "新增公司 skill"
            }
            note={
              editing.info?.source === "builtin"
                ? "這是內建的 skill。儲存後會複製一份成公司版本（連同參考檔案）取代內建的；之後刪掉公司版本就還原成內建的。"
                : undefined
            }
            deleteLabel={
              editing.info?.source === "company"
                ? editing.info.overridesBuiltin
                  ? "還原成內建"
                  : "刪除"
                : undefined
            }
            deleteNote={
              editing.info?.overridesBuiltin
                ? "公司版本的指示與參考檔案會刪除，改回使用內建的版本。"
                : "刪除後所有對話都不能再使用它，自建 Agent 勾選的也會失效。"
            }
            onClose={() => setEditing(undefined)}
            onSave={async (input) => {
              if (editing.skill) {
                await api.updateAdminSkill(editing.skill.name, {
                  description: input.description,
                  instructions: input.instructions,
                });
                setEditing(undefined);
                await changed(`已儲存 ${editing.skill.name}`);
              } else {
                await api.createAdminSkill(input);
                setEditing(undefined);
                await changed(`已新增 ${input.name}`);
              }
            }}
            onDelete={async () => {
              const name = editing.skill?.name;
              if (!name) return;
              await api.deleteAdminSkill(name);
              setEditing(undefined);
              await changed(
                editing.info?.overridesBuiltin
                  ? `已還原 ${name}`
                  : `已刪除 ${name}`,
              );
            }}
          />,
          document.body,
        )}
    </section>
  );
}
