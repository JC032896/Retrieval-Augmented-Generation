// 채팅 화면의 로그인 상태. 관리 화면과 같은 회사 로그인을 쓴다 (auth/session.tsx의 부품을 함께 쓴다).
// - oidc: 회사 로그인으로 갔다가 /callback으로 돌아온다. 토큰은 탭을 닫으면 사라진다.
// - dev_header: 개발·데모 전용. 로그인 id를 직접 고른다 (관리 화면에서 고른 사람도 그대로 쓴다).
import { createContext, type ReactNode, useContext, useEffect, useMemo, useState } from "react";
import { ApiError, createApi, type HeaderSource } from "../api/client";
import type { UiConfig } from "../api/types";
import { DEV_STORAGE_KEY, oidcManager, readDevIdentity } from "../auth/session";
import type { ChatMe } from "./types";

const BASE = "/";

export type ChatSession =
  | { state: "loading" }
  | { state: "error"; message: string }
  | { state: "signed-out"; config: UiConfig; signIn: (login?: string) => void }
  | {
      state: "signed-in";
      config: UiConfig;
      me: ChatMe;
      headers: HeaderSource;
      signOut: () => void;
    };

const SessionContext = createContext<ChatSession>({ state: "loading" });

export function useChatSession(): ChatSession {
  return useContext(SessionContext);
}

async function loadSession(setSession: (s: ChatSession) => void): Promise<void> {
  const configResponse = await fetch("/api/config");
  if (!configResponse.ok) throw new ApiError(configResponse.status, "설정을 읽지 못했습니다.");
  const config = (await configResponse.json()) as UiConfig;
  if (config.auth_mode === "disabled") {
    setSession({
      state: "error",
      message: "로그인 방식이 설정되지 않았습니다. 관리자에게 알려 주세요 (서버 설정 AUTH_MODE).",
    });
    return;
  }

  const manager = oidcManager(config, BASE);
  if (manager && window.location.pathname === `${BASE}callback`) {
    let user: Awaited<ReturnType<typeof manager.signinRedirectCallback>>;
    try {
      user = await manager.signinRedirectCallback();
    } catch {
      throw new Error(
        "회사 로그인에서 돌아오는 중 토큰을 받지 못했습니다. 관리자에게 로그인 서버가 이 주소를 " +
          "허용하는지(웹 출처, 리디렉션 주소) 확인해 달라고 알려 주세요.",
      );
    }
    const back = typeof user.state === "string" ? user.state : BASE;
    window.history.replaceState(null, "", back);
  }

  let headers: HeaderSource | null = null;
  let signOut = () => {};
  if (manager) {
    const user = await manager.getUser();
    if (user && !user.expired) {
      headers = async () => ({ Authorization: `Bearer ${user.access_token}` });
      signOut = () => void manager.signoutRedirect();
    }
  } else {
    const dev = readDevIdentity();
    if (dev) {
      headers = async () => ({ "X-User-Id": dev.login, "X-User-Groups": dev.groups });
      signOut = () => {
        sessionStorage.removeItem(DEV_STORAGE_KEY);
        window.location.assign(BASE);
      };
    }
  }

  const signIn = (login?: string) => {
    if (manager) {
      const here = window.location.pathname + window.location.search;
      void manager.signinRedirect({ state: here === `${BASE}callback` ? BASE : here });
    } else if (login) {
      sessionStorage.setItem(DEV_STORAGE_KEY, JSON.stringify({ login, groups: "" }));
      window.location.reload();
    }
  };

  if (!headers) {
    setSession({ state: "signed-out", config, signIn });
    return;
  }
  try {
    const me = await createApi(headers).get<ChatMe>("/api/me");
    setSession({ state: "signed-in", config, me, headers, signOut });
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      setSession({ state: "signed-out", config, signIn });
      return;
    }
    throw error;
  }
}

export function ChatSessionProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<ChatSession>({ state: "loading" });
  useEffect(() => {
    loadSession(setSession).catch((error: unknown) => {
      const message = error instanceof Error ? error.message : "로그인 상태를 확인하지 못했습니다.";
      setSession({ state: "error", message });
    });
  }, []);
  return <SessionContext.Provider value={session}>{children}</SessionContext.Provider>;
}

/** 테스트에서 정해 둔 세션을 넣는다. */
export function StaticChatSession({
  value,
  children,
}: {
  value: ChatSession;
  children: ReactNode;
}) {
  const memo = useMemo(() => value, [value]);
  return <SessionContext.Provider value={memo}>{children}</SessionContext.Provider>;
}
