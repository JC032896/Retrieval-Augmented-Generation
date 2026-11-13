import { describe, expect, it } from "vitest";
import { citedNumbers, markerOf, readAnswer, streamingText, stripCitations } from "./answer";
import type { Answer } from "./types";

function answer(text: string, overrides: Partial<Answer> = {}): Answer {
  return {
    text,
    refused: false,
    reason: null,
    citations: [1, 2, 3, 4].map((number) => ({
      number,
      chunk_id: 10 + number,
      file: `doc${number}.md`,
      title: `문서 ${number}`,
      section: null,
      page: null,
    })),
    invalid_citations: [],
    verification: { verified: true, problems: [] },
    ...overrides,
  };
}

describe("답 문장과 형광펜", () => {
  it("문장마다 인용 번호와 첫 번호의 형광펜 색을 붙이고 인용 표시는 뺀다", () => {
    const [line] = readAnswer(
      answer("재택은 주 2회까지입니다. [1] 전날 6시까지 신청합니다.[2][3] 끝으로 확인하세요."),
    );

    expect(line?.kind).toBe("text");
    expect(line?.sentences.map((s) => [s.text, s.numbers, s.marker])).toEqual([
      ["재택은 주 2회까지입니다.", [1], "yellow"],
      ["전날 6시까지 신청합니다.", [2, 3], "mint"],
      ["끝으로 확인하세요.", [], null],
    ]);
    expect(line?.sentences.map((s) => s.order)).toEqual([0, 1, 2]);
  });

  it("쉼표로 묶은 번호, 목록에 없는 번호, 넷째부터 도는 색", () => {
    const [line] = readAnswer(answer("두 문서 모두 같습니다. [2, 4] 없는 번호입니다. [9]"));

    expect(line?.sentences.map((s) => [s.numbers, s.marker])).toEqual([
      [[2, 4], "mint"],
      [[], null],
    ]);
    expect([1, 2, 3, 4, 5].map(markerOf)).toEqual(["yellow", "mint", "pink", "yellow", "mint"]);
    expect(citedNumbers("a [1] b [1, 3] c [2]")).toEqual([1, 3, 2]);
  });

  it("목록 줄과 빈 줄, 인용만 남은 조각은 앞 문장에 붙는다", () => {
    const lines = readAnswer(
      answer("신청 방법은 다음과 같습니다.\n\n- HB-HR에서 신청 [1]\n- 팀장 승인 [2]"),
    );

    expect(lines.map((l) => [l.kind, l.sentences.map((s) => s.text)])).toEqual([
      ["text", ["신청 방법은 다음과 같습니다."]],
      ["item", ["HB-HR에서 신청"]],
      ["item", ["팀장 승인"]],
    ]);
    expect(lines.map((l) => l.order)).toEqual([0, 1, 2]);
  });

  it("서버가 확인하지 못한 문장은 형광펜 대신 확인 안 됨으로 표시한다", () => {
    const [line] = readAnswer(
      answer("정산은 7일 이내입니다. [1] 한도는 50만 원입니다. [2]", {
        verification: {
          verified: false,
          problems: [
            {
              text: "한도는 50만 원입니다. [2]",
              status: "number_mismatch",
              unsupported_numbers: ["50만"],
            },
          ],
        },
      }),
    );

    expect(line?.sentences.map((s) => [s.text, s.unverified])).toEqual([
      ["정산은 7일 이내입니다.", false],
      ["한도는 50만 원입니다.", true],
    ]);
  });

  it("검증이 없는 답(거절)도 읽고, 받는 중인 글에서는 인용 표시만 뺀다", () => {
    const lines = readAnswer(
      answer("문서에서 찾을 수 없습니다.", { refused: true, verification: null }),
    );

    expect(lines[0]?.sentences[0]).toMatchObject({ numbers: [], unverified: false });
    expect(streamingText("7일 이내입니다. [1] 신청 [2")).toBe("7일 이내입니다.  신청 [2");
    expect(stripCitations("7일 이내입니다 [1].")).toBe("7일 이내입니다.");
  });
});
