// 채팅 작업 공간의 공유 상태: 지금 묻는 질문(실시간 답), 오늘 남은 질문 수, 기록 목록 새로고침.
// 기록 화면(/history/:id)에서 새로 물어도 첫 화면(/)으로 돌아와 답을 받는다.
import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { ApiError, createApi, type HeaderSource } from "../api/client";
import { askQuestion } from "./ask";
import type { Answer, ChatMe, Usage } from "./types";

export type LiveTurn =
  | { status: "idle" }
  | { status: "streaming"; question: string; text: string }
  | { status: "done"; question: string; answer: Answer; at: Date }
  | { status: "failed"; question: string; text: string; message: string };

type Workspace = {
  me: ChatMe;
  headers: HeaderSource;
  api: ReturnType<typeof createApi>;
  live: LiveTurn;
  ask: (question: string) => Promise<void>;
  reset: () => void;
  usage: Usage | null;
  historyRound: number; // 바뀌면 기록 목록을 다시 읽는다
  refreshHistory: () => void;
};

const WorkspaceContext = createContext<Workspace | null>(null);

export function useWorkspace(): Workspace {
  const value = useContext(WorkspaceContext);
  if (!value) throw new Error("WorkspaceProvider 밖에서 썼습니다");
  return value;
}

export function WorkspaceProvider({
  me,
  headers,
  fetcher,
  children,
}: {
  me: ChatMe;
  headers: HeaderSource;
  fetcher?: typeof fetch;
  children: ReactNode;
}) {
  const api = useMemo(() => createApi(headers, fetcher), [headers, fetcher]);
  const [live, setLive] = useState<LiveTurn>({ status: "idle" });
  const [usage, setUsage] = useState<Usage | null>(null);
  const [historyRound, setHistoryRound] = useState(0);
  const refreshHistory = useCallback(() => setHistoryRound((n) => n + 1), []);

  const loadUsage = useCallback(() => {
    api
      .get<Usage>("/api/usage")
      .then(setUsage)
      .catch(() => setUsage(null)); // 남은 수를 못 읽어도 질문은 할 수 있다
  }, [api]);
  useEffect(loadUsage, [loadUsage]);

  const ask = useCallback(
    async (question: string) => {
      let text = "";
      setLive({ status: "streaming", question, text });
      try {
        const outcome = await askQuestion(question, {
          headers,
          ...(fetcher ? { fetcher } : {}),
          onDelta: (piece) => {
            text += piece;
            setLive({ status: "streaming", question, text });
          },
        });
        setLive(
          outcome.kind === "done"
            ? { status: "done", question, answer: outcome.answer, at: new Date() }
            : { status: "failed", question, text, message: outcome.message },
        );
      } catch (error) {
        const message =
          error instanceof ApiError || error instanceof Error
            ? error.message
            : "질문을 보내지 못했습니다.";
        setLive({ status: "failed", question, text, message });
      }
      loadUsage();
      refreshHistory();
    },
    [headers, fetcher, loadUsage, refreshHistory],
  );

  const reset = useCallback(() => setLive({ status: "idle" }), []);

  const value = useMemo(
    () => ({ me, headers, api, live, ask, reset, usage, historyRound, refreshHistory }),
    [me, headers, api, live, ask, reset, usage, historyRound, refreshHistory],
  );
  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}
