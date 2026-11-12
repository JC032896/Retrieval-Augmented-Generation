// 배송조회 단계 표시: 문서가 접수되고 권한이 지정되고 바뀐 흐름을 점과 선으로 보여 준다.
// 처음 보일 때 점이 앞에서부터 차례로 채워진다 (움직임 줄이기 설정이면 바로 채워진다).
import { useEffect, useState } from "react";
import type { DocumentRow } from "../api/types";
import { trackingSteps } from "./format";
import styles from "./Tracking.module.css";

export function Tracking({ document }: { document: Pick<DocumentRow, "origin" | "last_change"> }) {
  const { steps, summary } = trackingSteps(document);
  const [filled, setFilled] = useState(false);
  useEffect(() => {
    const frame = requestAnimationFrame(() => setFilled(true));
    return () => cancelAnimationFrame(frame);
  }, []);
  return (
    <div className={styles.track}>
      <ol className={styles.steps} aria-label="배송조회">
        {steps.map((step, index) => (
          <li
            key={step.label}
            className={step.done && filled ? styles.done : undefined}
            style={{ transitionDelay: `calc(var(--step-delay) * ${index})` }}
          >
            <span className="visually-hidden">
              {step.label} {step.done ? "완료" : "없음"}
            </span>
          </li>
        ))}
      </ol>
      <span className={styles.summary}>{summary}</span>
    </div>
  );
}
