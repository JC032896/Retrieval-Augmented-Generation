"""요청에서 확인한 신원. auth.py와 oidc.py가 함께 쓴다 (서로 import하지 않게 따로 둔다)."""

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class Identity:
    """로그인 id와 로그인 시스템이 알려 준 그룹.

    그룹은 관리 화면의 역할(중앙 관리자, 부서 문서 담당, 감사 담당)을 정하는 데만 쓴다
    (api/roles.py). 문서 열람 권한은 그룹이 아니라 DB users 테이블의 부서·역할·등급으로 정한다.
    """

    login: str
    groups: frozenset[str] = frozenset()


def clean_groups(values: Iterable[object]) -> frozenset[str]:
    """문자열만 남기고 앞뒤 공백을 지운다. 빈 값은 버린다."""
    return frozenset(v.strip() for v in values if isinstance(v, str) and v.strip())
