"""OIDC(OpenID Connect) 토큰으로 사용자를 확인한다.

회사가 이미 쓰는 로그인 시스템(Microsoft Entra ID, Google Workspace, Okta, Keycloak 등)이 발급한
토큰을 `Authorization: Bearer <토큰>`으로 받는다. 회사마다 코드를 바꾸지 않고 설정만 넣는다.

검증 순서
1. 로그인 서버의 공개 정보(`{issuer}/.well-known/openid-configuration`)에서 공개 키 주소
   (jwks_uri)를 찾는다.
2. 토큰 머리글의 키 id(kid)로 공개 키를 골라 서명을 확인한다. 모르는 kid면 키가 교체됐을 수 있으니
   공개 키 목록을 한 번 다시 받는다. 단, 위조 토큰으로 로그인 서버에 요청을 퍼붓지 못하게
   다시 받는 간격을 제한한다.
3. 발급자(iss), 대상 앱(aud), 만료(exp)를 확인한다. 공개 키 방식 알고리즘만 허용한다
   (none이나 HS256을 허용하면 공개 키를 비밀 키처럼 써서 토큰을 위조할 수 있다).
4. 설정한 클레임(기본 email)의 값을 로그인 id로 돌려준다. 권한 속성은 여기서 읽지 않는다
   (auth.py 참고). email을 쓸 때 로그인 서버가 "확인 안 된 메일"이라고 표시했으면 거부한다.
5. 관리 화면용으로 그룹 클레임(기본 groups)도 함께 돌려준다 (identify, api/roles.py).
"""

import json
import threading
import time
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import jwt

from rag_service.api.errors import AuthError, AuthUnavailableError
from rag_service.api.identity import Identity, clean_groups

# 공개 키(비대칭) 서명만 허용한다
ALLOWED_ALGORITHMS = ("RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384")
DEFAULT_LEEWAY_SECONDS = 30  # 서버 간 시계 차이 허용
MIN_REFRESH_SECONDS = 60.0  # 모르는 kid 때문에 공개 키를 다시 받는 최소 간격
FETCH_TIMEOUT_SECONDS = 5.0

FetchJson = Callable[[str], Any]


@dataclass(frozen=True)
class OidcConfig:
    issuer: str  # 로그인 서버 주소. 토큰의 iss와 정확히 같아야 한다
    audience: str  # 이 앱의 id. 토큰의 aud에 있어야 한다
    login_claim: str = "email"  # users.login과 맞출 토큰 값 (Keycloak은 preferred_username도 흔함)
    # http를 허용할 내부 호스트 (예: compose 네트워크 안의 "keycloak"). 운영에서는 비워 둔다
    allow_http_hosts: tuple[str, ...] = ()
    # 관리 화면 역할을 정할 그룹 목록이 들어 있는 토큰 값 (api/roles.py)
    groups_claim: str = "groups"


def check_issuer_url(issuer: str, allow_http_hosts: Sequence[str] = ()) -> str:
    """https만 허용한다. 개발용 로그인 서버(localhost)와 명시한 내부 호스트만 http를 허용한다.

    allow_http_hosts는 같은 docker 네트워크 안의 데모용 Keycloak처럼 외부에 노출되지 않는
    경우에만 쓴다 (OIDC_ALLOW_HTTP_HOSTS). 토큰 서명은 그대로 검증하지만, 공개 키를 받는
    통신은 암호화되지 않는다.
    """
    url = urlparse(issuer)
    local = url.hostname in ("localhost", "127.0.0.1", *allow_http_hosts)
    if url.scheme == "https" or (url.scheme == "http" and local):
        return issuer
    raise ValueError(f"OIDC 발급자 주소는 https여야 합니다: {issuer}")


def fetch_json(url: str) -> Any:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT_SECONDS) as response:
        return json.load(response)


class SigningKeys:
    """로그인 서버의 공개 키 목록. 처음 필요할 때 받고, 모르는 kid면 제한된 빈도로 다시 받는다."""

    def __init__(
        self,
        issuer: str,
        *,
        fetch: FetchJson = fetch_json,
        clock: Callable[[], float] = time.monotonic,
        min_refresh_seconds: float = MIN_REFRESH_SECONDS,
    ) -> None:
        self._issuer = issuer
        self._fetch = fetch
        self._clock = clock
        self._min_refresh = min_refresh_seconds
        self._lock = threading.Lock()  # 요청은 여러 스레드에서 동시에 온다
        self._jwks_uri: str | None = None
        self._keys: dict[str, jwt.PyJWK] = {}
        self._fetched_at: float | None = None

    def get(self, kid: str) -> jwt.PyJWK:
        with self._lock:
            if kid not in self._keys and self._may_refresh():
                self._refresh()
            key = self._keys.get(kid)
            loaded = bool(self._keys)
        if key is None and not loaded:
            # 공개 키를 한 번도 받지 못했다 (로그인 서버 장애). 토큰 탓이 아니므로 401이 아니라 503
            raise AuthUnavailableError("로그인 서버의 공개 키를 아직 받지 못했습니다")
        if key is None:
            raise AuthError("토큰 서명 키를 알 수 없습니다")
        return key

    def _may_refresh(self) -> bool:
        return self._fetched_at is None or self._clock() - self._fetched_at >= self._min_refresh

    def _refresh(self) -> None:
        self._fetched_at = self._clock()
        try:
            if self._jwks_uri is None:
                self._jwks_uri = self._discover()
            key_set = jwt.PyJWKSet.from_dict(self._fetch(self._jwks_uri))
        except (OSError, ValueError, jwt.PyJWKSetError) as error:
            raise AuthUnavailableError("로그인 서버의 공개 키를 받지 못했습니다") from error
        self._keys = {key.key_id: key for key in key_set.keys if key.key_id is not None}

    def _discover(self) -> str:
        document = self._fetch(self._issuer.rstrip("/") + "/.well-known/openid-configuration")
        if document.get("issuer") != self._issuer:
            raise ValueError("공개 정보의 issuer가 설정과 다릅니다")
        jwks_uri = document.get("jwks_uri")
        if not isinstance(jwks_uri, str):
            raise ValueError("공개 정보에 jwks_uri가 없습니다")
        return jwks_uri


class OidcAuthenticator:
    def __init__(self, config: OidcConfig, *, keys: SigningKeys | None = None) -> None:
        self.config = config
        self._keys = keys or SigningKeys(check_issuer_url(config.issuer, config.allow_http_hosts))

    def login(self, headers: Mapping[str, str]) -> str:
        return self._login_from(self._claims(headers))

    def identify(self, headers: Mapping[str, str]) -> Identity:
        claims = self._claims(headers)
        return Identity(self._login_from(claims), self._groups_from(claims))

    def _claims(self, headers: Mapping[str, str]) -> dict[str, Any]:
        token = _bearer_token(headers)
        try:
            kid = jwt.get_unverified_header(token).get("kid")
            if not isinstance(kid, str):
                raise AuthError("토큰에 서명 키 id(kid)가 없습니다")
            claims = jwt.decode(
                token,
                key=self._keys.get(kid),
                algorithms=list(ALLOWED_ALGORITHMS),
                audience=self.config.audience,
                issuer=self.config.issuer,
                leeway=DEFAULT_LEEWAY_SECONDS,
                options={"require": ["exp", "iat", "iss", "aud"]},
            )
        except jwt.PyJWTError as error:
            raise AuthError("토큰이 유효하지 않습니다") from error
        return claims

    def _groups_from(self, claims: Mapping[str, Any]) -> frozenset[str]:
        """그룹 값이 없거나 형식이 다르면 그룹 없음 (관리 역할 없음). 질문 API는 그대로 쓴다."""
        value = claims.get(self.config.groups_claim)
        if isinstance(value, str):
            return clean_groups([value])
        if isinstance(value, list):
            return clean_groups(value)
        return frozenset()

    def _login_from(self, claims: Mapping[str, Any]) -> str:
        claim = self.config.login_claim
        value = claims.get(claim)
        if not isinstance(value, str) or not value.strip():
            raise AuthError(f"토큰에 사용자 값({claim})이 없습니다")
        if claim == "email":
            if claims.get("email_verified") is False:
                raise AuthError("확인되지 않은 메일 주소입니다")
            return value.strip().lower()  # 메일 주소는 대소문자를 구분하지 않는다
        return value.strip()


def _bearer_token(headers: Mapping[str, str]) -> str:
    scheme, _, token = headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise AuthError("Authorization: Bearer 토큰이 없습니다")
    return token.strip()
