import { describe, expect, it } from "vitest";
import { passageParagraphs } from "./passage";

const texts = (content: string, title = "출장비 규정") =>
  passageParagraphs(content, title).map((p) => p.text);

describe("근거 문단 본문 고치기", () => {
  it("문서 경로 머리를 빼고, 한 줄 바꿈은 잇고, 하이픈으로 끊긴 영문은 붙인다", () => {
    const content =
      "출장비 규정 > 정산\n\n출장에서 돌아온 날로부터 7일 이내에 경비 시스템 HB-\nExpense에 영수증을 올리고 정산을\n신청한다.\n\n해외 출장비는 환산한다.";

    expect(texts(content)).toEqual([
      "출장에서 돌아온 날로부터 7일 이내에 경비 시스템 HB-Expense에 영수증을 올리고 정산을 신청한다.",
      "해외 출장비는 환산한다.",
    ]);
    expect(passageParagraphs(content, "출장비 규정").map((p) => p.order)).toEqual([0, 1]);
  });

  it("목록 줄은 줄을 지키고, 제목과 다른 경로나 본문 중간의 경로 모양 줄은 남긴다", () => {
    expect(texts("1. 팀장 승인\n2. 신청 마감\n이어지는 설명", "재택")).toEqual([
      "1. 팀장 승인\n2. 신청 마감 이어지는 설명",
    ]);
    expect(texts("다른 문서 > 절\n\n본문", "출장비 규정")).toEqual(["다른 문서 > 절", "본문"]);
    expect(texts("본문\n\n출장비 규정 > 정산")).toEqual(["본문", "출장비 규정 > 정산"]);
    expect(texts("출장비 규정 > 정산\n\n본문", "")).toEqual(["출장비 규정 > 정산", "본문"]);
  });

  it("CRLF와 빈 문단을 정리한다", () => {
    expect(texts("첫 줄\r\n둘째 줄\r\n\r\n  \r\n- 항목")).toEqual(["첫 줄 둘째 줄", "- 항목"]);
  });
});
