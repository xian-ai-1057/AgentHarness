/**
 * 顯示 agent 的回覆。react-markdown 預設不會執行內容裡的 HTML，
 * 模型或工具輸出的文字不會變成可以執行的程式。
 *
 * 程式碼區塊會上色並加上「複製」按鈕；$$…$$ 用 KaTeX 排版。
 * 單一個 $ 只有內容看起來是 LaTeX（$\rightarrow$、$x^2$）才算數學式：
 * 回覆裡常有 NT$1,000 到 NT$2,000 這種金額，兩個 $ 之間的文字不能被
 * 當成數學式（見 chat/math.ts）。粗體旁邊是中文標點（**「重點」**）
 * 也要能顯示成粗體（見 chat/remark.ts）。
 *
 * KaTeX 與上色的程式比較大，內容裡真的有 $$ 或程式碼區塊時才載入。
 * 還在串流的回覆每來一段字就重畫一次，所以先不排版、不上色，等回覆
 * 完成後再做一次。
 *
 * localFiles 為 true 時（伺服器支援 /api/files），圖片的 src 是相對路徑
 * （或沙盒裡的 /workspace/...）就從這段對話的工作資料夾讀取。
 *
 * 外部網站的圖片不載入（index.html 的 CSP 也會擋），改顯示成連結
 * 「外部圖片：主機名稱」，被誘導的回覆就不能藉圖片網址把資料送出去。
 *
 * 有 citations 時（這一輪搜尋過知識庫），文字裡的 [編號] 變成出處標籤：
 * 對得到搜尋結果的可以點，點了打開原文；對不到的標成「找不到出處」
 * （見 chat/citations.ts）。程式碼與連結裡的 [編號] 不處理。
 */

import {
  createContext,
  memo,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import { fileUrl } from "../api.ts";
import "./chat/chat.css";
import { CodeBlock } from "./chat/CodeBlock.tsx";
import {
  type CitationMap,
  type KnowledgeSource,
  splitCitations,
} from "./chat/citations.ts";
import { externalImageHost, projectPath } from "./chat/filetype.ts";
import { useFolder } from "./chat/folder.ts";
import { prepareMath } from "./chat/math.ts";
import { remarkPlugins } from "./chat/remark.ts";

type Plugins = NonNullable<
  Parameters<typeof ReactMarkdown>[0]["rehypePlugins"]
>;

const CITE_PREFIX = "#cite-";

/** mdast 的節點（只用到的欄位）。 */
interface MdNode {
  type: string;
  value?: string;
  url?: string;
  children?: MdNode[];
}

// 這些節點裡的 [編號] 不是引用（程式碼、連結文字、HTML）。
const NOT_CITATION = new Set([
  "code",
  "inlineCode",
  "link",
  "linkReference",
  "definition",
  "html",
  "math",
  "inlineMath",
]);

/** 把文字裡的 [編號] 換成指向 #cite-編號 的連結，再由 CitationLink 顯示。 */
function remarkCitations() {
  const walk = (node: MdNode) => {
    if (!node.children) return;
    const children: MdNode[] = [];
    for (const child of node.children) {
      if (child.type === "text" && child.value) {
        for (const part of splitCitations(child.value)) {
          if (typeof part === "string") {
            children.push({ type: "text", value: part });
            continue;
          }
          for (const number of part) {
            children.push({
              type: "link",
              url: `${CITE_PREFIX}${number}`,
              children: [{ type: "text", value: String(number) }],
            });
          }
        }
        continue;
      }
      if (!NOT_CITATION.has(child.type)) walk(child);
      children.push(child);
    }
    node.children = children;
  };
  return (tree: MdNode) => walk(tree);
}

const citationPlugins = [...remarkPlugins, remarkCitations] as NonNullable<
  Parameters<typeof ReactMarkdown>[0]["remarkPlugins"]
>;

interface CitationState {
  citations: CitationMap;
  /** 點了出處；沒有時出處不能點（例如伺服器不提供原文）。 */
  onOpen?: (source: KnowledgeSource) => void;
}

const CitationContext = createContext<CitationState | undefined>(undefined);

/** 回覆裡的一個 [編號]。 */
function CitationLink({ number }: { number: number }) {
  const state = useContext(CitationContext);
  const source = state?.citations.get(number);
  if (!source) {
    return (
      <span
        className="ch-cite ch-cite-missing"
        title={`這一輪搜尋到的資料裡沒有第 ${number} 筆，這個引用可能不正確，請自行查證`}
      >
        {number}?
      </span>
    );
  }
  const onOpen = state?.onOpen;
  if (!onOpen) {
    return (
      <span className="ch-cite" title={source.citation}>
        {number}
      </span>
    );
  }
  return (
    <button
      type="button"
      className="ch-cite"
      title={`打開原文：${source.citation}`}
      aria-label={`出處 ${number}：${source.citation}`}
      onClick={() => onOpen(source)}
    >
      {number}
    </button>
  );
}

const MATH = /\$\$/;
// 縮排在清單或引用（>）底下的程式碼區塊也要算進去。
const FENCE = /^[ \t>]*(`{3,}|~{3,})/m;

// 載入過就留著，之後的訊息直接用。
let katexPlugin: Plugins[number] | undefined;
let highlightPlugin: Plugins[number] | undefined;
let mathLoading: Promise<void> | undefined;
let highlightLoading: Promise<void> | undefined;

function loadMath(): Promise<void> {
  mathLoading ??= Promise.all([
    import("rehype-katex"),
    import("katex/dist/katex.min.css"),
  ]).then(([module]) => {
    // 打錯的數學式用警告色顯示原文，不用紅色。
    katexPlugin = [
      module.default,
      { throwOnError: false, errorColor: "var(--warn-ink)" },
    ];
  });
  return mathLoading;
}

function loadHighlight(): Promise<void> {
  highlightLoading ??= import("rehype-highlight").then((module) => {
    highlightPlugin = module.default;
  });
  return highlightLoading;
}

/** 這段文字需要的 rehype 外掛；還沒載入的先載入，好了再重畫。 */
function useRehypePlugins(text: string, streaming: boolean): Plugins {
  const wantMath = !streaming && MATH.test(text);
  const wantCode = !streaming && FENCE.test(text);
  const [, setLoaded] = useState(0);

  useEffect(() => {
    const loads: Promise<void>[] = [];
    if (wantMath && !katexPlugin) loads.push(loadMath());
    if (wantCode && !highlightPlugin) loads.push(loadHighlight());
    if (loads.length === 0) return;
    let alive = true;
    Promise.all(loads).then(
      () => alive && setLoaded((count) => count + 1),
      () => undefined,
    );
    return () => {
      alive = false;
    };
  }, [wantMath, wantCode]);

  const math = wantMath ? katexPlugin : undefined;
  const code = wantCode ? highlightPlugin : undefined;
  return useMemo(() => {
    // KaTeX 要排在上色前面，數學式才不會被當成程式碼。
    const plugins: Plugins = [];
    if (math) plugins.push(math);
    if (code) plugins.push(code);
    return plugins;
  }, [math, code]);
}

/** 外部網站的圖片：顯示成連結，不載入。 */
function ExternalImage({
  src,
  host,
  alt,
}: {
  src: string;
  host: string;
  alt?: string;
}) {
  return (
    <a
      href={src}
      target="_blank"
      rel="noreferrer noopener"
      className="ch-ext-img"
      title={alt || src}
    >
      外部圖片：{host}
    </a>
  );
}

/** 一般的圖片：外部網址改成連結，其他照原樣顯示。 */
function PlainImage({
  src,
  alt,
  title,
}: {
  src?: string | Blob;
  alt?: string;
  title?: string;
}) {
  const host = typeof src === "string" ? externalImageHost(src) : undefined;
  if (host && typeof src === "string") {
    return <ExternalImage src={src} host={host} alt={alt} />;
  }
  return (
    <img
      src={src as string | undefined}
      alt={alt ?? ""}
      title={title}
      loading="lazy"
    />
  );
}

const components: Components = {
  a: ({ href, children }) =>
    href?.startsWith(CITE_PREFIX) ? (
      <CitationLink number={Number(href.slice(CITE_PREFIX.length))} />
    ) : (
      <a href={href} target="_blank" rel="noreferrer noopener">
        {children}
      </a>
    ),
  img: ({ src, alt, title }) => (
    <PlainImage src={src} alt={alt} title={title} />
  ),
  pre: ({ node, children }) => (
    <CodeBlock node={node as Parameters<typeof CodeBlock>[0]["node"]}>
      {children}
    </CodeBlock>
  ),
};

/** 圖片的 src 指向工作資料夾裡的檔案時，改從 /api/files 讀取。 */
function LocalImage({
  src,
  alt,
  title,
}: {
  src?: string | Blob;
  alt?: string;
  title?: string;
}) {
  const folder = useFolder();
  // 有工作資料夾時，沙盒的 /workspace 就是這個資料夾。
  const path =
    typeof src === "string"
      ? projectPath(src, folder !== undefined)
      : undefined;
  if (!path) return <PlainImage src={src} alt={alt} title={title} />;
  return (
    <img
      src={fileUrl(path, false, folder)}
      alt={alt ?? ""}
      title={title}
      loading="lazy"
    />
  );
}

const localComponents: Components = {
  ...components,
  img: ({ src, alt, title }) => (
    <LocalImage src={src} alt={alt} title={title} />
  ),
};

export const Markdown = memo(function Markdown({
  text,
  streaming = false,
  localFiles = false,
  citations,
  onOpenCitation,
}: {
  text: string;
  streaming?: boolean;
  /** 伺服器可以讀取工作資料夾的檔案（features.files）。 */
  localFiles?: boolean;
  /** 這段文字可以引用的知識庫出處；沒有時 [編號] 照原樣顯示。 */
  citations?: CitationMap;
  /** 點了出處（打開原文）。 */
  onOpenCitation?: (source: KnowledgeSource) => void;
}) {
  const source = useMemo(
    () => (streaming ? text : prepareMath(text)),
    [text, streaming],
  );
  const rehypePlugins = useRehypePlugins(source, streaming);
  const state = useMemo(
    () => (citations ? { citations, onOpen: onOpenCitation } : undefined),
    [citations, onOpenCitation],
  );
  return (
    <div className="md">
      <CitationContext.Provider value={state}>
        <ReactMarkdown
          remarkPlugins={state ? citationPlugins : remarkPlugins}
          rehypePlugins={rehypePlugins}
          components={localFiles ? localComponents : components}
        >
          {source}
        </ReactMarkdown>
      </CitationContext.Provider>
      {streaming && (
        <span className="caret" aria-hidden="true">
          ▍
        </span>
      )}
    </div>
  );
});

/**
 * 把一段文字包成 Markdown 的程式碼區塊。圍欄比內容裡最長的反引號
 * 還長一個，內容才不會提早結束區塊。
 */
export function fenced(text: string, language: string): string {
  const longest = Math.max(
    2,
    ...[...text.matchAll(/`+/g)].map((match) => match[0].length),
  );
  const fence = "`".repeat(longest + 1);
  return `${fence}${language}\n${text.replace(/\n$/, "")}\n${fence}`;
}
