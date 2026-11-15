/**
 * 右側面板：知識庫出處的原文。
 *
 * 「原文」分頁顯示整份文件讀出來的文字（GET /api/knowledge/source/text），
 * 引用的那一段用螢光標示，捲到畫面中間並閃一下；每次點對話裡的引用
 * 編號都會再閃一次。「原始檔案」分頁是原本的檔案：PDF 用瀏覽器內建的
 * 檢視器開到出處的頁碼，其他格式在新分頁開啟或下載。
 *
 * 和檔案面板一樣可以拖曳左邊的分隔線調整寬度（兩個面板共用寬度）。
 */

import { type ReactNode, useEffect, useRef, useState } from "react";
import type { KnowledgeSourceText } from "../../../src/web/protocol.ts";
import { api } from "../api.ts";
import "./chat/chat.css";
import {
  findCitedSection,
  type KnowledgeSource,
  sourceUrl,
} from "./chat/citations.ts";
import { DownloadIcon } from "./chat/icons.tsx";
import { PanelResizer } from "./chat/PanelResizer.tsx";
import { usePanelWidth } from "./chat/usePanelWidth.ts";
import { CloseIcon } from "./Icons.tsx";

type View = "text" | "file";
type Sections = KnowledgeSourceText["sections"];

export function SourcePanel({
  source,
  onClose,
}: {
  /** 每次點引用都是新的物件，用來再閃一次。 */
  source: KnowledgeSource;
  onClose: () => void;
}) {
  const panelRef = useRef<HTMLElement>(null);
  const { shown, changeWidth } = usePanelWidth(panelRef);
  const [view, setView] = useState<View>("text");
  const name = source.path.split("/").at(-1) ?? source.path;
  const url = sourceUrl(source);
  const pdf = /\.pdf$/i.test(source.path);
  const fileShown = source.page ? `${url}#page=${source.page}` : url;

  // 文件的文字；同一份文件換引用時不重新讀取。
  const docKey = `${source.base}\n${source.path}`;
  const [doc, setDoc] = useState<{
    key: string;
    sections?: Sections;
    error?: string;
  }>();
  useEffect(() => {
    let cancelled = false;
    const key = `${source.base}\n${source.path}`;
    api.knowledgeSourceText(source.base, source.path).then(
      (found) => {
        if (!cancelled) setDoc({ key, sections: found.sections });
      },
      (error: Error) => {
        if (!cancelled) setDoc({ key, error: error.message });
      },
    );
    return () => {
      cancelled = true;
    };
  }, [source.base, source.path]);
  const loaded = doc?.key === docKey ? doc : undefined;
  const sections = loaded?.sections;
  const hit = sections ? findCitedSection(sections, source) : -1;

  // 換引用、文字讀好或切回「原文」時，把引用的段落捲到中間並閃一下。
  const hitRef = useRef<HTMLElement>(null);
  // biome-ignore lint/correctness/useExhaustiveDependencies: 文字讀好時 hitRef 才指到段落，要再跑一次
  useEffect(() => {
    const element = hitRef.current;
    if (!element || view !== "text" || !source) return;
    element.scrollIntoView({ block: "center" });
    element.classList.remove("ch-source-flash");
    // 重新觸發動畫：先讓瀏覽器套用拿掉 class 的樣式。
    void element.offsetWidth;
    element.classList.add("ch-source-flash");
  }, [source, sections, view]);

  return (
    <>
      <PanelResizer
        width={shown}
        onWidth={changeWidth}
        onReset={() => changeWidth(null)}
      />
      <aside
        ref={panelRef}
        className="panel anim-panel ch-panel"
        style={shown === null ? undefined : { flex: `0 0 ${shown}px` }}
        aria-label={`出處 ${source.number}`}
      >
        <div className="panel-header">
          <div className="tabs" role="tablist">
            <ViewTab id="text" view={view} onView={setView}>
              原文
            </ViewTab>
            <ViewTab id="file" view={view} onView={setView}>
              原始檔案
            </ViewTab>
          </div>
          <div className="ch-panel-tools">
            <button
              type="button"
              className="icon-btn"
              aria-label="關閉面板"
              onClick={onClose}
            >
              <CloseIcon />
            </button>
          </div>
        </div>
        <div className="ch-tab-body">
          <div className="scroll">
            <div className="file-head ch-preview-head ch-source-head">
              <div className="ch-preview-title">
                <span className="ch-preview-name">
                  <span className="ch-cite ch-source-number">
                    {source.number}
                  </span>
                  {name}
                </span>
                <span className="mono subtle ch-preview-path">
                  {[source.base, source.location].filter(Boolean).join(" · ") ||
                    source.path}
                </span>
              </div>
              <a
                className="btn btn-outline ch-btn-small"
                href={sourceUrl(source, true)}
                download
                aria-label={`下載 ${name}`}
              >
                <DownloadIcon size={14} />
                下載
              </a>
            </div>
            {view === "text" ? (
              <SourceText
                sections={sections}
                error={loaded?.error}
                hit={hit}
                hitRef={hitRef}
                excerpt={source.excerpt}
                url={url}
              />
            ) : pdf ? (
              <div className="anim-in">
                <div className="ch-preview-pdf">
                  {/* 換到另一頁時重新建立：只改網址的 #page 不一定會跳頁。 */}
                  <iframe key={fileShown} src={fileShown} title={name} />
                  <a
                    className="ch-preview-open"
                    href={fileShown}
                    target="_blank"
                    rel="noreferrer noopener"
                  >
                    看不到內容？在新分頁開啟
                  </a>
                </div>
              </div>
            ) : (
              <p className="ch-preview-state">
                <a href={url} target="_blank" rel="noreferrer noopener">
                  在新分頁開啟原始檔案
                </a>
              </p>
            )}
          </div>
        </div>
      </aside>
    </>
  );
}

function ViewTab({
  id,
  view,
  onView,
  children,
}: {
  id: View;
  view: View;
  onView: (view: View) => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      role="tab"
      className="tab"
      aria-selected={view === id}
      onClick={() => onView(id)}
    >
      {children}
    </button>
  );
}

/** 整份文件的文字，引用的段落螢光標示。 */
function SourceText({
  sections,
  error,
  hit,
  hitRef,
  excerpt,
  url,
}: {
  sections?: Sections;
  error?: string;
  hit: number;
  hitRef: React.RefObject<HTMLElement | null>;
  excerpt: string;
  url: string;
}) {
  if (!sections) {
    return (
      <>
        <p className="ch-preview-state">
          {error ? `讀不到原文的文字：${error}` : "讀取原文中…"}
        </p>
        {error && <Excerpt text={excerpt} url={url} />}
      </>
    );
  }
  return (
    <div className="ch-source-doc anim-in">
      {hit < 0 && (
        <>
          <p className="ch-source-note">
            原文裡找不到這段引用，文件可能在回答之後改過。下面是當時引用的內容。
          </p>
          <Excerpt text={excerpt} url={url} />
        </>
      )}
      {sections.map((section, index) => {
        const heading =
          section.location &&
          section.location !== sections[index - 1]?.location;
        const cited = index === hit;
        return (
          <section
            // 文件的片段不會重新排序，用位置當 key 就夠了。
            // biome-ignore lint/suspicious/noArrayIndexKey: 見上一行
            key={index}
            ref={cited ? hitRef : undefined}
            className={`ch-source-section${cited ? " ch-source-hit" : ""}`}
          >
            {heading && <div className="ch-source-loc">{section.location}</div>}
            {cited ? (
              <mark className="ch-source-mark">{section.text}</mark>
            ) : (
              <p>{section.text}</p>
            )}
          </section>
        );
      })}
    </div>
  );
}

function Excerpt({ text, url }: { text: string; url: string }) {
  if (!text) {
    return (
      <p className="ch-preview-state">
        <a href={url} target="_blank" rel="noreferrer noopener">
          在新分頁開啟原始檔案
        </a>
      </p>
    );
  }
  return (
    <figure className="ch-source-excerpt">
      <figcaption>引用的片段</figcaption>
      <blockquote>{text}</blockquote>
    </figure>
  );
}
