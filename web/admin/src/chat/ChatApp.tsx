// 채팅 화면의 갈림길: 로그인 상태, 화면 주소(/, /history/:id), 좁은 화면의 목록 열기.
import { type ReactNode, useEffect, useState } from "react";
import { createBrowserRouter, Outlet, RouterProvider, useLocation } from "react-router";
import styles from "./ChatApp.module.css";
import { Rail } from "./Rail";
import { ChatSignIn } from "./SignIn";
import { type ChatSession, useChatSession } from "./session";
import { NewQuestion, SavedTurn } from "./Turn";
import { WorkspaceProvider } from "./workspace";

type SignedIn = Extract<ChatSession, { state: "signed-in" }>;

/** 왼쪽 목록칸 + 오른쪽 작업 칸. 좁은 화면에서는 위 막대의 '지난 질문'으로 목록을 연다. */
export function Workspace({ session, children }: { session: SignedIn; children?: ReactNode }) {
  const [open, setOpen] = useState(false);
  const location = useLocation();
  useEffect(() => {
    void location.pathname;
    setOpen(false); // 다른 기록으로 옮기면 목록을 닫는다
  }, [location.pathname]);
  const name = session.config.company_name || "사내 문서 질의";
  return (
    <div className={styles.workspace}>
      <header className={styles.bar}>
        <span className={styles.barName}>{name}</span>
        <button
          type="button"
          className={styles.barButton}
          aria-expanded={open}
          aria-controls="chat-rail"
          onClick={() => setOpen((v) => !v)}
        >
          {open ? "닫기" : "지난 질문"}
        </button>
      </header>
      <div id="chat-rail" className={`${styles.rail} ${open ? styles.open : ""}`}>
        <Rail
          companyName={session.config.company_name}
          logo={session.config.company_logo_url}
          onSignOut={session.signOut}
        />
      </div>
      <main className={styles.main}>{children ?? <Outlet />}</main>
    </div>
  );
}

function SignedInApp({ session }: { session: SignedIn }) {
  const [router] = useState(() =>
    createBrowserRouter([
      {
        path: "/",
        element: <Workspace session={session} />,
        children: [
          { index: true, element: <NewQuestion /> },
          { path: "history/:id", element: <SavedTurn /> },
          { path: "*", element: <NewQuestion /> },
        ],
      },
    ]),
  );
  return (
    <WorkspaceProvider me={session.me} headers={session.headers}>
      <RouterProvider router={router} />
    </WorkspaceProvider>
  );
}

function Message({ title, children }: { title: string; children: ReactNode }) {
  return (
    <main className={styles.message}>
      <h1>{title}</h1>
      {children}
    </main>
  );
}

export function ChatApp() {
  const session = useChatSession();
  useEffect(() => {
    const name =
      session.state === "signed-in" || session.state === "signed-out"
        ? session.config.company_name
        : "";
    document.title = name ? `${name} 문서 질의` : "사내 문서 질의";
  }, [session]);
  if (session.state === "loading") {
    return (
      <Message title="불러오는 중">
        <p>로그인 상태를 확인하고 있습니다.</p>
      </Message>
    );
  }
  if (session.state === "error") {
    return (
      <Message title="화면을 열 수 없습니다">
        <p>{session.message}</p>
        <button type="button" className={styles.reload} onClick={() => window.location.reload()}>
          다시 열기
        </button>
      </Message>
    );
  }
  if (session.state === "signed-out") {
    return <ChatSignIn config={session.config} onSignIn={session.signIn} />;
  }
  return <SignedInApp session={session} />;
}
