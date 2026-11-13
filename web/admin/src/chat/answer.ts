// 답 본문을 화면에 그릴 조각으로 나눈다: 문장마다 인용 번호와 형광펜 색, 인용 확인 여부.
// 서버의 문장 나누기(answer/verify.py split_sentences)와 같은 규칙을 써서, 서버가 "확인 안 됨"이라고
// 돌려준 문장(verification.problems[].text)을 그대로 찾는다.
import type { Answer } from "./types";

const CITATION = /\[(\d+(?:\s*,\s*\d+)*)\]/g;
const SENTENCE_END = /[.!?](?:\s*\[\d+(?:\s*,\s*\d+)*\])*(?=\s|$)/g;

/** 형광펜 세 색. 인용 번호 1·2·3에 차례로 붙고 넷째부터 다시 돈다. */
export const MARKERS = ["yellow", "mint", "pink"] as const;
export type Marker = (typeof MARKERS)[number];

export function markerOf(number: number): Marker {
  return MARKERS[(number - 1) % MARKERS.length] ?? "yellow";
}

export function citedNumbers(text: string): number[] {
  const found: number[] = [];
  for (const match of text.matchAll(CITATION)) {
    for (const part of (match[1] ?? "").split(",")) {
      const n = Number(part.trim());
      if (!found.includes(n)) found.push(n);
    }
  }
  return found;
}

export function stripCitations(text: string): string {
  return text
    .replace(CITATION, "")
    .replace(/\s+([.!?,])/g, "$1")
    .trim();
}

/** 한 줄을 문장으로 나눈다. 인용만 남은 조각은 앞 문장에 붙인다 (서버와 같은 규칙). */
function splitLine(line: string): string[] {
  const sentences: string[] = [];
  let start = 0;
  const pieces: string[] = [];
  for (const match of line.matchAll(SENTENCE_END)) {
    const end = (match.index ?? 0) + match[0].length;
    pieces.push(line.slice(start, end));
    start = end;
  }
  pieces.push(line.slice(start));
  for (const piece of pieces.map((p) => p.trim())) {
    if (!piece) continue;
    const last = sentences.length - 1;
    if (last >= 0 && !piece.replace(CITATION, "").replace(/^[\s.\-*]+|[\s.\-*]+$/g, "")) {
      sentences[last] = `${sentences[last]} ${piece}`;
    } else {
      sentences.push(piece);
    }
  }
  return sentences;
}

export type Sentence = {
  order: number; // 답 전체에서 몇 번째 문장인가 (0부터, 화면의 key와 형광펜 순서)
  text: string; // 인용 표시를 뺀 문장
  numbers: number[]; // 이 문장이 인용한 번호 (답의 인용 목록에 있는 것만)
  marker: Marker | null; // 첫 인용 번호의 형광펜. 인용이 없으면 null
  unverified: boolean; // 서버의 인용 검증에서 원문으로 확인되지 않은 문장
};

export type Line = { order: number; kind: "text" | "item"; sentences: Sentence[] };

const normalize = (text: string) => stripCitations(text).replace(/\s+/g, " ");

/** 답을 줄과 문장으로 나눈다. "- "로 시작하는 줄은 목록 항목이다. */
export function readAnswer(answer: Pick<Answer, "text" | "citations" | "verification">): Line[] {
  const known = new Set(answer.citations.map((c) => c.number));
  const problems = new Set((answer.verification?.problems ?? []).map((p) => normalize(p.text)));
  const lines: Line[] = [];
  let order = 0;
  for (const raw of answer.text.split("\n")) {
    const item = /^\s*[-*•]\s+/.exec(raw);
    const line = item ? raw.slice(item[0].length) : raw;
    if (!line.trim()) continue;
    const sentences = splitLine(line).map((sentence): Sentence => {
      const numbers = citedNumbers(sentence).filter((n) => known.has(n));
      const first = numbers[0];
      return {
        order: order++,
        text: stripCitations(sentence),
        numbers,
        marker: first === undefined ? null : markerOf(first),
        unverified: problems.has(normalize(sentence)),
      };
    });
    lines.push({ order: lines.length, kind: item ? "item" : "text", sentences });
  }
  return lines;
}

/** 실시간으로 받는 중인 답: 인용 표시만 뺀 글. 형광펜은 답이 끝나 검증된 뒤에 긋는다. */
export function streamingText(text: string): string {
  return text.replace(CITATION, "");
}
