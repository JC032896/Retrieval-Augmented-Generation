// 화면이 API 응답 하나를 읽는 방법: 불러오는 중, 오류, 결과 세 상태. reload로 다시 읽는다.
import { useCallback, useEffect, useState } from "react";
import { ApiError } from "./client";

export type Loadable<T> =
  | { state: "loading" }
  | { state: "error"; message: string; status: number }
  | { state: "ready"; data: T };

export function errorText(error: unknown): { message: string; status: number } {
  return {
    message: error instanceof Error ? error.message : "요청이 실패했습니다.",
    status: error instanceof ApiError ? error.status : 0,
  };
}

export function useLoad<T>(
  load: () => Promise<T>,
  enabled = true,
): Loadable<T> & { reload: () => void } {
  const [result, setResult] = useState<Loadable<T>>({ state: "loading" });
  const [round, setRound] = useState(0);
  const reload = useCallback(() => setRound((n) => n + 1), []);
  // round가 바뀌면(reload) 다시 읽는다
  useEffect(() => {
    if (!enabled) return;
    let alive = true;
    void round;
    load()
      .then((data) => alive && setResult({ state: "ready", data }))
      .catch((error: unknown) => alive && setResult({ state: "error", ...errorText(error) }));
    return () => {
      alive = false;
    };
  }, [load, enabled, round]);
  return { ...result, reload };
}
