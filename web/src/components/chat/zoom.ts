/**
 * 預覽的縮放比例。1 是原本的大小（圖片、Word、PowerPoint 是符合面板
 * 寬度，文字是一般字級）。
 *
 * 按鈕一次跳一個常用的比例；Ctrl（⌘）＋滾輪與觸控板的雙指縮放連續變化。
 */

/** 按「放大」「縮小」時依序經過的比例。 */
export const ZOOM_LEVELS = [
  0.25, 0.33, 0.5, 0.67, 0.75, 0.8, 0.9, 1, 1.1, 1.25, 1.5, 1.75, 2, 2.5, 3, 4,
];
export const MIN_ZOOM = ZOOM_LEVELS[0] ?? 0.25;
export const MAX_ZOOM = ZOOM_LEVELS.at(-1) ?? 4;

/** 落在最小與最大之間；不是數字時回到 1。 */
export function clampZoom(zoom: number): number {
  if (!Number.isFinite(zoom)) return 1;
  return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, zoom));
}

/**
 * 下一個（direction 為 1）或上一個（-1）比例。滾輪縮放後停在兩個比例
 * 之間時，跳到那個方向最近的一個。
 */
export function stepZoom(zoom: number, direction: 1 | -1): number {
  const eps = 0.005;
  if (direction > 0) {
    return ZOOM_LEVELS.find((level) => level > zoom + eps) ?? MAX_ZOOM;
  }
  return ZOOM_LEVELS.findLast((level) => level < zoom - eps) ?? MIN_ZOOM;
}

/** 滾輪一次最多改變的量（以像素計）：滑鼠滾一格約 100。 */
const WHEEL_STEP = 60;
/** 越大縮放越慢。 */
const WHEEL_SCALE = 250;

/**
 * Ctrl（⌘）＋滾輪或觸控板雙指縮放（瀏覽器送出帶 ctrlKey 的 wheel）後的
 * 比例。往上滾（deltaY 為負）放大。
 *
 * deltaMode：0 是像素，1 是行，2 是頁。
 */
export function wheelZoom(zoom: number, deltaY: number, deltaMode = 0): number {
  const pixels =
    deltaMode === 1 ? deltaY * 16 : deltaMode === 2 ? deltaY * 400 : deltaY;
  const limited = Math.max(-WHEEL_STEP, Math.min(WHEEL_STEP, pixels));
  return clampZoom(zoom * Math.exp(-limited / WHEEL_SCALE));
}

/** 顯示用的百分比，例如「125%」。 */
export function zoomLabel(zoom: number): string {
  return `${Math.round(zoom * 100)}%`;
}

/**
 * Ctrl（⌘）＋「+」「−」「0」對應的動作；不是縮放的按鍵時回傳 undefined。
 */
export function zoomKey(event: {
  key: string;
  ctrlKey: boolean;
  metaKey: boolean;
  altKey: boolean;
}): "in" | "out" | "reset" | undefined {
  if (!(event.ctrlKey || event.metaKey) || event.altKey) return undefined;
  if (event.key === "=" || event.key === "+") return "in";
  if (event.key === "-" || event.key === "_") return "out";
  if (event.key === "0") return "reset";
  return undefined;
}
