// 화면이 API 응답 하나를 읽는 방법: 불러오는 중, 오류, 결과 세 상태.
import { useEffect, useState } from "react";
import { ApiError } from "./client";

export type Loadable<T> =
  | { state: "loading" }
  | { state: "error"; message: string; status: number }
  | { state: "ready"; data: T };

export function useLoad<T>(load: () => Promise<T>, enabled = true): Loadable<T> {
  const [result, setResult] = useState<Loadable<T>>({ state: "loading" });
  useEffect(() => {
    if (!enabled) return;
    let alive = true;
    load()
      .then((data) => alive && setResult({ state: "ready", data }))
      .catch((error: unknown) => {
        if (!alive) return;
        const status = error instanceof ApiError ? error.status : 0;
        const message = error instanceof Error ? error.message : "불러오지 못했습니다.";
        setResult({ state: "error", message, status });
      });
    return () => {
      alive = false;
    };
  }, [load, enabled]);
  return result;
}
