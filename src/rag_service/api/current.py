"""요청한 사용자를 확인한다. 질문 API(ask.py)와 관리 API(admin.py)가 함께 쓴다.

토큰(또는 개발용 헤더)으로 신원을 확인하고, 권한 속성은 DB users 테이블에서 읽는다 (auth.py).
실패는 운영 로그에 남기고 HTTP 오류로 바꾼다: 확인 불가 401, 확인 수단 장애 503.
"""

import logging
from dataclasses import dataclass

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session, sessionmaker

from rag_service.api.auth import (
    Authenticator,
    AuthError,
    AuthUnavailableError,
    CurrentUser,
    Identity,
    load_user,
)
from rag_service.logs import log_event

# 401 응답에 붙이는 표준 머리글 (토큰을 Bearer 방식으로 보내라는 뜻)
BEARER_CHALLENGE = {"WWW-Authenticate": "Bearer"}


@dataclass(frozen=True)
class SignedIn:
    user: CurrentUser  # DB에 등록된 권한 속성
    identity: Identity  # 토큰이 알려 준 로그인 id와 그룹


def client_ip(request: Request) -> str | None:
    # 프록시 뒤에서는 uvicorn --proxy-headers --forwarded-allow-ips로 실제 주소를 받는다
    return request.client.host if request.client else None


def authenticate(
    request: Request,
    authenticator: Authenticator | None,
    sessions: sessionmaker[Session],
    logger: logging.Logger,
) -> SignedIn:
    """logger: 실패를 남길 로거. 요청을 받은 API의 로거를 넘겨 어느 API에서 실패했는지 남긴다."""
    if authenticator is None:
        raise HTTPException(503, "사용자 확인 방식이 설정되지 않았습니다 (AUTH_MODE)")
    ip = client_ip(request)
    try:
        identity = authenticator.identify(request.headers)
    except AuthError as error:
        log_event(logger, "auth_failed", level=logging.WARNING, reason=str(error), client_ip=ip)
        raise HTTPException(401, str(error), headers=BEARER_CHALLENGE) from error
    except AuthUnavailableError as error:
        logger.exception("사용자 확인 수단이 동작하지 않음")
        raise HTTPException(503, str(error)) from error
    with sessions() as session:
        user = load_user(session, identity.login)
    if user is None:
        log_event(
            logger,
            "auth_failed",
            level=logging.WARNING,
            reason="unregistered",
            login=identity.login,
            client_ip=ip,
        )
        raise HTTPException(401, "등록되지 않은 사용자입니다", headers=BEARER_CHALLENGE)
    return SignedIn(user, identity)
