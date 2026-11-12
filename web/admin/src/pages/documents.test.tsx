import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { describe, expect, it, vi } from "vitest";
import type { Me } from "../api/types";
import { type Session, StaticSession } from "../auth/session";
import { config, documentRow, me } from "../test/fixtures";
import { fakeServer } from "../test/server";
import { DocumentDetail } from "./DocumentDetail";
import { DocumentNew } from "./DocumentNew";
import { Documents } from "./Documents";

const ORG = { departments: ["개발팀", "인사팀", "경영진"], roles: ["사원", "팀장", "임원"] };
const LEE = me(["doc_manager"], {
  login: "lee",
  name: "이팀장",
  department: "개발팀",
  role: "팀장",
});
const PREVIEW = {
  count: 3,
  total_users: 6,
  users: [
    { login: "kim", name: "김사원", department: "개발팀", role: "사원", clearance_level: 1 },
    { login: "lee", name: "이팀장", department: "개발팀", role: "팀장", clearance_level: 2 },
    { login: "park", name: "박인사", department: "인사팀", role: "사원", clearance_level: 1 },
  ],
};
const UPLOADED = documentRow({
  id: 27,
  title: "회의실 예약",
  origin: "upload",
  owner_department: "개발팀",
  security_level: 1,
  departments: ["개발팀"],
  roles: [],
  viewers: 2,
  editable: true,
  source_path: "upload/회의실.md",
  last_change: { action: "upload", actor_login: "lee", created_at: "2026-11-12T12:00:00Z" },
});

function show(path: string, routes: Record<string, unknown>, user: Me = LEE) {
  const server = fakeServer(routes);
  vi.stubGlobal("fetch", server.fetcher);
  const session: Session = {
    state: "signed-in",
    config,
    me: user,
    headers: async () => ({ "X-User-Id": user.login }),
    signOut: () => {},
  };
  const router = createMemoryRouter(
    [
      { path: "/documents", element: <Documents me={user} /> },
      { path: "/documents/new", element: <DocumentNew me={user} /> },
      { path: "/documents/:id", element: <DocumentDetail /> },
    ],
    { initialEntries: [path] },
  );
  render(
    <StaticSession value={session}>
      <RouterProvider router={router} />
    </StaticSession>,
  );
  return { ...server, router };
}

describe("문서 한 건의 권한 바꾸기", () => {
  it("받는 사람 명단을 확인한 뒤에야 저장하고, 바뀐 점과 결과를 알려 준다", async () => {
    const user = userEvent.setup();
    const saved = { ...UPLOADED, departments: ["개발팀", "인사팀"], viewers: 3 };
    let current = UPLOADED;
    const { sent } = show("/documents/27", {
      "GET /admin/api/documents/27": () => current,
      "GET /admin/api/documents/27/changes": [],
      "GET /admin/api/org": ORG,
      "POST /admin/api/documents/access-preview": PREVIEW,
      "PUT /admin/api/documents/27/access": () => {
        current = saved;
        return saved;
      },
    });

    expect(await screen.findByRole("heading", { name: "회의실 예약" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "받는 사람 확인" })).toBeDisabled();
    await user.click(await screen.findByRole("checkbox", { name: "인사팀" }));
    expect(await screen.findByText("명이 볼 수 있습니다")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "받는 사람 확인" }));

    const confirm = screen.getByRole("region", { name: "받는 사람 3명을 확인해 주세요" });
    expect(within(confirm).getByText("부서 추가: 인사팀")).toBeInTheDocument();
    expect(sent.some((s) => s.method === "PUT")).toBe(false); // 아직 저장하지 않았다
    await user.click(within(confirm).getByRole("button", { name: "이 명단으로 저장" }));

    expect(await screen.findByRole("status")).toHaveTextContent("권한을 바꿨습니다");
    const put = sent.find((s) => s.method === "PUT");
    expect(put?.json).toEqual({
      title: "회의실 예약",
      security_level: 1,
      departments: ["개발팀", "인사팀"],
      roles: [],
      status: "current",
    });
    expect(await screen.findByText("바뀐 것이 없습니다.")).toBeInTheDocument();
  });

  it("아무도 볼 수 없게 되는 권한은 확인 단계로 넘어가지 않는다", async () => {
    const user = userEvent.setup();
    show("/documents/27", {
      "GET /admin/api/documents/27": UPLOADED,
      "GET /admin/api/documents/27/changes": [],
      "GET /admin/api/org": ORG,
      "POST /admin/api/documents/access-preview": PREVIEW,
    });

    await user.click(await screen.findByRole("checkbox", { name: "개발팀" }));

    expect(screen.getByText(/아무도 볼 수 없는 문서가 됩니다/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "받는 사람 확인" })).toBeDisabled();
  });

  it("폴더 문서는 보기만 하고, 없는 문서는 그렇다고 말한다", async () => {
    const folder = documentRow({ id: 1, title: "회사 소개" });
    show(
      "/documents/1",
      { "GET /admin/api/documents/1": folder, "GET /admin/api/documents/1/changes": [] },
      me(["admin"]),
    );

    expect(await screen.findByText(/acl.yaml과 원문 파일에서 바꾸고/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "받는 사람 확인" })).not.toBeInTheDocument();
    expect(screen.getByText(/관리 화면의 변경 이력이 없습니다/)).toBeInTheDocument();
  });

  it("다른 부서 문서(404)는 볼 권한이 없다고 안내한다", async () => {
    show("/documents/99", {
      "GET /admin/api/documents/99": new Response(JSON.stringify({ detail: "문서가 없습니다" }), {
        status: 404,
      }),
      "GET /admin/api/documents/99/changes": [],
    });

    expect(await screen.findByRole("alert")).toHaveTextContent("문서가 없거나 볼 권한이 없습니다");
  });

  it("삭제는 한 번 더 확인하고 목록으로 돌아간다", async () => {
    const user = userEvent.setup();
    const { sent, router } = show("/documents/27", {
      "GET /admin/api/documents/27": UPLOADED,
      "GET /admin/api/documents/27/changes": [],
      "GET /admin/api/org": ORG,
      "GET /admin/api/documents": [],
      "DELETE /admin/api/documents/27": undefined,
    });

    await user.click(await screen.findByRole("button", { name: "삭제" }));
    expect(sent.some((s) => s.method === "DELETE")).toBe(false);
    await user.click(screen.getByRole("button", { name: "UP-0027 삭제 확인" }));

    expect(await screen.findByRole("heading", { name: "문서" })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/documents");
    expect(sent.filter((s) => s.method === "DELETE").map((s) => s.path)).toEqual([
      "/admin/api/documents/27",
    ]);
  });
});

describe("문서 올리기", () => {
  it("파일을 고르면 제목을 채우고, 확인 뒤 좁은 기본 권한으로 올린다", async () => {
    const user = userEvent.setup();
    const { sent, router } = show("/documents/new", {
      "GET /admin/api/org": ORG,
      "POST /admin/api/documents/access-preview": {
        ...PREVIEW,
        count: 2,
        users: PREVIEW.users.slice(0, 2),
      },
      "POST /admin/api/documents": UPLOADED,
      "GET /admin/api/documents/27": UPLOADED,
      "GET /admin/api/documents/27/changes": [],
    });

    expect(await screen.findByRole("button", { name: "받는 사람 확인" })).toBeDisabled();
    await user.upload(
      screen.getByLabelText("올릴 파일"),
      new File(["# 회의실"], "회의실_예약.md", { type: "text/markdown" }),
    );
    expect(screen.getByLabelText("제목")).toHaveValue("회의실 예약");
    expect(await screen.findByText("명이 볼 수 있습니다")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "받는 사람 확인" }));
    await user.click(screen.getByRole("button", { name: "이 명단으로 올리기" }));

    expect(await screen.findByText(/올렸습니다/)).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/documents/27");
    const upload = sent.find((s) => s.method === "POST" && s.path === "/admin/api/documents");
    expect(upload?.form).toEqual({
      file: ["file:회의실_예약.md"],
      title: ["회의실 예약"],
      security_level: ["1"],
      departments: ["개발팀"],
    });
  });

  it("서버가 거절하면 이유를 보여 주고 다시 고칠 수 있다", async () => {
    const user = userEvent.setup();
    show("/documents/new", {
      "GET /admin/api/org": ORG,
      "POST /admin/api/documents/access-preview": PREVIEW,
      "POST /admin/api/documents": new Response(
        JSON.stringify({ detail: "같은 이름의 문서가 이미 있습니다" }),
        { status: 409 },
      ),
    });

    await user.upload(
      await screen.findByLabelText("올릴 파일"),
      new File(["x"], "규칙.md", { type: "text/markdown" }),
    );
    await screen.findByText("명이 볼 수 있습니다");
    await user.click(screen.getByRole("button", { name: "받는 사람 확인" }));
    await user.click(screen.getByRole("button", { name: "이 명단으로 올리기" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("같은 이름의 문서가 이미 있습니다");
    expect(screen.getByRole("button", { name: "받는 사람 확인" })).toBeEnabled();
  });

  it("중앙 관리자는 관리 부서를 고른다", async () => {
    const user = userEvent.setup();
    const { sent } = show(
      "/documents/new",
      {
        "GET /admin/api/org": ORG,
        "POST /admin/api/documents/access-preview": PREVIEW,
        "POST /admin/api/documents": UPLOADED,
        "GET /admin/api/documents/27": UPLOADED,
        "GET /admin/api/documents/27/changes": [],
      },
      me(["admin"]),
    );

    await user.selectOptions(await screen.findByLabelText("관리 부서"), "인사팀");
    await user.upload(screen.getByLabelText("올릴 파일"), new File(["x"], "a.md"));
    await screen.findByText("명이 볼 수 있습니다");
    await user.click(screen.getByRole("button", { name: "받는 사람 확인" }));
    await user.click(screen.getByRole("button", { name: "이 명단으로 올리기" }));

    await screen.findByText(/올렸습니다/);
    expect(sent.find((s) => s.path === "/admin/api/documents")?.form?.owner_department).toEqual([
      "인사팀",
    ]);
  });
});

describe("문서 목록", () => {
  it("찾기와 결과 수, 맞는 문서가 없을 때", async () => {
    const user = userEvent.setup();
    show("/documents", { "GET /admin/api/documents": [documentRow(), UPLOADED] });

    expect(await screen.findByText("2건")).toBeInTheDocument();
    await user.type(screen.getByRole("searchbox"), "회의실");
    expect(screen.getByText("2건 중 1건")).toBeInTheDocument();
    await user.clear(screen.getByRole("searchbox"));
    await user.type(screen.getByRole("searchbox"), "없는 문서");
    expect(screen.getByText(/조건에 맞는 문서가 없습니다/)).toBeInTheDocument();
  });
});
