import dataclasses
from collections.abc import Sequence
from pathlib import Path

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from rag_service.corpus import Corpus, load_corpus
from rag_service.db.models import Chunk, Document, DocumentAcl
from rag_service.ingest.pipeline import ingest_corpus
from rag_service.ingest.tokenizer import KoreanTokenizer
from tests.fixtures.db import db_engine, db_session
from tests.fixtures.embedding import FakeEmbedder

__all__ = ["db_engine", "db_session"]

SAMPLES = Path(__file__).resolve().parents[2] / "samples"
tokenizer = KoreanTokenizer()


@pytest.fixture
def corpus() -> Corpus:
    return load_corpus(SAMPLES)


def _ingest(session: Session, corpus: Corpus) -> None:
    ingest_corpus(session, corpus, embedder=FakeEmbedder(), tokenizer=tokenizer)
    session.commit()


def test_ingest_stores_documents_acl_and_chunks(db_session: Session, corpus: Corpus) -> None:
    stats = ingest_corpus(db_session, corpus, embedder=FakeEmbedder(), tokenizer=tokenizer)
    db_session.commit()

    assert stats.documents == 22
    assert stats.removed == 0
    assert db_session.scalar(select(func.count()).select_from(Document)) == 22
    assert db_session.scalar(select(func.count()).select_from(Chunk)) == stats.chunks
    acl_rows = sum(len(d.departments) + len(d.roles) for d in corpus.documents)
    assert db_session.scalar(select(func.count()).select_from(DocumentAcl)) == acl_rows


def test_chunks_carry_document_permissions(db_session: Session, corpus: Corpus) -> None:
    _ingest(db_session, corpus)

    for entry in corpus.documents:
        rows = db_session.execute(
            select(Chunk.allowed_departments, Chunk.allowed_roles, Chunk.security_level)
            .join(Document)
            .where(Document.source_path == entry.file)
        ).all()
        assert rows, entry.file
        for departments, roles, level in rows:
            assert (departments, roles, level) == (
                entry.departments,
                entry.roles,
                entry.security_level,
            ), entry.file


def test_code_tokens_are_searchable_as_whole_words(db_session: Session, corpus: Corpus) -> None:
    _ingest(db_session, corpus)

    sections = db_session.scalars(
        select(Chunk.section).where(text("tokens @@ 'sec-pw-01'::tsquery"))
    ).all()

    assert "SEC-PW-01 비밀번호 규칙" in sections


def test_reingest_of_unchanged_corpus_skips_everything(db_session: Session, corpus: Corpus) -> None:
    _ingest(db_session, corpus)
    first_ids = set(db_session.scalars(select(Document.id)))
    chunk_count = db_session.scalar(select(func.count()).select_from(Chunk))

    stats = ingest_corpus(db_session, corpus, embedder=FakeEmbedder(), tokenizer=tokenizer)
    db_session.commit()

    assert (stats.embedded, len(stats.skipped)) == (0, 22)
    assert db_session.scalar(select(func.count()).select_from(Document)) == 22
    assert db_session.scalar(select(func.count()).select_from(Chunk)) == chunk_count
    assert first_ids == set(db_session.scalars(select(Document.id)))


def test_documents_missing_from_corpus_are_removed_only_with_prune(
    db_session: Session, corpus: Corpus
) -> None:
    _ingest(db_session, corpus)
    smaller = dataclasses.replace(corpus, documents=corpus.documents[1:])
    removed_file = corpus.documents[0].file

    kept = ingest_corpus(db_session, smaller, embedder=FakeEmbedder(), tokenizer=tokenizer)
    assert (kept.removed, kept.unlisted) == (0, (removed_file,))
    assert db_session.scalar(select(Document).where(Document.source_path == removed_file))

    stats = ingest_corpus(
        db_session, smaller, embedder=FakeEmbedder(), tokenizer=tokenizer, prune=True
    )
    db_session.commit()

    assert stats.removed == 1
    assert db_session.scalar(select(Document).where(Document.source_path == removed_file)) is None


class ShortEmbedder(FakeEmbedder):
    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return super().embed(texts)[:-1]


def test_vector_count_mismatch_is_an_error(db_session: Session, corpus: Corpus) -> None:
    with pytest.raises(ValueError, match="벡터"):
        ingest_corpus(db_session, corpus, embedder=ShortEmbedder(), tokenizer=tokenizer)
