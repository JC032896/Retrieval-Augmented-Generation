// 질문 입력창. Enter로 묻고 Shift+Enter로 줄을 바꾼다. 한글 입력 중(조합 중)의 Enter는 무시한다.
import { type FormEvent, type KeyboardEvent, useState } from "react";
import styles from "./Composer.module.css";
import { useWorkspace } from "./workspace";

const MAX = 1000;

export function Composer({ onAsk }: { onAsk: (question: string) => void }) {
  const { busy, usage } = useWorkspace();
  const [text, setText] = useState("");
  const exhausted = usage?.questions_left === 0;
  const question = text.trim();
  const canAsk = !busy && !exhausted && question.length > 0 && question.length <= MAX;

  const submit = (event?: FormEvent) => {
    event?.preventDefault();
    if (!canAsk) return;
    onAsk(question);
    setText("");
  };
  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      submit();
    }
  };

  return (
    <form className={styles.composer} onSubmit={submit}>
      <label htmlFor="question" className="visually-hidden">
        질문
      </label>
      <div className={styles.box}>
        <textarea
          id="question"
          rows={1}
          value={text}
          maxLength={MAX + 200}
          disabled={exhausted}
          placeholder={exhausted ? "오늘 질문을 모두 썼습니다" : "규정이나 절차를 물어보세요"}
          aria-describedby="question-help"
          onChange={(event) => setText(event.target.value)}
          onKeyDown={onKeyDown}
        />
        <button type="submit" className={styles.send} disabled={!canAsk}>
          {busy ? "답하는 중" : "묻기"}
        </button>
      </div>
      <p id="question-help" className={styles.help}>
        <span>내가 볼 수 있는 문서에서만 찾고, 근거가 없으면 모른다고 답합니다.</span>
        {question.length > MAX * 0.9 ? (
          <span className={question.length > MAX ? styles.over : undefined}>
            {question.length.toLocaleString()} / {MAX.toLocaleString()}자
          </span>
        ) : usage?.questions_left != null ? (
          <span className={styles.left}>
            오늘 남은 질문 <strong className={styles.count}>{usage.questions_left}</strong>
          </span>
        ) : null}
      </p>
    </form>
  );
}
