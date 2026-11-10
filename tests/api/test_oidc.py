"""OIDC 토큰 검증 테스트. 위조·만료·다른 앱용 토큰은 거부하고, 공개 키 캐시는 키 교체를 따라간다."""

import base64
import hashlib
import hmac
import io
import json
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from pydantic import ValidationError

from rag_service.api.auth import AuthError, AuthUnavailableError, build_authenticator
from rag_service.api.oidc import OidcAuthenticator, OidcConfig, check_issuer_url, fetch_json
from rag_service.config import Settings
from tests.fixtures.oidc import (
    AUDIENCE,
    DISCOVERY_URL,
    ISSUER,
    JWKS_URL,
    FakeIssuer,
    bearer,
    new_private_key,
    standard_claims,
)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unsigned_parts(header: dict[str, Any]) -> str:
    return _b64(json.dumps(header).encode()) + "." + _b64(json.dumps(standard_claims()).encode())


def _alg_none(issuer: FakeIssuer) -> str:
    return _unsigned_parts({"alg": "none", "kid": issuer.kid}) + "."


def _hs256_with_public_key(issuer: FakeIssuer) -> str:
    """공개 키(누구나 받을 수 있음)를 HMAC 비밀 키로 써서 만든 위조 토큰."""
    secret = issuer.private_key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    signing_input = _unsigned_parts({"alg": "HS256", "typ": "JWT", "kid": issuer.kid})
    signature = hmac.new(secret, signing_input.encode(), hashlib.sha256).digest()
    return signing_input + "." + _b64(signature)


BAD_TOKENS: dict[str, Callable[[FakeIssuer], str]] = {
    "만료": lambda i: i.token(iat=int(time.time()) - 7200, exp=int(time.time()) - 3600),
    "다른 앱용": lambda i: i.token(aud="other-app"),
    "다른 발급자": lambda i: i.token(iss="https://evil.example.com"),
    "만료 시간 없음": lambda i: i.token(exp=None),
    "다른 키로 서명": lambda i: i.token(key=new_private_key()),
    "서명 없음(alg none)": _alg_none,
    "공개 키를 HMAC 비밀로 사용": _hs256_with_public_key,
    "kid 없음": lambda i: _unsigned_parts({"alg": "RS256"}) + ".c2ln",
    "형식 오류": lambda i: "abc.def",
}


def test_valid_token_returns_lowercased_email() -> None:
    issuer = FakeIssuer()

    login = issuer.authenticator().login(bearer(issuer.token(email="Kim@Example.com")))

    assert login == "kim@example.com"


def test_login_claim_is_configurable() -> None:
    issuer = FakeIssuer()

    assert issuer.authenticator("preferred_username").login(bearer(issuer.token())) == "kim"


@pytest.mark.parametrize("case", list(BAD_TOKENS))
def test_invalid_tokens_are_rejected(case: str) -> None:
    issuer = FakeIssuer()

    with pytest.raises(AuthError):
        issuer.authenticator().login(bearer(BAD_TOKENS[case](issuer)))


@pytest.mark.parametrize(
    "claims", [{"email": None}, {"email": "  "}, {"email_verified": False}], ids=str
)
def test_missing_or_unverified_login_value_is_rejected(claims: dict[str, Any]) -> None:
    issuer = FakeIssuer()

    with pytest.raises(AuthError):
        issuer.authenticator().login(bearer(issuer.token(**claims)))


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Basic a2ltOnB3"}, {"Authorization": "Bearer "}, {"X-User-Id": "kim"}],
    ids=str,
)
def test_request_without_bearer_token_is_rejected(headers: dict[str, str]) -> None:
    with pytest.raises(AuthError):
        FakeIssuer().authenticator().login(headers)


def test_keys_are_fetched_once_and_cached() -> None:
    issuer = FakeIssuer()
    authenticator = issuer.authenticator()

    authenticator.login(bearer(issuer.token()))
    authenticator.login(bearer(issuer.token()))

    assert issuer.fetched == [DISCOVERY_URL, JWKS_URL]


def test_rotated_key_is_picked_up_after_refresh_interval() -> None:
    now = [1000.0]
    issuer = FakeIssuer()
    authenticator = issuer.authenticator(clock=lambda: now[0])
    authenticator.login(bearer(issuer.token()))

    issuer.rotate("key-2")
    now[0] += 60

    assert authenticator.login(bearer(issuer.token(email="lee@example.com"))) == "lee@example.com"
    assert issuer.fetched == [DISCOVERY_URL, JWKS_URL, JWKS_URL]


def test_unknown_kid_does_not_refetch_within_interval() -> None:
    issuer = FakeIssuer()
    authenticator = issuer.authenticator(clock=lambda: 1000.0)
    authenticator.login(bearer(issuer.token()))

    for _ in range(3):  # 위조 토큰을 연달아 보내도 로그인 서버에 요청이 늘지 않는다
        with pytest.raises(AuthError):
            authenticator.login(bearer(issuer.token(kid="unknown")))

    assert issuer.fetched == [DISCOVERY_URL, JWKS_URL]


def test_login_server_down_is_unavailable() -> None:
    issuer = FakeIssuer()
    issuer.down = True

    with pytest.raises(AuthUnavailableError):
        issuer.authenticator().login(bearer(issuer.token()))


class _IssuerWithDiscovery(FakeIssuer):
    """공개 정보(discovery 문서)만 바꿔 내주는 로그인 서버."""

    def __init__(self, document: dict[str, str]) -> None:
        super().__init__()
        self.document = document

    def fetch(self, url: str) -> Any:
        return self.document if url == DISCOVERY_URL else super().fetch(url)


@pytest.mark.parametrize(
    "document", [{"issuer": "https://evil.example.com", "jwks_uri": JWKS_URL}, {"issuer": ISSUER}]
)
def test_bad_discovery_document_is_unavailable(document: dict[str, str]) -> None:
    issuer = _IssuerWithDiscovery(document)

    with pytest.raises(AuthUnavailableError):
        issuer.authenticator().login(bearer(issuer.token()))


@pytest.mark.parametrize(
    ("url", "ok"),
    [
        ("https://login.example.com", True),
        ("http://localhost:8080/realms/demo", True),
        ("http://login.example.com", False),
        ("ftp://login.example.com", False),
    ],
)
def test_issuer_must_be_https_except_localhost(url: str, ok: bool) -> None:
    if ok:
        assert check_issuer_url(url) == url
    else:
        with pytest.raises(ValueError, match="https"):
            check_issuer_url(url)


def test_fetch_json_reads_url_with_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[str, float]] = []

    @contextmanager
    def urlopen(request: Any, timeout: float) -> Iterator[io.BytesIO]:
        seen.append((request.full_url, timeout))
        yield io.BytesIO(b'{"issuer": "x"}')

    monkeypatch.setattr("urllib.request.urlopen", urlopen)

    assert fetch_json(DISCOVERY_URL) == {"issuer": "x"}
    assert seen == [(DISCOVERY_URL, 5.0)]


def test_build_authenticator_for_oidc() -> None:
    config = OidcConfig(ISSUER, AUDIENCE)

    assert isinstance(build_authenticator("oidc", config), OidcAuthenticator)
    with pytest.raises(ValueError, match="OIDC_ISSUER"):
        build_authenticator("oidc", None)


@pytest.fixture
def no_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """로컬 .env와 셸 환경 변수가 설정 테스트에 섞이지 않게 한다."""
    monkeypatch.chdir(tmp_path)
    for name in ("AUTH_MODE", "OIDC_ISSUER", "OIDC_AUDIENCE", "OIDC_LOGIN_CLAIM"):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.usefixtures("no_env")
def test_settings_build_oidc_config() -> None:
    settings = Settings(auth_mode="oidc", oidc_issuer=ISSUER, oidc_audience=AUDIENCE)

    assert settings.oidc == OidcConfig(ISSUER, AUDIENCE, "email")
    assert Settings().oidc is None


@pytest.mark.usefixtures("no_env")
@pytest.mark.parametrize(
    "values",
    [
        {},
        {"oidc_issuer": ISSUER},
        {"oidc_issuer": "http://login.example.com", "oidc_audience": "a"},
    ],
    ids=str,
)
def test_settings_reject_incomplete_or_insecure_oidc(values: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate({"auth_mode": "oidc", **values})
