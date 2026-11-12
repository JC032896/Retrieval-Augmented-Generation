"""관리 화면에서 올린 문서: 수집, 파일 교체, 권한 변경(재임베딩 없음), 삭제, 변경 이력.

폴더 수집(--prune)과 /health 신선도 요약이 올린 문서를 잘못 다루지 않는지도 본다.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from rag_service.corpus import load_corpus
from rag_service.db.changes import DocumentChange
from rag_service.db.models import Chunk, Document, User
from rag_service.ingest.check import index_summary
from rag_service.ingest.embedder import embedding_model_name
from rag_service.ingest.pipeline import ingest_corpus
from rag_service.ingest.tokenizer import KoreanTokenizer
from rag_service.ingest.uploads import (
    Access,
    UploadConflict,
    UploadError,
    add_upload,
    change_access,
    clean_filename,
    delete_upload,
    history,
    known_values,
    replace_upload,
    stored_file,
    who_can_view,
)
from tests.fixtures.db import db_engine, db_session
from tests.fixtures.embedding import FakeEmbedder

__all__ = ["db_engine", "db_session"]

GUIDE = (
    "# 보안 점검 안내\n\n## 점검 주기\n\n분기마다 취약점을 점검한다.\n\n"
    "## 보고\n\n결과는 팀장에게 보고한다.\n"
)
GUIDE_V2 = GUIDE.replace("결과는 팀장에게 보고한다.", "결과는 보안 담당에게 보고한다.")
DEV_ONLY = Access("보안 점검 안내", 1, ("개발팀",), ())
ORG = """
departments: [개발팀, 인사팀]
roles: [사원, 팀장]
users:
  - {id: kim, name: 김사원, department: 개발팀, role: 사원, clearance_level: 1}
  - {id: lee, name: 이팀장, department: 개발팀, role: 팀장, clearance_level: 2}
  - {id: park, name: 박인사, department: 인사팀, role: 사원, clearance_level: 1}
"""
ACL = "documents:\n  - {file: rule.md, title: 사내 규칙, security_level: 0, roles: [사원, 팀장]}\n"


@pytest.fixture(scope="module")
def tokenizer() -> KoreanTokenizer:
    return KoreanTokenizer()


@pytest.fixture
def session(db_engine: Engine, db_session: Session) -> Iterator[Session]:
    with db_engine.begin() as connection:
        connection.execute(text("TRUNCATE document_changes RESTART IDENTITY"))
    db_session.add_all(
        [
            User(login="kim", name="김사원", department="개발팀", role="사원", clearance_level=1),
            User(login="lee", name="이팀장", department="개발팀", role="팀장", clearance_level=2),
            User(login="park", name="박인사", department="인사팀", role="사원", clearance_level=1),
        ]
    )
    db_session.commit()
    yield db_session


def _upload(
    session: Session,
    upload_dir: Path,
    tokenizer: KoreanTokenizer,
    *,
    name: str = "보안점검.md",
    body: str = GUIDE,
    access: Access = DEV_ONLY,
    embedder: FakeEmbedder | None = None,
) -> Document:
    staged = add_upload(
        session,
        filename=name,
        data=body.encode("utf-8"),
        access=access,
        owner_department="개발팀",
        actor="lee",
        upload_dir=upload_dir,
        embedder=embedder or FakeEmbedder(),
        tokenizer=tokenizer,
    )
    session.commit()
    staged.finalize()
    return staged.document


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("보안점검.md", "보안점검.md"),
        ("C:\\Users\\kim\\보고서.PDF", "보고서.PDF"),  # 브라우저가 경로째 보내는 경우
        ("../../etc/규정.docx", "규정.docx"),
    ],
)
def test_clean_filename_keeps_only_the_base_name(name: str, expected: str) -> None:
    assert clean_filename(name) == expected


@pytest.mark.parametrize(
    "name", ["", "..", ".env.md", "메모.txt", "a:b.md", "탭\t이름.md", "가" * 118 + ".md"]
)
def test_clean_filename_rejects_unsafe_or_unsupported_names(name: str) -> None:
    with pytest.raises(UploadError):
        clean_filename(name)


def test_upload_is_indexed_with_permission_copies_and_moved_after_commit(
    session: Session, tmp_path: Path, tokenizer: KoreanTokenizer
) -> None:
    staged = add_upload(
        session,
        filename="보안점검.md",
        data=GUIDE.encode("utf-8"),
        access=DEV_ONLY,
        owner_department="개발팀",
        actor="lee",
        upload_dir=tmp_path,
        embedder=FakeEmbedder(),
        tokenizer=tokenizer,
    )
    target = stored_file(tmp_path, "upload/보안점검.md")
    assert not target.exists()  # 커밋 전에는 제자리에 두지 않는다
    session.commit()
    staged.finalize()

    document = staged.document
    chunks = session.scalars(select(Chunk).where(Chunk.document_id == document.id)).all()
    assert (document.source_path, document.origin, document.owner_department) == (
        "upload/보안점검.md",
        "upload",
        "개발팀",
    )
    assert target.read_text(encoding="utf-8") == GUIDE
    assert not list((tmp_path / "tmp").iterdir())
    assert len(chunks) == 2
    assert {
        (tuple(c.allowed_departments), tuple(c.allowed_roles), c.security_level) for c in chunks
    } == {(("개발팀",), (), 1)}
    [change] = history(session, document.source_path)
    assert (change.action, change.actor_login, change.before) == ("upload", "lee", None)
    assert change.after is not None
    assert change.after["departments"] == ["개발팀"]
    assert change.after["owner_department"] == "개발팀"


def test_same_name_is_a_conflict(
    session: Session, tmp_path: Path, tokenizer: KoreanTokenizer
) -> None:
    _upload(session, tmp_path, tokenizer)

    with pytest.raises(UploadConflict):
        _upload(session, tmp_path, tokenizer)


@pytest.mark.parametrize(
    ("access", "message"),
    [
        (Access("제목", 1, (), ()), "하나 이상"),
        (Access("제목", 1, ("총무팀",), ()), "총무팀"),
        (Access("제목", 1, (), ("인턴",)), "인턴"),
        (Access("  ", 1, ("개발팀",), ()), "제목"),
    ],
)
def test_access_must_name_known_departments_or_roles(
    session: Session, tmp_path: Path, tokenizer: KoreanTokenizer, access: Access, message: str
) -> None:
    with pytest.raises(UploadError, match=message):
        _upload(session, tmp_path, tokenizer, access=access)
    assert session.scalars(select(Document)).all() == []


@pytest.mark.parametrize(
    ("name", "body"),
    [("깨진.pdf", "PDF가 아님"), ("빈문서.md", "   \n\n")],
)
def test_unreadable_or_empty_file_is_rejected_and_cleaned_up(
    session: Session, tmp_path: Path, tokenizer: KoreanTokenizer, name: str, body: str
) -> None:
    with pytest.raises(UploadError):
        _upload(session, tmp_path, tokenizer, name=name, body=body)

    assert not list((tmp_path / "tmp").iterdir())
    assert session.scalars(select(Document)).all() == []


def test_discard_leaves_no_file_when_commit_fails(
    session: Session, tmp_path: Path, tokenizer: KoreanTokenizer
) -> None:
    staged = add_upload(
        session,
        filename="보안점검.md",
        data=GUIDE.encode("utf-8"),
        access=DEV_ONLY,
        owner_department="개발팀",
        actor="lee",
        upload_dir=tmp_path,
        embedder=FakeEmbedder(),
        tokenizer=tokenizer,
    )
    session.rollback()  # 커밋 실패를 흉내 낸다
    staged.discard()

    assert not stored_file(tmp_path, "upload/보안점검.md").exists()
    assert not list((tmp_path / "tmp").iterdir())
    assert session.scalars(select(Document)).all() == []


def test_replace_keeps_access_and_reuses_unchanged_vectors(
    session: Session, tmp_path: Path, tokenizer: KoreanTokenizer
) -> None:
    first = _upload(
        session, tmp_path, tokenizer, access=Access("보안 점검 안내", 2, ("개발팀",), ("팀장",))
    )
    embedder = FakeEmbedder()

    staged = replace_upload(
        session,
        first,
        filename="보안점검_v2.md",  # 다른 이름으로 올려도 처음 이름으로 저장한다
        data=GUIDE_V2.encode("utf-8"),
        actor="lee",
        upload_dir=tmp_path,
        embedder=embedder,
        tokenizer=tokenizer,
    )
    session.commit()
    staged.finalize()

    replaced = staged.document
    chunks = session.scalars(select(Chunk).where(Chunk.document_id == replaced.id)).all()
    assert replaced.source_path == "upload/보안점검.md"
    assert stored_file(tmp_path, replaced.source_path).read_text(encoding="utf-8") == GUIDE_V2
    assert [len(call) for call in embedder.calls] == [1]  # 바뀐 '보고' 조각만 임베딩
    assert {
        (tuple(c.allowed_departments), tuple(c.allowed_roles), c.security_level) for c in chunks
    } == {(("개발팀",), ("팀장",), 2)}
    assert [c.action for c in history(session, replaced.source_path)] == ["replace", "upload"]


def test_replace_requires_the_same_format(
    session: Session, tmp_path: Path, tokenizer: KoreanTokenizer
) -> None:
    document = _upload(session, tmp_path, tokenizer)

    with pytest.raises(UploadError, match=r"\.md"):
        replace_upload(
            session,
            document,
            filename="보안점검.pdf",
            data=b"%PDF",
            actor="lee",
            upload_dir=tmp_path,
            embedder=FakeEmbedder(),
            tokenizer=tokenizer,
        )


def test_change_access_updates_chunk_copies_without_reembedding(
    session: Session, tmp_path: Path, tokenizer: KoreanTokenizer
) -> None:
    document = _upload(session, tmp_path, tokenizer)
    vectors_before = session.scalars(
        select(Chunk.embedding).where(Chunk.document_id == document.id)
    ).all()
    wider = Access("보안 점검 안내 (전사)", 0, ("개발팀", "인사팀"), ("팀장",))

    assert change_access(session, document, wider, "han") is True
    session.commit()
    assert change_access(session, document, wider, "han") is False  # 같은 값이면 이력도 없음

    chunks = session.scalars(select(Chunk).where(Chunk.document_id == document.id)).all()
    assert {
        (tuple(sorted(c.allowed_departments)), tuple(c.allowed_roles), c.security_level)
        for c in chunks
    } == {(("개발팀", "인사팀"), ("팀장",), 0)}
    assert [list(v) for v in vectors_before] == [
        list(c.embedding) for c in sorted(chunks, key=lambda c: c.id)
    ]
    assert document.title == "보안 점검 안내 (전사)"
    access_change = history(session, document.source_path)[0]
    assert (access_change.action, access_change.actor_login) == ("access", "han")
    assert access_change.before is not None and access_change.after is not None
    assert (access_change.before["security_level"], access_change.after["security_level"]) == (1, 0)


def test_delete_removes_rows_and_file_but_keeps_history(
    session: Session, tmp_path: Path, tokenizer: KoreanTokenizer
) -> None:
    document = _upload(session, tmp_path, tokenizer)
    target = stored_file(tmp_path, document.source_path)

    staged = delete_upload(session, document, "han", tmp_path)
    assert target.exists()  # 커밋 전에는 원문을 지우지 않는다
    session.commit()
    staged.finalize()

    assert session.scalars(select(Document)).all() == []
    assert session.scalars(select(Chunk)).all() == []
    assert not target.exists()
    assert [c.action for c in history(session, "upload/보안점검.md")] == ["delete", "upload"]


def test_who_can_view_uses_the_search_permission_rule(session: Session) -> None:
    def logins(departments: tuple[str, ...], roles: tuple[str, ...], level: int) -> list[str]:
        return [u.login for u in who_can_view(session, departments, roles, level)]

    assert logins(("개발팀",), (), 1) == ["kim", "lee"]
    assert logins(("개발팀",), (), 2) == ["lee"]
    assert logins((), ("사원",), 1) == ["kim", "park"]
    assert logins(("인사팀",), ("팀장",), 2) == ["lee"]  # 박인사는 등급 부족
    assert logins((), (), 0) == []


def test_known_values_come_from_users_and_existing_acl(
    session: Session, tmp_path: Path, tokenizer: KoreanTokenizer
) -> None:
    assert known_values(session) == (["개발팀", "인사팀"], ["사원", "팀장"])


def test_folder_prune_and_health_leave_uploads_alone(
    session: Session, tmp_path: Path, tokenizer: KoreanTokenizer
) -> None:
    corpus_dir = tmp_path / "corpus"
    (corpus_dir / "docs").mkdir(parents=True)
    (corpus_dir / "org.yaml").write_text(ORG, encoding="utf-8")
    (corpus_dir / "acl.yaml").write_text(ACL, encoding="utf-8")
    (corpus_dir / "docs" / "rule.md").write_text(
        "# 사내 규칙\n\n## 출근\n\n9시에 출근한다.\n", encoding="utf-8"
    )
    upload_dir = tmp_path / "uploads"
    embedder = FakeEmbedder()
    uploaded = _upload(session, upload_dir, tokenizer, embedder=embedder)

    stats = ingest_corpus(
        session, load_corpus(corpus_dir), embedder=embedder, tokenizer=tokenizer, prune=True
    )
    session.commit()

    assert stats.deleted == () and stats.unlisted == ()
    assert session.get(Document, uploaded.id) is not None
    summary = index_summary(session, model=embedding_model_name(embedder))
    assert (summary["documents"], summary["mismatches"]) == (2, 0)

    stored_file(upload_dir, uploaded.source_path).unlink()
    assert index_summary(session, model=embedding_model_name(embedder))["source_missing"] == 1


def test_changes_cannot_be_edited_by_the_app_role(
    session: Session, tmp_path: Path, tokenizer: KoreanTokenizer, db_engine: Engine
) -> None:
    _upload(session, tmp_path, tokenizer)

    with db_engine.connect() as connection:
        connection.execute(text("SET ROLE rag_app"))
        assert connection.scalar(text("SELECT count(*) FROM document_changes")) == 1
        with pytest.raises(Exception, match="permission denied"):
            connection.execute(text("UPDATE document_changes SET actor_login = 'x'"))
        connection.rollback()
    assert session.scalars(select(DocumentChange.actor_login)).all() == ["lee"]
