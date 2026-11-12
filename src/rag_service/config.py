"""환경 변수(.env 포함)에서 읽는 서비스 설정."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL

from rag_service.api.oidc import OidcConfig, check_issuer_url
from rag_service.api.roles import RoleGroups


class Settings(BaseSettings):
    """docker-compose.yml, .env.example과 같은 이름(POSTGRES_*)을 쓴다."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    postgres_user: str = "rag"
    postgres_password: str = "rag"
    # 비밀번호를 파일에서 읽는다 (deploy/compose.yaml: 첫 실행 때 setup이 만든 비밀 볼륨).
    # 있으면 위 값보다 우선한다
    postgres_password_file: Path | None = None
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "rag"

    # 답변 생성 LLM. 키는 .env의 ANTHROPIC_API_KEY에만 둔다 (커밋 금지)
    anthropic_api_key: SecretStr | None = None
    # 답변 LLM 제공자 (answer/providers.py). openai_compatible이면 사내 서버(vLLM, Ollama 등)를
    # 부르고, LLM_MODEL은 그 서버의 모델 이름이다. 평가 결과는 README "답변 LLM 선택" 참고
    llm_provider: Literal["claude", "openai_compatible"] = "claude"
    llm_base_url: str | None = None  # 예: http://gpu-server:8000/v1 (openai_compatible에서만)
    llm_api_key: SecretStr | None = None  # 사내 서버가 키를 요구할 때만
    llm_model: str = "claude-sonnet-5-5"
    llm_effort: Literal["low", "medium", "high"] = "medium"
    llm_timeout_seconds: float = 120.0
    # LLM 사용 한도 (rag_service.api.limits). 비우면 그 한도를 두지 않는다. 넘으면 질문 API가 429
    llm_daily_requests_per_user: int | None = Field(default=200, ge=1)  # 사용자별 하루 질문 수
    llm_daily_budget_usd: float | None = Field(default=20.0, gt=0)  # 회사 전체 하루 비용 (달러)
    llm_concurrent_per_user: int | None = Field(
        default=3, ge=1
    )  # 사용자별 동시 질문 (프로세스마다)
    usage_utc_offset_hours: int = Field(default=9, ge=-12, le=14)  # "하루"의 기준 시간대 (9 = 한국)

    # API가 요청한 사용자를 확인하는 방식 (rag_service.api.auth 참고)
    # - disabled: 질문 API를 막는다 (기본값. 설정하지 않은 서버가 열린 채로 뜨지 않게)
    # - dev_header: X-User-Id 헤더를 그대로 믿는다. 개발과 데모 전용 (누구나 다른 사람 행세 가능)
    # - oidc: 회사 로그인 시스템이 발급한 토큰을 검증한다 (운영용, OIDC_* 설정 필요)
    auth_mode: Literal["disabled", "dev_header", "oidc"] = "disabled"
    oidc_issuer: str | None = None  # 예: https://login.microsoftonline.com/<테넌트>/v2.0
    oidc_audience: str | None = None  # 로그인 시스템에 등록한 이 앱의 id
    oidc_login_claim: str = "email"  # users.login과 맞출 토큰 값
    # http를 허용할 내부 호스트 (쉼표로 구분). deploy/의 데모 Keycloak("keycloak") 전용, 운영은 비움
    oidc_allow_http_hosts: str = ""
    # 관리 화면 역할 (rag_service.api.roles). 토큰의 그룹 값 이름과, 역할마다 대응하는 그룹
    oidc_groups_claim: str = "groups"
    admin_group: str = "rag-admin"  # 중앙 관리자
    doc_manager_group: str = "rag-doc-manager"  # 부서 문서 담당
    auditor_group: str = "rag-auditor"  # 감사 담당
    # 관리 화면에서 감사 기록을 읽는 감사 담당 DB 계정 (rag_auditor 역할: 감사 테이블 읽기만).
    # 앱 계정은 감사 기록을 읽을 수 없어서 따로 연결한다. 비우면 관리 화면의 감사 기록이 503.
    # false면 계정이 있어도 연결하지 않는다: 앱 프로세스가 감사 담당 비밀번호를 쓰지 않으므로
    # 앱이 뚫려도 감사 기록이 새지 않는다. 감사 조사는 scripts/replay.py 등 별도 도구로 한다
    admin_audit_view: bool = True
    audit_db_user: str | None = None
    audit_db_password: SecretStr | None = None
    audit_db_password_file: Path | None = None  # 있으면 audit_db_password보다 우선

    # 감사 기록 (rag_service.audit). 질문·답변 원문에는 개인정보가 섞일 수 있어 보관 기간을 둔다
    audit_store_text: bool = True  # false면 원문 대신 길이와 해시만 남긴다
    # purge 명령이 이보다 오래된 기록과, 남은 기록이 가리키지 않는 조각 스냅샷을 지운다.
    # 비우면(기본) 지우지 않는다. 보관 기간은 회사의 개인정보·감사 정책으로 정한다
    audit_retention_days: int | None = Field(default=None, ge=1)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    # 서버 시작 때 임베딩·리랭커 모델을 미리 읽는다 (rag_service.api.readiness). 운영 compose는 true
    preload_models: bool = False
    # LLM 요청 원문(근거 조각 본문 포함)을 DEBUG 로그로 남긴다. 개발 전용이라 AUTH_MODE=oidc와 함께
    # 켤 수 없고, LOG_LEVEL=DEBUG일 때만 실제로 출력된다
    log_prompts: bool = False

    @field_validator(
        "anthropic_api_key",
        "llm_base_url",
        "llm_api_key",
        "oidc_issuer",
        "oidc_audience",
        "audit_retention_days",
        "llm_daily_requests_per_user",
        "llm_daily_budget_usd",
        "llm_concurrent_per_user",
        "audit_db_user",
        "audit_db_password",
        "audit_db_password_file",
        mode="before",
    )
    @classmethod
    def _empty_is_unset(cls, value: object) -> object:
        """빈 값(KEY=)은 설정하지 않은 것으로 본다. compose는 비운 변수도 빈 문자열로 넘긴다."""
        return None if value == "" else value

    @model_validator(mode="after")
    def _read_password_file(self) -> "Settings":
        if self.postgres_password_file is not None:
            self.postgres_password = self.postgres_password_file.read_text(encoding="utf-8").strip()
        if self.audit_db_password_file is not None:
            password = self.audit_db_password_file.read_text(encoding="utf-8").strip()
            self.audit_db_password = SecretStr(password)
        return self

    @model_validator(mode="after")
    def _check_oidc(self) -> "Settings":
        if self.llm_provider == "openai_compatible" and not (
            self.llm_base_url and self.llm_base_url.startswith(("http://", "https://"))
        ):
            raise ValueError(
                "LLM_PROVIDER=openai_compatible에는 LLM_BASE_URL(http/https)이 필요합니다"
            )
        if self.log_prompts and self.auth_mode == "oidc":
            raise ValueError("LOG_PROMPTS는 개발 전용입니다 (AUTH_MODE=oidc와 함께 켤 수 없음)")
        if self.auth_mode == "oidc":
            if not self.oidc_issuer or not self.oidc_audience:
                raise ValueError("AUTH_MODE=oidc에는 OIDC_ISSUER와 OIDC_AUDIENCE가 필요합니다")
            check_issuer_url(self.oidc_issuer, self.allow_http_hosts)
        return self

    @property
    def oidc(self) -> OidcConfig | None:
        if not self.oidc_issuer or not self.oidc_audience:
            return None
        return OidcConfig(
            self.oidc_issuer,
            self.oidc_audience,
            self.oidc_login_claim,
            self.allow_http_hosts,
            self.oidc_groups_claim,
        )

    @property
    def role_groups(self) -> RoleGroups:
        return RoleGroups(self.admin_group, self.doc_manager_group, self.auditor_group)

    @property
    def allow_http_hosts(self) -> tuple[str, ...]:
        return tuple(h.strip() for h in self.oidc_allow_http_hosts.split(",") if h.strip())

    @property
    def database_url(self) -> URL:
        # 문자열을 직접 이어 붙이지 않고 URL.create를 써서 비밀번호의 특수문자를 안전하게 처리한다
        return URL.create(
            "postgresql+psycopg",
            username=self.postgres_user,
            password=self.postgres_password,
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        )

    @property
    def audit_database_url(self) -> URL | None:
        """감사 담당 계정으로 같은 DB에 접속하는 주소. 계정이나 비밀번호가 없으면 None."""
        if not self.audit_db_user or self.audit_db_password is None:
            return None
        return self.database_url.set(
            username=self.audit_db_user, password=self.audit_db_password.get_secret_value()
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
