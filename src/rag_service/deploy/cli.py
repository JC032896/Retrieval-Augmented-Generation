"""배포 보조 명령.

  python -m rag_service.deploy download-models   임베딩·리랭커 모델을 HF_HOME(모델 볼륨)에 받아 둔다
  python -m rag_service.deploy create-db-users   앱·감사자 로그인 계정을 만들거나 비밀번호를 맞춘다

download-models는 설치할 때 한 번, 인터넷이 되는 곳에서 실행한다. 폐쇄망이면 받아 둔 모델 폴더를
그대로 복사해 넣고, 앱은 HF_HUB_OFFLINE=1로 실행한다.

create-db-users는 마이그레이션 계정(테이블 소유자)으로 실행한다. 마이그레이션 0005가 만든 역할
(rag_app, rag_auditor)을 받는 로그인 계정을 만든다. 이미 있으면 비밀번호와 역할만 다시 맞춘다.
  APP_DB_USER / APP_DB_PASSWORD       앱 계정 (기본 이름 rag_service, 비밀번호 필수)
  AUDIT_DB_USER / AUDIT_DB_PASSWORD   감사 담당 계정 (기본 이름 rag_audit_ops, 비밀번호 없으면 생략)
"""

import argparse
import os
import re
from collections.abc import Callable, Mapping, Sequence
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


def create_db_users(engine: Engine, env: Mapping[str, str]) -> int:
    accounts = [
        (env.get("APP_DB_USER") or "rag_service", env.get("APP_DB_PASSWORD"), APP_ROLE),
        (env.get("AUDIT_DB_USER") or "rag_audit_ops", env.get("AUDIT_DB_PASSWORD"), AUDITOR_ROLE),
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
    commands.add_parser("download-models", help="임베딩·리랭커 모델을 모델 볼륨에 받아 둔다")
    commands.add_parser("create-db-users", help="앱·감사자 로그인 계정을 만든다")
    args = parser.parse_args(argv)

    if args.command == "download-models":
        return download_models(download)
    engine = engine or create_engine(get_settings().database_url)
    return create_db_users(engine, os.environ if env is None else env)
