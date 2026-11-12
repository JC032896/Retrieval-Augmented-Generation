// 화면 주소와 로그인 상태에 따른 갈림길.
import { createBrowserRouter, Navigate, Outlet, RouterProvider } from "react-router";
import type { Me } from "../api/types";
import { useSession } from "../auth/session";
import { Dashboard } from "../pages/Dashboard";
import { Notice } from "../pages/Notice";
import { SignIn } from "../pages/SignIn";
import { NAV, visibleNav } from "./nav";
import { Shell } from "./Shell";

// 다음 단계(B-5)에서 만드는 화면. 메뉴는 미리 두고 무엇이 올지 알려 준다
const UPCOMING: Record<string, string> = {
  "/documents": "문서 목록, 올리기, 받는 사람을 확인하는 권한 지정, 배송조회 이력",
  "/users": "부서·역할·등급별 사용자 목록 (문서 폴더의 org.yaml에서 수집)",
  "/audit": "질문·답변 감사 기록 검색과 한 건의 근거 문서",
  "/settings": "답변 LLM, 사용 한도, 로그인 설정 확인",
};

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

function routes(me: Me) {
  const allowed = new Set(visibleNav(me.roles).map((item) => item.path));
  return createBrowserRouter(
    [
      {
        path: "/",
        element: <Signed me={me} />,
        children: [
          { index: true, element: <Dashboard me={me} /> },
          ...NAV.filter((item) => item.path !== "/").map((item) => ({
            path: item.path.slice(1),
            element: allowed.has(item.path) ? (
              <Notice title={`${item.label}: 다음 단계에서 엽니다`}>
                <p>{UPCOMING[item.path]}</p>
              </Notice>
            ) : (
              <Notice title="이 화면을 볼 권한이 없습니다" tone="blocked">
                <p>역할에 맞는 메뉴만 왼쪽에 보입니다.</p>
              </Notice>
            ),
          })),
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
      return <RouterProvider router={routes(session.me)} />;
  }
}
