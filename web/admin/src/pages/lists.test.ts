import { describe, expect, it } from "vitest";
import { documentRow } from "../test/fixtures";
import { auditQuery, EMPTY_FILTER, money, outcomeLabel, seconds } from "./auditModel";
import { filterDocuments } from "./documentList";
import { groupByDepartment } from "./Users";

const rows = [
  documentRow({ id: 1, title: "회사 소개", security_level: 0, synced_at: "2026-11-12T01:00:00Z" }),
  documentRow({
    id: 14,
    title: "연봉 테이블",
    security_level: 3,
    synced_at: "2026-11-12T02:00:00Z",
  }),
  documentRow({
    id: 27,
    title: "회의실 예약",
    origin: "upload",
    security_level: 1,
    synced_at: "2026-11-12T03:00:00Z",
  }),
];
const all = { query: "", origin: "all", level: "all", sort: "recent" } as const;
const ids = (list: { id: number }[]) => list.map((d) => d.id);

describe("문서 목록 거르기", () => {
  it("제목이나 등기번호로 찾는다", () => {
    expect(ids(filterDocuments(rows, { ...all, query: "연봉" }))).toEqual([14]);
    expect(ids(filterDocuments(rows, { ...all, query: "up-0027" }))).toEqual([27]);
    expect(ids(filterDocuments(rows, { ...all, query: "없는 문서" }))).toEqual([]);
  });

  it("출처와 등급으로 거르고, 세 가지로 정렬한다", () => {
    expect(ids(filterDocuments(rows, { ...all, origin: "folder" }))).toEqual([14, 1]);
    expect(ids(filterDocuments(rows, { ...all, level: 3 }))).toEqual([14]);
    expect(ids(filterDocuments(rows, { ...all, sort: "title" }))).toEqual([14, 1, 27]);
    expect(ids(filterDocuments(rows, { ...all, sort: "level" }))).toEqual([14, 27, 1]);
    expect(ids(filterDocuments(rows, all))).toEqual([27, 14, 1]);
  });
});

describe("감사 기록 요청", () => {
  it("거르기를 서버 요청으로: 한국 날짜, 종료일은 그날까지 포함", () => {
    const url = new URL(
      auditQuery(
        { login: " kim ", outcome: "refused", since: "2026-11-01", until: "2026-11-12" },
        40,
      ),
      "http://x",
    );

    expect(Object.fromEntries(url.searchParams)).toEqual({
      limit: "50",
      login: "kim",
      outcome: "refused",
      since: "2026-11-01T00:00:00+09:00",
      until: "2026-11-12T15:00:00.000Z",
      before_id: "40",
    });
    expect(auditQuery(EMPTY_FILTER)).toBe("/admin/api/audit?limit=50");
  });

  it("결과, 비용, 시간 표시", () => {
    expect(["answered", "refused", "error", "cancelled", "x"].map(outcomeLabel)).toEqual([
      "답변",
      "거절",
      "오류",
      "중단",
      "x",
    ]);
    expect([money(0.0038), money(null), seconds(3120), seconds(null)]).toEqual([
      "$0.0038",
      "-",
      "3.1초",
      "-",
    ]);
  });
});

describe("사용자 묶기", () => {
  it("부서별로 처음 나온 순서대로", () => {
    const users = [
      { login: "kim", name: "김", department: "개발팀", role: "사원", clearance_level: 1 },
      { login: "han", name: "한", department: "경영진", role: "임원", clearance_level: 3 },
      { login: "lee", name: "이", department: "개발팀", role: "팀장", clearance_level: 2 },
    ];
    expect(groupByDepartment(users).map(([d, m]) => [d, m.map((u) => u.login)])).toEqual([
      ["개발팀", ["kim", "lee"]],
      ["경영진", ["han"]],
    ]);
  });
});
