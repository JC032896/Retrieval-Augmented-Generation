"""환경 변수(.env 포함)에서 읽는 서비스 설정."""

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


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
