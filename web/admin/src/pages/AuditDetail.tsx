// 감사 기록 한 건: 질문과 답변 원문, LLM에 보낸 근거 문서와 인용한 문서, 재현 정보.
import { useCallback } from "react";
import { Link, useParams } from "react-router";
import type { AuditDetail as Detail } from "../api/types";
import { useLoad } from "../api/useApi";
import { useApiClient } from "../auth/session";
import c from "../ui/controls.module.css";
import { dateTime } from "../ui/format";
import styles from "./AuditDetail.module.css";
import { money, outcomeLabel, seconds } from "./auditModel";

export function AuditDetail() {
  const { id } = useParams();
  const api = useApiClient();
  const record = useLoad(useCallback(() => api.get<Detail>(`/admin/api/audit/${id}`), [api, id]));

  if (record.state === "loading") {
    return (
      <p className={c.message} data-tone="muted">
        감사 기록을 불러오는 중입니다…
      </p>
    );
  }
  if (record.state === "error") {
    return (
      <div className={styles.page}>
        <p className={c.message} data-tone="blocked" role="alert">
          {record.status === 404
            ? "감사 기록이 없습니다."
            : `감사 기록을 불러오지 못했습니다. ${record.message}`}
        </p>
        <Link to="/audit">감사 기록 목록으로</Link>
      </div>
    );
  }
  const r = record.data;
  const cited = new Set(r.cited_files);
  return (
    <div className={styles.page}>
      <nav aria-label="위치" className={styles.crumb}>
        <Link to="/audit">감사 기록</Link> / {r.id}번
      </nav>
      <header className={c.pageHead}>
        <div>
          <h1>
            {dateTime(r.created_at)} · {r.user_login}
          </h1>
          <p>
            {r.user_department} · {r.user_role} · 열람 등급 {r.user_clearance_level} · 접속{" "}
            {r.client_ip ?? "기록 없음"}
          </p>
        </div>
        <span className={styles.outcome} data-outcome={r.outcome}>
          {outcomeLabel(r.outcome)}
          {r.refusal_reason ? ` (${r.refusal_reason})` : ""}
        </span>
      </header>

      <div className={styles.columns}>
        <div className={styles.main}>
          <section className={c.panel} aria-labelledby="q">
            <h2 id="q">질문</h2>
            <p className={styles.text}>
              {r.question ?? `원문을 저장하지 않는 설정입니다 (${r.question_chars}자).`}
            </p>
          </section>
          <section className={c.panel} aria-labelledby="a">
            <h2 id="a">답변</h2>
            <p className={styles.text}>
              {r.answer ?? "답변 원문이 없습니다 (거절, 오류, 중단이거나 원문 저장 안 함)."}
            </p>
            {r.verified !== null ? (
              <p className={styles.verified} data-ok={r.verified}>
                인용 검증 {r.verified ? "통과" : "실패"}
              </p>
            ) : null}
          </section>
          <section className={c.panel} aria-labelledby="ctx">
            <h2 id="ctx">LLM에 보낸 근거 문서</h2>
            {r.context_files.length === 0 ? (
              <p className={c.hint}>보낸 근거가 없습니다 (검색 결과 없음).</p>
            ) : (
              <ol className={styles.files}>
                {r.context_files.map((file) => (
                  <li key={file} data-cited={cited.has(file)}>
                    <span>{file}</span>
                    {cited.has(file) ? <strong>답변이 인용함</strong> : null}
                  </li>
                ))}
              </ol>
            )}
          </section>
        </div>

        <aside className={styles.side}>
          <dl className={c.facts}>
            <div>
              <dt>모델</dt>
              <dd>{r.model ?? "-"}</dd>
            </div>
            <div>
              <dt>토큰 (입력 / 출력)</dt>
              <dd>
                {r.input_tokens ?? "-"} / {r.output_tokens ?? "-"}
              </dd>
            </div>
            <div>
              <dt>비용</dt>
              <dd>{money(r.cost_usd)}</dd>
            </div>
            <div>
              <dt>걸린 시간</dt>
              <dd>
                검색 {seconds(r.retrieval_ms)} · 첫 글자 {seconds(r.first_token_ms)} · 전체{" "}
                {seconds(r.total_ms)}
              </dd>
            </div>
            <div>
              <dt>요청 번호</dt>
              <dd className={styles.code}>{r.request_id}</dd>
            </div>
            <div>
              <dt>요청 해시 (재현 확인용)</dt>
              <dd className={styles.code}>{r.request_sha256 ?? "-"}</dd>
            </div>
          </dl>
          <section className={c.panel} aria-labelledby="replay">
            <h2 id="replay">그때 요청을 다시 만들기</h2>
            <p className={c.hint}>
              감사 담당 계정으로 서버에서 실행하면 당시 근거 조각으로 LLM 요청을 다시 만들고 해시가
              같은지 확인합니다.
            </p>
            <pre className={styles.command}>python scripts/replay.py {r.id}</pre>
          </section>
        </aside>
      </div>
    </div>
  );
}
