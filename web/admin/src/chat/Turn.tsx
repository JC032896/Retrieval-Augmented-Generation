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

/**
 * 한 대화: 질문과 답들을 쌓고, 고른 답의 근거를 오른쪽에 보인다.
 * - 번호표를 누르면 그 답에 고정한다. 마우스를 올리거나 초점을 두는 동안에는 그 답을 미리 보인다.
 * - 고르지 않은 답의 형광펜은 옅게 칠한다. 색이 지금 오른쪽에 보이는 문단으로만 이어지게 한다.
 */
function ConversationLayout({ header }: { header?: ReactNode }) {
  const { conversation } = useWorkspace();
  const ask = useAsk();
  const turns = conversation.turns;
  const [pinned, setPinned] = useState<string | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [hover, setHover] = useState<number | null>(null);
  // 번호표를 눌러 옮겨 갈 근거 카드. 한 번 초점을 준 뒤에는 다시 끌어가지 않는다 (consumed)
  const [focus, setFocus] = useState<{
    turn: string;
    number: number;
    round: number;
    consumed: boolean;
  } | null>(null);
  const [seen, setSeen] = useState(turns.length);
  const thread = useRef<HTMLDivElement>(null);
  if (seen !== turns.length) {
    // 새 질문이 붙으면 마지막 답으로 돌아간다
    setSeen(turns.length);
    setPinned(null);
    setPreview(null);
    setFocus(null);
  }
  // 질문이 붙으면 그 질문이 가운데 칸 맨 위에 오게 한다 (마지막 질문 칸은 화면 높이만큼 자리를
  // 잡는다). 답이 끝나면 한 번 더 옮긴다. 답이 흘러 들어오는 동안에는 부드러운 스크롤이 끊기므로 바로
  const lastStatus = turns[turns.length - 1]?.state.status;
  useEffect(() => {
    void lastStatus;
    if (seen > 1) {
      const newest = thread.current?.lastElementChild;
      newest?.scrollIntoView?.({ block: "start" });
    }
  }, [seen, lastStatus]);

  const find = (key: string | null) => turns.find((turn) => turn.key === key);
  const shown = find(preview) ?? find(pinned) ?? turns[turns.length - 1];
  const focusHere = focus && focus.turn === shown?.key ? focus : null;
  const citations = shown?.state.status === "done" ? shown.state.answer.citations : [];
  const active = hover ?? focusHere?.number ?? null;
  const position = shown ? turns.indexOf(shown) + 1 : 0;
  const many = turns.length > 1;
  const onFocused = useCallback(
    () => setFocus((current) => current && { ...current, consumed: true }),
    [],
  );

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
              const isShown = turn === shown;
              return (
                <AnswerView
                  key={turn.key}
                  question={turn.question}
                  meta={many ? `${index + 1}번째 질문 · ${meta}` : meta}
                  searchQuestion={searchQuestion}
                  state={state}
                  selection={many ? (isShown ? "shown" : "other") : undefined}
                  linking={{
                    active: isShown ? active : null,
                    onHover: (number) => {
                      setPreview(number === null ? null : turn.key);
                      setHover(number);
                    },
                    onJump: (number) => {
                      setPinned(turn.key);
                      setFocus((current) => ({
                        turn: turn.key,
                        number,
                        round: (current?.round ?? 0) + 1,
                        consumed: false,
                      }));
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
          focus={
            focusHere && !focusHere.consumed
              ? { number: focusHere.number, round: focusHere.round }
              : null
          }
          onFocused={onFocused}
          onHover={setHover}
          waiting={shown?.state.status === "streaming"}
          {...(many && position > 0 ? { turnLabel: `${position}번째 질문` } : {})}
        />
      </div>
    </div>
  );
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

/**
 * 첫 화면(/)과 대화 화면(/history/:id)을 함께 그린다. 같은 구성 요소라서, 새 대화의 첫 답이 끝나 주소가
 * /history/:id로 바뀌어도 화면을 새로 만들지 않는다 (입력 중인 다음 질문과 초점이 그대로 남는다).
 */
export function ChatPage() {
  const { open, conversation } = useWorkspace();
  const param = useParams().id;
  const id = param === undefined ? null : Number(param);
  const [state, setState] = useState<"loading" | "ok" | "missing" | "failed">("loading");
  useEffect(() => {
    if (id === null) return;
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

  const current = id === null || conversation.id === id;
  if (current && conversation.turns.length > 0) {
    return (
      <ConversationLayout
        header={
          id !== null ? (
            <div className={styles.head}>
              <ForgetConversation id={id} />
            </div>
          ) : undefined
        }
      />
    );
  }
  return (
    <div className={styles.layout}>
      <div className={styles.conversation}>
        <div className={styles.scroll}>
          {id === null ? <Welcome /> : null}
          {id !== null && state === "loading" ? (
            <p className={styles.loading}>대화를 불러오는 중…</p>
          ) : null}
          {id !== null && (state === "missing" || state === "failed") ? (
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

/** 첫 화면과 대화 화면은 같은 구성 요소다 (위 ChatPage 설명). */
export const NewConversation = ChatPage;
export const SavedConversation = ChatPage;
