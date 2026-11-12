// 설정: 지금 서버가 쓰는 값 보기. 바꾸려면 서버의 .env를 고치고 다시 시작한다 (화면에서는 바꾸지 않는다).
import { useCallback } from "react";
import type { Status } from "../api/types";
import { useLoad } from "../api/useApi";
import { useApiClient, useSession } from "../auth/session";
import c from "../ui/controls.module.css";
import styles from "./Settings.module.css";

const AUTH: Record<string, string> = {
  oidc: "회사 로그인 시스템 (OIDC)",
  dev_header: "개발·데모 모드 (운영에서 쓰지 않음)",
  disabled: "꺼짐",
};

function Row({ name, value, env }: { name: string; value: string; env: string }) {
  return (
    <div className={styles.row}>
      <dt>{name}</dt>
      <dd>{value}</dd>
      <dd className={styles.env}>{env}</dd>
    </div>
  );
}

export function Settings() {
  const api = useApiClient();
  const session = useSession();
  const status = useLoad(useCallback(() => api.get<Status>("/admin/api/status"), [api]));
  const config = session.state === "signed-in" ? session.config : null;

  return (
    <div className={styles.page}>
      <header className={c.pageHead}>
        <div>
          <h1>설정</h1>
          <p>
            지금 서버가 쓰는 값입니다. 바꾸려면 서버의 deploy/.env에서 오른쪽 이름의 값을 고치고{" "}
            <code>docker compose up -d</code>로 다시 시작합니다.
          </p>
        </div>
      </header>
      {status.state === "loading" ? (
        <p className={c.message} data-tone="muted">
          설정을 불러오는 중입니다…
        </p>
      ) : status.state === "error" ? (
        <p className={c.message} data-tone="blocked" role="alert">
          설정을 불러오지 못했습니다. {status.message}
        </p>
      ) : (
        <div className={styles.sections}>
          <section className={c.panel} aria-labelledby="llm">
            <h2 id="llm">답변 LLM</h2>
            <dl>
              <Row name="제공자" value={status.data.llm.provider} env="LLM_PROVIDER" />
              <Row name="모델" value={status.data.llm.model} env="LLM_MODEL" />
              <Row
                name="상태"
                value={status.data.llm.configured ? "준비됨" : "API 키가 없어 질문이 멈춤"}
                env="ANTHROPIC_API_KEY"
              />
            </dl>
          </section>
          <section className={c.panel} aria-labelledby="limits">
            <h2 id="limits">사용 한도</h2>
            <dl>
              <Row
                name="사용자별 하루 질문"
                value={
                  status.data.limits.daily_requests_per_user === null
                    ? "한도 없음"
                    : `${status.data.limits.daily_requests_per_user}회`
                }
                env="LLM_DAILY_REQUESTS_PER_USER"
              />
              <Row
                name="회사 하루 비용"
                value={
                  status.data.limits.daily_budget_usd === null
                    ? "한도 없음"
                    : `$${status.data.limits.daily_budget_usd}`
                }
                env="LLM_DAILY_BUDGET_USD"
              />
              <Row
                name="사용자별 동시 질문"
                value={
                  status.data.limits.concurrent_per_user === null
                    ? "한도 없음"
                    : `${status.data.limits.concurrent_per_user}건`
                }
                env="LLM_CONCURRENT_PER_USER"
              />
              <Row
                name="하루의 기준 시간대"
                value={`UTC${status.data.limits.utc_offset_hours >= 0 ? "+" : ""}${status.data.limits.utc_offset_hours}`}
                env="USAGE_UTC_OFFSET_HOURS"
              />
            </dl>
          </section>
          <section className={c.panel} aria-labelledby="login">
            <h2 id="login">로그인</h2>
            <dl>
              <Row
                name="방식"
                value={AUTH[config?.auth_mode ?? "disabled"] ?? "-"}
                env="AUTH_MODE"
              />
              <Row name="발급자" value={config?.oidc?.authority ?? "-"} env="OIDC_ISSUER" />
              <Row
                name="관리 화면 클라이언트"
                value={config?.oidc?.client_id ?? "-"}
                env="ADMIN_UI_CLIENT_ID"
              />
              <Row
                name="회사 이름"
                value={config?.company_name || "설정 안 함"}
                env="COMPANY_NAME"
              />
            </dl>
          </section>
          <section className={c.panel} aria-labelledby="audit">
            <h2 id="audit">감사 기록과 서버</h2>
            <dl>
              <Row
                name="관리 화면의 감사 기록 보기"
                value={status.data.audit_db ? "켜짐 (앱이 감사 담당 DB 계정을 씀)" : "꺼짐"}
                env="ADMIN_AUDIT_VIEW"
              />
              <Row name="서비스 버전" value={status.data.version} env="이미지 태그" />
              <Row
                name="DB"
                value={status.data.db === "ok" ? "연결됨" : "연결 안 됨"}
                env="POSTGRES_*"
              />
            </dl>
          </section>
        </div>
      )}
    </div>
  );
}
