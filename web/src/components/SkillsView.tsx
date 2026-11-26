/**
 * Skills 頁（網址 /skills，Python 版）：每個人都看得到。
 *
 * - 我的 skill（帳號模式，features.personalSkills）：自己建立、只有自己
 *   能用的 skill，在自己的對話預設開啟，自建 Agent 也能勾選。可以新增、
 *   修改、刪除，或上傳 skill 資料夾的 zip。不能分享；要給別人用的請管理
 *   者在管理平台建成公司 skill。
 * - 公司與內建的 skill：依所屬群組開放，這裡只列出名稱與說明。管理者設成
 *   預設開啟的（例如 docx、xlsx）自動可用，和 Claude 一樣不列給一般成員，
 *   只有管理者看得到（標「自動開啟」）。
 *
 * 參考 Claude 的 Skills 設定頁：每個 skill 是 SKILL.md（名稱、說明、指示）
 * 加上參考檔案，agent 判斷用得上時才載入。
 */

import { useCallback, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import type {
  MySkillInfo,
  MySkillList,
  SkillDetail,
} from "../../../src/web/protocol.ts";
import { api } from "../api.ts";
import { isAdmin } from "../auth.ts";
import { refreshProject, useStore } from "../store.ts";
import { SparkIcon, UploadIcon } from "./chat/icons.tsx";
import { automaticSkills } from "./chat/options.ts";
import { AddIcon, ShieldIcon } from "./Icons.tsx";
import { Link } from "./Sidebar.tsx";
import { SkillDialog, useSkillUpload } from "./SkillDialog.tsx";
import { showToast } from "./shell/toast.tsx";

export function SkillsView() {
  const project = useStore((s) => s.project);
  const [data, setData] = useState<MySkillList>();
  const [loadError, setLoadError] = useState<string>();
  const [editing, setEditing] = useState<SkillDetail | "new">();

  const load = useCallback(async () => {
    setLoadError(undefined);
    try {
      setData(await api.mySkills());
    } catch (error) {
      setLoadError((error as Error).message);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    document.title = "Skills · Harness";
  }, []);

  const changed = async (message: string) => {
    showToast(message);
    await Promise.all([load(), refreshProject()]);
  };

  const upload = useSkillUpload((file, replace) =>
    api.uploadMySkill(file, replace),
  );

  const open = async (item: MySkillInfo) => {
    try {
      setEditing(await api.mySkill(item.name));
    } catch (error) {
      showToast((error as Error).message);
    }
  };

  const admin = isAdmin(project);
  const automatic = project ? automaticSkills(project) : new Set<string>();
  const shared = (data?.shared ?? []).filter(
    (item) => admin || !automatic.has(item.name),
  );
  const hidden = (data?.shared.length ?? 0) - shared.length;
  const full =
    data?.limits.maxSkills != null &&
    data.skills.length >= data.limits.maxSkills;

  return (
    <main className="main">
      <header className="main-header">
        <div className="main-title">
          <h1>Skills</h1>
        </div>
      </header>
      <div className="scroll">
        <div className="page kb-page">
          {loadError && (
            <div className="box box-row" role="alert">
              <span className="inline-error">讀不到 skills：{loadError}</span>
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
          {data && (
            <>
              <div className="page-head">
                <div>
                  <h2>Skills</h2>
                  <p>
                    Skill
                    是一段任務指示（可以附參考檔案），例如「整理會議記錄」「依公司格式寫週報」。agent
                    平常只看得到說明，判斷用得上時才載入指示照著做。
                  </p>
                </div>
                {data.enabled && (
                  <div className="skill-head-actions">
                    <button
                      type="button"
                      className="btn btn-outline"
                      disabled={full || upload.busy}
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
                      disabled={full}
                      title={
                        full
                          ? `每個人最多 ${data.limits.maxSkills} 個 skill`
                          : undefined
                      }
                      onClick={() => setEditing("new")}
                    >
                      <AddIcon size={15} />
                      新增 skill
                    </button>
                  </div>
                )}
              </div>
              {upload.element}
              {upload.error && (
                <p className="inline-error" role="alert">
                  上傳失敗：{upload.error}
                </p>
              )}

              {data.enabled ? (
                <section className="kb-group" aria-labelledby="h-skill-mine">
                  <div className="kb-group-head">
                    <h3 id="h-skill-mine">我的 skill</h3>
                    <span className="subtle">
                      只有你看得到，在你的對話預設開啟 · {data.skills.length}
                      {data.limits.maxSkills != null &&
                        `/${data.limits.maxSkills}`}{" "}
                      個
                    </span>
                  </div>
                  {data.skills.length === 0 ? (
                    <div className="kb-empty">
                      <span className="kb-empty-icon" aria-hidden="true">
                        <SparkIcon size={20} />
                      </span>
                      <div>
                        <p className="kb-empty-title">還沒有自己的 skill</p>
                        <p className="subtle">
                          把常做的工作步驟寫成 skill，之後對話時 agent
                          會照著做，不用每次重新交代。
                        </p>
                      </div>
                      <button
                        type="button"
                        className="btn btn-outline"
                        onClick={() => setEditing("new")}
                      >
                        <AddIcon size={15} />
                        建立第一個
                      </button>
                    </div>
                  ) : (
                    <ul className="kb-grid">
                      {data.skills.map((item) => (
                        <li key={item.name}>
                          <button
                            type="button"
                            className="kb-card skill-card"
                            onClick={() => open(item)}
                          >
                            <span className="kb-card-title">
                              <span className="kb-icon" aria-hidden="true">
                                <SparkIcon size={16} />
                              </span>
                              <span className="kb-card-name mono">
                                {item.name}
                              </span>
                            </span>
                            <span className="kb-card-desc">
                              {item.description}
                            </span>
                            <span className="kb-card-meta">
                              {item.files > 0
                                ? `${item.files} 個參考檔案`
                                : "沒有參考檔案"}
                              {item.shadowed && (
                                <span
                                  className="badge badge-warn"
                                  title="管理者新增了同名的公司 skill，對話裡會用公司的"
                                >
                                  被公司 skill 取代
                                </span>
                              )}
                            </span>
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </section>
              ) : (
                <p className="help">
                  這個版本沒有個人 skill（只在多人帳號模式提供）。
                  {admin && "要新增或修改 skill，請到管理平台的 Skills 頁。"}
                </p>
              )}

              <section className="kb-group" aria-labelledby="h-skill-shared">
                <div className="kb-group-head">
                  <h3 id="h-skill-shared">公司與內建的 skill</h3>
                  <span className="subtle">
                    由管理者提供，依你所屬的群組開放
                  </span>
                  {admin && (
                    <Link to="/admin/skills" className="btn btn-ghost btn-sm">
                      <ShieldIcon size={14} />
                      到管理平台管理
                    </Link>
                  )}
                </div>
                {hidden > 0 && (
                  <p className="help">
                    常用的 skill（例如製作 Word、Excel 檔）已自動開啟，對話時
                    agent 用得上就會使用，不用另外設定。
                  </p>
                )}
                {shared.length === 0 ? (
                  hidden === 0 && (
                    <p className="subtle kb-none">
                      目前沒有開放給你的公司 skill。
                    </p>
                  )
                ) : (
                  <ul className="kb-grid">
                    {shared.map((item) => (
                      <li key={item.name}>
                        <div className="kb-card kb-card-static">
                          <span className="kb-card-title">
                            <span className="kb-icon" aria-hidden="true">
                              <SparkIcon size={16} />
                            </span>
                            <span className="kb-card-name mono">
                              {item.name}
                            </span>
                          </span>
                          <span className="kb-card-desc">
                            {item.description}
                          </span>
                          <span className="kb-card-meta">
                            <span className="badge badge-muted">
                              {item.builtin ? "內建" : "公司"}
                            </span>
                            {automatic.has(item.name) && (
                              <span
                                className="badge badge-muted"
                                title="每段對話自動開啟，一般成員看不到這個 skill"
                              >
                                自動開啟
                              </span>
                            )}
                          </span>
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            </>
          )}
        </div>
      </div>

      {editing &&
        createPortal(
          <SkillDialog
            skill={editing === "new" ? undefined : editing}
            title={
              editing === "new" ? "新增我的 skill" : `編輯 ${editing.name}`
            }
            note={
              editing === "new"
                ? "只有你看得到、用得到，建立後在你的對話預設開啟。要給別人用的 skill 請找管理者建成公司 skill。"
                : undefined
            }
            deleteLabel={editing === "new" ? undefined : "刪除"}
            deleteNote="刪除後你的對話與自建 Agent 都不能再使用它。"
            onClose={() => setEditing(undefined)}
            onSave={async (input) => {
              if (editing === "new") {
                await api.createMySkill(input);
                setEditing(undefined);
                await changed(`已新增 ${input.name}`);
              } else {
                await api.updateMySkill(editing.name, {
                  description: input.description,
                  instructions: input.instructions,
                });
                setEditing(undefined);
                await changed(`已儲存 ${editing.name}`);
              }
            }}
            onDelete={async () => {
              if (editing === "new") return;
              await api.deleteMySkill(editing.name);
              setEditing(undefined);
              await changed(`已刪除 ${editing.name}`);
            }}
          />,
          document.body,
        )}
    </main>
  );
}
