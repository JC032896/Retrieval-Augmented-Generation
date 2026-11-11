"""환경 변수(.env 포함)에서 읽는 서비스 설정."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL

from rag_service.api.oidc import OidcConfig, check_issuer_url


class Settings(BaseSettings):
    """docker-compose.yml, .env.example과 같은 이름(POSTGRES_*)을 쓴다."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    postgres_user: str = "rag"
    postgres_password: str = "rag"
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "rag"

    # 답변 생성 LLM. 키는 .env의 ANTHROPIC_API_KEY에만 둔다 (커밋 금지)
    anthropic_api_key: SecretStr | None = None
    llm_model: str = "claude-sonnet-5-5"
    llm_effort: Literal["low", "medium", "high"] = "medium"
    llm_timeout_seconds: float = 120.0

    # API가 요청한 사용자를 확인하는 방식 (rag_service.api.auth 참고)
    # - disabled: 질문 API를 막는다 (기본값. 설정하지 않은 서버가 열린 채로 뜨지 않게)
    # - dev_header: X-User-Id 헤더를 그대로 믿는다. 개발과 데모 전용 (누구나 다른 사람 행세 가능)
    # - oidc: 회사 로그인 시스템이 발급한 토큰을 검증한다 (운영용, OIDC_* 설정 필요)
    auth_mode: Literal["disabled", "dev_header", "oidc"] = "disabled"
    oidc_issuer: str | None = None  # 예: https://login.microsoftonline.com/<테넌트>/v2.0
    oidc_audience: str | None = None  # 로그인 시스템에 등록한 이 앱의 id
    oidc_login_claim: str = "email"  # users.login과 맞출 토큰 값

    # 감사 기록 (rag_service.audit). 질문·답변 원문에는 개인정보가 섞일 수 있어 보관 기간을 둔다
    audit_store_text: bool = True  # false면 원문 대신 길이와 해시만 남긴다
    # purge 명령이 이보다 오래된 기록과, 남은 기록이 가리키지 않는 조각 스냅샷을 지운다.
    # 비우면(기본) 지우지 않는다. 보관 기간은 회사의 개인정보·감사 정책으로 정한다
    audit_retention_days: int | None = Field(default=None, ge=1)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    # LLM 요청 원문(근거 조각 본문 포함)을 DEBUG 로그로 남긴다. 개발 전용이라 AUTH_MODE=oidc와 함께
    # 켤 수 없고, LOG_LEVEL=DEBUG일 때만 실제로 출력된다
    log_prompts: bool = False

    @model_validator(mode="after")
    def _check_oidc(self) -> "Settings":
        if self.log_prompts and self.auth_mode == "oidc":
            raise ValueError("LOG_PROMPTS는 개발 전용입니다 (AUTH_MODE=oidc와 함께 켤 수 없음)")
        if self.auth_mode == "oidc":
            if not self.oidc_issuer or not self.oidc_audience:
                raise ValueError("AUTH_MODE=oidc에는 OIDC_ISSUER와 OIDC_AUDIENCE가 필요합니다")
            check_issuer_url(self.oidc_issuer)
        return self

    @property
    def oidc(self) -> OidcConfig | None:
        if not self.oidc_issuer or not self.oidc_audience:
            return None
        return OidcConfig(self.oidc_issuer, self.oidc_audience, self.oidc_login_claim)

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
