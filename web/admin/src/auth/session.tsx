// 로그인 상태. 서버 설정(/admin/api/config)에 따라 두 방식 중 하나로 로그인한다.
// - oidc: 회사 로그인 시스템으로 이동해 로그인하고 돌아온다 (authorization code + PKCE).
//   토큰은 탭을 닫으면 사라지는 sessionStorage에 둔다.
// - dev_header: 개발·데모 전용. 로그인 id와 그룹을 직접 고른다 (서버도 그대로 믿는다).
import { UserManager, WebStorageStateStore } from "oidc-client-ts";
import { createContext, type ReactNode, useContext, useEffect, useMemo, useState } from "react";
import { type Api, ApiError, createApi, type HeaderSource } from "../api/client";
import type { Me, UiConfig } from "../api/types";

export const DEV_STORAGE_KEY = "rag-admin-dev-identity";
const BASE = "/admin/";

export type DevIdentity = { login: string; groups: string };

export type Session =
  | { state: "loading" }
  | { state: "error"; message: string }
  | { state: "signed-out"; config: UiConfig; signIn: (dev?: DevIdentity) => void }
  | {
      state: "signed-in";
      config: UiConfig;
      me: Me;
      headers: HeaderSource;
      signOut: () => void;
    };

const SessionContext = createContext<Session>({ state: "loading" });

export function useSession(): Session {
  return useContext(SessionContext);
}

export function readDevIdentity(): DevIdentity | null {
  try {
    const raw = sessionStorage.getItem(DEV_STORAGE_KEY);
    return raw ? (JSON.parse(raw) as DevIdentity) : null;
  } catch {
    return null;
  }
}

/** 회사 로그인(OIDC) 관리자. base는 화면의 시작 주소 (관리 화면 /admin/, 채팅 화면 /). */
export function oidcManager(config: UiConfig, base: string = BASE): UserManager | null {
  if (config.auth_mode !== "oidc" || !config.oidc) return null;
  const origin = window.location.origin;
  return new UserManager({
    authority: config.oidc.authority,
    client_id: config.oidc.client_id,
    scope: config.oidc.scopes,
    redirect_uri: `${origin}${base}callback`,
    post_logout_redirect_uri: `${origin}${base}`,
    userStore: new WebStorageStateStore({ store: window.sessionStorage }),
  });
}

async function loadSession(setSession: (s: Session) => void): Promise<void> {
  const configResponse = await fetch("/admin/api/config");
  if (!configResponse.ok) throw new ApiError(configResponse.status, "설정을 읽지 못했습니다.");
  const config = (await configResponse.json()) as UiConfig;
  if (config.auth_mode === "disabled") {
    setSession({
      state: "error",
      message: "로그인 방식이 설정되지 않았습니다. 서버의 AUTH_MODE를 oidc로 설정해 주세요.",
    });
    return;
  }

  const manager = oidcManager(config);
  if (manager && window.location.pathname === `${BASE}callback`) {
    let user: Awaited<ReturnType<UserManager["signinRedirectCallback"]>>;
    try {
      user = await manager.signinRedirectCallback();
    } catch {
      throw new Error(
        "회사 로그인에서 돌아오는 중 토큰을 받지 못했습니다. 로그인 서버가 이 화면 주소를 허용하는지" +
          "(웹 출처, 리디렉션 주소) 확인해 주세요.",
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

  const signIn = (dev?: DevIdentity) => {
    if (manager) {
      const here = window.location.pathname + window.location.search;
      void manager.signinRedirect({ state: here === `${BASE}callback` ? BASE : here });
    } else if (dev) {
      sessionStorage.setItem(DEV_STORAGE_KEY, JSON.stringify(dev));
      window.location.reload();
    }
  };

  if (!headers) {
    setSession({ state: "signed-out", config, signIn });
    return;
  }
  try {
    const me = await createApi(headers).get<Me>("/admin/api/me");
    setSession({ state: "signed-in", config, me, headers, signOut });
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      setSession({ state: "signed-out", config, signIn });
      return;
    }
    throw error;
  }
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session>({ state: "loading" });
  useEffect(() => {
    loadSession(setSession).catch((error: unknown) => {
      const message = error instanceof Error ? error.message : "로그인 상태를 확인하지 못했습니다.";
      setSession({ state: "error", message });
    });
  }, []);
  return <SessionContext.Provider value={session}>{children}</SessionContext.Provider>;
}

/** 테스트와 미리 보기에서 정해 둔 세션을 넣는다. */
export function StaticSession({ value, children }: { value: Session; children: ReactNode }) {
  const memo = useMemo(() => value, [value]);
  return <SessionContext.Provider value={memo}>{children}</SessionContext.Provider>;
}

/** 로그인한 사람의 머리글을 붙이는 API 클라이언트. 로그인 전에는 쓰지 않는다. */
export function useApiClient(): Api {
  const session = useSession();
  const headers = session.state === "signed-in" ? session.headers : null;
  return useMemo(
    () =>
      createApi(
        headers ??
          (async () => {
            throw new ApiError(401, "로그인이 필요합니다.");
          }),
      ),
    [headers],
  );
}
