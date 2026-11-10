"""요청한 사용자 확인.

신원(누구인가)과 권한 속성(부서, 역할, 보안 등급)을 나눈다.
- 신원: Authenticator가 요청에서 로그인 id를 꺼낸다. 운영은 회사 로그인 시스템이 발급한
  OIDC 토큰(oidc.py), 개발과 데모는 X-User-Id 헤더를 쓴다.
- 권한 속성: 항상 DB users 테이블에서 읽는다. 요청에 실려 온 값은 믿지 않으므로, 퇴사나 등급
  변경이 다음 요청부터 바로 반영되고, 등록되지 않은 사용자는 아무 문서도 보지 못한다.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from rag_service.api.errors import AuthError, AuthUnavailableError
from rag_service.api.oidc import OidcAuthenticator, OidcConfig
from rag_service.db.models import User

__all__ = ["AuthError", "AuthUnavailableError"]  # 오류는 errors.py에 있고 여기서 함께 내보낸다

AuthMode = Literal["disabled", "dev_header", "oidc"]
DEV_USER_HEADER = "X-User-Id"


@dataclass(frozen=True)
class CurrentUser:
    """요청한 사용자. retrieval.access.Viewer를 만족하므로 그대로 권한 필터에 넘긴다."""

    login: str
    name: str
    department: str
    role: str
    clearance_level: int


class Authenticator(Protocol):
    def login(self, headers: Mapping[str, str]) -> str:
        """요청 헤더에서 확인된 로그인 id를 돌려준다.

        확인할 수 없으면 AuthError, 확인 수단(로그인 서버 등)이 멈췄으면 AuthUnavailableError.
        """
        ...


class DevHeaderAuthenticator:
    """X-User-Id 헤더 값을 그대로 믿는다. 개발·데모 전용 (누구나 다른 사람 행세를 할 수 있다)."""

    def login(self, headers: Mapping[str, str]) -> str:
        value = headers.get(DEV_USER_HEADER, "").strip()
        if not value:
            raise AuthError(f"{DEV_USER_HEADER} 헤더가 없습니다")
        return value


def build_authenticator(mode: AuthMode, oidc: OidcConfig | None = None) -> Authenticator | None:
    """disabled면 None. 질문 API는 이때 요청을 받지 않는다."""
    if mode == "dev_header":
        return DevHeaderAuthenticator()
    if mode == "oidc":
        if oidc is None:
            raise ValueError("AUTH_MODE=oidc에는 OIDC_ISSUER와 OIDC_AUDIENCE가 필요합니다")
        return OidcAuthenticator(oidc)
    return None


def load_user(session: Session, login: str) -> CurrentUser | None:
    user = session.scalars(select(User).where(User.login == login)).one_or_none()
    if user is None:
        return None
    return CurrentUser(user.login, user.name, user.department, user.role, user.clearance_level)
