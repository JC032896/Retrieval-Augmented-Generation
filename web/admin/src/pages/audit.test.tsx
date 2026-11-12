import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { describe, expect, it, vi } from "vitest";
import { createApi } from "../api/client";
import type { AuditSummary, AuditDetail as Detail } from "../api/types";
import { type Session, StaticSession } from "../auth/session";
import { config, me, status } from "../test/fixtures";
import { fakeServer } from "../test/server";
import { describe as describeChange, Timeline } from "../ui/Timeline";
import { Audit } from "./Audit";
import { AuditDetail } from "./AuditDetail";
import { Settings } from "./Settings";
import { Users } from "./Users";

function summary(id: number, overrides: Partial<AuditSummary> = {}): AuditSummary {
  return {
    id,
    created_at: `2026-11-12T0${id}:00:00Z`,
    request_id: `r-${id}`,
    user_login: "kim",
    user_department: "개발팀",
    user_role: "사원",
    question: `질문 ${id}`,
    question_chars: 4,
    outcome: "answered",
    refusal_reason: null,
    cited_files: ["a.md"],
    verified: true,
    model: "claude-sonnet-5-5",
    cost_usd: 0.002,
    total_ms: 2400,
    ...overrides,
  };
}

function show(
  path: string,
  element: React.ReactNode,
  routes: Record<string, unknown>,
  pattern = path,
) {
  const server = fakeServer(routes);
  vi.stubGlobal("fetch", server.fetcher);
  const user = me(["admin", "auditor"]);
  const session: Session = {
    state: "signed-in",
    config: {
      ...config,
      auth_mode: "oidc",
      oidc: { authority: "https://login.example.com", client_id: "rag", scopes: "openid" },
    },
    me: user,
    headers: async () => ({}),
    signOut: () => {},
  };
  const router = createMemoryRouter([{ path: pattern, element }], { initialEntries: [path] });
  render(
    <StaticSession value={session}>
      <RouterProvider router={router} />
    </StaticSession>,
  );
  return server;
}

describe("감사 기록 목록", () => {
  it("최근 것부터 보여 주고, 더 보기로 다음 쪽을 이어 붙이고, 거르기를 서버에 보낸다", async () => {
    const user = userEvent.setup();
    const { sent } = show("/audit", <Audit />, {
      "GET /admin/api/audit?limit=50": { items: [summary(3), summary(2)], next_before_id: 2 },
      "GET /admin/api/audit?limit=50&before_id=2": {
        items: [summary(1, { question: null })],
        next_before_id: null,
      },
      "GET /admin/api/audit?limit=50&outcome=refused": { items: [], next_before_id: null },
    });

    expect(await screen.findByText("질문 3")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "더 보기" }));
    expect(await screen.findByText("원문 저장 안 함 (4자)")).toBeInTheDocument();
    expect(screen.getByText("마지막 기록입니다 (3건).")).toBeInTheDocument();
    expect(screen.getAllByRole("row")).toHaveLength(4);

    await user.selectOptions(screen.getByLabelText("결과"), "refused");
    await user.click(screen.getByRole("button", { name: "거르기" }));
    expect(await screen.findByText("조건에 맞는 기록이 없습니다.")).toBeInTheDocument();
    expect(sent.map((s) => s.path)).toContain("/admin/api/audit?limit=50&outcome=refused");
  });

  it("감사 DB 계정이 없으면 이유를 보여 준다", async () => {
    show("/audit", <Audit />, {
      "GET /admin/api/audit?limit=50": new Response(
        JSON.stringify({ detail: "감사 기록 보기가 꺼져 있습니다 (ADMIN_AUDIT_VIEW)" }),
        { status: 503 },
      ),
    });

    expect(await screen.findByRole("alert")).toHaveTextContent("ADMIN_AUDIT_VIEW");
  });
});

describe("감사 기록 한 건", () => {
  it("질문·답변, 보낸 근거와 인용한 근거, 재현 명령", async () => {
    const detail: Detail = {
      ...summary(7, { cited_files: ["b.md"] }),
      client_ip: "10.0.0.1",
      user_clearance_level: 1,
      question_sha256: "q",
      answer: "7일 이내입니다. [1]",
      context_files: ["a.md", "b.md"],
      input_tokens: 100,
      output_tokens: 10,
      retrieval_ms: 200,
      first_token_ms: 900,
      prompt_template_version: "v1",
      model_params: null,
      context_chunks: null,
      request_sha256: "abc",
    };
    show("/audit/7", <AuditDetail />, { "GET /admin/api/audit/7": detail }, "/audit/:id");

    expect(await screen.findByText("7일 이내입니다. [1]")).toBeInTheDocument();
    const files = screen.getAllByRole("listitem");
    expect(files.map((li) => li.textContent)).toEqual(["a.md", "b.md답변이 인용함"]);
    expect(screen.getByText("인용 검증 통과")).toBeInTheDocument();
    expect(screen.getByText("python scripts/replay.py 7")).toBeInTheDocument();
  });

  it("없는 기록", async () => {
    show(
      "/audit/9",
      <AuditDetail />,
      {
        "GET /admin/api/audit/9": new Response(JSON.stringify({ detail: "없음" }), { status: 404 }),
      },
      "/audit/:id",
    );

    expect(await screen.findByRole("alert")).toHaveTextContent("감사 기록이 없습니다.");
  });
});

describe("배송조회 이력", () => {
  const base = { id: 1, created_at: "2026-11-12T03:00:00Z", actor_login: "lee" };
  const access = {
    title: "규칙",
    security_level: 1,
    departments: ["개발팀"],
    roles: [],
    status: "current",
  };

  it("올리기·권한 변경·교체를 한 줄로 설명한다", () => {
    expect(describeChange({ ...base, action: "upload", before: null, after: access })).toEqual([
      "등급 1 사내 · 개발팀",
    ]);
    expect(
      describeChange({
        ...base,
        action: "access",
        before: access,
        after: { ...access, security_level: 0, roles: ["임원"] },
      }),
    ).toEqual(["등급: 1 사내 → 0 공개", "역할 추가: 임원"]);
    expect(
      describeChange({
        ...base,
        action: "replace",
        before: { sha256: "a" },
        after: { sha256: "b" },
      }),
    ).toEqual(["권한은 그대로, 원문만 새 판으로"]);
    expect(describeChange({ ...base, action: "delete", before: access, after: null })).toEqual([]);
  });

  it("최근 단계를 표시하고, 이력이 없으면 이유를 말한다", () => {
    const { rerender } = render(
      <Timeline
        origin="upload"
        items={[
          {
            ...base,
            id: 2,
            action: "access",
            before: access,
            after: { ...access, title: "규칙2" },
          },
          { ...base, action: "upload", before: null, after: access },
        ]}
      />,
    );
    const steps = screen.getAllByRole("listitem");
    expect(steps[0]).toHaveAttribute("data-latest", "true");
    expect(steps[0]).toHaveTextContent("제목: 규칙 → 규칙2");

    rerender(<Timeline origin="upload" items={[]} />);
    expect(screen.getByText("아직 기록된 변경이 없습니다.")).toBeInTheDocument();
  });
});

describe("설정과 사용자", () => {
  it("설정은 지금 값과 바꿀 .env 이름을 보여 준다", async () => {
    show("/settings", <Settings />, {
      "GET /admin/api/status": status({ audit_db: false }),
    });

    expect(await screen.findByText("API 키가 없어 질문이 멈춤")).toBeInTheDocument();
    expect(screen.getByText("회사 로그인 시스템 (OIDC)")).toBeInTheDocument();
    expect(screen.getByText("https://login.example.com")).toBeInTheDocument();
    expect(screen.getByText("꺼짐")).toBeInTheDocument();
    expect(screen.getByText("LLM_DAILY_BUDGET_USD")).toBeInTheDocument();
  });

  it("사용자는 부서별로 묶고, 없으면 org.yaml을 안내한다", async () => {
    show("/users", <Users />, {
      "GET /admin/api/users": [
        { login: "kim", name: "김사원", department: "개발팀", role: "사원", clearance_level: 1 },
        { login: "han", name: "한임원", department: "경영진", role: "임원", clearance_level: 3 },
      ],
    });

    expect(await screen.findByRole("heading", { name: "개발팀 1명" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "경영진 1명" })).toBeInTheDocument();
    expect(screen.getByText("3 기밀")).toBeInTheDocument();
  });
});

describe("API 쓰기 요청", () => {
  it("JSON은 Content-Type을 붙이고, 파일은 브라우저에 맡기고, 삭제는 204", async () => {
    const { fetcher, sent } = fakeServer({
      "POST /p": { ok: true },
      "PUT /f": { ok: true },
      "DELETE /d": undefined,
    });
    const calls: RequestInit[] = [];
    const api = createApi(
      async () => ({ Authorization: "Bearer t" }),
      async (input, init) => {
        calls.push(init ?? {});
        return fetcher(input, init);
      },
    );
    const form = new FormData();
    form.append("title", "규칙");

    await api.post("/p", { a: 1 });
    await api.put("/f", form);
    await expect(api.delete("/d")).resolves.toBeUndefined();

    expect(sent.map((s) => [s.method, s.json, s.form])).toEqual([
      ["POST", { a: 1 }, null],
      ["PUT", null, { title: ["규칙"] }],
      ["DELETE", null, null],
    ]);
    const header = (i: number) => (calls[i]?.headers ?? {}) as Record<string, string>;
    expect(header(0)["Content-Type"]).toBe("application/json");
    expect(header(1)["Content-Type"]).toBeUndefined();
  });
});
