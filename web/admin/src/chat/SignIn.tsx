// 로그인 전 화면. 회사 로그인으로 보내거나, 개발·데모 모드에서는 로그인 id를 직접 넣는다.
import { type FormEvent, useState } from "react";
import type { UiConfig } from "../api/types";
import styles from "./SignIn.module.css";

export function ChatSignIn({
  config,
  onSignIn,
}: {
  config: UiConfig;
  onSignIn: (login?: string) => void;
}) {
  const [login, setLogin] = useState("");
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (login.trim()) onSignIn(login.trim());
  };
  return (
    <main className={styles.page}>
      <section className={styles.panel} aria-labelledby="sign-in">
        {config.company_name || config.company_logo_url ? (
          <p className={styles.org}>
            {config.company_logo_url ? (
              <img src={config.company_logo_url} alt="" className={styles.logo} />
            ) : null}
            {config.company_name}
          </p>
        ) : null}
        <h1 id="sign-in">
          사내 문서에 <span className={styles.mark}>물어보세요</span>
        </h1>
        <p className={styles.lead}>
          내가 볼 수 있는 문서에서만 답을 찾고, 답의 문장마다 근거 문단을 함께 보여 줍니다.
        </p>
        {config.auth_mode === "oidc" ? (
          <button type="button" className={styles.primary} onClick={() => onSignIn()}>
            회사 계정으로 로그인
          </button>
        ) : (
          <form className={styles.form} onSubmit={submit}>
            <p className={styles.warn}>
              개발·데모 모드입니다. 넣은 로그인 id를 서버가 그대로 믿으므로 운영에서 쓰지 않습니다.
            </p>
            <label htmlFor="dev-login" className={styles.label}>
              로그인 id
            </label>
            <input
              id="dev-login"
              required
              value={login}
              onChange={(event) => setLogin(event.target.value)}
              autoComplete="username"
              spellCheck={false}
            />
            <button type="submit" className={styles.primary}>
              이 사람으로 들어가기
            </button>
          </form>
        )}
      </section>
    </main>
  );
}
