"""배포 보조 명령.

  python -m rag_service.deploy prepare           첫 실행 준비: 비밀번호 파일, 모델 (compose의 setup)
  python -m rag_service.deploy download-models   임베딩·리랭커 모델을 HF_HOME(모델 볼륨)에 받아 둔다
  python -m rag_service.deploy create-db-users   앱·감사자 로그인 계정을 만들거나 비밀번호를 맞춘다

prepare는 매번 실행해도 안전하다. 비밀번호 파일이 이미 있으면 그대로 두고, 없을 때만 만든다
(환경 변수에 값이 있으면 그 값, 없으면 무작위). 비밀번호는 화면이나 로그에 출력하지 않는다.
모델은 없는 파일만 받고, HF_HUB_OFFLINE=1이면 받지 않고 있는지만 확인한다(폐쇄망).

download-models는 설치할 때 한 번, 인터넷이 되는 곳에서 실행한다. 폐쇄망이면 받아 둔 모델 폴더를
그대로 복사해 넣고, 앱은 HF_HUB_OFFLINE=1로 실행한다.

create-db-users는 마이그레이션 계정(테이블 소유자)으로 실행한다. 마이그레이션 0005가 만든 역할
(rag_app, rag_auditor)을 받는 로그인 계정을 만든다. 이미 있으면 비밀번호와 역할만 다시 맞춘다.
  APP_DB_USER / APP_DB_PASSWORD       앱 계정 (기본 이름 rag_service, 비밀번호 필수)
  AUDIT_DB_USER / AUDIT_DB_PASSWORD   감사 담당 계정 (기본 이름 rag_audit_ops, 비밀번호 없으면 생략)
비밀번호는 <이름>_FILE(파일 경로)로도 줄 수 있다.
"""

import argparse
import os
import re
import secrets
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, cast

import psycopg
from psycopg import sql
from sqlalchemy import Engine, create_engine

from rag_service.audit.models import APP_ROLE, AUDITOR_ROLE
from rag_service.config import get_settings
from rag_service.ingest.embedder import DEFAULT_MODEL
from rag_service.retrieval.rerank import DEFAULT_RERANK_MODEL

MODELS = (DEFAULT_MODEL, DEFAULT_RERANK_MODEL)
ROLE_NAME = re.compile(r"[a-z_][a-z0-9_]{0,62}")

Downloader = Callable[[str], str]  # 모델 이름 → 받은 폴더


def _snapshot_download(repo_id: str) -> str:
    # 수집·검색 코드는 huggingface_hub를 직접 쓰지 않으므로 이 명령에서만 불러온다
    from huggingface_hub import snapshot_download

    return snapshot_download(repo_id)


def download_models(download: Downloader = _snapshot_download) -> int:
    for name in MODELS:
        print(f"{name} → {download(name)}")
    print("모델 준비 완료. 앱은 HF_HUB_OFFLINE=1로 실행해도 됩니다.")
    return 0


# 비밀번호 파일: (폴더를 알려 주는 환경 변수, 파일 이름, 직접 줄 때 쓰는 환경 변수)
# 폴더마다 다른 볼륨이라, 서비스는 필요한 폴더만 받는다 (앱 컨테이너는 소유자 비밀번호를 모른다)
SECRET_FILES = (
    ("OWNER_SECRETS_DIR", "db_owner_password", "DB_OWNER_PASSWORD"),
    ("APP_SECRETS_DIR", "app_db_password", "APP_DB_PASSWORD"),
    ("APP_SECRETS_DIR", "audit_db_password", "AUDIT_DB_PASSWORD"),
    ("KEYCLOAK_SECRETS_DIR", "keycloak_admin_password", "KEYCLOAK_ADMIN_PASSWORD"),
)


def secret(env: Mapping[str, str], name: str) -> str | None:
    """환경 변수 name, 없으면 name_FILE이 가리키는 파일의 내용."""
    if env.get(name):
        return env[name]
    path = env.get(f"{name}_FILE")
    return Path(path).read_text(encoding="utf-8").strip() if path else None


def write_secrets(env: Mapping[str, str]) -> None:
    for dir_var, file_name, value_var in SECRET_FILES:
        folder = env.get(dir_var)
        if not folder:
            continue
        path = Path(folder) / file_name
        if path.exists():
            print(f"{file_name}: 있음, 그대로 둠")
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(env.get(value_var) or secrets.token_urlsafe(24), encoding="utf-8")
        # DB(postgres)와 앱(rag)이 다른 사용자로 읽는다. 폴더(볼륨)는 필요한 서비스에만 붙인다
        path.chmod(0o444)
        print(f"{file_name}: {'설정값으로 만듦' if env.get(value_var) else '무작위로 만듦'}")


def prepare(env: Mapping[str, str], download: Downloader = _snapshot_download) -> int:
    write_secrets(env)
    offline = env.get("HF_HUB_OFFLINE") == "1"
    for name in MODELS:
        try:
            print(f"{name} → {download(name)}")
        except Exception as error:  # 내려받기 실패, 폐쇄망에서 파일 없음 등
            hint = (
                "모델 볼륨에 받아 둔 모델 폴더를 복사해 넣으세요 (deploy/README.md 폐쇄망)"
                if offline
                else "인터넷 연결을 확인하고 다시 실행하세요"
            )
            print(f"{name}: 모델을 준비하지 못했습니다 ({type(error).__name__}). {hint}")
            return 1
    print("준비 완료")
    return 0


def create_db_users(engine: Engine, env: Mapping[str, str]) -> int:
    accounts = [
        (env.get("APP_DB_USER") or "rag_service", secret(env, "APP_DB_PASSWORD"), APP_ROLE),
        (
            env.get("AUDIT_DB_USER") or "rag_audit_ops",
            secret(env, "AUDIT_DB_PASSWORD"),
            AUDITOR_ROLE,
        ),
    ]
    if not accounts[0][1]:
        print("APP_DB_PASSWORD가 없습니다. 앱 계정 비밀번호를 설정하세요.")
        return 2
    for name, _, _ in accounts:
        if not ROLE_NAME.fullmatch(name):
            print(f"계정 이름은 영문 소문자, 숫자, _만 쓸 수 있습니다: {name}")
            return 2
    with engine.begin() as connection:
        # 역할 이름과 비밀번호는 바인드 변수로 넘길 수 없어 psycopg의 sql 조립(따옴표 처리)을 쓴다
        driver = cast(psycopg.Connection[Any], connection.connection.driver_connection)
        cursor = driver.cursor()
        for name, password, role in accounts:
            if not password:
                print(f"{name}: 비밀번호가 없어 만들지 않음")
                continue
            cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (name,))
            verb = "ALTER" if cursor.fetchone() else "CREATE"
            cursor.execute(
                sql.SQL("{} ROLE {} LOGIN PASSWORD {}").format(
                    sql.SQL(verb), sql.Identifier(name), sql.Literal(password)
                )
            )
            cursor.execute(
                sql.SQL("GRANT {} TO {}").format(sql.Identifier(role), sql.Identifier(name))
            )
            print(f"{name}: {'만듦' if verb == 'CREATE' else '비밀번호 갱신'} (역할 {role})")
    return 0


def main(
    argv: Sequence[str] | None = None,
    *,
    engine: Engine | None = None,
    env: Mapping[str, str] | None = None,
    download: Downloader = _snapshot_download,
) -> int:
    parser = argparse.ArgumentParser(prog="python -m rag_service.deploy")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("prepare", help="첫 실행 준비: 비밀번호 파일, 모델")
    commands.add_parser("download-models", help="임베딩·리랭커 모델을 모델 볼륨에 받아 둔다")
    commands.add_parser("create-db-users", help="앱·감사자 로그인 계정을 만든다")
    args = parser.parse_args(argv)

    env = os.environ if env is None else env
    if args.command == "prepare":
        return prepare(env, download)
    if args.command == "download-models":
        return download_models(download)
    engine = engine or create_engine(get_settings().database_url)
    return create_db_users(engine, env)
