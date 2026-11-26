/**
 * 管理平台 → 資料分級：機密的資料只交給核可的模型（例如地端模型）。
 *
 * 管理者定義等級（由低到高），指定每個模型最高能處理哪一級、知識庫與
 * 工具組的資料屬於哪一級。對話碰到超過目前模型等級的資料時，伺服器自動
 * 改用「自動改用的模型」；一個都沒有時停下來，資料不會送出。
 *
 * 改動先放在草稿裡，按「儲存」才寫回 harness.yaml。
 */

import { useCallback, useEffect, useState } from "react";
import type { ClassificationSettings } from "../../../../src/web/protocol.ts";
import { api } from "../../api.ts";
import { refreshProject } from "../../store.ts";
import { AddIcon, TrashIcon } from "../Icons.tsx";
import { showToast } from "../shell/toast.tsx";

type Levels = ClassificationSettings["levels"];

export function Classification() {
  const [saved, setSaved] = useState<ClassificationSettings>();
  const [draft, setDraft] = useState<ClassificationSettings>();
  const [loadError, setLoadError] = useState<string>();
  const [error, setError] = useState<string>();
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoadError(undefined);
    try {
      const found = await api.classification();
      setSaved(found);
      setDraft(structuredClone(found));
    } catch (failure) {
      setLoadError((failure as Error).message);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (loadError) {
    return (
      <div className="box box-row" role="alert">
        <span className="inline-error">讀不到資料分級設定：{loadError}</span>
        <button type="button" className="btn btn-outline" onClick={load}>
          重試
        </button>
      </div>
    );
  }
  if (!saved || !draft) {
    return (
      <p className="subtle" aria-busy="true">
        讀取中…
      </p>
    );
  }

  const dirty = JSON.stringify(strip(saved)) !== JSON.stringify(strip(draft));
  const edit = (change: Partial<ClassificationSettings>) => {
    setError(undefined);
    setDraft({ ...draft, ...change });
  };

  const save = async () => {
    setSaving(true);
    try {
      const found = await api.saveClassification(strip(draft));
      setSaved(found);
      setDraft(structuredClone(found));
      setError(undefined);
      showToast("已儲存資料分級");
      await refreshProject();
    } catch (failure) {
      setError((failure as Error).message);
    }
    setSaving(false);
  };

  const models = unique([
    ...(saved.modelNames ?? []),
    ...Object.keys(draft.models),
    ...(draft.routeTo ? [draft.routeTo] : []),
  ]);
  const top = draft.levels.at(-1)?.name ?? "";

  return (
    <section aria-labelledby="h-cls" className="settings-body">
      <div className="members-head">
        <div>
          <h2 id="h-cls">資料分級</h2>
          <p className="lead">
            {
              "替知識庫與工具組標上資料等級，並指定每個模型能處理到哪一級。對話用到超過目前模型等級的資料時，會自動改用可以處理的模型（例如地端模型）並在對話裡提示；沒有可以處理的模型就停下來，資料不會送出。"
            }
          </p>
        </div>
        <label className="skill-switch">
          <input
            type="checkbox"
            checked={draft.enabled}
            onChange={(event) => edit({ enabled: event.target.checked })}
          />
          啟用資料分級
        </label>
      </div>

      {!draft.enabled && (
        <p className="subtle">
          目前沒有啟用：所有模型都能讀到所有資料。啟用後才能設定等級。
          {saved.enabled && " 儲存後會拿掉每個知識庫的等級。"}
        </p>
      )}

      {draft.enabled && (
        <>
          <div className="box">
            <h3 className="kb-subheading">等級（由低到高）</h3>
            <LevelsEditor
              levels={draft.levels}
              onChange={(levels) => edit(dropMissing(draft, levels))}
            />
          </div>

          <div className="box">
            <h3 className="kb-subheading">模型能處理的等級</h3>
            <p className="help">
              每個模型最高能讀到哪一級的資料。沒有另外設定的模型用「其他模型」。
            </p>
            <div className="cls-row">
              <span>其他模型</span>
              <LevelSelect
                levels={draft.levels}
                value={draft.defaultClearance}
                empty={`不限制（可以處理「${top}」）`}
                onChange={(value) => edit({ defaultClearance: value })}
              />
            </div>
            <table className="cls-table">
              <thead>
                <tr>
                  <th>模型</th>
                  <th>最高能處理</th>
                </tr>
              </thead>
              <tbody>
                {models.map((model) => (
                  <tr key={model}>
                    <td className="mono">{model}</td>
                    <td>
                      <LevelSelect
                        levels={draft.levels}
                        value={draft.models[model] ?? null}
                        empty="同其他模型"
                        label={`${model} 最高能處理的等級`}
                        onChange={(value) =>
                          edit({ models: put(draft.models, model, value) })
                        }
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="cls-row">
              <span>超過時自動改用</span>
              <select
                className="field"
                aria-label="超過時自動改用的模型"
                value={draft.routeTo ?? ""}
                onChange={(event) =>
                  edit({ routeTo: event.target.value || null })
                }
              >
                <option value="">挑第一個可以處理的模型</option>
                {models.map((model) => (
                  <option key={model} value={model}>
                    {model}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="box">
            <h3 className="kb-subheading">資料來源的等級</h3>
            <p className="help">
              對話搜尋到這些知識庫、或用了這些工具組後，就算碰過這個等級的資料，之後每一輪都要用可以處理它的模型回覆。
            </p>
            <table className="cls-table">
              <thead>
                <tr>
                  <th>資料來源</th>
                  <th>等級</th>
                </tr>
              </thead>
              <tbody>
                {(saved.bases ?? []).map((base) => (
                  <tr key={`kb-${base.id}`}>
                    <td>知識庫「{base.name}」</td>
                    <td>
                      <LevelSelect
                        levels={draft.levels}
                        value={draft.knowledgeBases[base.id] ?? null}
                        empty="沒有分級"
                        label={`知識庫 ${base.name} 的等級`}
                        onChange={(value) =>
                          edit({
                            knowledgeBases: put(
                              draft.knowledgeBases,
                              base.id,
                              value,
                            ),
                          })
                        }
                      />
                    </td>
                  </tr>
                ))}
                {saved.personalEnabled && (
                  <tr>
                    <td>所有個人知識庫</td>
                    <td>
                      <LevelSelect
                        levels={draft.levels}
                        value={draft.personalKnowledge}
                        empty="沒有分級"
                        label="個人知識庫的等級"
                        onChange={(value) => edit({ personalKnowledge: value })}
                      />
                    </td>
                  </tr>
                )}
                {(saved.toolsetNames ?? []).map((name) => (
                  <tr key={`ts-${name}`}>
                    <td>
                      工具組 <span className="mono">{name}</span>
                    </td>
                    <td>
                      <LevelSelect
                        levels={draft.levels}
                        value={draft.toolsets[name] ?? null}
                        empty="沒有分級"
                        label={`工具組 ${name} 的等級`}
                        onChange={(value) =>
                          edit({ toolsets: put(draft.toolsets, name, value) })
                        }
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {dirty && (
        <section className="save-bar" aria-label="未儲存的變更">
          <span className={error ? "inline-error" : undefined}>
            {error ?? "資料分級有未儲存的變更"}
          </span>
          <div style={{ display: "flex", gap: 6 }}>
            <button
              type="button"
              className="btn btn-outline"
              disabled={saving}
              onClick={() => {
                setDraft(structuredClone(saved));
                setError(undefined);
              }}
            >
              捨棄
            </button>
            <button
              type="button"
              className="btn btn-accent"
              disabled={saving}
              onClick={save}
            >
              儲存
            </button>
          </div>
        </section>
      )}
    </section>
  );
}

function LevelsEditor({
  levels,
  onChange,
}: {
  levels: Levels;
  onChange: (levels: Levels) => void;
}) {
  const set = (index: number, change: Partial<Levels[number]>) =>
    onChange(
      levels.map((item, at) => (at === index ? { ...item, ...change } : item)),
    );
  return (
    <>
      <ol className="cls-levels">
        {levels.map((item, index) => (
          // biome-ignore lint/suspicious/noArrayIndexKey: 識別碼可以編輯，只能用位置
          <li key={index}>
            <span className="cls-rank">{index + 1}</span>
            <input
              className="field mono"
              aria-label={`第 ${index + 1} 級的識別碼`}
              value={item.id}
              onChange={(event) => set(index, { id: event.target.value })}
            />
            <input
              className="field"
              aria-label={`第 ${index + 1} 級的名稱`}
              value={item.name}
              onChange={(event) => set(index, { name: event.target.value })}
            />
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              aria-label={`刪除「${item.name}」`}
              disabled={levels.length <= 2}
              onClick={() => onChange(levels.filter((_, at) => at !== index))}
            >
              <TrashIcon size={15} />
            </button>
          </li>
        ))}
      </ol>
      <button
        type="button"
        className="btn btn-ghost"
        disabled={levels.length >= 8}
        onClick={() =>
          onChange([
            ...levels,
            { id: `level${levels.length + 1}`, name: "新等級" },
          ])
        }
      >
        <AddIcon size={15} />
        新增更高的等級
      </button>
    </>
  );
}

function LevelSelect({
  levels,
  value,
  empty,
  label,
  onChange,
}: {
  levels: Levels;
  value: string | null;
  empty: string;
  label?: string;
  onChange: (value: string | null) => void;
}) {
  return (
    <select
      className="field"
      aria-label={label}
      value={value ?? ""}
      onChange={(event) => onChange(event.target.value || null)}
    >
      <option value="">{empty}</option>
      {levels.map((item) => (
        <option key={item.id} value={item.id}>
          {item.name}
        </option>
      ))}
    </select>
  );
}

/** 拿掉只給畫面用的欄位，留下要存的設定。 */
function strip(settings: ClassificationSettings): ClassificationSettings {
  const {
    modelNames: _models,
    toolsetNames: _toolsets,
    bases: _bases,
    personalEnabled: _personal,
    ...rest
  } = settings;
  return rest;
}

function put(
  mapping: Record<string, string>,
  key: string,
  value: string | null,
): Record<string, string> {
  const next = { ...mapping };
  if (value) next[key] = value;
  else delete next[key];
  return next;
}

/** 等級改了之後，拿掉指向已經不存在的等級的設定。 */
function dropMissing(
  draft: ClassificationSettings,
  levels: Levels,
): Partial<ClassificationSettings> {
  const ids = new Set(levels.map((item) => item.id));
  const keep = (value: string | null) =>
    value && ids.has(value) ? value : null;
  const filter = (mapping: Record<string, string>) =>
    Object.fromEntries(
      Object.entries(mapping).filter(([, value]) => ids.has(value)),
    );
  return {
    levels,
    defaultClearance: keep(draft.defaultClearance),
    personalKnowledge: keep(draft.personalKnowledge),
    models: filter(draft.models),
    toolsets: filter(draft.toolsets),
    knowledgeBases: filter(draft.knowledgeBases),
  };
}

function unique(items: string[]): string[] {
  return [...new Set(items)];
}
