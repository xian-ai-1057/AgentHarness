/**
 * 用 PDF.js 在出處面板裡畫出 PDF，跳到引用的那一頁，把引用的段落用
 * 螢光標示在 PDF 上並閃一下。
 *
 * 瀏覽器內建的 PDF 檢視器（iframe）沒辦法從外面標示文字，所以這裡自己
 * 畫：每一頁畫成 canvas，捲到附近才畫；標示是蓋在 canvas 上的半透明
 * 方塊，位置由 PDF.js 讀出的文字段落算出來（見 pdfHighlight.ts）。
 *
 * 掃描的 PDF 沒有文字，找不到引用時只跳到出處的頁碼並說明原因。
 */

import type { PDFDocumentProxy, PDFPageProxy, RenderTask } from "pdfjs-dist";
import type { TextItem } from "pdfjs-dist/types/src/display/api";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import {
  type ItemMark,
  matchFrom,
  normalizeForMatch,
  type PageText,
  pageText,
  startPage,
} from "./pdfHighlight.ts";

/** cmaps 與標準字型的位置（打包時由 vite.config.ts 的 pdfjsAssets 複製）。 */
const PDFJS_ASSETS = "/pdfjs/";
/** 沒有頁碼或頁碼對不到時，頁數不超過這麼多才逐頁找引用。 */
const SEARCH_ALL_PAGES = 400;
/** 頁與頁、頁與面板邊緣的間距（px）。 */
const GAP = 12;
const ZOOMS = [0.5, 0.67, 0.8, 1, 1.25, 1.5, 2, 3];

type PdfJs = typeof import("pdfjs-dist");
let pdfjsLoading: Promise<PdfJs> | undefined;

/** 第一次用到時才載入 PDF.js（約 400KB，worker 另外載入）。 */
function loadPdfJs(): Promise<PdfJs> {
  pdfjsLoading ??= Promise.all([
    import("pdfjs-dist"),
    import("pdfjs-dist/build/pdf.worker.min.mjs?url"),
  ]).then(([pdfjs, worker]) => {
    pdfjs.GlobalWorkerOptions.workerSrc = worker.default;
    return pdfjs;
  });
  return pdfjsLoading;
}

/** 一頁在縮放 1 倍時的大小。 */
interface Size {
  width: number;
  height: number;
}

/** 螢光方塊，單位是縮放 1 倍時的 px。 */
interface Rect {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** 一頁的文字與每段文字的位置。 */
interface PageInfo {
  text: PageText;
  items: { transform: number[]; width: number }[];
  /** 縮放 1 倍時的座標轉換。 */
  transform: number[];
}

interface Loaded {
  url: string;
  pdf?: PDFDocumentProxy;
  sizes?: Size[];
  error?: string;
}

interface Highlight {
  /** 每次點引用都不同，用來讓方塊重新出現、再閃一次。 */
  key: object;
  /** 要捲到的頁（從 1 開始）。 */
  page: number;
  /** 頁碼 → 那一頁的螢光方塊。 */
  rects: Map<number, Rect[]>;
  /** 在 PDF 上找不到引用時的說明。 */
  note?: string;
}

export function PdfViewer({
  url,
  page,
  excerpt,
  trigger,
}: {
  url: string;
  /** 出處的頁碼（從 1 開始）。 */
  page?: number;
  /** 引用的片段。 */
  excerpt: string;
  /** 每次點引用都是新的物件，用來再捲動、閃一次。 */
  trigger: object;
}) {
  const [loaded, setLoaded] = useState<Loaded>();
  const [highlight, setHighlight] = useState<Highlight>();
  const [zoom, setZoom] = useState(1);
  const [width, setWidth] = useState(0);
  const boxRef = useRef<HTMLDivElement>(null);
  const infos = useRef(new Map<number, Promise<PageInfo>>());

  // 讀取 PDF 與每一頁的大小；同一份檔案換引用時不重新讀取。
  useEffect(() => {
    let cancelled = false;
    let task: { destroy: () => Promise<void> } | undefined;
    infos.current = new Map();
    setLoaded({ url });
    loadPdfJs()
      .then(async (pdfjs) => {
        const loading = pdfjs.getDocument({
          url,
          cMapUrl: `${PDFJS_ASSETS}cmaps/`,
          cMapPacked: true,
          standardFontDataUrl: `${PDFJS_ASSETS}standard_fonts/`,
          // 不用 eval 產生字型的繪圖程式（安全性；稍慢一點）。
          isEvalSupported: false,
        });
        task = loading;
        const pdf = await loading.promise;
        const sizes = await Promise.all(
          Array.from({ length: pdf.numPages }, async (_, index) => {
            const viewport = (await pdf.getPage(index + 1)).getViewport({
              scale: 1,
            });
            return { width: viewport.width, height: viewport.height };
          }),
        );
        if (!cancelled) setLoaded({ url, pdf, sizes });
      })
      .catch((error: Error) => {
        if (!cancelled) setLoaded({ url, error: error.message });
      });
    return () => {
      cancelled = true;
      void task?.destroy();
    };
  }, [url]);
  const pdf = loaded?.url === url ? loaded.pdf : undefined;
  const sizes = loaded?.url === url ? loaded.sizes : undefined;

  // 面板寬度改變（拖曳分隔線）時重新計算縮放。
  useEffect(() => {
    // 量捲動區的寬度：PDF 本身放大後會比面板寬，量它會越放越大。
    const box = boxRef.current?.closest(".scroll") ?? boxRef.current;
    if (!box) return;
    let timer: number | undefined;
    const observer = new ResizeObserver(() => {
      window.clearTimeout(timer);
      // 拖曳時不要每一格都重畫。
      timer = window.setTimeout(() => setWidth(box.clientWidth), 120);
    });
    observer.observe(box);
    setWidth(box.clientWidth);
    return () => {
      observer.disconnect();
      window.clearTimeout(timer);
    };
  }, []);
  const widest = sizes ? Math.max(...sizes.map((size) => size.width)) : 0;
  const fit = widest && width ? Math.max(0.2, (width - GAP * 2) / widest) : 0;
  const scale = fit * zoom;

  // 找出引用在哪幾頁、算出螢光方塊。
  useEffect(() => {
    if (!pdf) return;
    let cancelled = false;
    const info = (number: number) => {
      let found = infos.current.get(number);
      if (!found) {
        found = readPage(pdf, number);
        infos.current.set(number, found);
      }
      return found;
    };
    locate(pdf, info, normalizeForMatch(excerpt), page).then(
      (found) => {
        if (!cancelled) setHighlight({ key: trigger, ...found });
      },
      () => {
        if (!cancelled) {
          setHighlight({
            key: trigger,
            page: page ?? 1,
            rects: new Map(),
            note: "讀不到這份 PDF 的文字，沒辦法標示引用的段落。",
          });
        }
      },
    );
    return () => {
      cancelled = true;
    };
  }, [pdf, excerpt, page, trigger]);
  const shown = highlight?.key === trigger ? highlight : undefined;

  // 標示好、或縮放改變後，把引用的段落捲到面板中間。
  const scrolled = useRef<object>(undefined);
  useEffect(() => {
    const box = boxRef.current;
    if (!box || !shown || !scale) return;
    if (scrolled.current === shown.key) return;
    scrolled.current = shown.key;
    const target =
      box.querySelector<HTMLElement>(".ch-pdf-mark") ??
      box.querySelector<HTMLElement>(`[data-page="${shown.page}"]`);
    target?.scrollIntoView({
      block: target.classList.contains("ch-pdf-mark") ? "center" : "start",
    });
  }, [shown, scale]);

  // 縮放時保持看到的位置：記住畫面中心佔全長的比例，縮放後再捲回去。
  const keep = useRef<{ top: number; left: number }>(undefined);
  const changeZoom = (next: number) => {
    const scroller = boxRef.current?.closest(".scroll");
    if (scroller) {
      keep.current = {
        top:
          (scroller.scrollTop + scroller.clientHeight / 2) /
          scroller.scrollHeight,
        left:
          (scroller.scrollLeft + scroller.clientWidth / 2) /
          scroller.scrollWidth,
      };
    }
    setZoom(next);
  };
  // biome-ignore lint/correctness/useExhaustiveDependencies: 縮放改變、頁面大小更新後才捲回去
  useLayoutEffect(() => {
    const scroller = boxRef.current?.closest(".scroll");
    const position = keep.current;
    if (!scroller || !position) return;
    keep.current = undefined;
    scroller.scrollTop =
      position.top * scroller.scrollHeight - scroller.clientHeight / 2;
    scroller.scrollLeft =
      position.left * scroller.scrollWidth - scroller.clientWidth / 2;
  }, [scale]);

  if (loaded?.error) {
    return (
      <div className="ch-pdf-state">
        <p>沒辦法在這裡顯示這份 PDF：{loaded.error}</p>
        <a
          href={page ? `${url}#page=${page}` : url}
          target="_blank"
          rel="noreferrer noopener"
        >
          在新分頁開啟原始檔案
        </a>
      </div>
    );
  }

  return (
    <div className="ch-pdf anim-in" ref={boxRef}>
      {!sizes || !pdf || !scale ? (
        <p className="ch-preview-state">讀取 PDF 中…</p>
      ) : (
        sizes.map((size, index) => {
          const number = index + 1;
          return (
            <PdfPage
              key={number}
              pdf={pdf}
              number={number}
              size={size}
              scale={scale}
              rects={shown?.rects.get(number)}
              flash={shown?.key}
              note={number === shown?.page ? shown.note : undefined}
            />
          );
        })
      )}
      {sizes && (
        <div className="ch-pdf-tools">
          <span className="ch-pdf-pages">共 {sizes.length} 頁</span>
          <button
            type="button"
            className="icon-btn"
            aria-label="縮小"
            disabled={zoom <= (ZOOMS[0] ?? 0)}
            onClick={() => changeZoom(nextZoom(zoom, -1))}
          >
            −
          </button>
          <button
            type="button"
            className="ch-pdf-zoom"
            aria-label="符合寬度"
            title="符合寬度"
            onClick={() => changeZoom(1)}
          >
            {Math.round(zoom * 100)}%
          </button>
          <button
            type="button"
            className="icon-btn"
            aria-label="放大"
            disabled={zoom >= (ZOOMS.at(-1) ?? 0)}
            onClick={() => changeZoom(nextZoom(zoom, 1))}
          >
            +
          </button>
        </div>
      )}
    </div>
  );
}

function nextZoom(zoom: number, direction: 1 | -1): number {
  const next =
    direction > 0
      ? ZOOMS.find((value) => value > zoom + 0.001)
      : ZOOMS.findLast((value) => value < zoom - 0.001);
  return next ?? zoom;
}

/** 讀出一頁的文字與每段文字的位置。 */
async function readPage(
  pdf: PDFDocumentProxy,
  number: number,
): Promise<PageInfo> {
  const page = await pdf.getPage(number);
  const content = await page.getTextContent();
  const items = content.items.filter((item): item is TextItem => "str" in item);
  return {
    text: pageText(items.map((item) => item.str)),
    items: items.map((item) => ({
      transform: item.transform as number[],
      width: item.width,
    })),
    transform: page.getViewport({ scale: 1 }).transform,
  };
}

/** 找出引用從哪一頁開始，並算出每一頁的螢光方塊。 */
async function locate(
  pdf: PDFDocumentProxy,
  info: (number: number) => Promise<PageInfo>,
  excerpt: string,
  page: number | undefined,
): Promise<Omit<Highlight, "key">> {
  const total = pdf.numPages;
  const cited = page && page >= 1 && page <= total ? page : undefined;
  const pages: (PageText | undefined)[] = new Array(total).fill(undefined);
  const read = async (from: number, to: number) => {
    const numbers = [];
    for (let number = from; number <= Math.min(to, total); number++) {
      numbers.push(number);
    }
    for (const [index, found] of (
      await Promise.all(numbers.map(info))
    ).entries()) {
      pages[(numbers[index] ?? 1) - 1] = found.text;
    }
  };

  let start: number | undefined;
  if (cited) {
    await read(cited, cited);
    start = startPage(pages, excerpt, cited);
  }
  if (start === undefined && total <= SEARCH_ALL_PAGES) {
    await read(1, total);
    start = startPage(pages, excerpt, cited);
  }
  if (start === undefined) {
    return {
      page: cited ?? 1,
      rects: new Map(),
      note: excerpt
        ? `這份 PDF 上找不到引用的文字（可能是掃描檔，或文字的順序不同）${cited ? `，已開在第 ${cited} 頁` : ""}。可以到「解析文字」看標示的段落。`
        : undefined,
    };
  }
  // 引用可能跨頁：再讀後面幾頁。
  await read(start, start + 3);
  const { Util } = await loadPdfJs();
  const rects = new Map<number, Rect[]>();
  for (const [number, marks] of matchFrom(pages, excerpt, start)) {
    rects.set(number, toRects(await info(number), marks, Util.transform));
  }
  return { page: start, rects };
}

/** 文字段落要標示的比例 → 縮放 1 倍時的方塊。 */
function toRects(
  page: PageInfo,
  marks: ItemMark[],
  transform: (a: number[], b: number[]) => number[],
): Rect[] {
  const rects: Rect[] = [];
  for (const mark of marks) {
    const item = page.items[mark.item];
    if (!item) continue;
    const matrix = transform(page.transform, item.transform);
    const height = Math.hypot(matrix[2] ?? 0, matrix[3] ?? 0);
    const left = matrix[4] ?? 0;
    const baseline = matrix[5] ?? 0;
    rects.push({
      x: left + item.width * mark.from - 1,
      y: baseline - height * 0.95,
      width: item.width * (mark.to - mark.from) + 2,
      height: height * 1.25,
    });
  }
  return rects;
}

/** 一頁：捲到附近才畫；縮放改變時重畫。 */
function PdfPage({
  pdf,
  number,
  size,
  scale,
  rects,
  flash,
  note,
}: {
  pdf: PDFDocumentProxy;
  number: number;
  size: Size;
  scale: number;
  rects?: Rect[];
  flash?: object;
  /** 在 PDF 上找不到引用時的說明，顯示在這一頁上方。 */
  note?: string;
}) {
  const pageRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [near, setNear] = useState(false);
  const width = Math.floor(size.width * scale);
  const height = Math.floor(size.height * scale);

  useEffect(() => {
    const element = pageRef.current;
    if (!element) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) setNear(true);
      },
      // 提早一點畫，捲動時比較不會看到空白。
      { rootMargin: "800px 0px" },
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!near || !canvas) return;
    let cancelled = false;
    let task: RenderTask | undefined;
    pdf.getPage(number).then((page: PDFPageProxy) => {
      if (cancelled) return;
      const viewport = page.getViewport({ scale });
      // 依螢幕的像素密度畫，避免在 Retina 螢幕上模糊；太大時降低解析度。
      const ratio = Math.min(
        window.devicePixelRatio || 1,
        Math.sqrt(16_000_000 / (viewport.width * viewport.height)),
      );
      canvas.width = Math.floor(viewport.width * ratio);
      canvas.height = Math.floor(viewport.height * ratio);
      const context = canvas.getContext("2d");
      if (!context) return;
      task = page.render({
        canvasContext: context,
        viewport,
        transform: ratio === 1 ? undefined : [ratio, 0, 0, ratio, 0, 0],
      });
      task.promise.catch(() => {
        // 換頁、縮放時取消重畫，不是錯誤。
      });
    });
    return () => {
      cancelled = true;
      task?.cancel();
    };
  }, [pdf, number, scale, near]);

  const marks = useMemo(
    () =>
      (rects ?? []).map((rect) => ({
        left: rect.x * scale,
        top: rect.y * scale,
        width: rect.width * scale,
        height: rect.height * scale,
      })),
    [rects, scale],
  );
  // 換引用時讓方塊重新出現，動畫才會再跑一次。
  const flashKey = flashKeyOf(flash);

  return (
    <div
      ref={pageRef}
      className="ch-pdf-page"
      data-page={number}
      style={{ width, height }}
    >
      <canvas
        ref={canvasRef}
        style={{ width, height }}
        role="img"
        aria-label={`第 ${number} 頁`}
      />
      {marks.map((style, index) => (
        <span
          // 方塊不會重新排序；flashKey 改變時全部重建以重播動畫。
          // biome-ignore lint/suspicious/noArrayIndexKey: 見上一行
          key={`${flashKey}-${index}`}
          className="ch-pdf-mark"
          style={style}
        />
      ))}
      {note && <p className="ch-pdf-note">{note}</p>}
    </div>
  );
}

/** 每個不同的物件給一個數字，當 React key 用。 */
const flashKeys = new WeakMap<object, number>();
let lastFlashKey = 0;
function flashKeyOf(flash?: object): number {
  if (!flash) return 0;
  let key = flashKeys.get(flash);
  if (key === undefined) {
    key = ++lastFlashKey;
    flashKeys.set(flash, key);
  }
  return key;
}
