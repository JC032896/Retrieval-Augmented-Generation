"""첫 실행 자동 준비: .env 없이 docker compose up -d, 비밀번호 파일 생성과 보관, 비밀 볼륨 분리."""

import stat
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml
from sqlalchemy import Engine, create_engine, text

from rag_service.config import Settings
from rag_service.deploy import cli
from tests.fixtures.db import CONNECT_ARGS, db_engine

__all__ = ["db_engine"]

DEPLOY = Path(__file__).resolve().parents[1] / "deploy"


def _services(name: str) -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load((DEPLOY / name).read_text(encoding="utf-8"))
    return dict(data["services"])


def test_compose_needs_no_env_file() -> None:
    for name in ("compose.yaml", "compose.override.yaml"):
        assert ":?" not in (DEPLOY / name).read_text(encoding="utf-8"), name


def _mounts(service: dict[str, Any], volume: str) -> bool:
    return any(str(v).startswith(f"{volume}:") for v in service.get("volumes", []))


def test_each_secret_volume_reaches_only_the_services_that_need_it() -> None:
    base, demo = _services("compose.yaml"), _services("compose.override.yaml")
    # compose처럼 서비스 단위로 합친다 (override의 app은 environment만 덧붙인다)
    services = {name: base.get(name, {}) | demo.get(name, {}) for name in base | demo}
    expected = {
        "owner-secrets": {"setup", "db", "migrate"},
        "app-secrets": {"setup", "migrate", "sync", "app"},
        "keycloak-secrets": {"setup", "keycloak"},
    }
    for volume, names in expected.items():
        assert {n for n, s in services.items() if _mounts(s, volume)} == names, volume
    assert [n for n, s in services.items() if s.get("user") == "0"] == ["setup"]


def test_everything_waits_for_setup_and_demo_login_is_an_override() -> None:
    base = _services("compose.yaml")
    demo = _services("compose.override.yaml")

    assert base["db"]["depends_on"]["setup"]["condition"] == "service_completed_successfully"
    assert demo["keycloak"]["depends_on"]["setup"]["condition"] == "service_completed_successfully"
    assert "keycloak" not in base
    assert demo["app"]["environment"]["OIDC_ISSUER"] == "http://keycloak:8080/realms/hanbit"
    assert "keycloak_admin_password" in " ".join(demo["keycloak"]["entrypoint"])


@pytest.fixture
def secret_dirs(tmp_path: Path) -> dict[str, str]:
    return {
        "OWNER_SECRETS_DIR": str(tmp_path / "owner"),
        "APP_SECRETS_DIR": str(tmp_path / "app"),
        "KEYCLOAK_SECRETS_DIR": str(tmp_path / "keycloak"),
    }


def test_secrets_are_generated_once_and_kept(
    secret_dirs: dict[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    cli.write_secrets({**secret_dirs, "APP_DB_PASSWORD": "chosen-by-admin"})
    first = {p.name: p.read_text() for p in Path(secret_dirs["APP_SECRETS_DIR"]).iterdir()}
    out = capsys.readouterr().out

    cli.write_secrets(secret_dirs)

    owner = Path(secret_dirs["OWNER_SECRETS_DIR"]) / "db_owner_password"
    assert len(owner.read_text()) >= 32
    assert first["app_db_password"] == "chosen-by-admin"
    assert first == {p.name: p.read_text() for p in Path(secret_dirs["APP_SECRETS_DIR"]).iterdir()}
    assert not stat.S_IMODE(owner.stat().st_mode) & stat.S_IWUSR  # 읽기 전용
    assert "app_db_password: 설정값으로 만듦" in out
    assert "chosen-by-admin" not in out  # 비밀번호는 출력하지 않는다
    assert "있음, 그대로 둠" in capsys.readouterr().out


def test_folders_not_given_are_skipped(tmp_path: Path) -> None:
    cli.write_secrets({"APP_SECRETS_DIR": str(tmp_path)})

    assert sorted(p.name for p in tmp_path.iterdir()) == ["app_db_password", "audit_db_password"]


def test_prepare_reports_missing_models_with_the_right_hint(
    secret_dirs: dict[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    def offline(name: str) -> str:
        raise FileNotFoundError(name)

    assert cli.prepare({**secret_dirs, "HF_HUB_OFFLINE": "1"}, offline) == 1
    assert "폐쇄망" in capsys.readouterr().out
    assert cli.prepare(secret_dirs, offline) == 1
    assert "인터넷 연결" in capsys.readouterr().out
    assert cli.main(["prepare"], env=secret_dirs, download=lambda name: f"/models/{name}") == 0
    assert "준비 완료" in capsys.readouterr().out


def test_settings_read_the_database_password_from_a_file(tmp_path: Path) -> None:
    secret = tmp_path / "app_db_password"
    secret.write_text("s3cret\n", encoding="utf-8")

    settings = Settings(postgres_password="ignored", postgres_password_file=secret)

    assert settings.postgres_password == "s3cret"
    assert settings.database_url.password == "s3cret"


APP_USER = "rag_test_file_login"


@pytest.fixture
def cleanup(db_engine: Engine) -> Iterator[None]:
    yield
    with db_engine.begin() as connection:
        connection.execute(text(f"DROP ROLE IF EXISTS {APP_USER}"))


def test_db_users_take_passwords_from_files(
    db_engine: Engine, cleanup: None, tmp_path: Path
) -> None:
    password = tmp_path / "app_db_password"
    password.write_text("from-file", encoding="utf-8")
    env = {"APP_DB_USER": APP_USER, "APP_DB_PASSWORD_FILE": str(password)}

    assert cli.main(["create-db-users"], engine=db_engine, env=env) == 0

    login = create_engine(
        db_engine.url.set(username=APP_USER, password="from-file"), connect_args=CONNECT_ARGS
    )
    with login.connect() as connection:
        assert connection.scalar(text("SELECT current_user")) == APP_USER
    login.dispose()
