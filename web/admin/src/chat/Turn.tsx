// 가운데(질문과 답, 입력창)와 오른쪽(근거 문단) 두 칸. 첫 화면(/)은 지금 묻는 질문을,
// 기록 화면(/history/:id)은 저장된 질문을 보여 준다.
import { type ReactNode, useCallback, useState } from "react";
import { useNavigate, useParams } from "react-router";
import { useLoad } from "../api/useApi";
import { type AnswerState, AnswerView } from "./AnswerView";
import { Composer } from "./Composer";
import { whenText } from "./Rail";
import { Sources } from "./Sources";
import styles from "./Turn.module.css";
import type { Answer, Citation, Turn } from "./types";
import { useWorkspace } from "./workspace";

function metaOf(at: string, answer: Answer | null): string {
  const parts = [whenText(at)];
  if (answer) {
    if (answer.refused) parts.push("근거를 찾지 못함");
    else {
      const sources = new Set(answer.citations.map((c) => c.number)).size;
      parts.push(`근거 ${sources}건`);
      if (answer.verification) {
        parts.push(answer.verification.verified ? "인용 확인됨" : "확인 안 된 문장 있음");
      }
    }
  }
  return parts.join(" · ");
}

function useAskHere() {
  const { ask } = useWorkspace();
  const navigate = useNavigate();
  return useCallback(
    (question: string) => {
      navigate("/");
      void ask(question);
    },
    [ask, navigate],
  );
}

function TurnLayout({
  render,
  citations,
  waiting,
  centered = false,
}: {
  render: (linking: {
    active: number | null;
    onHover: (n: number | null) => void;
    onJump: (n: number) => void;
  }) => ReactNode;
  citations: Citation[];
  waiting: boolean;
  /** 첫 방문: 입력창이 가운데 안내 아래에 있으므로 아래 고정 입력창을 두지 않는다 */
  centered?: boolean;
}) {
  const askHere = useAskHere();
  // 마우스·초점이 가리키는 번호가 먼저이고, 없으면 마지막으로 눌러 옮겨 간 번호를 진하게 둔다
  const [hover, setHover] = useState<number | null>(null);
  const [focus, setFocus] = useState<{ number: number; round: number } | null>(null);
  const active = hover ?? focus?.number ?? null;
  const onJump = (number: number) => {
    setFocus((current) => ({ number, round: (current?.round ?? 0) + 1 }));
  };
  return (
    <div className={styles.layout}>
      <div className={styles.conversation}>
        <div className={styles.scroll}>{render({ active, onHover: setHover, onJump })}</div>
        {centered ? null : (
          <div className={styles.composer}>
            <Composer onAsk={askHere} />
          </div>
        )}
      </div>
      <div className={styles.sources}>
        <Sources
          citations={citations}
          active={active}
          focus={focus}
          onHover={setHover}
          waiting={waiting}
        />
      </div>
    </div>
  );
}

/** 첫 방문: 가운데에 인사와 입력창, 그 아래 안내 한 줄 (입력창의 도움말). */
function Welcome() {
  const { me } = useWorkspace();
  const askHere = useAskHere();
  return (
    <section className={styles.welcome} aria-labelledby="welcome">
      <h1 id="welcome">{me.name} 님, 무엇이 궁금한가요?</h1>
      <Composer onAsk={askHere} />
    </section>
  );
}

export function NewQuestion() {
  const { live, ask } = useWorkspace();
  const answer = live.status === "done" ? live.answer : null;
  return (
    <TurnLayout
      citations={answer?.citations ?? []}
      waiting={live.status === "streaming" || live.status === "idle"}
      centered={live.status === "idle"}
      render={(linking) => {
        if (live.status === "idle") return <Welcome />;
        let state: AnswerState;
        let meta: string;
        if (live.status === "streaming") {
          state = { kind: "streaming", text: live.text };
          meta = "답을 쓰는 중";
        } else if (live.status === "done") {
          state = { kind: "answer", answer: live.answer };
          meta = metaOf(live.at.toISOString(), live.answer);
        } else {
          state = {
            kind: "failed",
            text: live.text,
            message: live.message,
            onRetry: () => void ask(live.question),
          };
          meta = "답하지 못함";
        }
        return <AnswerView question={live.question} meta={meta} state={state} linking={linking} />;
      }}
    />
  );
}

function ForgetTurn({ id }: { id: number }) {
  const { api, refreshHistory } = useWorkspace();
  const navigate = useNavigate();
  const [asking, setAsking] = useState(false);
  if (!asking) {
    return (
      <button type="button" className={styles.quiet} onClick={() => setAsking(true)}>
        이 기록 지우기
      </button>
    );
  }
  return (
    <fieldset className={styles.confirm}>
      <legend className="visually-hidden">기록 지우기 확인</legend>
      <span>이 질문과 답을 내 기록에서 지울까요?</span>
      <button
        type="button"
        className={styles.danger}
        onClick={async () => {
          await api.delete(`/api/history/${id}`);
          refreshHistory();
          navigate("/");
        }}
      >
        지우기
      </button>
      <button type="button" className={styles.quiet} onClick={() => setAsking(false)}>
        취소
      </button>
    </fieldset>
  );
}

export function SavedTurn() {
  const { api } = useWorkspace();
  const askHere = useAskHere();
  const id = Number(useParams().id);
  const load = useCallback(() => api.get<Turn>(`/api/history/${id}`), [api, id]);
  const turn = useLoad(load, Number.isInteger(id));
  const answer = turn.state === "ready" ? turn.data.answer : null;
  return (
    <TurnLayout
      citations={answer?.citations ?? []}
      waiting={turn.state === "loading"}
      render={(linking) => {
        if (turn.state === "loading") return <p className={styles.loading}>기록을 불러오는 중…</p>;
        if (turn.state === "error") {
          return (
            <section className={styles.welcome}>
              <h1>기록을 열 수 없습니다</h1>
              <p>
                {turn.status === 404 ? "이미 지웠거나 보관 기간이 지난 기록입니다." : turn.message}
              </p>
            </section>
          );
        }
        const data = turn.data;
        const state: AnswerState =
          data.hidden || !data.answer
            ? { kind: "hidden", onRetry: () => askHere(data.question) }
            : { kind: "answer", answer: data.answer };
        return (
          <AnswerView
            question={data.question}
            meta={metaOf(data.created_at, data.answer)}
            state={state}
            linking={linking}
            actions={<ForgetTurn id={data.id} />}
          />
        );
      }}
    />
  );
}
