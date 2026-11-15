/**
 * 預覽面板的縮放：上方的「− 100% +」、Ctrl（⌘）＋滾輪、觸控板雙指縮放，
 * 以及 Ctrl（⌘）＋「+」「−」「0」。
 *
 * 面板（FilePanel）用 usePreviewZoom 保存比例，換檔案時回到 100%。可以
 * 縮放的內容（圖片、文字、表格、Word 與 PowerPoint 的簡易預覽）用
 * useZoomTarget 登記並取得比例；有內容登記時面板才顯示縮放按鈕。PDF
 * 由瀏覽器內建的檢視器顯示，用它自己的縮放，不登記。
 */

import {
  createContext,
  type ReactNode,
  type RefObject,
  useCallback,
  useContext,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { MinusIcon, PlusIcon } from "./icons.tsx";
import {
  clampZoom,
  MAX_ZOOM,
  MIN_ZOOM,
  stepZoom,
  wheelZoom,
  zoomKey,
  zoomLabel,
} from "./zoom.ts";

type ZoomUpdate = number | ((zoom: number) => number);

export interface PreviewZoom {
  zoom: number;
  setZoom: (next: ZoomUpdate) => void;
  /** 可以縮放的內容掛上時登記，回傳取消登記的函式。 */
  register: () => () => void;
}

const ZoomContext = createContext<PreviewZoom | null>(null);
export const ZoomProvider = ZoomContext.Provider;

/**
 * 面板保存的縮放比例；key（預覽的路徑）改變時回到 100%。
 */
export function usePreviewZoom(key: string | undefined) {
  const [state, setState] = useState({ key, zoom: 1 });
  const zoom = state.key === key ? state.zoom : 1;
  const [targets, setTargets] = useState(0);
  const setZoom = useCallback(
    (next: ZoomUpdate) => {
      setState((prev) => {
        const current = prev.key === key ? prev.zoom : 1;
        const value = clampZoom(
          typeof next === "function" ? next(current) : next,
        );
        return value === current && prev.key === key
          ? prev
          : { key, zoom: value };
      });
    },
    [key],
  );
  const register = useCallback(() => {
    setTargets((count) => count + 1);
    return () => setTargets((count) => count - 1);
  }, []);
  const value = useMemo<PreviewZoom>(
    () => ({ zoom, setZoom, register }),
    [zoom, setZoom, register],
  );
  return { value, available: targets > 0 };
}

/**
 * 可以縮放的內容呼叫：登記自己，回傳目前的比例。不在預覽面板裡
 * （沒有 ZoomProvider）或 enabled 為 false 時固定是 1。
 */
export function useZoomTarget(enabled = true): number {
  const context = useContext(ZoomContext);
  const register = context?.register;
  useEffect(() => {
    if (!register || !enabled) return;
    return register();
  }, [register, enabled]);
  return context && enabled ? context.zoom : 1;
}

/** 在 iframe 裡的內容（Word、PowerPoint）自己接手滾輪與按鍵時使用。 */
export function useZoomContext(): PreviewZoom | null {
  return useContext(ZoomContext);
}

const MOD = /Mac|iPhone|iPad/.test(globalThis.navigator?.platform ?? "")
  ? "⌘"
  : "Ctrl";

export function ZoomControls({
  zoom,
  setZoom,
}: {
  zoom: number;
  setZoom: (next: ZoomUpdate) => void;
}) {
  const label = zoomLabel(zoom);
  return (
    <fieldset className="ch-zoom" aria-label="縮放">
      <button
        type="button"
        className="ch-zoom-btn"
        aria-label="縮小"
        title={`縮小（${MOD} −）`}
        disabled={zoom <= MIN_ZOOM}
        onClick={() => setZoom((value) => stepZoom(value, -1))}
      >
        <MinusIcon size={14} />
      </button>
      <button
        type="button"
        className="ch-zoom-value"
        aria-label={`目前 ${label}，回到 100%`}
        title={`回到 100%（${MOD} 0）`}
        onClick={() => setZoom(1)}
      >
        {label}
      </button>
      <button
        type="button"
        className="ch-zoom-btn"
        aria-label="放大"
        title={`放大（${MOD} +）`}
        disabled={zoom >= MAX_ZOOM}
        onClick={() => setZoom((value) => stepZoom(value, 1))}
      >
        <PlusIcon size={14} />
      </button>
    </fieldset>
  );
}

/** 縮放前游標的位置，縮放後捲動畫面讓同一個地方留在游標下。 */
interface Anchor {
  x: number;
  y: number;
  left: number;
  top: number;
  from: number;
}

/**
 * 在 target（面板的捲動區或 iframe 的文件）上接手 Ctrl（⌘）＋滾輪、
 * Safari 的雙指縮放手勢，以及 Ctrl（⌘）＋「+」「−」「0」，不讓瀏覽器
 * 縮放整個網頁。回傳取消的函式。
 */
export function listenZoom(
  target: EventTarget,
  getZoom: () => number,
  setZoom: (next: ZoomUpdate) => void,
  onWheelAnchor?: (event: WheelEvent) => void,
): () => void {
  let gesture: number | undefined;
  const onWheel = (event: Event) => {
    const wheel = event as WheelEvent;
    if (!(wheel.ctrlKey || wheel.metaKey)) return;
    event.preventDefault();
    if (gesture !== undefined) return;
    const next = wheelZoom(getZoom(), wheel.deltaY, wheel.deltaMode);
    if (next === getZoom()) return;
    onWheelAnchor?.(wheel);
    setZoom(next);
  };
  const onKey = (event: Event) => {
    const action = zoomKey(event as KeyboardEvent);
    if (!action) return;
    event.preventDefault();
    setZoom((zoom) =>
      action === "reset" ? 1 : stepZoom(zoom, action === "in" ? 1 : -1),
    );
  };
  // Safari 的觸控板雙指縮放不是 wheel，是 gesture 事件。
  const onGestureStart = (event: Event) => {
    event.preventDefault();
    gesture = getZoom();
  };
  const onGestureChange = (event: Event) => {
    event.preventDefault();
    const scale = (event as Event & { scale?: number }).scale;
    if (gesture !== undefined && typeof scale === "number") {
      setZoom(gesture * scale);
    }
  };
  const onGestureEnd = (event: Event) => {
    event.preventDefault();
    gesture = undefined;
  };
  const options = { passive: false } as const;
  target.addEventListener("wheel", onWheel, options);
  target.addEventListener("keydown", onKey);
  target.addEventListener("gesturestart", onGestureStart, options);
  target.addEventListener("gesturechange", onGestureChange, options);
  target.addEventListener("gestureend", onGestureEnd, options);
  return () => {
    target.removeEventListener("wheel", onWheel);
    target.removeEventListener("keydown", onKey);
    target.removeEventListener("gesturestart", onGestureStart);
    target.removeEventListener("gesturechange", onGestureChange);
    target.removeEventListener("gestureend", onGestureEnd);
  };
}

/**
 * 面板捲動區的縮放手勢。Ctrl（⌘）＋滾輪縮放時，游標下的內容留在原地。
 */
export function useZoomGestures(
  ref: RefObject<HTMLElement | null>,
  zoom: PreviewZoom,
  enabled: boolean,
) {
  const zoomRef = useRef(zoom.zoom);
  zoomRef.current = zoom.zoom;
  const anchorRef = useRef<Anchor | null>(null);
  const { setZoom } = zoom;

  useEffect(() => {
    const element = ref.current;
    if (!element || !enabled) return;
    return listenZoom(
      element,
      () => zoomRef.current,
      setZoom,
      (event) => {
        const target = element.querySelector("[data-zoom-target]");
        if (!target) return;
        const rect = target.getBoundingClientRect();
        anchorRef.current = {
          x: event.clientX,
          y: event.clientY,
          left: rect.left,
          top: rect.top,
          from: zoomRef.current,
        };
      },
    );
  }, [ref, enabled, setZoom]);

  useLayoutEffect(() => {
    const anchor = anchorRef.current;
    anchorRef.current = null;
    const element = ref.current;
    if (!anchor || !element || anchor.from === zoom.zoom) return;
    const target = element.querySelector<HTMLElement>("[data-zoom-target]");
    if (!target) return;
    const ratio = zoom.zoom / anchor.from;
    const rect = target.getBoundingClientRect();
    const wantLeft = anchor.x - (anchor.x - anchor.left) * ratio;
    const wantTop = anchor.y - (anchor.y - anchor.top) * ratio;
    scrollAxis(target, element, "x", rect.left - wantLeft);
    scrollAxis(target, element, "y", rect.top - wantTop);
  }, [ref, zoom.zoom]);
}

/** 從 target 往外找第一個能在這個方向捲動的元素，捲動 delta。 */
function scrollAxis(
  target: HTMLElement,
  root: HTMLElement,
  axis: "x" | "y",
  delta: number,
) {
  if (Math.abs(delta) < 0.5) return;
  let node: HTMLElement | null = target.parentElement;
  while (node) {
    const scrollable =
      axis === "x"
        ? node.scrollWidth > node.clientWidth
        : node.scrollHeight > node.clientHeight;
    if (scrollable) {
      if (axis === "x") node.scrollLeft += delta;
      else node.scrollTop += delta;
      return;
    }
    if (node === root) return;
    node = node.parentElement;
  }
}

/**
 * 放大後可以按住拖曳來移動畫面（像看地圖）。只在內容超出時有作用。
 */
export function useDragPan(ref: RefObject<HTMLElement | null>) {
  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    let start: { x: number; y: number; left: number; top: number } | null =
      null;
    const overflow = () =>
      element.scrollWidth > element.clientWidth ||
      element.scrollHeight > element.clientHeight;
    const onDown = (event: PointerEvent) => {
      if (event.button !== 0 || event.pointerType === "touch" || !overflow()) {
        return;
      }
      start = {
        x: event.clientX,
        y: event.clientY,
        left: element.scrollLeft,
        top: element.scrollTop,
      };
      element.setPointerCapture(event.pointerId);
      element.dataset.dragging = "true";
      event.preventDefault();
    };
    const onMove = (event: PointerEvent) => {
      if (!start) return;
      element.scrollLeft = start.left - (event.clientX - start.x);
      element.scrollTop = start.top - (event.clientY - start.y);
    };
    const onUp = (event: PointerEvent) => {
      if (!start) return;
      start = null;
      delete element.dataset.dragging;
      if (element.hasPointerCapture(event.pointerId)) {
        element.releasePointerCapture(event.pointerId);
      }
    };
    element.addEventListener("pointerdown", onDown);
    element.addEventListener("pointermove", onMove);
    element.addEventListener("pointerup", onUp);
    element.addEventListener("pointercancel", onUp);
    return () => {
      element.removeEventListener("pointerdown", onDown);
      element.removeEventListener("pointermove", onMove);
      element.removeEventListener("pointerup", onUp);
      element.removeEventListener("pointercancel", onUp);
    };
  }, [ref]);
}

/**
 * 用 CSS zoom 縮放裡面的內容（文字、Markdown、表格）。文字放大後依面板
 * 寬度重新換行，和瀏覽器的縮放一樣。
 */
export function Zoomed({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  const zoom = useZoomTarget();
  return (
    <div
      data-zoom-target=""
      className={className}
      style={zoom === 1 ? undefined : { zoom }}
    >
      {children}
    </div>
  );
}
