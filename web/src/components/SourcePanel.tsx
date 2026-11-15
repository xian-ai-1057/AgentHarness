/**
 * 右側面板：知識庫出處的原文（Python 版的 GET /api/knowledge/source）。
 *
 * 上方是這次引用的片段，下方是原始文件：PDF 用瀏覽器內建的檢視器開，
 * 直接跳到出處的頁碼；其他格式提供在新分頁開啟與下載。
 */

import "./chat/chat.css";
import { type KnowledgeSource, sourceUrl } from "./chat/citations.ts";
import { DownloadIcon } from "./chat/icons.tsx";
import { CloseIcon } from "./Icons.tsx";

export function SourcePanel({
  source,
  onClose,
}: {
  source: KnowledgeSource;
  onClose: () => void;
}) {
  const name = source.path.split("/").at(-1) ?? source.path;
  const url = sourceUrl(source);
  const pdf = /\.pdf$/i.test(source.path);
  const shown = source.page ? `${url}#page=${source.page}` : url;
  return (
    <aside className="panel anim-panel ch-panel" aria-label="出處">
      <div className="panel-header">
        <div className="tabs">
          <span className="tab" aria-current="true">
            出處 {source.number}
          </span>
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
          <div className="file-head ch-preview-head">
            <div className="ch-preview-title">
              <span className="ch-preview-name">{name}</span>
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
          {source.excerpt && (
            <figure className="ch-source-excerpt">
              <figcaption>引用的片段</figcaption>
              <blockquote>{source.excerpt}</blockquote>
            </figure>
          )}
          {pdf ? (
            <div className="anim-in">
              <div className="ch-preview-pdf">
                {/* 換到另一頁時重新建立：只改網址的 #page 不一定會跳頁。 */}
                <iframe key={shown} src={shown} title={name} />
                <a
                  className="ch-preview-open"
                  href={shown}
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
                在新分頁開啟原文
              </a>
            </p>
          )}
        </div>
      </div>
    </aside>
  );
}
