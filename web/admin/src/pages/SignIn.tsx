// 로그인 전 화면. 회사 로그인으로 보내거나, 개발·데모 모드에서는 사용자를 직접 고른다.
import { type FormEvent, useState } from "react";
import type { UiConfig } from "../api/types";
import type { DevIdentity } from "../auth/session";
import styles from "./SignIn.module.css";

const DEV_GROUPS = [
  { value: "rag-admin", label: "중앙 관리자 (rag-admin)" },
  { value: "rag-doc-manager", label: "부서 문서 담당 (rag-doc-manager)" },
  { value: "rag-auditor", label: "감사 담당 (rag-auditor)" },
];

function DevSignIn({ onSignIn }: { onSignIn: (dev: DevIdentity) => void }) {
  const [login, setLogin] = useState("");
  const [groups, setGroups] = useState<string[]>([]);
  const submit = (event: FormEvent) => {
    event.preventDefault();
    onSignIn({ login: login.trim(), groups: groups.join(",") });
  };
  return (
    <form className={styles.form} onSubmit={submit}>
      <p className={styles.warn}>
        개발·데모 모드입니다. 고른 사람과 그룹을 서버가 그대로 믿으므로 운영에서 쓰지 않습니다.
      </p>
      <label className={styles.field}>
        <span>로그인 id</span>
        <input
          required
          value={login}
          onChange={(event) => setLogin(event.target.value)}
          autoComplete="username"
          spellCheck={false}
        />
      </label>
      <fieldset className={styles.field}>
        <legend>관리 역할 그룹</legend>
        {DEV_GROUPS.map((group) => (
          <label key={group.value} className={styles.check}>
            <input
              type="checkbox"
              checked={groups.includes(group.value)}
              onChange={(event) =>
                setGroups((current) =>
                  event.target.checked
                    ? [...current, group.value]
                    : current.filter((value) => value !== group.value),
                )
              }
            />
            {group.label}
          </label>
        ))}
      </fieldset>
      <button type="submit" className={styles.primary}>
        이 사람으로 들어가기
      </button>
    </form>
  );
}

export function SignIn({
  config,
  onSignIn,
}: {
  config: UiConfig;
  onSignIn: (dev?: DevIdentity) => void;
}) {
  return (
    <main className={styles.page}>
      <div className={styles.rail}>
        {config.company_logo_url ? (
          <img src={config.company_logo_url} alt="" className={styles.logo} />
        ) : null}
        <span className={styles.org}>{config.company_name || "사내 문서 질의"}</span>
      </div>
      <section className={styles.panel} aria-labelledby="sign-in">
        <h1 id="sign-in">문서 질의 관리</h1>
        <p className={styles.lead}>
          문서를 올리고 볼 수 있는 사람을 정하고, 서비스 상태와 감사 기록을 확인합니다.
        </p>
        {config.auth_mode === "oidc" ? (
          <button type="button" className={styles.primary} onClick={() => onSignIn()}>
            회사 계정으로 로그인
          </button>
        ) : (
          <DevSignIn onSignIn={onSignIn} />
        )}
      </section>
    </main>
  );
}
