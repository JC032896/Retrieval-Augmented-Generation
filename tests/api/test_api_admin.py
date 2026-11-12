"""관리 API (/admin/api): 그룹 값에 따른 역할, 역할별 접근, 감사 기록 조회.

감사 기록은 실제 DB의 rag_auditor 역할로 접속한 연결로 읽는다 (앱 계정은 읽을 수 없다).
"""

import logging
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from rag_service.api.admin import Admin, AdminServices, LlmInfo, get_admin_services, status
from rag_service.api.auth import CurrentUser, DevHeaderAuthenticator
from rag_service.api.limits import UsageLimits
from rag_service.api.roles import AdminRole
from rag_service.audit.models import AUDITOR_ROLE, AuditLog
from rag_service.db.models import User
from rag_service.main import app
from tests.fixtures.db import db_engine, db_session

__all__ = ["db_engine", "db_session"]

ADMIN = "rag-admin"
DOC_MANAGER = "rag-doc-manager"
AUDITOR = "rag-auditor"
T0 = datetime(2026, 11, 12, 1, 0, tzinfo=UTC)


def _headers(login: str = "kim", groups: str = "") -> dict[str, str]:
    return {"X-User-Id": login, "X-User-Groups": groups}


@pytest.fixture
def auditor_engine(db_engine: Engine) -> Iterator[Engine]:
    """테스트 DB에 rag_auditor 역할로 접속하는 엔진 (운영의 감사 담당 계정과 같은 권한)."""
    engine = create_engine(db_engine.url)

    @event.listens_for(engine, "connect")
    def _as_auditor(dbapi_connection: Any, _: Any) -> None:
        with dbapi_connection.cursor() as cursor:
            cursor.execute(f"SET ROLE {AUDITOR_ROLE}")

    yield engine
    engine.dispose()


def _audit_row(i: int, login: str, outcome: str = "answered") -> AuditLog:
    return AuditLog(
        created_at=T0 + timedelta(minutes=i),
        request_id=f"req-{i}",
        client_ip="10.0.0.1",
        user_login=login,
        user_department="개발팀",
        user_role="사원",
        user_clearance_level=1,
        question=f"질문 {i}",
        question_sha256=f"sha-{i}",
        question_chars=4,
        answer=f"답변 {i}" if outcome == "answered" else None,
        outcome=outcome,
        refusal_reason="no_hits" if outcome == "refused" else None,
        context_files=["travel.md"],
        cited_files=["travel.md"] if outcome == "answered" else [],
        verified=True if outcome == "answered" else None,
        model="claude-sonnet-5-5",
        input_tokens=100,
        output_tokens=10,
        cost_usd=0.001,
        retrieval_ms=20,
        first_token_ms=300,
        total_ms=900,
        prompt_template_version="2026-11-09.1",
        model_params={"max_tokens": 1024},
        context_chunks=[{"chunk_key": "travel.md#0", "content_sha256": "c0"}],
        request_sha256=f"r-{i}",
    )


@pytest.fixture
def services(db_engine: Engine, db_session: Session, auditor_engine: Engine) -> AdminServices:
    with db_engine.begin() as connection:
        connection.execute(text("TRUNCATE audit_log, chunk_snapshots RESTART IDENTITY"))
    db_session.add_all(
        [
            User(login="kim", name="김사원", department="개발팀", role="사원", clearance_level=1),
            User(login="han", name="한임원", department="경영진", role="임원", clearance_level=3),
            User(login="lee", name="이팀장", department="개발팀", role="팀장", clearance_level=2),
        ]
    )
    db_session.add_all(
        [_audit_row(i, "kim") for i in range(1, 4)]
        + [_audit_row(4, "lee", "refused"), _audit_row(5, "kim", "error")]
    )
    db_session.commit()
    return AdminServices(
        sessions=sessionmaker(db_engine),
        audit_sessions=sessionmaker(auditor_engine),
        authenticator=DevHeaderAuthenticator(),
        llm=LlmInfo("claude", "claude-sonnet-5-5", configured=False),
        limits=UsageLimits(daily_requests_per_user=200, daily_budget_usd=20.0),
    )


@pytest.fixture
def client(services: AdminServices) -> Iterator[TestClient]:
    app.dependency_overrides[get_admin_services] = lambda: services
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_me_lists_roles_from_groups_in_a_fixed_order(client: TestClient) -> None:
    groups = f"{AUDITOR}, other-group,{ADMIN}"

    body = client.get("/admin/api/me", headers=_headers("han", groups)).json()

    assert body == {
        "login": "han",
        "name": "한임원",
        "department": "경영진",
        "role": "임원",
        "clearance_level": 3,
        "roles": ["admin", "auditor"],
    }


def test_me_without_admin_groups_is_200_with_no_roles(client: TestClient) -> None:
    response = client.get("/admin/api/me", headers=_headers("kim"))

    assert response.status_code == 200
    assert response.json()["roles"] == []


def test_unknown_or_missing_user_is_401(client: TestClient) -> None:
    unknown = client.get("/admin/api/me", headers=_headers("ghost", ADMIN))
    missing = client.get("/admin/api/me")

    assert unknown.status_code == missing.status_code == 401
    assert unknown.headers["WWW-Authenticate"] == "Bearer"


@pytest.mark.parametrize(
    ("path", "groups", "expected"),
    [
        ("/admin/api/status", "", 403),
        ("/admin/api/status", DOC_MANAGER, 200),
        ("/admin/api/status", AUDITOR, 200),
        ("/admin/api/users", DOC_MANAGER, 403),
        ("/admin/api/users", AUDITOR, 403),
        ("/admin/api/users", ADMIN, 200),
        # 중앙 관리자도 감사 담당 그룹이 없으면 감사 기록을 볼 수 없다
        ("/admin/api/audit", ADMIN, 403),
        ("/admin/api/audit", DOC_MANAGER, 403),
        ("/admin/api/audit", AUDITOR, 200),
        ("/admin/api/audit/1", ADMIN, 403),
        ("/admin/api/audit/1", AUDITOR, 200),
    ],
)
def test_each_endpoint_requires_its_role(
    client: TestClient, path: str, groups: str, expected: int
) -> None:
    assert client.get(path, headers=_headers("lee", groups)).status_code == expected


def test_forbidden_access_is_logged(client: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="rag_service.api.admin"):
        client.get("/admin/api/users", headers=_headers("lee", DOC_MANAGER))

    [record] = [r for r in caplog.records if r.getMessage() == "admin_forbidden"]
    fields = record.__dict__["fields"]
    assert (fields["login"], fields["roles"], fields["required"]) == (
        "lee",
        ["doc_manager"],
        ["admin"],
    )


def test_users_are_listed_by_department_then_login(client: TestClient) -> None:
    body = client.get("/admin/api/users", headers=_headers("han", ADMIN)).json()

    assert [(u["department"], u["login"]) for u in body] == [
        ("개발팀", "kim"),
        ("개발팀", "lee"),
        ("경영진", "han"),
    ]
    assert body[2] == {
        "login": "han",
        "name": "한임원",
        "department": "경영진",
        "role": "임원",
        "clearance_level": 3,
    }


def test_status_reports_db_index_llm_audit_and_limits(client: TestClient) -> None:
    body = client.get("/admin/api/status", headers=_headers("han", ADMIN)).json()

    assert body["db"] == "ok"
    assert body["index"]["documents"] == 0
    assert body["llm"] == {"provider": "claude", "model": "claude-sonnet-5-5", "configured": False}
    assert body["audit_db"] is True
    assert body["limits"] == {
        "daily_requests_per_user": 200,
        "daily_budget_usd": 20.0,
        "concurrent_per_user": None,
        "utc_offset_hours": 9,
    }
    assert body["models"]["status"] in ("lazy", "loading", "ready", "error")


def test_status_shows_db_error_instead_of_failing() -> None:
    # 사용자 확인도 같은 DB를 쓰므로, 확인을 마친 뒤의 상태 조회만 끊긴 DB로 부른다
    broken = create_engine(
        "postgresql+psycopg://nobody:x@127.0.0.1:1/none", connect_args={"connect_timeout": 1}
    )
    services = AdminServices(sessions=sessionmaker(broken), audit_sessions=None, authenticator=None)
    han = Admin(CurrentUser("han", "한임원", "경영진", "임원", 3), frozenset({AdminRole.ADMIN}))
    try:
        response = status(han, services)
    finally:
        broken.dispose()

    assert (response.db, response.index) == (
        "error",
        {"error": "DB에 연결하거나 인덱스를 읽을 수 없습니다"},
    )
    assert response.audit_db is False


def test_audit_list_is_newest_first_with_filters_and_paging(client: TestClient) -> None:
    auditor = _headers("lee", AUDITOR)

    first = client.get("/admin/api/audit", params={"limit": 2}, headers=auditor).json()
    second = client.get(
        "/admin/api/audit",
        params={"limit": 2, "before_id": first["next_before_id"]},
        headers=auditor,
    ).json()
    last = client.get(
        "/admin/api/audit",
        params={"limit": 2, "before_id": second["next_before_id"]},
        headers=auditor,
    ).json()

    assert [i["id"] for i in first["items"]] == [5, 4]
    assert [i["id"] for i in second["items"]] == [3, 2]
    assert ([i["id"] for i in last["items"]], last["next_before_id"]) == ([1], None)
    assert first["items"][1]["question"] == "질문 4"
    assert "answer" not in first["items"][0]  # 목록에는 답변 원문을 싣지 않는다

    kim = client.get("/admin/api/audit", params={"login": "kim"}, headers=auditor).json()
    refused = client.get("/admin/api/audit", params={"outcome": "refused"}, headers=auditor).json()
    window = client.get(
        "/admin/api/audit",
        params={
            "since": (T0 + timedelta(minutes=2)).isoformat(),
            "until": (T0 + timedelta(minutes=4)).isoformat(),
        },
        headers=auditor,
    ).json()

    assert [i["id"] for i in kim["items"]] == [5, 3, 2, 1]
    assert [(i["id"], i["refusal_reason"]) for i in refused["items"]] == [(4, "no_hits")]
    assert [i["id"] for i in window["items"]] == [3, 2]  # since 포함, until 제외


def test_audit_list_rejects_unknown_outcome_and_oversized_page(client: TestClient) -> None:
    auditor = _headers("lee", AUDITOR)

    assert (
        client.get("/admin/api/audit", params={"outcome": "deleted"}, headers=auditor).status_code
        == 422
    )
    assert client.get("/admin/api/audit", params={"limit": 201}, headers=auditor).status_code == 422


def test_audit_detail_has_answer_and_replay_fields(client: TestClient) -> None:
    auditor = _headers("lee", AUDITOR)

    body = client.get("/admin/api/audit/2", headers=auditor).json()
    missing = client.get("/admin/api/audit/999", headers=auditor)

    assert (body["question"], body["answer"], body["request_sha256"]) == ("질문 2", "답변 2", "r-2")
    assert body["context_chunks"] == [{"chunk_key": "travel.md#0", "content_sha256": "c0"}]
    assert (body["client_ip"], body["user_clearance_level"]) == ("10.0.0.1", 1)
    assert missing.status_code == 404


def test_audit_viewing_is_logged_without_question_text(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    auditor = _headers("lee", AUDITOR)
    with caplog.at_level(logging.INFO, logger="rag_service.api.admin"):
        client.get("/admin/api/audit", params={"login": "kim"}, headers=auditor)
        client.get("/admin/api/audit/2", headers=auditor)

    records = [r for r in caplog.records if r.getMessage() == "admin_audit_viewed"]
    fields = [r.__dict__["fields"] for r in records]
    assert fields[0]["viewer"] == "lee"
    assert (fields[0]["filters"]["login"], fields[0]["count"]) == ("kim", 4)
    assert fields[1] == {"viewer": "lee", "audit_id": 2}
    assert "질문" not in repr(fields)


def test_audit_without_auditor_account_is_503(services: AdminServices) -> None:
    without = AdminServices(
        sessions=services.sessions, audit_sessions=None, authenticator=services.authenticator
    )
    app.dependency_overrides[get_admin_services] = lambda: without
    try:
        response = TestClient(app).get("/admin/api/audit", headers=_headers("lee", AUDITOR))
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert "AUDIT_DB_USER" in response.json()["detail"]


def test_disabled_auth_is_503(services: AdminServices) -> None:
    disabled = AdminServices(sessions=services.sessions, audit_sessions=None, authenticator=None)
    app.dependency_overrides[get_admin_services] = lambda: disabled
    try:
        response = TestClient(app).get("/admin/api/me", headers=_headers("han", ADMIN))
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
