// 화면 테스트용 서버 응답. 실제 API 모양(schema.d.ts)을 따른다.
import type { DocumentRow, Me, Status, UiConfig } from "../api/types";

export const config: UiConfig = {
  auth_mode: "dev_header",
  oidc: null,
  company_name: "한빛소프트",
  company_logo_url: "",
};

export function me(roles: Me["roles"], overrides: Partial<Me> = {}): Me {
  return {
    login: "han",
    name: "한임원",
    department: "경영진",
    role: "임원",
    clearance_level: 3,
    roles,
    ...overrides,
  };
}

export function status(overrides: Partial<Status> = {}): Status {
  return {
    version: "0.1.0",
    db: "ok",
    models: { status: "ready" },
    index: {
      documents: 23,
      mismatches: 0,
      last_synced_at: "2026-11-12T10:58:23+00:00",
    },
    llm: { provider: "claude", model: "claude-sonnet-5-5", configured: false },
    audit_db: true,
    limits: {
      daily_requests_per_user: 200,
      daily_budget_usd: 20,
      concurrent_per_user: 3,
      utc_offset_hours: 9,
    },
    ...overrides,
  };
}

export function documentRow(overrides: Partial<DocumentRow> = {}): DocumentRow {
  return {
    id: 16,
    title: "2025 연봉 테이블",
    source_path: "16_salary.md",
    origin: "folder",
    owner_department: null,
    security_level: 3,
    status: "current",
    departments: ["인사팀"],
    roles: ["임원"],
    chunks: 4,
    viewers: 2,
    editable: false,
    created_at: "2026-11-11T05:00:00+00:00",
    synced_at: "2026-11-12T10:58:23+00:00",
    last_change: null,
    ...overrides,
  };
}

/** 경로마다 응답을 정해 둔 fetch. 부른 경로와 머리글을 기록한다. */
export function fakeFetch(routes: Record<string, unknown>) {
  const calls: { path: string; headers: Record<string, string> }[] = [];
  const fetcher = async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    calls.push({ path, headers: (init?.headers ?? {}) as Record<string, string> });
    if (!(path in routes)) {
      return new Response(JSON.stringify({ detail: "없는 경로" }), { status: 404 });
    }
    const body = routes[path];
    if (body instanceof Response) return body;
    return new Response(JSON.stringify(body), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  };
  return { fetcher, calls };
}
