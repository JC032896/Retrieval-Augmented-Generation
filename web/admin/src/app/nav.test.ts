import { describe, expect, it } from "vitest";
import { visibleNav } from "./nav";

const labels = (roles: Parameters<typeof visibleNav>[0]) => visibleNav(roles).map((i) => i.label);

describe("역할별 메뉴", () => {
  it("역할마다 할 수 있는 메뉴만 보인다", () => {
    expect(labels(["admin"])).toEqual(["대시보드", "문서", "사용자", "설정"]);
    expect(labels(["doc_manager"])).toEqual(["대시보드", "문서"]);
    expect(labels(["auditor"])).toEqual(["대시보드", "감사 기록"]);
    expect(labels([])).toEqual(["대시보드"]);
  });

  it("중앙 관리자도 감사 담당 그룹이 없으면 감사 기록 메뉴가 없다", () => {
    expect(labels(["admin"])).not.toContain("감사 기록");
    expect(labels(["admin", "auditor"])).toContain("감사 기록");
  });
});
