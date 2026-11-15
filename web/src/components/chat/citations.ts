/**
 * 知識庫的出處（Python 版的 search_knowledge）。
 *
 * search_knowledge 的結果是給模型看的文字，每筆是「[編號] 來源：出處」
 * 加上片段內容（見 python/src/harness/knowledge.py 的 format_hits）。回覆
 * 裡的 [編號] 對照同一輪最近一次搜尋的結果：對得到的變成可以點的出處，
 * 點了在右側面板打開原文；對不到的標成「找不到出處」，提醒使用者這個
 * 引用可能是模型自己編的。
 *
 * 純函式，不碰 window，測試可以直接引用。
 */

import type { Block } from "../../transcript.ts";

export const SEARCH_TOOL = "search_knowledge";

/** 一筆搜尋結果的出處。 */
export interface KnowledgeSource {
  number: number;
  /** 原本的出處文字，例如「行內規範 / R03_分級辦法.pdf › 第五點（第 2 頁）」。 */
  citation: string;
  /** 知識庫名稱；只搜尋一個知識庫時沒有。 */
  base: string;
  /** 相對於知識庫資料夾的檔案路徑。 */
  path: string;
  /** 在文件裡的位置（標題、條號、頁碼），沒有則為空字串。 */
  location: string;
  /** PDF 的頁碼（從位置裡的「第 N 頁」取出）。 */
  page?: number;
  /** 片段內容。 */
  excerpt: string;
}

export type CitationMap = ReadonlyMap<number, KnowledgeSource>;

const HEADER = /^\[(\d+)\] 來源：(.+)$/;
const PAGE = /第\s*(\d+)\s*頁/;
const BASE_SEPARATOR = " / ";
const LOCATION_SEPARATOR = " › ";

/** 拆開出處文字：「知識庫 / 路徑 › 位置」，知識庫與位置都可以沒有。 */
export function parseCitation(citation: string): {
  base: string;
  path: string;
  location: string;
} {
  let rest = citation.trim();
  let location = "";
  const at = rest.indexOf(LOCATION_SEPARATOR);
  if (at >= 0) {
    location = rest.slice(at + LOCATION_SEPARATOR.length).trim();
    rest = rest.slice(0, at).trim();
  }
  let base = "";
  const slash = rest.indexOf(BASE_SEPARATOR);
  if (slash >= 0) {
    base = rest.slice(0, slash).trim();
    rest = rest.slice(slash + BASE_SEPARATOR.length).trim();
  }
  return { base, path: rest, location };
}

/** 讀出 search_knowledge 結果裡的每一筆；不是這種格式時回傳空陣列。 */
export function parseSearchResult(text: string): KnowledgeSource[] {
  const found: KnowledgeSource[] = [];
  for (const part of text.split("\n\n---\n\n")) {
    const newline = part.indexOf("\n");
    const header = newline < 0 ? part : part.slice(0, newline);
    const match = HEADER.exec(header.trim());
    if (!match) continue;
    const citation = (match[2] ?? "").trim();
    const { base, path, location } = parseCitation(citation);
    const page = PAGE.exec(location);
    found.push({
      number: Number(match[1]),
      citation,
      base,
      path,
      location,
      page: page ? Number(page[1]) : undefined,
      excerpt: newline < 0 ? "" : part.slice(newline + 1).trim(),
    });
  }
  return found;
}

/**
 * 每段文字可以引用的出處：同一輪裡，這段文字之前最近一次搜尋的結果
 * （編號相同時以後面的搜尋為準）。這一輪還沒搜尋過的文字不在結果裡，
 * 那些文字裡的 [編號] 不處理（可能根本不是引用）。
 *
 * @returns 文字區塊的 key → 出處。
 */
export function citationsByBlock(
  blocks: readonly Block[],
): Map<string, CitationMap> {
  const result = new Map<string, CitationMap>();
  let current: Map<number, KnowledgeSource> | undefined;
  for (const block of blocks) {
    if (block.kind === "steps") {
      for (const step of block.steps) {
        if (step.name !== SEARCH_TOOL || step.result === undefined) continue;
        const hits = parseSearchResult(step.result);
        current = new Map(current);
        for (const hit of hits) current.set(hit.number, hit);
      }
    } else if (block.kind === "text" && current) {
      result.set(block.key, current);
    }
  }
  return result;
}

/** 方括號裡的編號：[1]、[1][2]、[1, 3]、[2、5]。 */
export const CITATION_PATTERN = /\[(\d{1,3}(?:\s*[,，、]\s*\d{1,3})*)\]/g;

/** 把一段文字拆成文字與引用編號，例如 "見 [1, 2]。" → ["見 ", [1, 2], "。"]。 */
export function splitCitations(text: string): (string | number[])[] {
  const parts: (string | number[])[] = [];
  let last = 0;
  for (const match of text.matchAll(CITATION_PATTERN)) {
    const start = match.index ?? 0;
    if (start > last) parts.push(text.slice(last, start));
    parts.push((match[1] ?? "").split(/\s*[,，、]\s*/).map(Number));
    last = start + match[0].length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return parts;
}

/** 開啟原文的網址（GET /api/knowledge/source）。 */
export function sourceUrl(source: KnowledgeSource, download = false): string {
  const query = new URLSearchParams({ base: source.base, path: source.path });
  if (download) query.set("download", "1");
  return `/api/knowledge/source?${query.toString()}`;
}
