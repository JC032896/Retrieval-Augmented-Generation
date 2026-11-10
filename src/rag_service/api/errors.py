"""사용자 확인 오류. auth.py와 oidc.py가 함께 쓴다 (서로 import하지 않게 따로 둔다)."""


class AuthError(Exception):
    """요청에서 사용자를 확인할 수 없다 (HTTP 401)."""


class AuthUnavailableError(Exception):
    """사용자를 확인할 수단이 지금 동작하지 않는다. 예: 로그인 서버 연결 실패 (HTTP 503)."""
