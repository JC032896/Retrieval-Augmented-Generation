import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it, vi } from "vitest";
import type { Me } from "../api/types";
import { type Session, StaticSession } from "../auth/session";
import { config, documentRow, fakeFetch, me, status } from "../test/fixtures";
import { Dashboard } from "./Dashboard";

function show(user: Me, routes: Record<string, unknown>) {
  const { fetcher, calls } = fakeFetch(routes);
  vi.stubGlobal("fetch", fetcher);
  const session: Session = {
    state: "signed-in",
    config,
    me: user,
    headers: async () => ({ "X-User-Id": user.login }),
    signOut: () => {},
  };
  render(
    <StaticSession value={session}>
      <MemoryRouter>
        <Dashboard me={user} />
      </MemoryRouter>
    </StaticSession>,
  );
  return calls;
}

const uploaded = documentRow({
  id: 24,
  title: "재택근무 보안 수칙",
  origin: "upload",
  security_level: 1,
  departments: ["개발팀", "인사팀"],
  roles: [],
  viewers: 3,
  last_change: { action: "access", actor_login: "lee", created_at: "2026-11-12T11:00:00Z" },
});

describe("대시보드", () => {
  it("상태 라벨, 최근 문서 전달, 확인할 일을 보여 준다", async () => {
    const calls = show(me(["admin"]), {
      "/admin/api/status": status(),
      "/admin/api/documents": [documentRow(), uploaded],
    });

    const board = await screen.findByRole("list", { name: "오늘의 상태" });
    expect(within(board).getAllByRole("listitem")).toHaveLength(4);
    expect(within(board).getByText("설정 안 됨")).toBeInTheDocument();

    const rows = await screen.findAllByRole("row");
    expect(rows[1]).toHaveTextContent("UP-0024");
    expect(rows[1]).toHaveTextContent("개발팀, 인사팀 · 3명");
    expect(rows[1]).toHaveTextContent("권한 변경 · lee");
    expect(rows[2]).toHaveTextContent("FD-0016");
    expect(within(rows[2] as HTMLElement).getByText("3 기밀")).toBeInTheDocument();

    expect(screen.getByRole("link", { name: "설정에서 확인" })).toHaveAttribute(
      "href",
      "/settings",
    );
    expect(calls.every((c) => c.headers["X-User-Id"] === "han")).toBe(true);
  });

  it("감사 담당에게는 문서 목록 대신 감사 기록으로 가는 길을 알려 주고 문서 API를 부르지 않는다", async () => {
    const calls = show(me(["auditor"], { login: "park" }), { "/admin/api/status": status() });

    expect(
      await screen.findByText(/문서 목록은 중앙 관리자와 부서 문서 담당에게/),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "감사 기록" })).toHaveAttribute("href", "/audit");
    expect(calls.map((c) => c.path)).toEqual(["/admin/api/status"]);
  });

  it("문서가 없거나 불러오지 못하면 그렇다고 말한다", async () => {
    show(me(["doc_manager"]), {
      "/admin/api/status": new Response(JSON.stringify({ detail: "DB 연결 실패" }), {
        status: 500,
      }),
      "/admin/api/documents": [],
    });

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "상태를 불러오지 못했습니다. DB 연결 실패",
    );
    expect(await screen.findByText(/아직 문서가 없습니다/)).toBeInTheDocument();
  });

  it("막힌 것이 없으면 확인할 일이 비어 있다고 알린다", async () => {
    show(me(["doc_manager"]), {
      "/admin/api/status": status({
        llm: { provider: "claude", model: "claude-sonnet-5-5", configured: true },
      }),
      "/admin/api/documents": [uploaded],
    });

    expect(await screen.findByText("지금 막힌 것이 없습니다.")).toBeInTheDocument();
  });
});
