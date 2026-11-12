// 문서 목록: 찾기(제목·등기번호), 출처·등급 거르기, 정렬. 줄을 누르면 문서 한 건 화면으로 간다.
import { Plus } from "lucide-react";
import { useCallback, useMemo, useState } from "react";
import { Link } from "react-router";
import type { DocumentRow, Me } from "../api/types";
import { useLoad } from "../api/useApi";
import { useApiClient } from "../auth/session";
import c from "../ui/controls.module.css";
import { audience, LEVELS, registeredNumber } from "../ui/format";
import { Level } from "../ui/Level";
import { Tracking, TrackingLegend } from "../ui/Tracking";
import styles from "./Documents.module.css";
import { type DocumentFilter, filterDocuments } from "./documentList";

export function Documents({ me }: { me: Me }) {
  const api = useApiClient();
  const documents = useLoad(
    useCallback(() => api.get<DocumentRow[]>("/admin/api/documents"), [api]),
  );
  const [filter, setFilter] = useState<DocumentFilter>({
    query: "",
    origin: "all",
    level: "all",
    sort: "recent",
  });
  const rows = useMemo(
    () => (documents.state === "ready" ? filterDocuments(documents.data, filter) : []),
    [documents, filter],
  );
  const isAdmin = me.roles.includes("admin");

  return (
    <div className={styles.page}>
      <header className={c.pageHead}>
        <div>
          <h1>문서</h1>
          <p>
            {isAdmin
              ? "모든 문서입니다. 문서 폴더(acl.yaml)에서 수집한 문서는 보기만 하고, 올린 문서는 권한을 바꿀 수 있습니다."
              : `${me.department}에서 올린 문서입니다.`}
          </p>
        </div>
        <Link to="/documents/new" className={c.button} data-kind="primary">
          <Plus aria-hidden="true" size={18} strokeWidth={2} />
          문서 올리기
        </Link>
      </header>

      <search className={styles.filters} aria-label="문서 거르기">
        <label className={c.field}>
          <span className={c.label}>찾기</span>
          <input
            className={c.input}
            type="search"
            placeholder="제목이나 등기번호"
            value={filter.query}
            onChange={(event) => setFilter({ ...filter, query: event.target.value })}
          />
        </label>
        <label className={c.field}>
          <span className={c.label}>출처</span>
          <select
            className={c.select}
            value={filter.origin}
            onChange={(event) =>
              setFilter({ ...filter, origin: event.target.value as DocumentFilter["origin"] })
            }
          >
            <option value="all">전체</option>
            <option value="upload">올린 문서</option>
            <option value="folder">문서 폴더</option>
          </select>
        </label>
        <label className={c.field}>
          <span className={c.label}>보안 등급</span>
          <select
            className={c.select}
            value={filter.level}
            onChange={(event) =>
              setFilter({
                ...filter,
                level: event.target.value === "all" ? "all" : Number(event.target.value),
              })
            }
          >
            <option value="all">전체</option>
            {LEVELS.map((item) => (
              <option key={item.level} value={item.level}>
                {item.level} {item.name}
              </option>
            ))}
          </select>
        </label>
        <label className={c.field}>
          <span className={c.label}>정렬</span>
          <select
            className={c.select}
            value={filter.sort}
            onChange={(event) =>
              setFilter({ ...filter, sort: event.target.value as DocumentFilter["sort"] })
            }
          >
            <option value="recent">최근에 움직인 순</option>
            <option value="title">제목순</option>
            <option value="level">등급 높은 순</option>
          </select>
        </label>
      </search>

      {documents.state === "loading" ? (
        <p className={c.message} data-tone="muted">
          문서를 불러오는 중입니다…
        </p>
      ) : documents.state === "error" ? (
        <p className={c.message} data-tone="blocked" role="alert">
          문서를 불러오지 못했습니다. {documents.message}
        </p>
      ) : documents.data.length === 0 ? (
        <p className={c.message} data-tone="muted">
          아직 문서가 없습니다. 오른쪽 위 "문서 올리기"로 첫 문서를 올리세요.
        </p>
      ) : (
        <>
          <p className={styles.count} aria-live="polite">
            {rows.length === documents.data.length
              ? `${rows.length}건`
              : `${documents.data.length}건 중 ${rows.length}건`}
          </p>
          {rows.length === 0 ? (
            <p className={c.message} data-tone="muted">
              조건에 맞는 문서가 없습니다. 찾는 말이나 거르기를 바꿔 보세요.
            </p>
          ) : (
            <>
              <TrackingLegend />
              <table className={styles.table}>
                <caption className="visually-hidden">문서 목록</caption>
                <thead>
                  <tr>
                    <th scope="col">등기번호</th>
                    <th scope="col">문서</th>
                    <th scope="col">등급</th>
                    <th scope="col">관리 부서</th>
                    <th scope="col">볼 수 있는 사람</th>
                    <th scope="col">배송조회</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((document) => (
                    <tr key={document.id} data-status={document.status}>
                      <td className={c.number}>
                        <Link to={`/documents/${document.id}`}>{registeredNumber(document)}</Link>
                      </td>
                      <td>
                        <Link to={`/documents/${document.id}`} className={styles.title}>
                          {document.title}
                        </Link>
                        {document.status === "superseded" ? (
                          <span className={styles.superseded}>폐지</span>
                        ) : null}
                      </td>
                      <td>
                        <Level level={document.security_level} />
                      </td>
                      <td>{document.owner_department ?? "문서 폴더"}</td>
                      <td>{audience(document)}</td>
                      <td>
                        <Tracking document={document} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </>
      )}
    </div>
  );
}
