"""관리 화면 업로드: 스캔 PDF를 못 읽으면 이유(OCR 꺼짐 등)를 알리고 흔적을 남기지 않는다."""

from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from rag_service.db.models import Document, User
from rag_service.ingest import parsers
from rag_service.ingest.tokenizer import KoreanTokenizer
from rag_service.ingest.uploads import Access, UploadError, add_upload
from tests.fixtures.db import db_engine, db_session
from tests.fixtures.embedding import FakeEmbedder

__all__ = ["db_engine", "db_session"]


def test_scanned_pdf_without_ocr_is_rejected_with_the_reason(
    db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_session.add(
        User(login="lee", name="이팀장", department="개발팀", role="팀장", clearance_level=2)
    )
    db_session.commit()
    pdf = tmp_path / "source.pdf"
    Image.new("RGB", (850, 1100), "white").save(pdf, "PDF", resolution=100)
    monkeypatch.setattr(parsers, "configured_ocr", lambda: None)
    uploads = tmp_path / "uploads"

    with pytest.raises(UploadError, match=r"^스캔규정\.pdf: 1쪽은 .*OCR_ENGINE"):
        add_upload(
            db_session,
            filename="스캔규정.pdf",
            data=pdf.read_bytes(),
            access=Access("스캔 규정", 0, ("개발팀",), ()),
            owner_department="개발팀",
            actor="lee",
            upload_dir=uploads,
            embedder=FakeEmbedder(),
            tokenizer=KoreanTokenizer(),
        )

    assert not list((uploads / "tmp").iterdir())
    assert db_session.scalars(select(Document)).all() == []
