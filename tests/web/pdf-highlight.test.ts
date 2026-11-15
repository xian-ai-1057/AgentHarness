import { describe, expect, it } from "vitest";
import {
  matchFrom,
  matchPage,
  normalizeForMatch,
  pageText,
  startPage,
} from "../../web/src/components/chat/pdfHighlight.ts";

const ARTICLE =
  "第五條 高風險人工智慧系統上線前，應由業務單位提出風險評估報告，經人工智慧專責主管核准後始得使用。";

describe("normalizeForMatch", () => {
  it("去掉空白並把全形轉半形", () => {
    expect(normalizeForMatch("第 ５ 條\n高風險（AI）")).toBe("第5條高風險(AI)");
  });
});

describe("pageText", () => {
  it("記住每個字來自哪一段", () => {
    const page = pageText(["第一條 總則", "本辦法"]);
    expect(page.text).toBe("第一條總則本辦法");
    expect(page.item).toEqual([0, 0, 0, 0, 0, 1, 1, 1]);
    expect(page.offset).toEqual([0, 1, 2, 4, 5, 0, 1, 2]);
    expect(page.lengths).toEqual([6, 3]);
  });
});

describe("matchPage", () => {
  it("引用在一行中間開始時只標示那一段的後半", () => {
    const page = pageText([
      "第四條 本辦法適用全行。",
      ARTICLE.slice(0, 30),
      ARTICLE.slice(30),
      "第六條 其他。",
    ]);
    const excerpt = normalizeForMatch(ARTICLE);
    const match = matchPage(page, excerpt);
    expect(match?.rest).toBe("");
    expect(match?.marks.map((mark) => mark.item)).toEqual([1, 2]);
    expect(match?.marks[0]?.from).toBe(0);
    expect(match?.marks[1]?.to).toBe(1);
  });

  it("只標示引用的部分，不包含前後的條文", () => {
    const page = pageText([`第四條 本辦法適用全行。${ARTICLE}第六條 其他。`]);
    const match = matchPage(page, normalizeForMatch(ARTICLE));
    const mark = match?.marks[0];
    const line = `第四條 本辦法適用全行。${ARTICLE}第六條 其他。`;
    expect(mark?.from).toBeCloseTo(line.indexOf("第五條") / line.length);
    expect(mark?.to).toBeCloseTo(line.indexOf("第六條") / line.length);
  });

  it("片段後半在下一頁時回傳還沒對到的部分", () => {
    const page = pageText(["第四條 其他。", ARTICLE.slice(0, 25)]);
    const match = matchPage(page, normalizeForMatch(ARTICLE));
    expect(match?.marks.map((mark) => mark.item)).toEqual([1]);
    expect(match?.rest).toBe(normalizeForMatch(ARTICLE.slice(25)));
  });

  it("跨頁時剛好切在哪個字都接得上", () => {
    const excerpt = normalizeForMatch(ARTICLE);
    for (let cut = 18; cut < excerpt.length - 20; cut++) {
      const first = matchPage(
        pageText(["頁首", excerpt.slice(0, cut)]),
        excerpt,
      );
      expect(first?.rest).toBe(excerpt.slice(cut));
      const second = matchPage(
        pageText([excerpt.slice(cut), "第六條 其他。"]),
        first?.rest ?? "",
      );
      expect(second?.marks).toEqual([{ item: 0, from: 0, to: 1 }]);
    }
  });

  it("對不到時是 null（例如掃描檔沒有文字）", () => {
    expect(matchPage(pageText([]), normalizeForMatch(ARTICLE))).toBeNull();
    expect(
      matchPage(pageText(["完全無關的內容"]), normalizeForMatch(ARTICLE)),
    ).toBeNull();
  });
});

describe("startPage 與 matchFrom", () => {
  const pages = [
    pageText([
      "第一條 總則。",
      "第四條 本辦法適用全行。",
      ARTICLE.slice(0, 25),
    ]),
    pageText(["頁首：AI 治理辦法", ARTICLE.slice(25), "第六條 其他。"]),
  ];
  const excerpt = normalizeForMatch(ARTICLE);

  it("有頁碼時從那一頁開始，跨頁時也標示下一頁", () => {
    expect(startPage(pages, excerpt, 1)).toBe(1);
    const marks = matchFrom(pages, excerpt, 1);
    expect([...marks.keys()]).toEqual([1, 2]);
    expect(marks.get(2)?.map((mark) => mark.item)).toEqual([1]);
  });

  it("沒有頁碼或頁碼不對時，找片段開頭所在的頁", () => {
    expect(startPage(pages, excerpt)).toBe(1);
    expect(startPage(pages, excerpt, 2)).toBe(2);
    expect(startPage(pages, normalizeForMatch("第六條 其他。"))).toBe(2);
    expect(startPage(pages, normalizeForMatch("沒有這一段"))).toBeUndefined();
  });
});
