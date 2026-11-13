// 질문 하나와 그 답. 답이 끝나 인용이 확인되면 근거 있는 문장에 형광펜이 그어지고,
// 문장이나 번호표에 마우스·초점을 두면 오른쪽 근거 칸의 같은 색 문단이 함께 진해진다.
import { type ReactNode, useEffect, useRef } from "react";
import styles from "./AnswerView.module.css";
import { type Line, markerOf, readAnswer, type Sentence, streamingText } from "./answer";
import type { Answer } from "./types";

export type AnswerState =
  | { kind: "streaming"; text: string }
  | { kind: "answer"; answer: Answer }
  | { kind: "failed"; text: string; message: string; onRetry: () => void }
  | { kind: "hidden"; onRetry: () => void };

type Linking = {
  active: number | null;
  onHover: (number: number | null) => void;
  onJump: (number: number) => void;
};

function titleOf(answer: Answer, number: number): string {
  return answer.citations.find((c) => c.number === number)?.title ?? "근거";
}

function SentenceView({
  sentence,
  answer,
  linking,
}: {
  sentence: Sentence;
  answer: Answer;
  linking: Linking;
}) {
  const first = sentence.numbers[0];
  const lit =
    first !== undefined && linking.active !== null && sentence.numbers.includes(linking.active);
  const className = sentence.unverified
    ? styles.unverified
    : sentence.marker
      ? `${styles.marked} ${lit ? styles.lit : ""}`
      : undefined;
  const delay = { animationDelay: `${Math.min(sentence.order, 8) * 70}ms` };
  const tags = sentence.numbers.map((number) => (
    <button
      key={number}
      type="button"
      className={styles.tag}
      data-marker={markerOf(number)}
      aria-label={`근거 ${number}: ${titleOf(answer, number)}`}
      onMouseEnter={() => linking.onHover(number)}
      onMouseLeave={() => linking.onHover(null)}
      onFocus={() => linking.onHover(number)}
      onBlur={() => linking.onHover(null)}
      onClick={() => linking.onJump(number)}
    >
      {number}
    </button>
  ));
  // 번호표가 혼자 다음 줄로 떨어지지 않게 마지막 어절과 번호표를 줄바꿈 없는 묶음으로 둔다
  const cut = tags.length > 0 ? sentence.text.lastIndexOf(" ") : -1;
  const head = cut > 0 ? sentence.text.slice(0, cut + 1) : "";
  const tail = cut > 0 ? sentence.text.slice(cut + 1) : sentence.text;
  return (
    <>
      <span
        data-sentence={sentence.order}
        data-marker={sentence.unverified ? undefined : (sentence.marker ?? undefined)}
        data-cite={sentence.unverified ? undefined : first}
      >
        {head ? (
          <span className={className} style={delay}>
            {head}
          </span>
        ) : null}
        {tags.length > 0 ? (
          <span className={styles.keep}>
            <span className={className} style={delay}>
              {tail}
            </span>
            {tags}
          </span>
        ) : (
          <span className={className} style={delay}>
            {tail}
          </span>
        )}
      </span>{" "}
    </>
  );
}

/** 칠한 문장 위에 마우스가 오면 같은 번호의 근거를 진하게 한다 (키보드는 번호표 버튼으로 같은 일을 한다). */
function useSentenceHover(onHover: Linking["onHover"]) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const body = ref.current;
    if (!body) return;
    const over = (event: MouseEvent) => {
      const cite = (event.target as Element).closest<HTMLElement>("[data-cite]")?.dataset.cite;
      onHover(cite ? Number(cite) : null);
    };
    const out = () => onHover(null);
    body.addEventListener("mouseover", over);
    body.addEventListener("mouseleave", out);
    return () => {
      body.removeEventListener("mouseover", over);
      body.removeEventListener("mouseleave", out);
    };
  }, [onHover]);
  return ref;
}

function AnswerBody({ answer, linking }: { answer: Answer; linking: Linking }) {
  const lines: Line[] = readAnswer(answer);
  const ref = useSentenceHover(linking.onHover);
  const blocks: ReactNode[] = [];
  let items: ReactNode[] = [];
  const flush = (key: string) => {
    if (items.length > 0) {
      blocks.push(
        <ul key={key} className={styles.list}>
          {items}
        </ul>,
      );
      items = [];
    }
  };
  for (const line of lines) {
    const content = line.sentences.map((sentence) => (
      <SentenceView key={sentence.order} sentence={sentence} answer={answer} linking={linking} />
    ));
    if (line.kind === "item") {
      items.push(<li key={line.order}>{content}</li>);
    } else {
      flush(`list-before-${line.order}`);
      blocks.push(<p key={line.order}>{content}</p>);
    }
  }
  flush("list-end");
  const unverified = lines.some((line) => line.sentences.some((s) => s.unverified));
  return (
    <>
      <div ref={ref} className={styles.body}>
        {blocks}
      </div>
      {answer.refused ? (
        <p className={styles.note}>
          볼 수 있는 문서에서 근거를 찾지 못해 답하지 않았습니다. 문서 이름이나 용어를 바꿔 다시
          물어보세요.
        </p>
      ) : null}
      {unverified ? (
        <p className={styles.note}>
          <span className={styles.unverifiedSample}>점선 밑줄</span>은 근거 문단에서 확인되지 않은
          문장입니다. 오른쪽 원문과 직접 비교해 보세요.
        </p>
      ) : null}
      {answer.invalid_citations.length > 0 ? (
        <p className={styles.note}>
          근거 목록에 없는 번호({answer.invalid_citations.join(", ")})가 답에 있어 표시하지
          않았습니다.
        </p>
      ) : null}
    </>
  );
}

export function AnswerView({
  question,
  meta,
  state,
  linking,
  actions,
  searchQuestion = null,
  selection,
}: {
  question: string;
  meta: ReactNode;
  state: AnswerState;
  linking: Linking;
  actions?: ReactNode;
  /** 이어 묻는 질문을 서버가 다시 쓴 질문 (검색과 답은 이 질문으로 했다) */
  searchQuestion?: string | null;
  /** 대화에 질문이 여럿일 때: 근거 칸이 보여 주는 답(shown)인가, 다른 답(other)인가 */
  selection?: "shown" | "other" | undefined;
}) {
  return (
    <article
      className={[
        styles.turn,
        selection === "shown" ? styles.shown : "",
        selection === "other" ? styles.other : "",
      ].join(" ")}
      aria-busy={state.kind === "streaming"}
      aria-current={selection === "shown" ? "true" : undefined}
    >
      <header className={styles.head}>
        <p className={styles.meta}>{meta}</p>
        <h2 className={styles.question}>{question}</h2>
        {searchQuestion ? (
          <p className={styles.understood}>
            이렇게 이해하고 찾았습니다: <q>{searchQuestion}</q>
          </p>
        ) : null}
        {actions ? <div className={styles.actions}>{actions}</div> : null}
      </header>
      {state.kind === "streaming" ? (
        <div className={styles.body}>
          <p className={styles.streaming}>
            {streamingText(state.text) || "볼 수 있는 문서에서 찾는 중입니다…"}
          </p>
        </div>
      ) : null}
      {state.kind === "answer" ? <AnswerBody answer={state.answer} linking={linking} /> : null}
      {state.kind === "failed" ? (
        <div className={styles.problem} role="alert">
          {state.text ? <p className={styles.partial}>{streamingText(state.text)}</p> : null}
          <p>{state.message}</p>
          <button type="button" className={styles.retry} onClick={state.onRetry}>
            다시 묻기
          </button>
        </div>
      ) : null}
      {state.kind === "hidden" ? (
        <div className={styles.hidden}>
          <p>
            이 답의 근거 문서를 지금은 볼 수 없어(권한이 바뀌었거나 문서가 지워짐) 답을 가렸습니다.
            같은 질문을 다시 하면 지금 볼 수 있는 문서로 답합니다.
          </p>
          <button type="button" className={styles.retry} onClick={state.onRetry}>
            다시 묻기
          </button>
        </div>
      ) : null}
    </article>
  );
}
