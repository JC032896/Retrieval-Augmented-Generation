"""배포 보조 명령: 모델 내려받기, 앱·감사자 로그인 계정 만들기 (실제 계정으로 접속해 권한 확인)."""

import runpy
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import ProgrammingError

from rag_service.deploy import cli
from tests.fixtures.db import CONNECT_ARGS, db_engine

__all__ = ["db_engine"]

APP_USER, AUDIT_USER = "rag_test_app_login", "rag_test_audit_login"


def test_download_models_fetches_embedding_and_reranker(
    capsys: pytest.CaptureFixture[str],
) -> None:
    fetched: list[str] = []

    def fake(name: str) -> str:
        fetched.append(name)
        return f"/models/{name}"

    assert cli.main(["download-models"], download=fake) == 0

    assert fetched == ["BAAI/bge-m3", "BAAI/bge-reranker-v2-m3"]
    assert "HF_HUB_OFFLINE=1" in capsys.readouterr().out


def test_default_downloader_uses_hugging_face_snapshots(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("huggingface_hub.snapshot_download", lambda repo_id: f"/cache/{repo_id}")

    assert cli._snapshot_download("BAAI/bge-m3") == "/cache/BAAI/bge-m3"


@pytest.fixture
def cleanup(db_engine: Engine) -> Iterator[None]:
    yield
    with db_engine.begin() as connection:
        for name in (APP_USER, AUDIT_USER):
            connection.execute(text(f"DROP ROLE IF EXISTS {name}"))


def _login(engine: Engine, user: str, password: str) -> Engine:
    url = engine.url.set(username=user, password=password)
    return create_engine(url, connect_args=CONNECT_ARGS)


def _env(app_password: str, audit_password: str = "") -> dict[str, str]:
    return {
        "APP_DB_USER": APP_USER,
        "APP_DB_PASSWORD": app_password,
        "AUDIT_DB_USER": AUDIT_USER,
        "AUDIT_DB_PASSWORD": audit_password,
    }


def test_created_accounts_get_only_their_role(
    db_engine: Engine, cleanup: None, capsys: pytest.CaptureFixture[str]
) -> None:
    code = cli.main(["create-db-users"], engine=db_engine, env=_env("app-pw", "audit-pw"))

    assert code == 0
    assert f"{APP_USER}: 만듦 (역할 rag_app)" in capsys.readouterr().out
    app = _login(db_engine, APP_USER, "app-pw")
    with app.connect() as connection:
        connection.execute(text("SELECT count(*) FROM documents"))
        with pytest.raises(ProgrammingError, match="permission denied"):
            connection.execute(text("SELECT question FROM audit_log"))
    app.dispose()
    auditor = _login(db_engine, AUDIT_USER, "audit-pw")
    with auditor.connect() as connection:
        connection.execute(text("SELECT count(*) FROM audit_log"))
        with pytest.raises(ProgrammingError, match="permission denied"):
            connection.execute(text("SELECT count(*) FROM documents"))
    auditor.dispose()


def test_running_again_updates_the_password_and_skips_missing_audit_account(
    db_engine: Engine, cleanup: None, capsys: pytest.CaptureFixture[str]
) -> None:
    cli.main(["create-db-users"], engine=db_engine, env=_env("old-pw"))
    capsys.readouterr()

    assert cli.main(["create-db-users"], engine=db_engine, env=_env("new-pw")) == 0

    out = capsys.readouterr().out
    assert f"{APP_USER}: 비밀번호 갱신" in out
    assert f"{AUDIT_USER}: 비밀번호가 없어 만들지 않음" in out
    app = _login(db_engine, APP_USER, "new-pw")
    with app.connect() as connection:
        assert connection.scalar(text("SELECT current_user")) == APP_USER
    app.dispose()


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({}, "APP_DB_PASSWORD가 없습니다"),
        ({"APP_DB_PASSWORD": "x", "APP_DB_USER": "Bad-Name"}, "영문 소문자"),
    ],
)
def test_invalid_input_stops_before_touching_the_db(
    env: dict[str, str], message: str, capsys: pytest.CaptureFixture[str]
) -> None:
    unused = create_engine("postgresql+psycopg://nobody@127.0.0.1:1/none")

    assert cli.main(["create-db-users"], engine=unused, env=env) == 2
    assert message in capsys.readouterr().out


def test_reads_process_environment_by_default(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("APP_DB_PASSWORD", raising=False)

    assert cli.main(["create-db-users"]) == 2  # 엔진은 만들지만 접속하기 전에 멈춘다
    assert "APP_DB_PASSWORD가 없습니다" in capsys.readouterr().out


def test_module_entry_point_calls_main(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "main", lambda: 4)

    with pytest.raises(SystemExit) as excinfo:
        runpy.run_module("rag_service.deploy", run_name="__main__")

    assert excinfo.value.code == 4
