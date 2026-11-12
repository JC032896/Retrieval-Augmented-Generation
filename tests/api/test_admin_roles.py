"""관리 역할의 재료: 토큰·개발 헤더의 그룹 값, 그룹 → 역할 대응, 관련 설정."""

from pathlib import Path
from typing import Any, Literal

import pytest
from pydantic import SecretStr

from rag_service.api import admin as admin_module
from rag_service.api.admin import get_admin_services
from rag_service.api.auth import DevHeaderAuthenticator, Identity
from rag_service.api.oidc import OidcAuthenticator, OidcConfig, SigningKeys
from rag_service.api.roles import AdminRole, RoleGroups
from rag_service.config import Settings
from tests.fixtures.oidc import AUDIENCE, ISSUER, FakeIssuer, bearer


def _oidc(issuer: FakeIssuer, groups_claim: str = "groups") -> OidcAuthenticator:
    config = OidcConfig(ISSUER, AUDIENCE, "preferred_username", groups_claim=groups_claim)
    return OidcAuthenticator(config, keys=SigningKeys(ISSUER, fetch=issuer.fetch))


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (["rag-admin", " rag-auditor ", "", 7, None], {"rag-admin", "rag-auditor"}),
        ("rag-admin", {"rag-admin"}),
        (None, set()),  # 그룹 값이 없는 토큰 (질문만 하는 직원)
        ({"rag-admin": True}, set()),  # 모르는 형식은 그룹 없음으로 본다
    ],
)
def test_oidc_token_groups(value: Any, expected: set[str]) -> None:
    issuer = FakeIssuer()

    identity = _oidc(issuer).identify(bearer(issuer.token(groups=value)))

    assert identity == Identity("kim", frozenset(expected))


def test_oidc_groups_claim_name_is_configurable() -> None:
    issuer = FakeIssuer()
    token = issuer.token(groups=["rag-admin"], roles=["rag-auditor"])

    assert _oidc(issuer, "roles").identify(bearer(token)).groups == {"rag-auditor"}
    # login만 쓰는 질문 API는 그룹과 상관없이 같은 로그인 id를 받는다
    assert _oidc(issuer).login(bearer(token)) == "kim"


def test_dev_header_groups() -> None:
    authenticator = DevHeaderAuthenticator()

    with_groups = authenticator.identify({"X-User-Id": "han", "X-User-Groups": "rag-admin, ,x"})
    without = authenticator.identify({"X-User-Id": "kim"})

    assert with_groups == Identity("han", frozenset({"rag-admin", "x"}))
    assert without == Identity("kim")


def test_groups_map_to_roles_without_implying_each_other() -> None:
    groups = RoleGroups()

    assert groups.roles(["rag-admin"]) == {AdminRole.ADMIN}
    assert groups.roles(["rag-admin", "rag-auditor", "other"]) == {
        AdminRole.ADMIN,
        AdminRole.AUDITOR,
    }
    assert groups.roles(["Rag-Admin", "rag-admins"]) == frozenset()  # 정확히 같은 이름만
    # Entra ID처럼 그룹 객체 id를 쓰는 회사
    custom = RoleGroups(admin="1f0c-admin-id", doc_manager="d0c", auditor="a0d")
    assert custom.roles(["1f0c-admin-id", "a0d"]) == {AdminRole.ADMIN, AdminRole.AUDITOR}


def test_settings_role_groups_and_groups_claim() -> None:
    settings = Settings(
        auth_mode="oidc",
        oidc_issuer=ISSUER,
        oidc_audience=AUDIENCE,
        oidc_groups_claim="roles",
        admin_group="it-admins",
        doc_manager_group="doc-owners",
        auditor_group="compliance",
    )

    assert settings.role_groups == RoleGroups("it-admins", "doc-owners", "compliance")
    assert settings.oidc is not None
    assert settings.oidc.groups_claim == "roles"


def test_audit_database_url_needs_user_and_password(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    password_file = tmp_path / "audit_db_password"
    password_file.write_text("from-file\n", encoding="utf-8")
    # compose는 비운 변수도 빈 문자열로 넘긴다
    for name in ("AUDIT_DB_USER", "AUDIT_DB_PASSWORD", "AUDIT_DB_PASSWORD_FILE"):
        monkeypatch.setenv(name, "")

    unset = Settings()
    no_password = Settings(audit_db_user="rag_audit_ops")
    from_file = Settings(
        postgres_db="rag",
        audit_db_user="rag_audit_ops",
        audit_db_password=SecretStr("ignored"),
        audit_db_password_file=password_file,
    )

    assert unset.audit_database_url is None
    assert no_password.audit_database_url is None
    url = from_file.audit_database_url
    assert url is not None
    assert (url.username, url.password, url.database) == ("rag_audit_ops", "from-file", "rag")
    assert from_file.database_url.username != "rag_audit_ops"  # 앱 연결은 그대로


@pytest.mark.parametrize(
    ("audit_user", "audit_view", "connected"),
    [(None, True, False), ("rag_audit_ops", True, True), ("rag_audit_ops", False, False)],
)
@pytest.mark.parametrize(
    ("provider", "key", "configured"),
    [("claude", None, False), ("claude", "sk-test", True), ("openai_compatible", None, True)],
)
def test_admin_services_from_settings(
    monkeypatch: pytest.MonkeyPatch,
    audit_user: str | None,
    audit_view: bool,
    connected: bool,
    provider: Literal["claude", "openai_compatible"],
    key: str | None,
    configured: bool,
) -> None:
    settings = Settings(
        auth_mode="dev_header",
        llm_provider=provider,
        llm_base_url="http://llm:8000/v1" if provider == "openai_compatible" else None,
        anthropic_api_key=None if key is None else SecretStr(key),
        audit_db_user=audit_user,
        admin_audit_view=audit_view,
        audit_db_password=SecretStr("pw"),
        admin_group="it-admins",
        llm_daily_requests_per_user=10,
    )
    monkeypatch.setattr(admin_module, "get_settings", lambda: settings)
    get_admin_services.cache_clear()
    try:
        built = get_admin_services()
    finally:
        get_admin_services.cache_clear()

    assert isinstance(built.authenticator, DevHeaderAuthenticator)
    assert built.role_groups.admin == "it-admins"
    assert built.llm.configured is configured
    # 끄면 계정이 있어도 앱이 감사 담당 계정으로 연결하지 않는다
    assert (built.audit_sessions is not None) is connected
    assert built.limits.daily_requests_per_user == 10
