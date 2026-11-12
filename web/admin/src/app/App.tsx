// 화면 주소와 로그인 상태에 따른 갈림길.
import { type ReactNode, useMemo } from "react";
import { createBrowserRouter, Navigate, Outlet, RouterProvider } from "react-router";
import type { Me } from "../api/types";
import { useSession } from "../auth/session";
import { Audit } from "../pages/Audit";
import { AuditDetail } from "../pages/AuditDetail";
import { Dashboard } from "../pages/Dashboard";
import { DocumentDetail } from "../pages/DocumentDetail";
import { DocumentNew } from "../pages/DocumentNew";
import { Documents } from "../pages/Documents";
import { Notice } from "../pages/Notice";
import { Settings } from "../pages/Settings";
import { SignIn } from "../pages/SignIn";
import { Users } from "../pages/Users";
import { visibleNav } from "./nav";
import { Shell } from "./Shell";

function NoRole({ me }: { me: Me }) {
  return (
    <Notice title="관리 권한이 없습니다">
      <p>
        {me.name}({me.department}) 님은 로그인되었지만 관리 역할 그룹에 들어 있지 않습니다. 회사
        로그인 시스템 담당자에게 중앙 관리자, 부서 문서 담당, 감사 담당 중 필요한 그룹을 요청해
        주세요.
      </p>
    </Notice>
  );
}

function Signed({ me }: { me: Me }) {
  const session = useSession();
  if (session.state !== "signed-in") return null;
  return (
    <Shell config={session.config} me={me} onSignOut={session.signOut}>
      {me.roles.length === 0 ? <NoRole me={me} /> : <Outlet />}
    </Shell>
  );
}

function Forbidden() {
  return (
    <Notice title="이 화면을 볼 권한이 없습니다" tone="blocked">
      <p>역할에 맞는 메뉴만 왼쪽에 보입니다.</p>
    </Notice>
  );
}

function routes(me: Me) {
  const allowed = new Set(visibleNav(me.roles).map((item) => item.path));
  const only = (path: string, element: ReactNode) => (allowed.has(path) ? element : <Forbidden />);
  return createBrowserRouter(
    [
      {
        path: "/",
        element: <Signed me={me} />,
        children: [
          { index: true, element: <Dashboard me={me} /> },
          { path: "documents", element: only("/documents", <Documents me={me} />) },
          { path: "documents/new", element: only("/documents", <DocumentNew me={me} />) },
          { path: "documents/:id", element: only("/documents", <DocumentDetail />) },
          { path: "users", element: only("/users", <Users />) },
          { path: "audit", element: only("/audit", <Audit />) },
          { path: "audit/:id", element: only("/audit", <AuditDetail />) },
          { path: "settings", element: only("/settings", <Settings />) },
          { path: "callback", element: <Navigate to="/" replace /> },
          {
            path: "*",
            element: (
              <Notice title="없는 화면입니다">
                <p>왼쪽 메뉴에서 화면을 골라 주세요.</p>
              </Notice>
            ),
          },
        ],
      },
    ],
    { basename: "/admin" },
  );
}

function SignedRouter({ me }: { me: Me }) {
  const router = useMemo(() => routes(me), [me]);
  return <RouterProvider router={router} />;
}

export function App() {
  const session = useSession();
  switch (session.state) {
    case "loading":
      return <p className="visually-hidden">로그인 상태를 확인하는 중입니다…</p>;
    case "error":
      return (
        <main style={{ padding: "var(--space-6)" }}>
          <Notice title="관리 화면을 열 수 없습니다" tone="blocked">
            <p>{session.message}</p>
            <p>
              <a href="/admin/">처음부터 다시 열기</a>
            </p>
          </Notice>
        </main>
      );
    case "signed-out":
      return <SignIn config={session.config} onSignIn={session.signIn} />;
    case "signed-in":
      return <SignedRouter me={session.me} />;
  }
}
