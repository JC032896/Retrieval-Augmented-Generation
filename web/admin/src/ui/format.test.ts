import { describe, expect, it } from "vitest";
import { documentRow } from "../test/fixtures";
import { audience, levelName, registeredNumber, trackingSteps } from "./format";

describe("등기번호", () => {
  it("폴더 문서는 FD, 올린 문서는 UP에 네 자리 번호", () => {
    expect(registeredNumber({ id: 16, origin: "folder" })).toBe("FD-0016");
    expect(registeredNumber({ id: 24, origin: "upload" })).toBe("UP-0024");
    expect(registeredNumber({ id: 12345, origin: "upload" })).toBe("UP-12345");
  });
});

describe("보안 등급", () => {
  it("네 등급의 이름과 모르는 등급", () => {
    expect([0, 1, 2, 3].map(levelName)).toEqual(["공개", "사내", "대외비", "기밀"]);
    expect(levelName(9)).toBe("등급 9");
  });
});

describe("배송조회 단계", () => {
  it("폴더 문서는 수집과 권한 지정까지", () => {
    const { steps, summary } = trackingSteps(documentRow());
    expect(steps.map((s) => s.done)).toEqual([true, true, false]);
    expect(steps[0]?.label).toBe("폴더 수집");
    expect(summary).toBe("폴더 수집");
  });

  it("올린 뒤 권한을 바꾸면 세 단계가 모두 채워지고 누가 바꿨는지 보인다", () => {
    const { steps, summary } = trackingSteps(
      documentRow({
        origin: "upload",
        last_change: { action: "access", actor_login: "lee", created_at: "2026-11-12T11:00:00Z" },
      }),
    );
    expect(steps.map((s) => s.done)).toEqual([true, true, true]);
    expect(steps.map((s) => s.label)).toEqual(["올림", "권한 지정", "권한 변경"]);
    expect(summary).toBe("권한 변경 · lee");
  });

  it("방금 올린 문서는 변경 단계가 비어 있다", () => {
    const { steps, summary } = trackingSteps(
      documentRow({
        origin: "upload",
        last_change: { action: "upload", actor_login: "lee", created_at: "2026-11-12T11:00:00Z" },
      }),
    );
    expect(steps[2]).toEqual({ label: "변경 없음", done: false });
    expect(summary).toBe("올림 · lee");
  });
});

describe("볼 수 있는 사람", () => {
  it("부서와 역할, 사람 수", () => {
    expect(audience(documentRow())).toBe("인사팀, 임원 · 2명");
    expect(audience(documentRow({ departments: [], roles: [], viewers: 0 }))).toBe("없음 · 0명");
  });
});
