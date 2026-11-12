// 사용자: 문서 폴더의 org.yaml에서 수집한 사람과 권한 속성. 부서별로 묶어 보기만 한다.
import { useCallback, useMemo } from "react";
import type { UserRow } from "../api/types";
import { useLoad } from "../api/useApi";
import { useApiClient } from "../auth/session";
import c from "../ui/controls.module.css";
import { Level } from "../ui/Level";
import styles from "./Users.module.css";

export function groupByDepartment(users: readonly UserRow[]): [string, UserRow[]][] {
  const groups = new Map<string, UserRow[]>();
  for (const user of users)
    groups.set(user.department, [...(groups.get(user.department) ?? []), user]);
  return [...groups.entries()];
}

export function Users() {
  const api = useApiClient();
  const users = useLoad(useCallback(() => api.get<UserRow[]>("/admin/api/users"), [api]));
  const groups = useMemo(
    () => (users.state === "ready" ? groupByDepartment(users.data) : []),
    [users],
  );

  return (
    <div className={styles.page}>
      <header className={c.pageHead}>
        <div>
          <h1>사용자</h1>
          <p>
            문서 폴더의 org.yaml에서 수집한 사람입니다. 문서를 볼 수 있는지는 부서·역할·열람
            등급으로 정합니다. 바꾸려면 org.yaml을 고치고 다시 수집합니다.
          </p>
        </div>
      </header>
      {users.state === "loading" ? (
        <p className={c.message} data-tone="muted">
          사용자를 불러오는 중입니다…
        </p>
      ) : users.state === "error" ? (
        <p className={c.message} data-tone="blocked" role="alert">
          사용자를 불러오지 못했습니다. {users.message}
        </p>
      ) : users.data.length === 0 ? (
        <p className={c.message} data-tone="muted">
          등록된 사용자가 없습니다. 문서 폴더의 org.yaml을 확인하고 다시 수집해 주세요.
        </p>
      ) : (
        <div className={styles.groups}>
          {groups.map(([department, members]) => (
            <section
              key={department}
              className={styles.group}
              aria-labelledby={`dept-${department}`}
            >
              <h2 id={`dept-${department}`}>
                {department} <span className={styles.count}>{members.length}명</span>
              </h2>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th scope="col">이름</th>
                    <th scope="col">로그인 id</th>
                    <th scope="col">역할</th>
                    <th scope="col">열람 등급</th>
                  </tr>
                </thead>
                <tbody>
                  {members.map((user) => (
                    <tr key={user.login}>
                      <td>{user.name}</td>
                      <td className={styles.login}>{user.login}</td>
                      <td>{user.role}</td>
                      <td>
                        <Level level={user.clearance_level} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          ))}
        </div>
      )}
    </div>
  );
}
