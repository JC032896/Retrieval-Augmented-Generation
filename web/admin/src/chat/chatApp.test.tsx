import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { DEV_STORAGE_KEY } from "../auth/session";
import { fakeServer } from "../test/server";
import { ChatApp } from "./ChatApp";
import { ChatSessionProvider } from "./session";

const devConfig = {
  auth_mode: "dev_header",
  oidc: null,
  company_name: "한빛소프트",
  company_logo_url: "",
};

function start(routes: Record<string, unknown>) {
  const server = fakeServer(routes);
  vi.stubGlobal("fetch", server.fetcher);
  render(
    <ChatSessionProvider>
      <ChatApp />
    </ChatSessionProvider>,
  );
  return server.sent;
}

describe("채팅 화면 로그인", () => {
  it("로그인 전에는 회사 이름과 개발용 로그인 id 입력을 보이고, 고른 사람을 기억한다", async () => {
    start({ "GET /api/config": devConfig });

    expect(await screen.findByRole("heading", { name: "사내 문서에 물어보세요" })).toBeVisible();
    expect(screen.getByText("한빛소프트")).toBeInTheDocument();
    expect(document.title).toBe("한빛소프트 문서 질의");
    await userEvent.type(screen.getByLabelText("로그인 id"), " kim ");
    await userEvent.click(screen.getByRole("button", { name: "이 사람으로 들어가기" }));

    expect(JSON.parse(sessionStorage.getItem(DEV_STORAGE_KEY) ?? "{}")).toEqual({
      login: "kim",
      groups: "",
    });
  });

  it("기억한 사람으로 들어가 작업 공간을 연다", async () => {
    sessionStorage.setItem(DEV_STORAGE_KEY, JSON.stringify({ login: "kim", groups: "rag-admin" }));
    const sent = start({
      "GET /api/config": devConfig,
      "GET /api/me": {
        login: "kim",
        name: "김사원",
        department: "개발팀",
        admin_roles: ["admin"],
        history_days: 90,
      },
      "GET /api/usage": { questions_left: null, daily_questions: null },
      "GET /api/history": { items: [], next_before: null },
    });

    expect(
      await screen.findByRole("heading", { name: "김사원 님, 무엇이 궁금한가요?" }),
    ).toBeVisible();
    expect(screen.getByRole("link", { name: "관리 화면" })).toBeInTheDocument();
    expect(sent.find((s) => s.path === "/api/me")).toBeDefined();
  });

  it("등록되지 않은 사람이면 다시 로그인 화면을 보인다", async () => {
    sessionStorage.setItem(DEV_STORAGE_KEY, JSON.stringify({ login: "ghost", groups: "" }));
    start({
      "GET /api/config": devConfig,
      "GET /api/me": new Response(JSON.stringify({ detail: "등록되지 않은 사용자입니다" }), {
        status: 401,
      }),
    });
    expect(await screen.findByRole("heading", { name: "사내 문서에 물어보세요" })).toBeVisible();
  });

  it("로그인 방식이 설정되지 않았으면 관리자에게 알릴 이유를 보인다", async () => {
    start({ "GET /api/config": { ...devConfig, auth_mode: "disabled" } });

    expect(await screen.findByRole("heading", { name: "화면을 열 수 없습니다" })).toBeVisible();
    expect(screen.getByText(/AUTH_MODE/)).toBeInTheDocument();
  });
});
