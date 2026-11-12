import { describe, expect, it } from "vitest";
import type { Status } from "../api/types";
import { documentRow, status } from "../test/fixtures";
import { recentDocuments, statusLabels, todos } from "./statusModel";

// 최종 검토(B-6): 4번째 송장 라벨은 고정 한도가 아니라 '오늘 질문'(질문 수, 사람 수, 비용 / 하루 한도)
function used(cost: number, requests = 12, users = 4): Partial<Status> {
  return { usage: { since: "2026-11-11T15:00:00Z", requests, users, cost_usd: cost } };
}

describe("상태 라벨", () => {
  it("답변 LLM이 없으면 막힘으로 표시하고, 4번째는 오늘 질문이다", () => {
    const labels = statusLabels(status(used(1.5)));
    expect(labels.map((l) => [l.key, l.value, l.tone])).toEqual([
      ["index", "23", "ok"],
      ["models", "준비됨", "ok"],
      ["llm", "설정 안 됨", "blocked"],
      ["today", "12", "ok"],
    ]);
    expect(labels[3]?.note).toBe("4명 · 비용 $1.50 / 하루 $20");
    expect(labels[3]?.unit).toBe("건");
  });

  it("DB 오류, 어긋난 색인, 모델 오류, 사용량을 읽지 못함", () => {
    const broken = statusLabels(status({ db: "error", index: { error: "읽기 실패" } }));
    expect(broken[0]).toMatchObject({ value: "읽지 못함", tone: "blocked" });
    expect(broken[3]).toMatchObject({ value: "읽지 못함", tone: "pending" });

    const drift = statusLabels(status({ index: { documents: 23, mismatches: 2 } }));
    expect(drift[0]).toMatchObject({ note: "원문과 2건 어긋남", tone: "blocked" });

    const model = statusLabels(status({ models: { status: "error", error: "OSError" } }));
    expect(model[1]).toMatchObject({ value: "읽지 못함", note: "OSError", tone: "blocked" });

    const loading = statusLabels(status({ models: { status: "loading" } }));
    expect(loading[1]).toMatchObject({ value: "읽는 중", tone: "pending" });

    const ready = statusLabels(
      status({ llm: { provider: "openai_compatible", model: "gemma3:12b", configured: true } }),
    );
    expect(ready[2]).toMatchObject({ value: "준비됨", note: "openai_compatible · gemma3:12b" });
  });

  it("오늘 비용이 한도의 80%면 주의, 넘으면 막힘, 한도가 없으면 비용만", () => {
    expect(statusLabels(status(used(16)))[3]?.tone).toBe("pending");
    expect(statusLabels(status(used(20)))[3]?.tone).toBe("blocked");

    const free = statusLabels(
      status({
        ...used(31.25),
        limits: {
          daily_requests_per_user: null,
          daily_budget_usd: null,
          concurrent_per_user: null,
          utc_offset_hours: 9,
        },
      }),
    );
    expect(free[3]).toMatchObject({ value: "12", note: "4명 · 비용 $31.25", tone: "ok" });
  });
});

describe("확인할 일", () => {
  it("막힌 것만 알리고, 링크는 그 화면을 쓸 수 있는 역할에만 준다", () => {
    const admin = todos(status({ index: { documents: 1, mismatches: 1 } }), ["admin"]);
    // 감사 기록 보기 같은 서버 설명은 할 일이 아니므로 설정 화면에만 둔다
    expect(admin.map((t) => t.title)).toEqual([
      "답변 LLM 키가 없습니다",
      "원문과 색인이 1건 어긋납니다",
    ]);
    expect(admin[0]?.link?.to).toBe("/settings");

    const manager = todos(status(), ["doc_manager"]);
    expect(manager.map((t) => t.title)).toEqual(["답변 LLM 키가 없습니다"]);
    expect(manager[0]?.link).toBeUndefined();
  });

  it("오늘 비용이 한도에 가까우면 알린다", () => {
    const fine = { llm: { provider: "claude", model: "claude-sonnet-5-5", configured: true } };
    const near = todos(status({ ...fine, ...used(18) }), ["admin"]);
    const over = todos(status({ ...fine, ...used(20) }), ["doc_manager"]);

    expect(near.map((t) => [t.title, t.link?.to])).toEqual([
      ["오늘 비용이 한도의 90%입니다", "/settings"],
    ]);
    expect(over.map((t) => [t.title, t.link])).toEqual([
      ["오늘 비용 한도에 닿았습니다", undefined],
    ]);
    expect(todos(status({ ...fine, ...used(10) }), ["admin"])).toEqual([]);
  });

  it("DB와 모델 오류, 그리고 아무 일도 없을 때", () => {
    const failing = todos(status({ db: "error", models: { status: "error" } }), ["auditor"]);
    expect(failing.map((t) => t.title)).toEqual([
      "DB에 연결하지 못했습니다",
      "답변 LLM 키가 없습니다",
      "검색 모델을 읽지 못했습니다",
    ]);

    const fine = status({
      llm: { provider: "claude", model: "claude-sonnet-5-5", configured: true },
      audit_db: false,
    });
    expect(todos(fine, ["admin"])).toEqual([]);
  });
});

describe("최근 문서", () => {
  it("관리 화면의 마지막 변경, 수집, 등록 시각 순으로 최근 것부터", () => {
    const rows = [
      documentRow({ id: 1, synced_at: "2026-11-12T01:00:00Z" }),
      documentRow({
        id: 2,
        synced_at: null,
        last_change: { action: "access", actor_login: "lee", created_at: "2026-11-12T09:00:00Z" },
      }),
      documentRow({ id: 3, synced_at: null, created_at: "2026-11-12T05:00:00Z" }),
    ];
    expect(recentDocuments(rows).map((d) => d.id)).toEqual([2, 3, 1]);
    expect(recentDocuments(rows, 1)).toHaveLength(1);
  });
});
