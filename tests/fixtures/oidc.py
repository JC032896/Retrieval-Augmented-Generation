"""테스트용 가짜 OIDC 로그인 서버. 실제처럼 RSA 키로 토큰을 서명하고 공개 키 목록을 내준다.

네트워크 없이 SigningKeys의 fetch 자리에 FakeIssuer.fetch를 넣어 쓴다.
"""

import json
import time
from collections.abc import Callable
from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from rag_service.api.oidc import OidcAuthenticator, OidcConfig, SigningKeys

ISSUER = "https://login.example.com"
AUDIENCE = "rag-service"
DISCOVERY_URL = ISSUER + "/.well-known/openid-configuration"
JWKS_URL = ISSUER + "/keys"


def new_private_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


class FakeIssuer:
    def __init__(self, kid: str = "key-1") -> None:
        self.kid = kid
        self.private_key = new_private_key()
        self.fetched: list[str] = []  # 받아 간 주소 (캐시 동작 확인용)
        self.down = False  # True면 로그인 서버가 응답하지 않는 것처럼 동작

    def rotate(self, kid: str) -> None:
        """서명 키를 새것으로 바꾼다 (로그인 서버의 정기 키 교체)."""
        self.kid = kid
        self.private_key = new_private_key()

    def fetch(self, url: str) -> Any:
        self.fetched.append(url)
        if self.down:
            raise OSError("연결 실패")
        if url == DISCOVERY_URL:
            return {"issuer": ISSUER, "jwks_uri": JWKS_URL}
        if url == JWKS_URL:
            jwk = json.loads(RSAAlgorithm.to_jwk(self.private_key.public_key()))
            return {"keys": [{**jwk, "kid": self.kid, "use": "sig", "alg": "RS256"}]}
        raise OSError(f"없는 주소: {url}")

    def token(
        self,
        *,
        kid: str | None = None,
        key: rsa.RSAPrivateKey | None = None,
        **claims: Any,
    ) -> str:
        """정상 토큰. claims로 값을 바꾸고, None을 주면 그 값을 뺀다."""
        return jwt.encode(
            standard_claims(**claims),
            key or self.private_key,
            algorithm="RS256",
            headers={"kid": kid or self.kid},
        )

    def authenticator(
        self,
        login_claim: str = "email",
        *,
        clock: Callable[[], float] = time.monotonic,
        min_refresh_seconds: float = 60.0,
    ) -> OidcAuthenticator:
        keys = SigningKeys(
            ISSUER, fetch=self.fetch, clock=clock, min_refresh_seconds=min_refresh_seconds
        )
        return OidcAuthenticator(OidcConfig(ISSUER, AUDIENCE, login_claim), keys=keys)


def standard_claims(**overrides: Any) -> dict[str, Any]:
    now = int(time.time())
    claims = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": "user-1",
        "iat": now,
        "exp": now + 300,
        "email": "kim@example.com",
        "email_verified": True,
        "preferred_username": "kim",
    } | overrides
    return {name: value for name, value in claims.items() if value is not None}


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
