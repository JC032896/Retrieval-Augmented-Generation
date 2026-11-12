import { describe, expect, it } from "vitest";
import { documentRow, status } from "../test/fixtures";
import { recentDocuments, statusLabels, todos } from "./statusModel";

describe("상태 라벨", () => {
  it("답변 LLM이 없으면 막힘으로 표시한다", () => {
    const labels = statusLabels(status());
    expect(labels.map((l) => [l.key, l.value, l.tone])).toEqual([
      ["index", "23", "ok"],
      ["models", "준비됨", "ok"],
      ["llm", "설정 안 됨", "blocked"],
      ["limits", "200", "ok"],
    ]);
    expect(labels[3]?.note).toBe("회사 하루 $20 · 동시 3건");
  });

  it("DB 오류, 어긋난 색인, 모델 오류, 한도 없음", () => {
    const broken = statusLabels(status({ db: "error", index: { error: "읽기 실패" } }));
    expect(broken[0]).toMatchObject({ value: "읽지 못함", tone: "blocked" });

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

    const free = statusLabels(
      status({
        limits: {
          daily_requests_per_user: null,
          daily_budget_usd: null,
          concurrent_per_user: null,
          utc_offset_hours: 9,
        },
      }),
    );
    expect(free[3]).toMatchObject({ value: "없음", note: "회사 비용 한도 없음" });
    expect(free[3]?.unit).toBeUndefined();
  });
});

describe("확인할 일", () => {
  it("막힌 것을 먼저 알리고, 링크는 그 화면을 쓸 수 있는 역할에만 준다", () => {
    const admin = todos(status({ index: { documents: 1, mismatches: 1 } }), ["admin"]);
    expect(admin.map((t) => t.title)).toEqual([
      "답변 LLM 키가 없습니다",
      "원문과 색인이 1건 어긋납니다",
      "관리 화면에서 감사 기록을 볼 수 있습니다",
    ]);
    expect(admin[0]?.link?.to).toBe("/settings");

    const manager = todos(status(), ["doc_manager"]);
    expect(manager.map((t) => t.title)).toEqual(["답변 LLM 키가 없습니다"]);
    expect(manager[0]?.link).toBeUndefined();
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
