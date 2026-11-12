import { describe, expect, it } from "vitest";
import { documentRow } from "../test/fixtures";
import { changes, draftOf, draftProblem, narrowDraft, sameDraft } from "./access";
import { levelName } from "./format";

describe("권한 초안", () => {
  it("새 문서의 기본 권한은 좁다: 관리 부서만, 사내 등급", () => {
    expect(narrowDraft("개발팀", "회의실 예약")).toEqual({
      title: "회의실 예약",
      security_level: 1,
      departments: ["개발팀"],
      roles: [],
      status: "current",
    });
  });

  it("제목이 없거나 아무도 볼 수 없으면 저장할 수 없다", () => {
    expect(draftProblem(narrowDraft("개발팀", "  "))).toMatch("제목");
    expect(draftProblem({ ...narrowDraft("개발팀", "제목"), departments: [] })).toMatch(
      "아무도 볼 수 없는",
    );
    expect(draftProblem(narrowDraft("개발팀", "제목"))).toBeNull();
  });

  it("순서와 앞뒤 공백은 같은 것으로 본다", () => {
    const saved = draftOf(documentRow({ departments: ["인사팀", "개발팀"], roles: ["임원"] }));
    expect(
      sameDraft(saved, { ...saved, title: ` ${saved.title} `, departments: ["개발팀", "인사팀"] }),
    ).toBe(true);
    expect(sameDraft(saved, { ...saved, security_level: 2 })).toBe(false);
  });

  it("바뀐 점을 사람이 읽는 문장으로", () => {
    const before = draftOf(
      documentRow({ title: "연봉 테이블", departments: ["인사팀"], roles: ["임원"] }),
    );
    const after = {
      ...before,
      title: "연봉표",
      security_level: 2,
      departments: ["인사팀", "재무팀"],
      roles: [],
      status: "superseded" as const,
    };

    expect(changes(before, after, levelName)).toEqual([
      "제목: 연봉 테이블 → 연봉표",
      "등급: 3 기밀 → 2 대외비",
      "부서 추가: 재무팀",
      "역할 제외: 임원",
      "상태: 폐지로 바꿈",
    ]);
    expect(changes(after, { ...after, status: "current" }, levelName)).toEqual([
      "상태: 현행으로 바꿈",
    ]);
    expect(changes(before, before, levelName)).toEqual([]);
  });
});
