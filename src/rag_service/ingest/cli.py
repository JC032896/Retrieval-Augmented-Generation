"""문서 수집 명령.

  uv run python -m rag_service.ingest samples            증분 수집 (바뀐 문서만)
  uv run python -m rag_service.ingest samples --dry-run  할 일만 출력
  uv run python -m rag_service.ingest samples --prune    목록에서 빠진 이 폴더 문서도 지운다
  uv run python -m rag_service.ingest samples --force    전부 다시 청킹·임베딩 (청킹 방식 변경 시)
  uv run python -m rag_service.ingest check samples      신선도 점검 (읽기 전용, 문제 시 exit 1)

폴더 이름이 check라면 ./check처럼 써서 점검 명령과 구분한다.
"""

import argparse
import sys
import time
from collections.abc import Callable, Sequence
from datetime import date
from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from rag_service.config import get_settings
from rag_service.corpus import load_corpus
from rag_service.ingest.check import check_index
from rag_service.ingest.embedder import DEFAULT_MODEL, Embedder, SentenceTransformerEmbedder
from rag_service.ingest.pipeline import IngestStats, ingest_corpus, plan_sync, summarize
from rag_service.ingest.tokenizer import KoreanTokenizer


def main(
    argv: Sequence[str] | None = None,
    *,
    embedder_factory: Callable[[], Embedder] = SentenceTransformerEmbedder,
    model_name: str = DEFAULT_MODEL,
    engine: Engine | None = None,
) -> int:
    """model_name은 모델을 읽지 않는 --dry-run과 check가 쓰는 임베딩 모델 이름이다.

    실제 수집은 embedder_factory가 만든 임베더의 이름을 쓴다 (기본값끼리는 같다).
    """
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "check":
        return _check(args[1:], model_name=model_name, engine=engine)

    parser = argparse.ArgumentParser(
        prog="python -m rag_service.ingest",
        description="코퍼스 폴더(org.yaml, acl.yaml, docs/)를 DB에 맞춘다 (바뀐 문서만 수집).",
        epilog="신선도 점검: python -m rag_service.ingest check <폴더>",
    )
    parser.add_argument("root", type=Path, help="코퍼스 폴더 (예: samples)")
    parser.add_argument(
        "--prune", action="store_true", help="이 폴더에서 수집했지만 목록에서 빠진 문서를 지운다"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="할 일만 출력하고 DB는 바꾸지 않는다"
    )
    parser.add_argument("--force", action="store_true", help="바뀌지 않은 문서도 다시 수집한다")
    parsed = parser.parse_args(args)

    corpus = load_corpus(parsed.root)  # 파일 검증을 모델 로딩보다 먼저 한다
    engine = engine or create_engine(get_settings().database_url)
    started = time.perf_counter()
    with Session(engine) as session, session.begin():
        if parsed.dry_run:  # 모델(수 GB)을 읽지 않는다
            plan = plan_sync(
                session, corpus, model=model_name, prune=parsed.prune, force=parsed.force
            )
            stats = IngestStats(**vars(plan), documents=len(corpus.documents), dry_run=True)
            session.rollback()
        else:
            stats = ingest_corpus(
                session,
                corpus,
                embedder=embedder_factory(),
                tokenizer=KoreanTokenizer(),
                prune=parsed.prune,
                force=parsed.force,
            )
    print("\n".join(summarize(stats, time.perf_counter() - started)))
    return 0


def _check(argv: Sequence[str], *, model_name: str, engine: Engine | None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m rag_service.ingest check",
        description="원문 폴더와 DB 인덱스가 맞는지 점검한다 (읽기 전용).",
    )
    parser.add_argument("root", type=Path, help="코퍼스 폴더 (예: samples)")
    parser.add_argument(
        "--embedding-model", default=model_name, help=f"기대하는 임베딩 모델 (기본 {model_name})"
    )
    parser.add_argument(
        "--today", type=date.fromisoformat, default=date.today(), help="시행일 판단 기준일"
    )
    parsed = parser.parse_args(argv)

    corpus = load_corpus(parsed.root)
    engine = engine or create_engine(get_settings().database_url)
    with Session(engine) as session:
        findings = check_index(session, corpus, model=parsed.embedding_model, today=parsed.today)
    errors = sum(1 for finding in findings if finding.level == "error")
    for finding in findings:
        print(finding)
    print(
        f"점검: 문서 {len(corpus.documents)}개, 오류 {errors}개,"
        f" 경고 {len(findings) - errors}개 (기준일 {parsed.today}, 모델 {parsed.embedding_model})"
    )
    return 1 if errors else 0
