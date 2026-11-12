// 배송조회 단계 표시: 문서가 접수되고 권한이 지정되고 바뀐 흐름을 점과 선으로 보여 준다.
// 처음 보일 때 점이 앞에서부터 차례로 채워진다 (움직임 줄이기 설정이면 바로 채워진다).
import { useEffect, useState } from "react";
import type { DocumentRow } from "../api/types";
import { trackingSteps } from "./format";
import styles from "./Tracking.module.css";

/** 배송조회 점 셋의 뜻. 표 위에 한 번 둔다 (오랜만에 와도 읽을 수 있게). */
const LEGEND = ["접수(폴더 수집·올림)", "권한 지정", "그 뒤 변경(권한·파일)"];

export function TrackingLegend() {
  return (
    <p className={styles.legend}>
      배송조회
      {LEGEND.map((name) => (
        <span key={name} className={styles.legendItem}>
          <span className={styles.dot} aria-hidden="true" />
          {name}
        </span>
      ))}
    </p>
  );
}

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
      {document.last_change ? <span className={styles.summary}>{summary}</span> : null}
    </div>
  );
}
