"""감사 기록 관리 명령. 사용법: uv run python -m rag_service.audit purge [--days 90]

보관 기간이 지난 기록과, 남은 기록이 가리키지 않는 조각 스냅샷을 지운다. 매일 한 번 스케줄러(cron,
작업 스케줄러, Kubernetes CronJob)로 실행한다. 기간은 --days가 없으면 설정 AUDIT_RETENTION_DAYS를
쓰고, 그것도 없으면(기본) 아무것도 지우지 않는다.

감사 테이블을 지워야 하므로 앱 계정(rag_app)이 아니라 DB 소유자(마이그레이션) 계정으로 실행한다.
"""

import argparse
from collections.abc import Sequence

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from rag_service.audit.record import purge, purge_orphan_snapshots
from rag_service.config import get_settings


def main(argv: Sequence[str] | None = None, *, engine: Engine | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m rag_service.audit")
    commands = parser.add_subparsers(dest="command", required=True)
    purge_parser = commands.add_parser("purge", help="보관 기간이 지난 감사 기록 삭제")
    purge_parser.add_argument("--days", type=int, help="이 일수보다 오래된 기록을 지운다")
    args = parser.parse_args(argv)

    settings = get_settings()
    days = args.days if args.days is not None else settings.audit_retention_days
    if days is None:
        print("보관 기간(AUDIT_RETENTION_DAYS)이 설정되지 않아 아무것도 지우지 않습니다")
        return 0
    engine = engine or create_engine(settings.database_url)
    with Session(engine) as session, session.begin():
        deleted = purge(session, older_than_days=days)
        snapshots = purge_orphan_snapshots(session)
    print(
        f"{days}일보다 오래된 감사 기록 {deleted}건 삭제,"
        f" 쓰이지 않는 조각 스냅샷 {snapshots}건 삭제"
    )
    return 0
