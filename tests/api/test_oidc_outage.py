"""로그인 서버 장애 중에는 토큰 탓(401)이 아니라 서버 문제(503)로 알리고, 복구되면 다시 받는다."""

import pytest

from rag_service.api.auth import AuthUnavailableError
from tests.fixtures.oidc import DISCOVERY_URL, JWKS_URL, FakeIssuer, bearer


def test_outage_stays_unavailable_until_keys_are_fetched() -> None:
    now = [1000.0]
    issuer = FakeIssuer()
    authenticator = issuer.authenticator(clock=lambda: now[0])
    issuer.down = True

    for _ in range(2):  # 다시 받는 간격 안의 두 번째 요청도 401이 아니라 503이어야 한다
        with pytest.raises(AuthUnavailableError):
            authenticator.login(bearer(issuer.token()))
    assert issuer.fetched == [DISCOVERY_URL]  # 장애 중에는 간격 안에서 다시 요청하지 않는다

    issuer.down = False
    now[0] += 60

    assert authenticator.login(bearer(issuer.token())) == "kim@example.com"
    assert issuer.fetched == [DISCOVERY_URL, DISCOVERY_URL, JWKS_URL]
