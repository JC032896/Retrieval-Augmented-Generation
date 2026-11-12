"""올린 문서의 실패 경로: 수집이나 커밋이 실패해도 받은 파일이 남지 않는다.

모델을 읽지 못한 오류는 관리 화면 상태에 그대로 보인다.
"""

from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from rag_service.api import admin_documents
from rag_service.api.admin import Admin, AdminServices, status
from rag_service.api.auth import CurrentUser
from rag_service.api.readiness import MODELS
from rag_service.api.roles import AdminRole
from rag_service.db.models import Document, User
from rag_service.ingest import uploads
from rag_service.ingest.tokenizer import KoreanTokenizer
from rag_service.ingest.uploads import Access, Staged, add_upload, replace_upload
from tests.fixtures.db import db_engine, db_session
from tests.fixtures.embedding import FakeEmbedder

__all__ = ["db_engine", "db_session"]

GUIDE = "# 보안 점검 안내\n\n## 점검 주기\n\n분기마다 취약점을 점검한다.\n"


def _fail(*_: object, **__: object) -> None:
    raise RuntimeError("임베딩 서버 오류")


@pytest.fixture(scope="module")
def tokenizer() -> KoreanTokenizer:
    return KoreanTokenizer()


@pytest.fixture
def session(db_session: Session) -> Session:
    db_session.add(
        User(login="lee", name="이팀장", department="개발팀", role="팀장", clearance_level=2)
    )
    db_session.commit()
    return db_session


def _add(session: Session, upload_dir: Path, tokenizer: KoreanTokenizer) -> Staged:
    return add_upload(
        session,
        filename="보안점검.md",
        data=GUIDE.encode("utf-8"),
        access=Access("보안 점검 안내", 1, ("개발팀",), ()),
        owner_department="개발팀",
        actor="lee",
        upload_dir=upload_dir,
        embedder=FakeEmbedder(),
        tokenizer=tokenizer,
    )


def test_failed_indexing_on_upload_removes_the_received_file(
    session: Session, tmp_path: Path, tokenizer: KoreanTokenizer, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(uploads, "write_document", _fail)

    with pytest.raises(RuntimeError):
        _add(session, tmp_path, tokenizer)

    assert not list((tmp_path / "tmp").iterdir())


def test_failed_indexing_on_replace_keeps_the_old_file(
    session: Session, tmp_path: Path, tokenizer: KoreanTokenizer, monkeypatch: pytest.MonkeyPatch
) -> None:
    staged = _add(session, tmp_path, tokenizer)
    session.commit()
    staged.finalize()
    monkeypatch.setattr(uploads, "write_document", _fail)

    with pytest.raises(RuntimeError):
        replace_upload(
            session,
            staged.document,
            filename="보안점검.md",
            data=GUIDE.replace("분기마다", "매달").encode("utf-8"),
            actor="lee",
            upload_dir=tmp_path,
            embedder=FakeEmbedder(),
            tokenizer=tokenizer,
        )

    assert not list((tmp_path / "tmp").iterdir())
    assert staged.target is not None
    assert staged.target.read_text(encoding="utf-8") == GUIDE


def test_failed_commit_discards_the_staged_file(
    db_engine: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    temp_dir = tmp_path / "tmp" / "staged"
    temp_dir.mkdir(parents=True)
    (temp_dir / "보안점검.md").write_text(GUIDE, encoding="utf-8")
    staged = Staged(Document(), temp_dir, target=tmp_path / "docs" / "보안점검.md")
    monkeypatch.setattr(Session, "commit", _fail)

    with Session(db_engine) as session, pytest.raises(RuntimeError):
        admin_documents._commit(session, staged)

    assert not temp_dir.exists()
    assert not (tmp_path / "docs" / "보안점검.md").exists()


def test_status_shows_model_load_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(MODELS, "status", "error")
    monkeypatch.setattr(MODELS, "error", "OSError: 모델 파일 없음")
    broken = create_engine(
        "postgresql+psycopg://nobody:x@127.0.0.1:1/none", connect_args={"connect_timeout": 1}
    )
    services = AdminServices(sessions=sessionmaker(broken), audit_sessions=None, authenticator=None)
    han = Admin(CurrentUser("han", "한임원", "경영진", "임원", 3), frozenset({AdminRole.ADMIN}))
    try:
        response = status(han, services)
    finally:
        broken.dispose()

    assert response.models == {"status": "error", "error": "OSError: 모델 파일 없음"}
