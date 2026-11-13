"""내용은 그대로이고 수정 시각만 바뀐 문서(복사, 백업 되살리기, git checkout).

/health의 신선도 요약은 원문을 읽지 않고 수정 시각만 비교한다. 수집이 이런 문서를 건너뛰면서 저장된
수정 시각을 그대로 두면, 관리 화면에 '원문과 어긋남'이 계속 남는다 (v0.3.0 업데이트 검증에서 찾음).
"""

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from rag_service.corpus import load_corpus
from rag_service.db.models import Document
from rag_service.ingest.check import index_summary
from rag_service.ingest.pipeline import IngestStats, ingest_corpus
from rag_service.ingest.tokenizer import KoreanTokenizer
from tests.fixtures.corpus_copy import copy_samples, set_acl
from tests.fixtures.db import db_engine, db_session
from tests.fixtures.embedding import FakeEmbedder

__all__ = ["db_engine", "db_session"]

GUIDE = "06_remote_work_guide.md"
LATER = datetime(2030, 1, 2, 3, 4, 5, tzinfo=UTC)


@pytest.fixture
def root(db_session: Session, tmp_path: Path) -> Path:
    root = copy_samples(tmp_path / "corpus")
    _ingest(db_session, root)
    return root


def _ingest(session: Session, root: Path) -> IngestStats:
    stats = ingest_corpus(
        session, load_corpus(root), embedder=FakeEmbedder(), tokenizer=KoreanTokenizer()
    )
    session.commit()
    return stats


def _touch(root: Path, file: str) -> None:
    stamp = LATER.timestamp()
    os.utime(root / "docs" / file, (stamp, stamp))


def _stored_mtime(session: Session, file: str) -> datetime | None:
    query = select(Document.source_mtime).where(Document.source_path == file)
    return session.scalars(query).one()


def test_touched_file_is_skipped_and_its_time_is_refreshed(db_session: Session, root: Path) -> None:
    _touch(root, GUIDE)
    assert index_summary(db_session, model="FakeEmbedder")["source_changed"] == 1

    stats = _ingest(db_session, root)

    assert GUIDE in stats.skipped
    assert (stats.changed, stats.embedded) == ((), 0)
    assert _stored_mtime(db_session, GUIDE) == LATER
    summary = index_summary(db_session, model="FakeEmbedder")
    assert (summary["source_changed"], summary["mismatches"]) == (0, 0)


def test_metadata_update_also_refreshes_the_time(db_session: Session, root: Path) -> None:
    set_acl(root, GUIDE, title="재택근무 안내서")
    _touch(root, GUIDE)

    stats = _ingest(db_session, root)

    assert stats.updated == (GUIDE,)
    assert _stored_mtime(db_session, GUIDE) == LATER
    assert index_summary(db_session, model="FakeEmbedder")["source_changed"] == 0


def test_untouched_files_keep_their_stored_time(db_session: Session, root: Path) -> None:
    before = _stored_mtime(db_session, GUIDE)

    stats = _ingest(db_session, root)

    assert GUIDE in stats.skipped
    assert _stored_mtime(db_session, GUIDE) == before
