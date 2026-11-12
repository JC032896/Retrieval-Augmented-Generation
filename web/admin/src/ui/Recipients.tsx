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

export type RecipientDiff = { added: UserRow[]; removed: UserRow[] };

/** 저장된 권한(기준)과 비교해 새로 보게 되는 사람과 더 이상 못 보는 사람. 기준이 없으면 비교하지 않는다. */
export function diffRecipients(baseline: State | undefined, current: State): RecipientDiff | null {
  if (baseline?.state !== "ready" || current.state !== "ready") return null;
  const before = new Set(baseline.preview.users.map((u) => u.login));
  const after = new Set(current.preview.users.map((u) => u.login));
  return {
    added: current.preview.users.filter((u) => !before.has(u.login)),
    removed: baseline.preview.users.filter((u) => !after.has(u.login)),
  };
}

export function personName(user: UserRow): string {
  return `${user.name}(${user.role})`;
}

export function Recipients({ preview, baseline }: { preview: State; baseline?: State }) {
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
  const diff = diffRecipients(baseline, preview);
  const added = new Set(diff?.added.map((u) => u.login));
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
              <span className={styles.people}>
                {members.map((user) => (
                  <span
                    key={user.login}
                    className={added.has(user.login) ? styles.added : undefined}
                  >
                    {added.has(user.login) ? "+ " : ""}
                    {personName(user)}
                    {added.has(user.login) ? <span className={styles.tag}>새로 봄</span> : null}
                  </span>
                ))}
              </span>
            </li>
          ))}
        </ul>
      )}
      {diff && diff.removed.length > 0 ? (
        <div className={styles.removed}>
          <span className={styles.department}>더 이상 못 봄</span>
          <span className={styles.people}>
            {diff.removed.map((user) => (
              <span key={user.login}>− {personName(user)}</span>
            ))}
          </span>
        </div>
      ) : null}
    </div>
  );
}
