// 대시보드: 모든 역할이 처음 보는 화면. 오늘의 상태(송장 라벨), 최근 문서 전달, 확인할 일.
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router";
import type { DocumentRow, Me, Status } from "../api/types";
import { useLoad } from "../api/useApi";
import { useApiClient } from "../auth/session";
import { audience, dateTime, registeredNumber } from "../ui/format";
import { Level } from "../ui/Level";
import { Tracking } from "../ui/Tracking";
import styles from "./Dashboard.module.css";
import { recentDocuments, statusLabels, todos } from "./statusModel";

function useNow(): Date {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 60_000);
    return () => window.clearInterval(timer);
  }, []);
  return now;
}

function StatusBoard({ status }: { status: Status }) {
  return (
    <ul className={styles.labels} aria-label="오늘의 상태">
      {statusLabels(status).map((label) => (
        <li key={label.key} className={styles.label} data-tone={label.tone}>
          <span className={styles.labelHead}>
            <span>{label.title}</span>
            <span className={styles.code} aria-hidden="true">
              {label.code}
            </span>
          </span>
          <span className={styles.value} data-kind={/^\d/.test(label.value) ? "number" : "text"}>
            {label.value}
            {label.unit ? <span className={styles.unit}>{label.unit}</span> : null}
          </span>
          <span className={styles.note}>{label.note}</span>
        </li>
      ))}
    </ul>
  );
}

function DocumentTable({ documents }: { documents: DocumentRow[] }) {
  if (documents.length === 0) {
    return (
      <p className={styles.empty}>
        아직 문서가 없습니다. 문서 폴더를 수집하거나 문서 화면에서 올리면 여기에 보입니다.
      </p>
    );
  }
  return (
    <table className={styles.table}>
      <caption className="visually-hidden">최근에 움직인 문서</caption>
      <thead>
        <tr>
          <th scope="col">등기번호</th>
          <th scope="col">문서</th>
          <th scope="col">등급</th>
          <th scope="col">볼 수 있는 사람</th>
          <th scope="col">배송조회</th>
        </tr>
      </thead>
      <tbody>
        {documents.map((document) => (
          <tr key={document.id}>
            <td className={styles.number}>{registeredNumber(document)}</td>
            <td>{document.title}</td>
            <td>
              <Level level={document.security_level} />
            </td>
            <td>{audience(document)}</td>
            <td>
              <Tracking document={document} />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function Dashboard({ me }: { me: Me }) {
  const api = useApiClient();
  const now = useNow();
  const canSeeDocuments = me.roles.includes("admin") || me.roles.includes("doc_manager");
  const status = useLoad(useCallback(() => api.get<Status>("/admin/api/status"), [api]));
  const documents = useLoad(
    useCallback(() => api.get<DocumentRow[]>("/admin/api/documents"), [api]),
    canSeeDocuments,
  );
  const synced =
    status.state === "ready" && typeof status.data.index.last_synced_at === "string"
      ? ` · 마지막 수집 ${dateTime(status.data.index.last_synced_at)}`
      : "";

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <h1>오늘의 상태</h1>
        <p>
          {dateTime(now)} 기준{synced}
        </p>
      </header>

      {status.state === "loading" ? (
        <p className={styles.loading}>상태를 불러오는 중입니다…</p>
      ) : null}
      {status.state === "error" ? (
        <p className={styles.error} role="alert">
          상태를 불러오지 못했습니다. {status.message}
        </p>
      ) : null}
      {status.state === "ready" ? <StatusBoard status={status.data} /> : null}

      <div className={styles.columns}>
        <section aria-labelledby="recent">
          <div className={styles.sectionHead}>
            <h2 id="recent">최근 문서 전달</h2>
            {canSeeDocuments ? <Link to="/documents">문서 전체 보기</Link> : null}
          </div>
          {!canSeeDocuments ? (
            <p className={styles.empty}>
              문서 목록은 중앙 관리자와 부서 문서 담당에게 보입니다.
              {me.roles.includes("auditor") ? (
                <>
                  {" "}
                  누가 무엇을 물었는지는 <Link to="/audit">감사 기록</Link>에서 봅니다.
                </>
              ) : null}
            </p>
          ) : documents.state === "loading" ? (
            <p className={styles.loading}>문서를 불러오는 중입니다…</p>
          ) : documents.state === "error" ? (
            <p className={styles.error} role="alert">
              문서를 불러오지 못했습니다. {documents.message}
            </p>
          ) : (
            <DocumentTable documents={recentDocuments(documents.data)} />
          )}
        </section>

        <section
          aria-labelledby="todo"
          className={styles.todo}
          data-blocked={status.state === "ready" && todos(status.data, me.roles).length > 0}
        >
          <h2 id="todo">확인할 일</h2>
          {status.state !== "ready" ? null : todos(status.data, me.roles).length === 0 ? (
            <p className={styles.clear}>지금 막힌 것이 없습니다.</p>
          ) : (
            <ul>
              {todos(status.data, me.roles).map((item) => (
                <li key={item.title}>
                  <strong>{item.title}</strong>
                  <span>{item.detail}</span>
                  {item.link ? <Link to={item.link.to}>{item.link.label}</Link> : null}
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  );
}
