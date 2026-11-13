// 가운데(한 대화의 질문과 답들, 아래 입력창)와 오른쪽(고른 답의 근거 문단) 두 칸.
// 첫 화면(/)은 새 대화, 기록 화면(/history/:id)은 저장된 대화다. 같은 대화에서 이어 물으면 아래에 쌓인다.
import { type ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router";
import { type AnswerState, AnswerView } from "./AnswerView";
import { Composer } from "./Composer";
import { whenText } from "./Rail";
import { Sources } from "./Sources";
import styles from "./Turn.module.css";
import type { Answer } from "./types";
import { type TurnView, useWorkspace } from "./workspace";

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

/** 지금 대화에 묻는다. 새 대화의 첫 질문이 저장되면 주소를 그 대화로 바꾼다. */
function useAsk() {
  const { ask } = useWorkspace();
  const navigate = useNavigate();
  return useCallback(
    (question: string) => {
      void ask(question, (id) => navigate(`/history/${id}`, { replace: true }));
    },
    [ask, navigate],
  );
}

function stateOf(turn: TurnView, retry: () => void): { state: AnswerState; meta: string } {
  switch (turn.state.status) {
    case "streaming":
      return { state: { kind: "streaming", text: turn.state.text }, meta: "답을 쓰는 중" };
    case "done":
      return {
        state: { kind: "answer", answer: turn.state.answer },
        meta: metaOf(turn.at, turn.state.answer),
      };
    case "failed":
      return {
        state: {
          kind: "failed",
          text: turn.state.text,
          message: turn.state.message,
          onRetry: retry,
        },
        meta: "답하지 못함",
      };
    case "hidden":
      return { state: { kind: "hidden", onRetry: retry }, meta: whenText(turn.at) };
  }
}

function Welcome() {
  const { me } = useWorkspace();
  const ask = useAsk();
  return (
    <section className={styles.welcome} aria-labelledby="welcome">
      <h1 id="welcome">{me.name} 님, 무엇이 궁금한가요?</h1>
      <Composer onAsk={ask} />
    </section>
  );
}

function EmptySources() {
  return <Sources citations={[]} active={null} focus={null} onHover={() => {}} waiting />;
}

/** 한 대화: 질문과 답들을 쌓고, 고른 답(기본은 마지막)의 근거를 오른쪽에 보인다. */
function ConversationLayout({ header }: { header?: ReactNode }) {
  const { conversation } = useWorkspace();
  const ask = useAsk();
  const turns = conversation.turns;
  // 근거 칸이 보여 주는 답. 새 질문이 붙으면 마지막 답으로 돌아간다
  const [selected, setSelected] = useState<string | null>(null);
  const [hover, setHover] = useState<number | null>(null);
  const [focus, setFocus] = useState<{ number: number; round: number } | null>(null);
  const [seen, setSeen] = useState(turns.length);
  const thread = useRef<HTMLDivElement>(null);
  if (seen !== turns.length) {
    setSeen(turns.length);
    setSelected(null);
    setFocus(null);
  }
  // 질문이 붙으면 그 질문이 가운데 칸 맨 위에 오게 한다. 답이 흘러 들어오는 동안에는 부드러운
  // 스크롤이 끊기므로 바로 옮긴다
  // 답이 끝나면 한 번 더 옮긴다 (붙인 순간에는 아래 내용이 짧아 맨 위까지 못 올라간다)
  const lastStatus = turns[turns.length - 1]?.state.status;
  useEffect(() => {
    void lastStatus;
    if (seen > 1) {
      const newest = thread.current?.lastElementChild;
      newest?.scrollIntoView?.({ block: "start" });
    }
  }, [seen, lastStatus]);

  const shown = turns.find((turn) => turn.key === selected) ?? turns[turns.length - 1];
  const citations = shown?.state.status === "done" ? shown.state.answer.citations : [];
  const active = hover ?? focus?.number ?? null;
  const position = shown ? turns.indexOf(shown) + 1 : 0;

  return (
    <div className={styles.layout}>
      <div className={styles.conversation}>
        <div className={styles.scroll}>
          <h1 className="visually-hidden">대화: {turns[0]?.question ?? ""}</h1>
          {header}
          <div ref={thread} className={styles.thread}>
            {turns.map((turn, index) => {
              const { state, meta } = stateOf(turn, () => ask(turn.question));
              const searchQuestion =
                turn.state.status === "done" ? (turn.state.answer.search_question ?? null) : null;
              return (
                <AnswerView
                  key={turn.key}
                  question={turn.question}
                  meta={turns.length > 1 ? `${index + 1}번째 질문 · ${meta}` : meta}
                  searchQuestion={searchQuestion}
                  state={state}
                  linking={{
                    active: turn === shown ? active : null,
                    onHover: (number) => {
                      if (number !== null) setSelected(turn.key);
                      setHover(number);
                    },
                    onJump: (number) => {
                      setSelected(turn.key);
                      setFocus((current) => ({ number, round: (current?.round ?? 0) + 1 }));
                    },
                  }}
                />
              );
            })}
          </div>
        </div>
        <div className={styles.composer}>
          <Composer onAsk={ask} />
        </div>
      </div>
      <div className={styles.sources}>
        <Sources
          key={shown?.key ?? "none"}
          citations={citations}
          active={active}
          focus={focus}
          onHover={setHover}
          waiting={shown?.state.status === "streaming"}
          {...(turns.length > 1 && position > 0 ? { turnLabel: `${position}번째 질문` } : {})}
        />
      </div>
    </div>
  );
}

export function NewConversation() {
  const { conversation } = useWorkspace();
  if (conversation.turns.length === 0) {
    return (
      <div className={styles.layout}>
        <div className={styles.conversation}>
          <div className={styles.scroll}>
            <Welcome />
          </div>
        </div>
        <div className={styles.sources}>
          <EmptySources />
        </div>
      </div>
    );
  }
  return <ConversationLayout />;
}

function ForgetConversation({ id }: { id: number }) {
  const { api, refreshHistory, reset } = useWorkspace();
  const navigate = useNavigate();
  const [asking, setAsking] = useState(false);
  if (!asking) {
    return (
      <button type="button" className={styles.quiet} onClick={() => setAsking(true)}>
        이 대화 지우기
      </button>
    );
  }
  return (
    <fieldset className={styles.confirm}>
      <legend className="visually-hidden">대화 지우기 확인</legend>
      <span>이 대화의 질문과 답을 모두 내 기록에서 지울까요?</span>
      <button
        type="button"
        className={styles.danger}
        onClick={async () => {
          await api.delete(`/api/conversations/${id}`);
          reset();
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

export function SavedConversation() {
  const { open, conversation } = useWorkspace();
  const id = Number(useParams().id);
  const [state, setState] = useState<"loading" | "ok" | "missing" | "failed">(
    conversation.id === id ? "ok" : "loading",
  );
  useEffect(() => {
    if (!Number.isInteger(id)) {
      setState("missing");
      return;
    }
    let alive = true;
    void open(id).then((result) => alive && setState(result));
    return () => {
      alive = false;
    };
  }, [id, open]);

  if (state === "ok" && conversation.id === id) {
    return (
      <ConversationLayout
        header={
          <div className={styles.head}>
            <ForgetConversation id={id} />
          </div>
        }
      />
    );
  }
  return (
    <div className={styles.layout}>
      <div className={styles.conversation}>
        <div className={styles.scroll}>
          {state === "loading" ? <p className={styles.loading}>대화를 불러오는 중…</p> : null}
          {state === "missing" || state === "failed" ? (
            <section className={styles.welcome}>
              <h1>대화를 열 수 없습니다</h1>
              <p>
                {state === "missing"
                  ? "이미 지웠거나 보관 기간이 지난 대화입니다."
                  : "대화를 불러오지 못했습니다. 잠시 뒤 다시 열어 주세요."}
              </p>
            </section>
          ) : null}
        </div>
      </div>
      <div className={styles.sources}>
        <EmptySources />
      </div>
    </div>
  );
}
