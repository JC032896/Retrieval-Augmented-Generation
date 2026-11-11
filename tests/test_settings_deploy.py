"""배포용 설정: 빈 값은 '설정 안 함', OIDC http 허용 호스트는 명시한 것만."""

import pytest
from pydantic import ValidationError

from rag_service.api.oidc import OidcAuthenticator, check_issuer_url
from rag_service.config import Settings

DEMO = "http://keycloak:8080/realms/hanbit"


def test_empty_values_mean_unset() -> None:
    keys = (
        "anthropic_api_key",
        "oidc_issuer",
        "oidc_audience",
        "audit_retention_days",
        "llm_daily_requests_per_user",
        "llm_daily_budget_usd",
        "llm_concurrent_per_user",
    )
    settings = Settings.model_validate(dict.fromkeys(keys, ""))

    assert settings.anthropic_api_key is None
    assert (settings.oidc_issuer, settings.oidc_audience) == (None, None)
    assert settings.audit_retention_days is None
    assert settings.llm_daily_requests_per_user is None
    assert settings.llm_daily_budget_usd is None
    assert settings.llm_concurrent_per_user is None


def test_http_issuer_needs_an_explicit_internal_host() -> None:
    with pytest.raises(ValueError, match="https"):
        check_issuer_url(DEMO)
    with pytest.raises(ValueError, match="https"):
        check_issuer_url("http://evil.example/realms/x", ["keycloak"])

    assert check_issuer_url(DEMO, ["keycloak"]) == DEMO


def test_settings_pass_allowed_hosts_to_the_authenticator() -> None:
    with pytest.raises(ValidationError, match="https"):
        Settings(auth_mode="oidc", oidc_issuer=DEMO, oidc_audience="rag-service")

    settings = Settings(
        auth_mode="oidc",
        oidc_issuer=DEMO,
        oidc_audience="rag-service",
        oidc_allow_http_hosts=" keycloak , ,other ",
    )
    assert settings.allow_http_hosts == ("keycloak", "other")
    assert settings.oidc is not None
    assert settings.oidc.allow_http_hosts == ("keycloak", "other")
    assert OidcAuthenticator(settings.oidc).config.issuer == DEMO
