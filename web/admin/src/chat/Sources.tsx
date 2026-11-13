// 오른쪽 근거 칸: 답이 인용한 문단. 번호표와 같은 형광펜 색으로 제목을 칠하고, 답의 문장이나
// 번호표에 마우스·초점이 가면 같은 번호의 문단 전체가 옅게 칠해진다. 원문 안의 정확한 문장을
// 칠한 척하지 않는다 (서버는 문단 단위로만 근거를 안다).
import { useCallback, useEffect, useRef } from "react";
import { useLoad } from "../api/useApi";
import { markerOf } from "./answer";
import { passageParagraphs } from "./passage";
import styles from "./Sources.module.css";
import type { Citation, Passage } from "./types";
import { useWorkspace } from "./workspace";

function PassageCard({
  citation,
  active,
  focused,
  onHover,
}: {
  citation: Citation;
  active: boolean;
  focused: number;
  onHover: (number: number | null) => void;
}) {
  const { api } = useWorkspace();
  const load = useCallback(
    () => api.get<Passage>(`/api/passages/${citation.chunk_id}`),
    [api, citation],
  );
  const passage = useLoad(load);
  const ref = useRef<HTMLElement>(null);
  useEffect(() => {
    if (focused > 0) {
      ref.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
      ref.current?.focus({ preventScroll: true });
    }
  }, [focused]);

  const where = [citation.section, citation.page ? `${citation.page}쪽` : null]
    .filter(Boolean)
    .join(" · ");
  return (
    <article
      ref={ref}
      tabIndex={-1}
      className={`${styles.card} ${active ? styles.active : ""}`}
      data-marker={markerOf(citation.number)}
      aria-labelledby={`source-${citation.number}`}
      onMouseEnter={() => onHover(citation.number)}
      onMouseLeave={() => onHover(null)}
    >
      <h3 id={`source-${citation.number}`} className={styles.title}>
        <span className={styles.tag}>{citation.number}</span>{" "}
        <span className={styles.titleText}>{citation.title}</span>
      </h3>
      <p className={styles.where}>
        {where ? `${where} · ` : ""}
        {passage.state === "ready" && passage.data.status === "superseded" ? (
          <strong className={styles.old}>폐지되었거나 새 판으로 바뀐 문서</strong>
        ) : (
          "현행"
        )}
      </p>
      {passage.state === "loading" ? <p className={styles.waiting}>문단을 불러오는 중…</p> : null}
      {passage.state === "error" ? (
        <p className={styles.gone}>
          {passage.status === 404
            ? "이 문단은 문서가 바뀌었거나 지금 볼 수 없어 보여 줄 수 없습니다."
            : passage.message}
        </p>
      ) : null}
      {passage.state === "ready" ? (
        <div className={styles.content}>
          {passageParagraphs(passage.data.content, citation.title).map((paragraph) => (
            <p key={paragraph.order}>{paragraph.text}</p>
          ))}
        </div>
      ) : null}
    </article>
  );
}

export function Sources({
  citations,
  active,
  focus,
  onHover,
  waiting,
  turnLabel,
}: {
  citations: Citation[];
  active: number | null;
  focus: { number: number; round: number } | null;
  onHover: (number: number | null) => void;
  waiting: boolean;
  /** 대화에 질문이 여럿이면 어느 질문의 근거인지 ("2번째 질문") */
  turnLabel?: string;
}) {
  const unique = [...new Map(citations.map((c) => [c.number, c])).values()].sort(
    (a, b) => a.number - b.number,
  );
  return (
    <aside className={styles.panel} aria-labelledby="sources-title">
      <h2 id="sources-title" className={styles.heading}>
        근거 문단{unique.length > 0 ? ` ${unique.length}` : ""}
        {turnLabel ? <span className={styles.turn}> · {turnLabel}</span> : null}
      </h2>
      {unique.length === 0 ? (
        <p className={styles.empty}>
          {waiting
            ? "답이 끝나면 답에 쓰인 근거 문단이 여기에 나옵니다."
            : "이 답에는 인용한 근거 문단이 없습니다."}
        </p>
      ) : (
        unique.map((citation) => (
          <PassageCard
            key={citation.number}
            citation={citation}
            active={active === citation.number}
            focused={focus?.number === citation.number ? focus.round : 0}
            onHover={onHover}
          />
        ))
      )}
    </aside>
  );
}
