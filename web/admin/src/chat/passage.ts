// 근거 문단 본문을 읽기 좋게 고친다. 수집한 조각에는 PDF의 줄바꿈과 문서 경로 머리가 그대로 있어서,
// 그대로 보이면 문장 중간에서 줄이 끊기고 제목·조항 줄과 같은 경로가 한 번 더 나온다.
// - 빈 줄(문단 경계)만 남기고, 한 줄 바꿈은 공백으로 잇는다. 목록 줄(1. / - )은 줄을 지킨다
// - 영문·숫자가 하이픈으로 끊긴 줄("HB-" + "Expense")은 공백 없이 잇는다
// - 첫 문단이 문서 제목으로 시작하는 경로("출장비 규정 > 정산") 한 줄이면 뺀다

const LIST_ITEM = /^(?:\d+[.)]|[-*•])\s+/;

export type Paragraph = { order: number; text: string };

export function passageParagraphs(content: string, title: string): Paragraph[] {
  const paragraphs: Paragraph[] = [];
  for (const block of content.replace(/\r\n?/g, "\n").split(/\n\s*\n/)) {
    const lines = block
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean);
    const [only] = lines;
    if (only === undefined) continue;
    if (paragraphs.length === 0 && lines.length === 1 && only.includes(" > ")) {
      if (title && only.startsWith(title)) continue;
    }
    let text = "";
    for (const line of lines) {
      if (!text) text = line;
      else if (LIST_ITEM.test(line)) text += `\n${line}`;
      else if (/[A-Za-z0-9]-$/.test(text) && /^[A-Za-z0-9]/.test(line)) text += line;
      else text += ` ${line}`;
    }
    paragraphs.push({ order: paragraphs.length, text });
  }
  return paragraphs;
}
