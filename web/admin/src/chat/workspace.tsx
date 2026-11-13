// 채팅 작업 공간의 공유 상태: 지금 보고 있는 대화(질문과 답들), 오늘 남은 질문 수, 목록 새로고침.
// 한 대화에서 이어 물으면 앞 질문들을 함께 보내고, 서버는 그 질문들로 새 질문을 다시 써서 검색한다.
// 대화의 첫 질문이 끝나면 서버가 정한 대화 id로 주소(/history/:id)를 바꾼다.
import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { ApiError, createApi, type HeaderSource } from "../api/client";
import { askQuestion } from "./ask";
import type { Answer, ChatMe, Conversation, Usage } from "./types";

/** 대화 속 질문 하나와 그 답의 상태. */
export type TurnState =
  | { status: "streaming"; text: string }
  | { status: "done"; answer: Answer }
  | { status: "failed"; text: string; message: string }
  | { status: "hidden" };

export type TurnView = {
  key: string; // 화면 안의 고유 값 (저장된 질문은 "t<id>")
  question: string;
  at: string; // ISO 시각
  state: TurnState;
};

export type ConversationView = {
  id: number | null; // 아직 저장되지 않았거나 기록을 두지 않는 설치면 null
  turns: TurnView[];
};

type Workspace = {
  me: ChatMe;
  headers: HeaderSource;
  api: ReturnType<typeof createApi>;
  conversation: ConversationView;
  /** 지금 대화에 질문을 붙인다. 새 대화의 첫 질문이면 끝난 뒤 onStarted에 대화 id를 준다 */
  ask: (question: string, onStarted?: (id: number) => void) => Promise<void>;
  /** 저장된 대화를 연다 (이미 열려 있으면 다시 읽지 않는다) */
  open: (id: number) => Promise<"ok" | "missing" | "failed">;
  reset: () => void;
  busy: boolean;
  usage: Usage | null;
  historyRound: number; // 바뀌면 대화 목록을 다시 읽는다
  refreshHistory: () => void;
};

const WorkspaceContext = createContext<Workspace | null>(null);

export function useWorkspace(): Workspace {
  const value = useContext(WorkspaceContext);
  if (!value) throw new Error("WorkspaceProvider 밖에서 썼습니다");
  return value;
}

const EMPTY: ConversationView = { id: null, turns: [] };

function fromSaved(saved: Conversation): ConversationView {
  return {
    id: saved.id,
    turns: saved.turns.map((turn) => ({
      key: `t${turn.id}`,
      question: turn.question,
      at: turn.created_at,
      state:
        turn.hidden || !turn.answer
          ? { status: "hidden" }
          : { status: "done", answer: turn.answer },
    })),
  };
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
  const [conversation, setConversation] = useState<ConversationView>(EMPTY);
  // 비동기 작업이 끝난 뒤 '지금의' 대화를 읽기 위한 사본
  const current = useRef<ConversationView>(EMPTY);
  const [busy, setBusy] = useState(false);
  const [usage, setUsage] = useState<Usage | null>(null);
  const [historyRound, setHistoryRound] = useState(0);
  const refreshHistory = useCallback(() => setHistoryRound((n) => n + 1), []);
  const counter = useRef(0);

  const update = useCallback((next: (view: ConversationView) => ConversationView) => {
    current.current = next(current.current);
    setConversation(current.current);
  }, []);

  const loadUsage = useCallback(() => {
    api
      .get<Usage>("/api/usage")
      .then(setUsage)
      .catch(() => setUsage(null)); // 남은 수를 못 읽어도 질문은 할 수 있다
  }, [api]);
  useEffect(loadUsage, [loadUsage]);

  const setTurn = useCallback(
    (key: string, state: TurnState) =>
      update((view) => ({
        ...view,
        turns: view.turns.map((turn) => (turn.key === key ? { ...turn, state } : turn)),
      })),
    [update],
  );

  const ask = useCallback(
    async (question: string, onStarted?: (id: number) => void) => {
      counter.current += 1;
      const key = `live${counter.current}`;
      const before = current.current;
      const previous = before.turns.map((turn) => turn.question);
      update((view) => ({
        ...view,
        turns: [
          ...view.turns,
          { key, question, at: new Date().toISOString(), state: { status: "streaming", text: "" } },
        ],
      }));
      setBusy(true);
      let text = "";
      let started: number | null = null;
      try {
        const outcome = await askQuestion(question, {
          headers,
          ...(fetcher ? { fetcher } : {}),
          conversation: { id: before.id, previous },
          onConversation: (id) => {
            started = id;
            if (id !== null) update((view) => ({ ...view, id }));
          },
          onDelta: (piece) => {
            text += piece;
            setTurn(key, { status: "streaming", text });
          },
        });
        setTurn(
          key,
          outcome.kind === "done"
            ? { status: "done", answer: outcome.answer }
            : { status: "failed", text, message: outcome.message },
        );
      } catch (error) {
        const message =
          error instanceof ApiError || error instanceof Error
            ? error.message
            : "질문을 보내지 못했습니다.";
        setTurn(key, { status: "failed", text, message });
      }
      setBusy(false);
      loadUsage();
      refreshHistory();
      if (started !== null && before.id === null) onStarted?.(started);
    },
    [headers, fetcher, update, setTurn, loadUsage, refreshHistory],
  );

  const open = useCallback(
    async (id: number) => {
      if (current.current.id === id) return "ok" as const;
      try {
        const saved = await api.get<Conversation>(`/api/conversations/${id}`);
        update(() => fromSaved(saved));
        return "ok" as const;
      } catch (error) {
        return error instanceof ApiError && error.status === 404
          ? ("missing" as const)
          : ("failed" as const);
      }
    },
    [api, update],
  );

  const reset = useCallback(() => update(() => EMPTY), [update]);

  const value = useMemo(
    () => ({
      me,
      headers,
      api,
      conversation,
      ask,
      open,
      reset,
      busy,
      usage,
      historyRound,
      refreshHistory,
    }),
    [me, headers, api, conversation, ask, open, reset, busy, usage, historyRound, refreshHistory],
  );
  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}
