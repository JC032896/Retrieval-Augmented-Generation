// 감사 기록 목록: 누가 언제 무엇을 물었고 어떻게 답했는지. 거르기와 "더 보기"(최근 것부터).
// 질문 원문은 감사 담당만 본다. 본 사실은 서버 운영 로그에 남는다 (admin_audit_viewed).
import { type FormEvent, useCallback, useEffect, useState } from "react";
import { Link } from "react-router";
import type { AuditPage, AuditSummary } from "../api/types";
import { errorText } from "../api/useApi";
import { useApiClient } from "../auth/session";
import c from "../ui/controls.module.css";
import { dateTime } from "../ui/format";
import styles from "./Audit.module.css";
import {
  type AuditFilter,
  auditQuery,
  EMPTY_FILTER,
  money,
  OUTCOMES,
  outcomeLabel,
  seconds,
} from "./auditModel";

type Rows = {
  items: AuditSummary[];
  next: number | null;
  state: "loading" | "more" | "ready" | "error";
  message?: string;
};

export function Audit() {
  const api = useApiClient();
  const [form, setForm] = useState<AuditFilter>(EMPTY_FILTER);
  const [filter, setFilter] = useState<AuditFilter>(EMPTY_FILTER);
  const [rows, setRows] = useState<Rows>({ items: [], next: null, state: "loading" });

  const load = useCallback(
    async (beforeId?: number) => {
      setRows((current) => ({ ...current, state: beforeId ? "more" : "loading" }));
      try {
        const page = await api.get<AuditPage>(auditQuery(filter, beforeId));
        setRows((current) => ({
          items: beforeId ? [...current.items, ...page.items] : page.items,
          next: page.next_before_id ?? null,
          state: "ready",
        }));
      } catch (error) {
        setRows((current) => ({ ...current, state: "error", message: errorText(error).message }));
      }
    },
    [api, filter],
  );

  useEffect(() => {
    void load();
  }, [load]);

  const apply = (event: FormEvent) => {
    event.preventDefault();
    setFilter(form);
  };

  return (
    <div className={styles.page}>
      <header className={c.pageHead}>
        <div>
          <h1>감사 기록</h1>
          <p>질문과 답변, 근거 문서. 이 화면을 본 사실도 운영 로그에 남습니다.</p>
        </div>
      </header>

      <form className={styles.filters} onSubmit={apply} aria-label="감사 기록 거르기">
        <label className={c.field}>
          <span className={c.label}>사용자 로그인 id</span>
          <input
            className={c.input}
            value={form.login}
            onChange={(event) => setForm({ ...form, login: event.target.value })}
            spellCheck={false}
          />
        </label>
        <label className={c.field}>
          <span className={c.label}>결과</span>
          <select
            className={c.select}
            value={form.outcome}
            onChange={(event) =>
              setForm({ ...form, outcome: event.target.value as AuditFilter["outcome"] })
            }
          >
            <option value="">전체</option>
            {Object.entries(OUTCOMES).map(([value, item]) => (
              <option key={value} value={value}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
        <label className={c.field}>
          <span className={c.label}>시작일</span>
          <input
            className={c.input}
            type="date"
            value={form.since}
            onChange={(event) => setForm({ ...form, since: event.target.value })}
          />
        </label>
        <label className={c.field}>
          <span className={c.label}>종료일 (포함)</span>
          <input
            className={c.input}
            type="date"
            value={form.until}
            onChange={(event) => setForm({ ...form, until: event.target.value })}
          />
        </label>
        <div className={c.actions}>
          <button type="submit" className={c.button} data-kind="primary">
            거르기
          </button>
          <button
            type="button"
            className={c.button}
            onClick={() => {
              setForm(EMPTY_FILTER);
              setFilter(EMPTY_FILTER);
            }}
          >
            지우기
          </button>
        </div>
      </form>

      {rows.state === "error" ? (
        <p className={c.message} data-tone="blocked" role="alert">
          감사 기록을 불러오지 못했습니다. {rows.message}
        </p>
      ) : null}
      {rows.state === "loading" ? (
        <p className={c.message} data-tone="muted">
          감사 기록을 불러오는 중입니다…
        </p>
      ) : rows.items.length === 0 && rows.state !== "error" ? (
        <p className={c.message} data-tone="muted">
          조건에 맞는 기록이 없습니다.
        </p>
      ) : rows.items.length > 0 ? (
        <>
          <table className={styles.table}>
            <caption className="visually-hidden">감사 기록 (최근 것부터)</caption>
            <thead>
              <tr>
                <th scope="col">시각</th>
                <th scope="col">사용자</th>
                <th scope="col">질문</th>
                <th scope="col">결과</th>
                <th scope="col">인용 문서</th>
                <th scope="col" className={styles.right}>
                  비용
                </th>
                <th scope="col" className={styles.right}>
                  걸린 시간
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.items.map((item) => (
                <tr key={item.id}>
                  <td className={styles.when}>
                    <Link to={`/audit/${item.id}`}>{dateTime(item.created_at)}</Link>
                  </td>
                  <td>
                    {item.user_login}
                    <span className={styles.sub}>{item.user_department}</span>
                  </td>
                  <td className={styles.question}>
                    {item.question ?? (
                      <span className={styles.sub}>원문 저장 안 함 ({item.question_chars}자)</span>
                    )}
                  </td>
                  <td>
                    <span className={styles.outcome} data-outcome={item.outcome}>
                      {outcomeLabel(item.outcome)}
                    </span>
                  </td>
                  <td>{item.cited_files.length ? `${item.cited_files.length}건` : "-"}</td>
                  <td className={styles.right}>{money(item.cost_usd)}</td>
                  <td className={styles.right}>{seconds(item.total_ms)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className={styles.more}>
            {rows.next !== null ? (
              <button
                type="button"
                className={c.button}
                disabled={rows.state === "more"}
                onClick={() => void load(rows.next ?? undefined)}
              >
                {rows.state === "more" ? "불러오는 중…" : "더 보기"}
              </button>
            ) : (
              <p className={c.hint}>마지막 기록입니다 ({rows.items.length}건).</p>
            )}
          </div>
        </>
      ) : null}
    </div>
  );
}
