// 받는 사람 명단: 이 권한으로 저장하면 문서를 볼 수 있게 되는 사람 (서버의 검색 권한 규칙과 같다).
// 고르는 동안 잠시 기다렸다가 서버에 묻고, 부서별로 묶어 보여 준다.
import { useEffect, useState } from "react";
import type { Api } from "../api/client";
import type { UserRow } from "../api/types";
import { errorText } from "../api/useApi";
import type { AccessDraft } from "./access";
import styles from "./Recipients.module.css";

export type Preview = { count: number; total_users: number; users: UserRow[] };

type State =
  | { state: "idle" }
  | { state: "loading" }
  | { state: "ready"; preview: Preview }
  | { state: "error"; message: string };

const WAIT_MS = 250;

export function usePreview(api: Api, draft: AccessDraft): State {
  const [result, setResult] = useState<State>({ state: "idle" });
  const { departments, roles, security_level } = draft;
  useEffect(() => {
    if (departments.length === 0 && roles.length === 0) {
      setResult({ state: "idle" });
      return;
    }
    let alive = true;
    setResult({ state: "loading" });
    const timer = window.setTimeout(() => {
      api
        .post<Preview>("/admin/api/documents/access-preview", {
          departments,
          roles,
          security_level,
        })
        .then((preview) => alive && setResult({ state: "ready", preview }))
        .catch((error: unknown) => alive && setResult({ state: "error", ...errorText(error) }));
    }, WAIT_MS);
    return () => {
      alive = false;
      window.clearTimeout(timer);
    };
  }, [api, departments, roles, security_level]);
  return result;
}

function byDepartment(users: readonly UserRow[]): [string, UserRow[]][] {
  const groups = new Map<string, UserRow[]>();
  for (const user of users) {
    groups.set(user.department, [...(groups.get(user.department) ?? []), user]);
  }
  return [...groups.entries()];
}

export function Recipients({ preview }: { preview: State }) {
  if (preview.state === "idle") {
    return (
      <p className={styles.empty}>부서나 역할을 고르면 볼 수 있게 되는 사람이 여기 보입니다.</p>
    );
  }
  if (preview.state === "loading") {
    return <p className={styles.empty}>받는 사람을 확인하는 중입니다…</p>;
  }
  if (preview.state === "error") {
    return (
      <p className={styles.error} role="alert">
        받는 사람을 확인하지 못했습니다. {preview.message}
      </p>
    );
  }
  const { count, total_users, users } = preview.preview;
  return (
    <div className={styles.box} aria-live="polite">
      <p className={styles.count}>
        <span className={styles.number}>{count}</span>명이 볼 수 있습니다
        <span className={styles.total}> · 전체 {total_users}명 중</span>
      </p>
      {count === 0 ? (
        <p className={styles.error}>
          지금 고른 권한으로는 아무도 볼 수 없습니다. 등급을 낮추거나 부서·역할을 더 고르세요.
        </p>
      ) : (
        <ul className={styles.groups}>
          {byDepartment(users).map(([department, members]) => (
            <li key={department}>
              <span className={styles.department}>{department}</span>
              <span>{members.map((user) => `${user.name}(${user.role})`).join(", ")}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
