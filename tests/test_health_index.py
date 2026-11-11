"""/health의 인덱스 신선도 요약 (원문 존재와 수정 시각, 임베딩 모델, 마지막 수집 시각)."""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, update
from sqlalchemy.orm import Session, sessionmaker

from rag_service.corpus import load_corpus
from rag_service.db.models import Document
from rag_service.ingest.check import index_summary
from rag_service.ingest.pipeline import ingest_corpus
from rag_service.ingest.tokenizer import KoreanTokenizer
from rag_service.main import app, get_index_sessions
from tests.fixtures.corpus_copy import copy_samples
from tests.fixtures.db import CONNECT_ARGS, db_engine, db_session
from tests.fixtures.embedding import FakeEmbedder

__all__ = ["db_engine", "db_session"]

GUIDE = "06_remote_work_guide.md"


@pytest.fixture
def root(db_session: Session, tmp_path: Path) -> Path:
    root = copy_samples(tmp_path / "corpus")
    ingest_corpus(
        db_session, load_corpus(root), embedder=FakeEmbedder(), tokenizer=KoreanTokenizer()
    )
    db_session.commit()
    return root


def test_fresh_index_has_no_mismatches(db_session: Session, root: Path) -> None:
    summary = index_summary(db_session, model="FakeEmbedder")

    assert summary["documents"] == 22
    assert summary["mismatches"] == 0
    assert summary["last_synced_at"] is not None


def test_counts_changed_missing_new_and_model_mismatch(db_session: Session, root: Path) -> None:
    docs = root / "docs"
    os.utime(docs / GUIDE, (1_000_000_000, 1_000_000_000))
    (docs / "01_company_intro.md").unlink()
    (docs / "99_new.md").write_text("# 새 문서\n", encoding="utf-8")
    db_session.execute(  # 폴더를 모르는 문서(0006 이전)는 파일을 보지 않는다
        update(Document)
        .where(Document.source_path == "02_employment_rules.md")
        .values(corpus_root=None)
    )
    db_session.commit()

    summary = index_summary(db_session, model="BAAI/bge-m3")

    changed = (summary["source_changed"], summary["source_missing"], summary["source_new"])
    assert changed == (1, 1, 1)
    assert summary["model_mismatch"] == 22
    assert summary["mismatches"] == 25


def test_empty_db_has_no_sync_time(db_session: Session) -> None:
    assert index_summary(db_session, model="FakeEmbedder")["last_synced_at"] is None


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_health_includes_index_summary(client: TestClient, db_engine: Engine, root: Path) -> None:
    app.dependency_overrides[get_index_sessions] = lambda: sessionmaker(db_engine)

    body = client.get("/health").json()

    assert body["status"] == "ok"
    assert body["index"]["documents"] == 22
    assert body["index"]["model_mismatch"] == 22  # 서버의 기본 모델은 BAAI/bge-m3


def test_health_stays_ok_when_index_cannot_be_read(client: TestClient, db_engine: Engine) -> None:
    missing = create_engine(db_engine.url.set(database="rag_no_such_db"), connect_args=CONNECT_ARGS)
    app.dependency_overrides[get_index_sessions] = lambda: sessionmaker(missing)

    body = client.get("/health").json()

    assert body["status"] == "ok"
    assert body["index"] == {"error": "DB에 연결하거나 인덱스를 읽을 수 없습니다"}
