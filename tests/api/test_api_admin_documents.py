"""관리 API의 문서 관리: 역할별 범위, 올리기(multipart), 권한 미리 보기와 변경, 교체, 삭제, 이력.

- 부서 문서 담당은 자기 부서가 관리하는 올린 문서만 보고 바꾼다 (다른 부서 문서는 404)
- 폴더에서 수집한 문서는 누구도 화면에서 바꿀 수 없다 (409)
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from httpx2 import Response
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from rag_service.api.admin import AdminServices, get_admin_services
from rag_service.api.auth import DevHeaderAuthenticator
from rag_service.api.readiness import MODELS
from rag_service.api.services import Services, get_services
from rag_service.corpus import load_corpus
from rag_service.ingest.pipeline import ingest_corpus
from rag_service.ingest.tokenizer import KoreanTokenizer
from rag_service.ingest.uploads import stored_file
from rag_service.main import app
from tests.fixtures.db import db_engine, db_session
from tests.fixtures.embedding import FakeEmbedder
from tests.fixtures.rerank import OverlapReranker

__all__ = ["db_engine", "db_session"]

ORG = """
departments: [개발팀, 인사팀, 경영진]
roles: [사원, 팀장, 임원]
users:
  - {id: kim, name: 김사원, department: 개발팀, role: 사원, clearance_level: 1}
  - {id: lee, name: 이팀장, department: 개발팀, role: 팀장, clearance_level: 2}
  - {id: park, name: 박인사, department: 인사팀, role: 사원, clearance_level: 1}
  - {id: han, name: 한임원, department: 경영진, role: 임원, clearance_level: 3}
"""
ACL = """
documents:
  - {file: rule.md, title: 사내 규칙, security_level: 0, roles: [사원, 팀장, 임원]}
"""
GUIDE = "# 보안 점검 안내\n\n## 점검 주기\n\n분기마다 취약점을 점검한다.\n"
ADMIN = "rag-admin"
DOC_MANAGER = "rag-doc-manager"
MAX_BYTES = 4096


def _as(login: str, groups: str) -> dict[str, str]:
    return {"X-User-Id": login, "X-User-Groups": groups}


LEE = _as("lee", DOC_MANAGER)  # 개발팀 문서 담당
PARK = _as("park", DOC_MANAGER)  # 인사팀 문서 담당
HAN = _as("han", ADMIN)  # 중앙 관리자


@pytest.fixture(scope="module")
def tokenizer() -> KoreanTokenizer:
    return KoreanTokenizer()


@pytest.fixture
def services(
    tmp_path: Path, db_engine: Engine, db_session: Session, tokenizer: KoreanTokenizer
) -> AdminServices:
    with db_engine.begin() as connection:
        connection.execute(text("TRUNCATE document_changes RESTART IDENTITY"))
    corpus = tmp_path / "corpus"
    (corpus / "docs").mkdir(parents=True)
    (corpus / "org.yaml").write_text(ORG, encoding="utf-8")
    (corpus / "acl.yaml").write_text(ACL, encoding="utf-8")
    (corpus / "docs" / "rule.md").write_text("# 사내 규칙\n\n9시 출근.\n", encoding="utf-8")
    ingest_corpus(db_session, load_corpus(corpus), embedder=FakeEmbedder(), tokenizer=tokenizer)
    db_session.commit()
    return AdminServices(
        sessions=sessionmaker(db_engine),
        audit_sessions=None,
        authenticator=DevHeaderAuthenticator(),
        upload_dir=tmp_path / "uploads",
        upload_max_bytes=MAX_BYTES,
    )


@pytest.fixture
def client(services: AdminServices, tokenizer: KoreanTokenizer) -> Iterator[TestClient]:
    models = Services(
        sessions=services.sessions,
        embedder=FakeEmbedder(),
        reranker=OverlapReranker(),
        tokenizer=tokenizer,
        llm=None,
        authenticator=None,
    )
    app.dependency_overrides[get_admin_services] = lambda: services
    app.dependency_overrides[get_services] = lambda: models
    yield TestClient(app)
    app.dependency_overrides.clear()


def _upload(
    client: TestClient,
    headers: dict[str, str],
    *,
    name: str = "보안점검.md",
    body: bytes = GUIDE.encode("utf-8"),
    **form: Any,
) -> Response:
    data = {"title": "보안 점검 안내", "security_level": "1", "departments": ["개발팀"]} | form
    return client.post(
        "/admin/api/documents", headers=headers, data=data, files={"file": (name, body)}
    )


def _titles(client: TestClient, headers: dict[str, str]) -> list[tuple[str, str, bool]]:
    rows = client.get("/admin/api/documents", headers=headers).json()
    return [(r["title"], r["origin"], r["editable"]) for r in rows]


def test_doc_manager_uploads_for_own_department(
    client: TestClient, services: AdminServices
) -> None:
    response = _upload(client, LEE)

    assert response.status_code == 201
    body = response.json()
    assert (body["source_path"], body["origin"], body["owner_department"]) == (
        "upload/보안점검.md",
        "upload",
        "개발팀",
    )
    assert (body["departments"], body["roles"], body["security_level"]) == (["개발팀"], [], 1)
    assert (body["chunks"], body["viewers"], body["editable"]) == (1, 2, True)  # kim, lee
    assert stored_file(services.upload_dir, "upload/보안점검.md").is_file()


def test_doc_manager_cannot_upload_for_another_department(client: TestClient) -> None:
    response = _upload(client, LEE, owner_department="인사팀")

    assert response.status_code == 403


def test_admin_chooses_owner_department_which_must_exist(client: TestClient) -> None:
    ok = _upload(client, HAN, owner_department="인사팀")
    unknown = _upload(client, HAN, name="기타.md", owner_department="총무팀")

    assert (ok.status_code, ok.json()["owner_department"]) == (201, "인사팀")
    assert unknown.status_code == 422


def test_document_lists_are_scoped_by_role(client: TestClient) -> None:
    _upload(client, LEE)
    _upload(client, PARK, name="인사규정.md", title="인사 규정", departments=["인사팀"])

    assert _titles(client, HAN) == [  # 먼저 넣은 문서부터
        ("사내 규칙", "folder", False),
        ("보안 점검 안내", "upload", True),
        ("인사 규정", "upload", True),
    ]
    assert _titles(client, LEE) == [("보안 점검 안내", "upload", True)]
    assert _titles(client, PARK) == [("인사 규정", "upload", True)]
    assert client.get("/admin/api/documents", headers=_as("kim", "")).status_code == 403
    assert client.get("/admin/api/documents", headers=_as("han", "rag-auditor")).status_code == 403


def test_other_department_document_is_hidden_and_folder_document_is_read_only(
    client: TestClient,
) -> None:
    hr = _upload(client, PARK, name="인사규정.md", title="인사 규정", departments=["인사팀"]).json()
    folder = next(
        r for r in client.get("/admin/api/documents", headers=HAN).json() if r["origin"] == "folder"
    )
    access = {"title": "x", "security_level": 0, "departments": ["개발팀"], "roles": []}

    assert (
        client.put(f"/admin/api/documents/{hr['id']}/access", json=access, headers=LEE).status_code
        == 404
    )
    assert client.delete(f"/admin/api/documents/{hr['id']}", headers=LEE).status_code == 404
    assert client.get(f"/admin/api/documents/{hr['id']}/changes", headers=LEE).status_code == 404
    folder_put = client.put(f"/admin/api/documents/{folder['id']}/access", json=access, headers=HAN)
    assert folder_put.status_code == 409
    assert "acl.yaml" in folder_put.json()["detail"]
    assert client.delete(f"/admin/api/documents/{folder['id']}", headers=HAN).status_code == 409


def test_preview_shows_who_will_see_before_saving(client: TestClient) -> None:
    body = client.post(
        "/admin/api/documents/access-preview",
        json={"departments": ["인사팀"], "roles": ["팀장"], "security_level": 2},
        headers=LEE,
    ).json()

    assert (body["count"], body["total_users"]) == (1, 4)
    assert [u["login"] for u in body["users"]] == ["lee"]  # 박인사는 등급 1이라 못 본다


def test_access_change_is_applied_and_recorded(client: TestClient) -> None:
    document = _upload(client, LEE).json()
    wider = {
        "title": "보안 점검 안내 (전사)",
        "security_level": 0,
        "departments": ["개발팀", "인사팀"],
        "roles": [],
        "status": "current",
    }

    updated = client.put(f"/admin/api/documents/{document['id']}/access", json=wider, headers=LEE)
    same = client.put(f"/admin/api/documents/{document['id']}/access", json=wider, headers=LEE)
    changes = client.get(f"/admin/api/documents/{document['id']}/changes", headers=HAN).json()

    assert updated.status_code == same.status_code == 200
    assert (updated.json()["title"], updated.json()["viewers"]) == ("보안 점검 안내 (전사)", 3)
    assert [(c["action"], c["actor_login"]) for c in changes] == [
        ("access", "lee"),
        ("upload", "lee"),
    ]
    assert changes[0]["after"]["departments"] == ["개발팀", "인사팀"]


@pytest.mark.parametrize(
    ("change", "status"),
    [
        ({"departments": [], "roles": []}, 422),  # 아무도 못 보는 문서
        ({"departments": ["총무팀"]}, 422),
        ({"security_level": 4}, 422),
        ({"title": "  "}, 422),
        ({"status": "deleted"}, 422),
    ],
)
def test_invalid_access_is_rejected(
    client: TestClient, change: dict[str, Any], status: int
) -> None:
    document = _upload(client, LEE).json()
    access = {"title": "제목", "security_level": 1, "departments": ["개발팀"], "roles": []} | change

    response = client.put(f"/admin/api/documents/{document['id']}/access", json=access, headers=LEE)

    assert response.status_code == status


def test_replace_file_keeps_id_path_and_access(client: TestClient, services: AdminServices) -> None:
    document = _upload(client, LEE).json()
    new_body = GUIDE.replace("분기마다", "매달").encode("utf-8")

    response = client.put(
        f"/admin/api/documents/{document['id']}/file",
        headers=LEE,
        files={"file": ("보안점검_v2.md", new_body)},
    )
    wrong_type = client.put(
        f"/admin/api/documents/{response.json()['id']}/file",
        headers=LEE,
        files={"file": ("보안점검.docx", b"PK")},
    )

    assert response.status_code == 200
    assert (response.json()["source_path"], response.json()["departments"]) == (
        "upload/보안점검.md",
        ["개발팀"],
    )
    assert stored_file(services.upload_dir, "upload/보안점검.md").read_bytes() == new_body
    assert wrong_type.status_code == 422


def test_delete_removes_document_and_file(client: TestClient, services: AdminServices) -> None:
    document = _upload(client, LEE).json()

    deleted = client.delete(f"/admin/api/documents/{document['id']}", headers=LEE)

    assert deleted.status_code == 204
    assert client.delete(f"/admin/api/documents/{document['id']}", headers=LEE).status_code == 404
    assert not stored_file(services.upload_dir, "upload/보안점검.md").exists()
    assert _titles(client, LEE) == []


@pytest.mark.parametrize(
    ("name", "body", "status"),
    [
        ("보안점검.md", b"#" * (MAX_BYTES + 1), 413),
        ("메모.txt", b"text", 422),
        ("깨진.pdf", b"not a pdf", 422),
    ],
)
def test_bad_files_are_rejected(client: TestClient, name: str, body: bytes, status: int) -> None:
    assert _upload(client, LEE, name=name, body=body).status_code == status


def test_same_name_is_409(client: TestClient) -> None:
    _upload(client, LEE)

    assert _upload(client, LEE).status_code == 409


def test_org_lists_departments_and_roles(client: TestClient) -> None:
    body = client.get("/admin/api/org", headers=LEE).json()

    assert body == {
        "departments": ["개발팀", "경영진", "인사팀"],
        "roles": ["사원", "임원", "팀장"],
    }


def test_upload_waits_while_models_are_loading(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(MODELS, "status", "loading")

    assert _upload(client, LEE).status_code == 503
