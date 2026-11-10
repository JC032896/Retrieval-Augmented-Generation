"""문서 수집 명령. 사용법: uv run python -m rag_service.ingest samples"""

import argparse
from collections.abc import Callable, Sequence
from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from rag_service.config import get_settings
from rag_service.corpus import load_corpus
from rag_service.ingest.embedder import Embedder, SentenceTransformerEmbedder
from rag_service.ingest.pipeline import ingest_corpus
from rag_service.ingest.tokenizer import KoreanTokenizer


def main(
    argv: Sequence[str] | None = None,
    *,
    embedder_factory: Callable[[], Embedder] = SentenceTransformerEmbedder,
    engine: Engine | None = None,
) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m rag_service.ingest",
        description="코퍼스 폴더(org.yaml, acl.yaml, docs/)를 DB에 저장한다.",
    )
    parser.add_argument("root", type=Path, help="코퍼스 폴더 (예: samples)")
    args = parser.parse_args(argv)

    corpus = load_corpus(args.root)  # 파일 검증을 모델 로딩보다 먼저 한다
    engine = engine or create_engine(get_settings().database_url)
    with Session(engine) as session, session.begin():
        stats = ingest_corpus(
            session, corpus, embedder=embedder_factory(), tokenizer=KoreanTokenizer()
        )
    print(
        f"문서 {stats.documents}개, 조각 {stats.chunks}개, 사용자 {stats.users}명 저장"
        f" (삭제된 문서 {stats.removed}개)"
    )
    return 0
