from pathlib import Path

import pytest

from rag_service.config import Settings, get_settings

POSTGRES_ENV_VARS = (
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "POSTGRES_DB",
)


@pytest.fixture
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """로컬 .env와 셸의 POSTGRES_* 값이 테스트에 섞이지 않게 한다."""
    monkeypatch.chdir(tmp_path)  # .env가 없는 디렉터리
    for name in POSTGRES_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_database_url_uses_psycopg_driver_and_defaults(isolated_env: pytest.MonkeyPatch) -> None:
    url = Settings().database_url

    assert url.drivername == "postgresql+psycopg"
    assert (url.host, url.port, url.database) == ("localhost", 5432, "rag")


def test_database_url_escapes_special_characters_in_password(
    isolated_env: pytest.MonkeyPatch,
) -> None:
    settings = Settings(postgres_password="p@ss:w/rd")

    rendered = settings.database_url.render_as_string(hide_password=False)

    assert "p%40ss%3Aw%2Frd@" in rendered


def test_settings_read_postgres_env_vars(isolated_env: pytest.MonkeyPatch) -> None:
    isolated_env.setenv("POSTGRES_HOST", "db.internal")
    isolated_env.setenv("POSTGRES_PORT", "6543")

    url = Settings().database_url

    assert (url.host, url.port) == ("db.internal", 6543)


def test_settings_read_dotenv_file(isolated_env: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("POSTGRES_DB=from_dotenv\n", encoding="utf-8")

    assert Settings().database_url.database == "from_dotenv"


def test_get_settings_is_cached() -> None:
    assert get_settings() is get_settings()
