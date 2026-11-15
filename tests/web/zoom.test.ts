/** 預覽面板的縮放比例：按鈕的級距、滾輪、快捷鍵。 */

import { describe, expect, it } from "vitest";
import {
  clampZoom,
  MAX_ZOOM,
  MIN_ZOOM,
  stepZoom,
  wheelZoom,
  zoomKey,
  zoomLabel,
} from "../../web/src/components/chat/zoom.ts";

describe("stepZoom", () => {
  it("一次跳一個常用的比例", () => {
    expect(stepZoom(1, 1)).toBe(1.1);
    expect(stepZoom(1, -1)).toBe(0.9);
    expect(stepZoom(1.5, 1)).toBe(1.75);
  });

  it("停在兩個比例之間時跳到那個方向最近的一個", () => {
    expect(stepZoom(1.33, 1)).toBe(1.5);
    expect(stepZoom(1.33, -1)).toBe(1.25);
  });

  it("不超過最大與最小", () => {
    expect(stepZoom(MAX_ZOOM, 1)).toBe(MAX_ZOOM);
    expect(stepZoom(MIN_ZOOM, -1)).toBe(MIN_ZOOM);
  });
});

describe("wheelZoom", () => {
  it("往上滾放大、往下滾縮小", () => {
    expect(wheelZoom(1, -100)).toBeGreaterThan(1);
    expect(wheelZoom(1, 100)).toBeLessThan(1);
  });

  it("觸控板的小幅移動也會改變比例（不會卡在原地）", () => {
    expect(wheelZoom(1, -2)).toBeGreaterThan(1);
  });

  it("一次滾很多也只改變一點", () => {
    expect(wheelZoom(1, -10_000)).toBeCloseTo(wheelZoom(1, -60));
  });

  it("以行為單位的滾輪換算成像素", () => {
    expect(wheelZoom(1, -3, 1)).toBeCloseTo(wheelZoom(1, -48));
  });

  it("不超過最大與最小", () => {
    expect(wheelZoom(MAX_ZOOM, -100)).toBe(MAX_ZOOM);
    expect(wheelZoom(MIN_ZOOM, 100)).toBe(MIN_ZOOM);
  });
});

describe("clampZoom 與 zoomLabel", () => {
  it("不是數字時回到 100%", () => {
    expect(clampZoom(Number.NaN)).toBe(1);
  });

  it("顯示四捨五入的百分比", () => {
    expect(zoomLabel(1)).toBe("100%");
    expect(zoomLabel(1.234)).toBe("123%");
  });
});

describe("zoomKey", () => {
  const key = (k: string, mods: Partial<Record<string, boolean>> = {}) =>
    zoomKey({
      key: k,
      ctrlKey: mods.ctrl ?? false,
      metaKey: mods.meta ?? false,
      altKey: mods.alt ?? false,
    });

  it("Ctrl 或 ⌘ 加上 + − 0", () => {
    expect(key("=", { ctrl: true })).toBe("in");
    expect(key("+", { meta: true })).toBe("in");
    expect(key("-", { ctrl: true })).toBe("out");
    expect(key("0", { meta: true })).toBe("reset");
  });

  it("沒按 Ctrl、⌘ 或多按了 Alt 時不處理", () => {
    expect(key("=")).toBeUndefined();
    expect(key("-", { ctrl: true, alt: true })).toBeUndefined();
    expect(key("a", { ctrl: true })).toBeUndefined();
  });
});
