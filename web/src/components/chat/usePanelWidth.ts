/**
 * 右側面板（檔案面板、出處面板）共用的寬度狀態：拖曳分隔線調整過的寬度
 * 記在 localStorage，兩種面板用同一個寬度。
 *
 * 視窗變窄時，記住的寬度可能讓對話區太擠：跟著縮回可用範圍（不改記住的
 * 值，視窗再放大時回到原本的寬度）。
 */

import { type RefObject, useEffect, useState } from "react";
import { clampWidth, loadPanelWidth, savePanelWidth } from "./panelWidth.ts";

/**
 * Args:
 *   panelRef: 面板本身（aside）；用它和旁邊的對話區（.main）算可用寬度。
 *
 * Returns:
 *   shown：要顯示的寬度（null 表示用 CSS 的預設寬度）；changeWidth：
 *   拖曳或鍵盤調整時呼叫，null 回到預設寬度。
 */
export function usePanelWidth(panelRef: RefObject<HTMLElement | null>): {
  shown: number | null;
  changeWidth: (next: number | null) => void;
} {
  const [width, setWidth] = useState<number | null>(loadPanelWidth);
  const [available, setAvailable] = useState(Number.POSITIVE_INFINITY);
  useEffect(() => {
    const measure = () => {
      const panel = panelRef.current;
      const chat = panel?.parentElement?.querySelector(":scope > .main");
      if (!panel || !chat) return;
      setAvailable(
        panel.getBoundingClientRect().width +
          chat.getBoundingClientRect().width,
      );
    };
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [panelRef]);

  return {
    shown: width === null ? null : clampWidth(width, available),
    changeWidth(next) {
      setWidth(next);
      savePanelWidth(next);
    },
  };
}
