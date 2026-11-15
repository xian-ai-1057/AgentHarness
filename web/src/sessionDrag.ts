/**
 * 把對話拖到側欄的專案上（features.categories）。
 *
 * 拖曳的資料放在自訂的 MIME 類型，只有對話列會放這個類型；放置目標
 * （側欄的專案）只認這個類型，拖別的東西（檔案、文字、其他連結）經過時
 * 不會亮起來。對話列是 <a>，瀏覽器原本的連結資料（網址）保留，拖到
 * 網址列或別的分頁仍然可以打開。
 */

import type { DragEvent } from "react";

export const SESSION_DRAG_TYPE = "application/x-harness-session";

/** 對話列的 onDragStart：記下要移動的對話。 */
export function startSessionDrag(
  event: DragEvent<HTMLElement>,
  sessionId: string,
): void {
  event.dataTransfer.setData(SESSION_DRAG_TYPE, sessionId);
  event.dataTransfer.effectAllowed = "all";
  // 用整列當拖曳圖，不同瀏覽器拖連結時的預設圖不一樣。
  event.dataTransfer.setDragImage(event.currentTarget, 16, 16);
}

/**
 * 正在拖的是不是對話。dragover 時讀不到資料內容（瀏覽器的保護），
 * 只看得到類型。
 */
export function isSessionDrag(
  event: DragEvent<HTMLElement> | globalThis.DragEvent,
): boolean {
  return event.dataTransfer?.types.includes(SESSION_DRAG_TYPE) ?? false;
}

/** drop 時取出對話的識別碼；不是對話時回傳 undefined。 */
export function readSessionDrag(
  event: DragEvent<HTMLElement>,
): string | undefined {
  return event.dataTransfer.getData(SESSION_DRAG_TYPE) || undefined;
}
