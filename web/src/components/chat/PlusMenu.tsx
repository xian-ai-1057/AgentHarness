/**
 * 輸入框左下角的 ＋ 選單：上傳檔案、選 skills、勾選這段對話要搜尋的知識庫。
 *
 * 和 Claude 一樣，常用的能力（網頁搜尋、讀檔等工具，以及管理者設成預設
 * 開啟的 docx、xlsx 等 skill）自動可用，這裡不逐一列出；要調整請管理者
 * 到管理平台。這裡只列使用者自己挑的 skill（含自己的 skill）與知識庫。
 *
 * Skills 與知識庫在同一個彈出框裡換頁顯示，手機上也好點。可以複選，所以
 * 勾選後選單不關；送出訊息時（closeSignal 改變）才關。
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { BookIcon, CheckIcon, ChevronIcon } from "../Icons.tsx";
import {
  BackIcon,
  PlusIcon,
  SearchIcon,
  SparkIcon,
  UploadIcon,
} from "./icons.tsx";
import {
  activeDefaultSkills,
  type ComposerOptions,
  chosenKnowledge,
  missingTool,
  toggleKnowledge,
  toggleSkill,
} from "./options.ts";
import { focusTrigger, Popover } from "./Popover.tsx";

type View = "main" | "skills" | "knowledge";

export function PlusMenu({
  options,
  closeSignal,
  onUpload,
}: {
  options: ComposerOptions;
  /** 改變時關掉選單（例如送出了訊息）。 */
  closeSignal?: number;
  /** 打開選檔視窗；沒有提供時不顯示「上傳檔案」。 */
  onUpload?: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [view, setView] = useState<View>("main");
  const anchor = useRef<HTMLDivElement>(null);
  // 從子頁按「回上一層」時，記下是哪一頁，回到主選單後焦點放在那一項。
  const returnTo = useRef<View>(undefined);
  const close = useCallback(() => {
    setOpen(false);
    setView("main");
  }, []);
  // biome-ignore lint/correctness/useExhaustiveDependencies: 只在 closeSignal 改變時關
  useEffect(close, [closeSignal]);
  const back = (from: View) => {
    returnTo.current = from;
    setView("main");
  };
  useEffect(() => {
    if (view !== "main" || !returnTo.current) return;
    anchor.current
      ?.querySelector<HTMLElement>(`[data-view="${returnTo.current}"]`)
      ?.focus();
    returnTo.current = undefined;
  }, [view]);

  const { skills, value, knowledgeBases, defaultKnowledge } = options;
  const searched = chosenKnowledge(value, defaultKnowledge);
  const defaults = options.defaultSkills ?? [];
  const activeDefaults = activeDefaultSkills(options);
  // 預設開啟的（自己的 skill）排在前面，勾選狀態看有沒有被關掉。需要的
  // 工具在這段對話被取消時（舊對話才會有）不能勾選。
  const skillItems = [
    ...skills.filter((skill) => defaults.includes(skill.name)),
    ...skills.filter((skill) => !defaults.includes(skill.name)),
  ].map((skill) => {
    const missing = missingTool(options, skill.name);
    return {
      name: skill.name,
      description: missing
        ? `這段對話停用了 ${missing}，移除「已停用工具」標籤後才能使用。`
        : skill.description,
      // 個人 skill 只有自己能用，也是預設開啟。
      tag: skill.personal
        ? "我的"
        : defaults.includes(skill.name)
          ? "預設"
          : undefined,
      disabled: Boolean(missing),
      checked:
        !missing &&
        (activeDefaults.includes(skill.name) ||
          value.skills.includes(skill.name)),
    };
  });
  const skillCount = skillItems.filter((item) => item.checked).length;

  return (
    <div className="ch-anchor" ref={anchor}>
      <button
        type="button"
        className="icon-btn ch-plus-btn"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label="更多選項：上傳檔案、skills、知識庫"
        onClick={() => (open ? close() : setOpen(true))}
      >
        <PlusIcon />
      </button>
      <Popover
        open={open}
        onClose={close}
        anchor={anchor}
        label="更多選項"
        className="ch-plus-pop"
      >
        {view === "main" && (
          <div className="ch-pop-list" role="menu" aria-label="更多選項">
            {onUpload && (
              <button
                type="button"
                role="menuitem"
                className="ch-pop-item"
                onClick={() => {
                  focusTrigger(anchor);
                  close();
                  onUpload();
                }}
              >
                <UploadIcon />
                <span className="ch-pop-main">
                  <span className="ch-pop-title">上傳檔案</span>
                </span>
              </button>
            )}
            {skills.length > 0 && (
              <button
                type="button"
                role="menuitem"
                className="ch-pop-item"
                data-view="skills"
                onClick={() => setView("skills")}
              >
                <SparkIcon />
                <span className="ch-pop-main">
                  <span className="ch-pop-title">Skills</span>
                </span>
                {skillCount > 0 && (
                  <span className="ch-count">{skillCount}</span>
                )}
                <ChevronIcon size={14} />
              </button>
            )}
            {knowledgeBases.length > 0 && (
              <button
                type="button"
                role="menuitem"
                className="ch-pop-item"
                data-view="knowledge"
                onClick={() => setView("knowledge")}
              >
                <BookIcon />
                <span className="ch-pop-main">
                  <span className="ch-pop-title">知識庫</span>
                </span>
                <span className="ch-count">
                  {searched.length}/{knowledgeBases.length}
                </span>
                <ChevronIcon size={14} />
              </button>
            )}
          </div>
        )}
        {view === "skills" && (
          <Checklist
            title="Skills"
            hint={
              defaults.length > 0
                ? "標「我的」的 skill 每段對話都開著，需要時 agent 會自己使用，取消勾選就不用；其他勾選的 skill 會請 agent 先讀過再回答。常用的 skill（例如 Word、Excel）已自動開啟，不必勾選。"
                : "勾選的 skill 會請 agent 先讀過再回答。常用的 skill（例如 Word、Excel）已自動開啟，不必勾選。"
            }
            items={skillItems}
            onToggle={(name) => options.onChange(toggleSkill(options, name))}
            onBack={() => back("skills")}
          />
        )}
        {view === "knowledge" && (
          <Checklist
            title="知識庫"
            hint="勾選的知識庫，agent 回答前會一起搜尋，並標出資料來自哪個知識庫。"
            items={knowledgeBases.map((base) => ({
              name: base.id,
              label: base.name,
              description: base.personal
                ? `我的知識庫${base.description ? ` · ${base.description}` : ""}`
                : base.description,
              checked: searched.includes(base.id),
            }))}
            onToggle={(id) =>
              options.onChange({
                knowledge: toggleKnowledge(
                  value,
                  defaultKnowledge,
                  knowledgeBases,
                  id,
                ),
              })
            }
            onBack={() => back("knowledge")}
          />
        )}
        {view !== "main" && options.nextTurn && (
          <div className="ch-pop-note">下一則訊息開始使用</div>
        )}
      </Popover>
    </div>
  );
}

function Checklist({
  title,
  hint,
  items,
  onToggle,
  onBack,
}: {
  title: string;
  hint: string;
  items: {
    name: string;
    /** 顯示的名稱；沒有時顯示 name。 */
    label?: string;
    description: string;
    /** 名稱旁邊的小標籤，例如「預設」。 */
    tag?: string;
    /** 不能勾選（例如需要的工具被取消了）。 */
    disabled?: boolean;
    checked: boolean;
  }[];
  onToggle: (name: string) => void;
  onBack: () => void;
}) {
  const [query, setQuery] = useState("");
  const search = useRef<HTMLInputElement>(null);
  // 換頁後焦點放在搜尋框，鍵盤可以直接輸入。
  useEffect(() => search.current?.focus(), []);
  const needle = query.trim().toLowerCase();
  const shown = needle
    ? items.filter((item) =>
        `${item.name} ${item.label ?? ""} ${item.description}`
          .toLowerCase()
          .includes(needle),
      )
    : items;
  return (
    <div className="ch-pop-view">
      <div className="ch-pop-head">
        <button
          type="button"
          className="icon-btn ch-pop-back"
          aria-label="回上一層"
          onClick={onBack}
        >
          <BackIcon />
        </button>
        <span className="ch-pop-heading">{title}</span>
      </div>
      <div className="ch-pop-search">
        <SearchIcon size={14} />
        <input
          ref={search}
          type="search"
          placeholder={`搜尋${title}`}
          aria-label={`搜尋${title}`}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => {
            // 輸入框在表單裡，Enter 會送出訊息；改成勾選第一個符合的項目。
            if (event.key !== "Enter" || event.nativeEvent.isComposing) return;
            event.preventDefault();
            const first = shown.find((item) => !item.disabled);
            if (first) onToggle(first.name);
          }}
        />
      </div>
      <div className="ch-pop-list" role="menu" aria-label={title}>
        {shown.map((item) => (
          <button
            key={item.name}
            type="button"
            role="menuitemcheckbox"
            aria-checked={item.checked}
            className="ch-pop-item"
            title={item.description}
            disabled={item.disabled}
            onClick={() => onToggle(item.name)}
          >
            <span className={`ch-box${item.checked ? " on" : ""}`}>
              {item.checked && <CheckIcon size={12} />}
            </span>
            <span className="ch-pop-main">
              <span className={`ch-pop-title${item.label ? "" : " mono"}`}>
                {item.label ?? item.name}
                {item.tag && <span className="ch-pop-tag">{item.tag}</span>}
              </span>
              {item.description && (
                <span className="ch-pop-sub clamp">{item.description}</span>
              )}
            </span>
          </button>
        ))}
        {shown.length === 0 && (
          <div className="ch-pop-empty">找不到符合的項目</div>
        )}
      </div>
      <div className="ch-pop-hint">{hint}</div>
    </div>
  );
}
