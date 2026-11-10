"""수집이 수명 관리 정보(원문 해시, 임베딩 모델, 시행일, 조각 키, 본문 해시)를 남기는지 검사한다."""

import hashlib
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from rag_service.corpus import load_corpus
from rag_service.db.models import EMBEDDING_DIM, Chunk, Document
from rag_service.ingest.embedder import SentenceTransformerEmbedder, embedding_model_name
from rag_service.ingest.pipeline import ingest_corpus, text_sha256
from rag_service.ingest.tokenizer import KoreanTokenizer
from tests.fixtures.db import db_engine, db_session
from tests.fixtures.embedding import FakeEmbedder

__all__ = ["db_engine", "db_session"]

SAMPLES = Path(__file__).resolve().parents[2] / "samples"


def test_documents_and_chunks_carry_lifecycle_fields(db_session: Session) -> None:
    corpus = load_corpus(SAMPLES)

    ingest_corpus(db_session, corpus, embedder=FakeEmbedder(), tokenizer=KoreanTokenizer())

    documents = {d.source_path: d for d in db_session.scalars(select(Document))}
    for entry in corpus.documents:
        document = documents[entry.file]
        raw = corpus.doc_path(entry).read_bytes()
        assert document.content_sha256 == hashlib.sha256(raw).hexdigest(), entry.file
        assert document.embedding_model == "FakeEmbedder"
        assert document.source_mtime is not None
    assert (documents["16_travel_expense_rules_2025.md"].effective_to) == date(2025, 12, 31)
    pilot = documents["17_remote_work_pilot_2023.md"]
    assert (pilot.effective_from, pilot.effective_to) == (date(2023, 7, 1), date(2023, 12, 31))
    assert documents["05_travel_expense_rules.pdf"].effective_from is None  # 근거 없음 → 미상

    rows = db_session.execute(select(Chunk, Document.source_path).join(Document)).all()
    assert all(chunk.content_sha256 == text_sha256(chunk.content) for chunk, _ in rows)
    assert all((chunk.chunk_key or "").startswith(f"{path}#") for chunk, path in rows)
    distinct_keys = db_session.scalar(select(func.count(func.distinct(Chunk.chunk_key))))
    assert distinct_keys == len(rows)


class _FakeModel:
    def get_sentence_embedding_dimension(self) -> int:
        return EMBEDDING_DIM

    def encode(self, texts: list[str], **kwargs: Any) -> Any:
        return np.zeros((len(texts), EMBEDDING_DIM))


def test_embedding_model_name_prefers_the_real_model_name() -> None:
    embedder = SentenceTransformerEmbedder("org/model-x", loader=lambda name: _FakeModel())

    assert embedding_model_name(embedder) == "org/model-x"
    assert embedding_model_name(FakeEmbedder()) == "FakeEmbedder"
