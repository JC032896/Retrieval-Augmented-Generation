"""GET /admin/api/documents/{id}: 문서 한 건. 관리 화면의 문서 상세가 쓴다.

중앙 관리자는 폴더 문서도 보고(바꿀 수는 없음), 부서 문서 담당은 자기 부서 올린 문서만 본다.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from rag_service.api.admin import AdminServices, get_admin_services
from rag_service.api.auth import DevHeaderAuthenticator
from rag_service.corpus import load_corpus
from rag_service.ingest.pipeline import ingest_corpus
from rag_service.ingest.tokenizer import KoreanTokenizer
from rag_service.ingest.uploads import Access, add_upload
from rag_service.main import app
from tests.fixtures.db import db_engine, db_session
from tests.fixtures.embedding import FakeEmbedder

__all__ = ["db_engine", "db_session"]

ORG = """
departments: [개발팀, 인사팀, 경영진]
roles: [사원, 팀장, 임원]
users:
  - {id: lee, name: 이팀장, department: 개발팀, role: 팀장, clearance_level: 2}
  - {id: park, name: 박인사, department: 인사팀, role: 사원, clearance_level: 1}
  - {id: han, name: 한임원, department: 경영진, role: 임원, clearance_level: 3}
"""
ACL = """
documents:
  - {file: rule.md, title: 사내 규칙, security_level: 0, roles: [사원, 팀장, 임원]}
"""


def _as(login: str, groups: str) -> dict[str, str]:
    return {"X-User-Id": login, "X-User-Groups": groups}


@pytest.fixture
def client(tmp_path: Path, db_engine: Engine, db_session: Session) -> Iterator[TestClient]:
    with db_engine.begin() as connection:
        connection.execute(text("TRUNCATE document_changes RESTART IDENTITY"))
    tokenizer = KoreanTokenizer()
    corpus = tmp_path / "corpus"
    (corpus / "docs").mkdir(parents=True)
    (corpus / "org.yaml").write_text(ORG, encoding="utf-8")
    (corpus / "acl.yaml").write_text(ACL, encoding="utf-8")
    (corpus / "docs" / "rule.md").write_text("# 사내 규칙\n\n9시 출근.\n", encoding="utf-8")
    ingest_corpus(db_session, load_corpus(corpus), embedder=FakeEmbedder(), tokenizer=tokenizer)
    staged = add_upload(
        db_session,
        filename="보안점검.md",
        data="# 보안 점검\n\n분기마다 점검한다.\n".encode(),
        access=Access("보안 점검", 1, ("개발팀",), ()),
        owner_department="개발팀",
        actor="lee",
        upload_dir=tmp_path / "uploads",
        embedder=FakeEmbedder(),
        tokenizer=tokenizer,
    )
    db_session.commit()
    staged.finalize()
    services = AdminServices(
        sessions=sessionmaker(db_engine),
        audit_sessions=None,
        authenticator=DevHeaderAuthenticator(),
    )
    app.dependency_overrides[get_admin_services] = lambda: services
    yield TestClient(app)
    app.dependency_overrides.clear()


def _ids(client: TestClient) -> dict[str, int]:
    rows = client.get("/admin/api/documents", headers=_as("han", "rag-admin")).json()
    return {row["origin"]: row["id"] for row in rows}


def test_admin_sees_any_document_but_cannot_edit_folder_ones(client: TestClient) -> None:
    ids = _ids(client)
    han = _as("han", "rag-admin")

    folder = client.get(f"/admin/api/documents/{ids['folder']}", headers=han).json()
    upload = client.get(f"/admin/api/documents/{ids['upload']}", headers=han).json()

    assert (folder["title"], folder["editable"]) == ("사내 규칙", False)
    assert (upload["title"], upload["editable"], upload["owner_department"]) == (
        "보안 점검",
        True,
        "개발팀",
    )
    assert upload["last_change"]["action"] == "upload"


def test_doc_manager_sees_only_own_department_uploads(client: TestClient) -> None:
    ids = _ids(client)

    own = client.get(f"/admin/api/documents/{ids['upload']}", headers=_as("lee", "rag-doc-manager"))
    other = client.get(
        f"/admin/api/documents/{ids['upload']}", headers=_as("park", "rag-doc-manager")
    )
    folder = client.get(
        f"/admin/api/documents/{ids['folder']}", headers=_as("lee", "rag-doc-manager")
    )
    missing = client.get("/admin/api/documents/9999", headers=_as("han", "rag-admin"))
    auditor = client.get(f"/admin/api/documents/{ids['upload']}", headers=_as("han", "rag-auditor"))

    assert own.status_code == 200
    assert other.status_code == folder.status_code == missing.status_code == 404
    assert auditor.status_code == 403
