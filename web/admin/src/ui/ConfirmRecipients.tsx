// 권한 저장의 마지막 단계: 받는 사람 명단과 바뀌는 점을 보여 주고, 확인해야 저장한다.
import type { ReactNode } from "react";
import styles from "./ConfirmRecipients.module.css";
import c from "./controls.module.css";
import type { usePreview } from "./Recipients";

export function ConfirmRecipients({
  preview,
  lines,
  busy,
  confirmLabel,
  onConfirm,
  onBack,
  children,
}: {
  preview: ReturnType<typeof usePreview>;
  lines: string[];
  busy: boolean;
  confirmLabel: string;
  onConfirm: () => void;
  onBack: () => void;
  children?: ReactNode;
}) {
  const count = preview.state === "ready" ? preview.preview.count : null;
  return (
    <section className={styles.confirm} aria-labelledby="confirm-title">
      <h2 id="confirm-title">
        {count === null ? "받는 사람을 확인하는 중입니다" : `받는 사람 ${count}명을 확인해 주세요`}
      </h2>
      {lines.length > 0 ? (
        <ul className={styles.lines}>
          {lines.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      ) : null}
      {children}
      <div className={c.actions}>
        <button
          type="button"
          className={c.button}
          data-kind="primary"
          disabled={busy || count === null || count === 0}
          onClick={onConfirm}
        >
          {busy ? "저장하는 중…" : confirmLabel}
        </button>
        <button type="button" className={c.button} onClick={onBack} disabled={busy}>
          다시 고치기
        </button>
      </div>
    </section>
  );
}
