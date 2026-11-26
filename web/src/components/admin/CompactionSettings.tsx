/**
 * 管理平台「模型」裡的對話壓縮設定（Python 版）。
 *
 * 對話接近模型的上下文上限時，較早的內容會自動濃縮成摘要。要知道上限
 * 才能提前壓縮：litellm 認得的模型會自動查到；自架模型（vLLM、LiteLLM
 * Proxy 後面的模型）從端點的模型資料查，查不到時在這裡填。設定寫進
 * harness.yaml 的 compaction，自己測試並儲存，不經過下方的儲存列。
 */

import { useEffect, useState } from "react";
import type {
  CompactionModel,
  CompactionSettings,
} from "../../../../src/web/protocol.ts";
import { api } from "../../api.ts";
import { formatTokens } from "../../format.ts";
import { CheckIcon } from "../Icons.tsx";

const SOURCE_TEXT: Record<string, string> = {
  config: "手動設定",
  detected: "從端點查到",
  default: "harness.yaml 的 contextWindow",
  litellm: "litellm 的模型資料",
};

export function CompactionSection() {
  const [settings, setSettings] = useState<CompactionSettings>();
  const [loadError, setLoadError] = useState<string>();
  const [auto, setAuto] = useState(true);
  const [percent, setPercent] = useState("80");
  // 模型名稱 → 輸入框的內容（空字串表示不另外設定）。
  const [windows, setWindows] = useState<Record<string, string>>({});
  const [state, setState] = useState<"idle" | "saving" | "saved">("idle");
  const [error, setError] = useState<string>();

  const load = () =>
    api.compactionSettings().then(
      (value) => {
        setSettings(value);
        setAuto(value.auto);
        setPercent(String(Math.round(value.thresholdRatio * 100)));
        setWindows(
          Object.fromEntries(
            value.models.map((m) => [m.name, m.configured?.toString() ?? ""]),
          ),
        );
      },
      (failure: Error) => setLoadError(failure.message),
    );
  // biome-ignore lint/correctness/useExhaustiveDependencies: 只在打開時讀一次
  useEffect(() => {
    void load();
  }, []);

  if (loadError) {
    return <p className="inline-error">讀不到對話壓縮的設定：{loadError}</p>;
  }
  if (!settings) return null;

  const submit = async () => {
    setState("saving");
    setError(undefined);
    const contextWindows: Record<string, number | null> = {};
    for (const [name, value] of Object.entries(windows)) {
      const trimmed = value.replace(/[,\s_]/g, "");
      contextWindows[name] = trimmed ? Number(trimmed) : null;
    }
    try {
      await api.saveCompactionSettings({
        auto,
        thresholdRatio: Number(percent) / 100,
        contextWindows,
      });
      await load();
      setState("saved");
    } catch (failure) {
      setError((failure as Error).message);
      setState("idle");
    }
  };

  return (
    <div
      className="settings-body"
      style={{ paddingTop: 24, borderTop: "1px solid var(--line)", gap: 16 }}
    >
      <div>
        <h3 id="h-compaction" style={{ margin: 0 }}>
          對話壓縮
        </h3>
        <p className="help" style={{ marginTop: 4 }}>
          對話接近模型的上下文上限時，把較早的內容濃縮成摘要，長對話才不會超過上限而出錯。
          使用者也可以在對話中輸入 <code>/compact</code> 立刻壓縮。
          {!settings.enabled &&
            " 目前 harness.yaml 寫了 compaction: false（完全不壓縮），儲存後會重新開啟。"}
        </p>
      </div>

      <label className="model-choice" style={{ gap: 8 }}>
        <input
          type="checkbox"
          checked={auto}
          onChange={(event) => setAuto(event.target.checked)}
        />
        <span>自動壓縮</span>
      </label>

      <div className="form-row">
        <label htmlFor="compaction-threshold">自動壓縮的門檻（%）</label>
        <input
          id="compaction-threshold"
          className="field mono"
          style={{ width: 120 }}
          type="number"
          min={50}
          max={95}
          step={5}
          value={percent}
          disabled={!auto}
          onChange={(event) => setPercent(event.target.value)}
        />
        <div className="help">
          用到上下文上限的這個比例時開始壓縮，預設
          80%。模型回覆需要的空間（max_tokens）會另外扣掉。
        </div>
      </div>

      <fieldset className="form-row model-choices">
        <legend>各模型的上下文上限（tokens）</legend>
        <div className="help">
          查得到上限的模型不必填。自架模型查不到時請填上（例如 vLLM 的
          <code>--max-model-len</code>），否則只會在模型回報超過上限後才壓縮。
        </div>
        <ul className="model-choices-list">
          {settings.models.map((model) => (
            <ModelWindow
              key={model.name}
              model={model}
              value={windows[model.name] ?? ""}
              onChange={(value) =>
                setWindows((current) => ({ ...current, [model.name]: value }))
              }
            />
          ))}
        </ul>
      </fieldset>

      <div className="connection-actions">
        <button
          type="button"
          className="btn btn-outline"
          disabled={state === "saving"}
          onClick={() => void submit()}
        >
          {state === "saving" ? "正在儲存…" : "儲存對話壓縮設定"}
        </button>
        {state === "saved" && (
          <span className="ok-text anim-in" role="status">
            <CheckIcon size={14} />
            已儲存，下一輪對話開始生效
          </span>
        )}
        {error && (
          <span className="inline-error" role="alert">
            {error}
          </span>
        )}
      </div>
    </div>
  );
}

function ModelWindow({
  model,
  value,
  onChange,
}: {
  model: CompactionModel;
  value: string;
  onChange: (value: string) => void;
}) {
  const id = `compaction-window-${model.name}`;
  const found =
    model.detected ?? (model.source !== "config" ? model.window : null);
  let note = "查不到上限：只會在模型回報超過上限後才壓縮";
  if (model.window && model.source) {
    note = `目前使用 ${formatTokens(model.window)}（${SOURCE_TEXT[model.source]}）`;
  }
  return (
    <li
      style={{
        display: "grid",
        gridTemplateColumns: "minmax(0, 1fr) 150px",
        gap: 8,
        alignItems: "center",
        padding: "8px 12px",
      }}
    >
      <label htmlFor={id} style={{ minWidth: 0 }}>
        <span className="model-choice-label">{model.label}</span>
        {model.label !== model.name && (
          <span className="model-choice-name mono"> {model.name}</span>
        )}
        <div className={`help${model.window ? "" : " inline-error"}`}>
          {note}
        </div>
      </label>
      <input
        id={id}
        className="field mono"
        inputMode="numeric"
        value={value}
        placeholder={found ? String(found) : "例如 196608"}
        onChange={(event) => onChange(event.target.value)}
      />
    </li>
  );
}
