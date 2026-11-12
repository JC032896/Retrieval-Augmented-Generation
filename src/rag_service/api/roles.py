"""관리 화면 역할. 회사 로그인 시스템(OIDC) 토큰의 그룹 값으로 정한다.

- admin(중앙 관리자): 설치 상태, 사용량 숫자, 전체 문서와 권한, 사용자 목록
- doc_manager(부서 문서 담당): 자기 부서 문서만 올리고 바꾸고 권한을 정한다 (부서는 DB users에서)
- auditor(감사 담당): 감사 기록(질문·답변 원문 포함)을 본다

역할은 서로 포함하지 않는다. 중앙 관리자라도 감사 담당 그룹에 없으면 감사 기록 원문을 볼 수 없다
(운영 관리와 감사 조사를 나눈다, PRODUCT.md "역할을 섞지 않는다").
한 사람이 두 그룹에 있으면 두 역할을 모두 갖는다.
그룹 이름은 회사 로그인 시스템에 맞춰 설정으로 바꾼다 (ADMIN_GROUP 등).
"""

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum


class AdminRole(StrEnum):
    ADMIN = "admin"
    DOC_MANAGER = "doc_manager"
    AUDITOR = "auditor"


@dataclass(frozen=True)
class RoleGroups:
    """역할마다 대응하는 로그인 시스템 그룹 이름 (Entra ID는 그룹 객체 id를 넣기도 한다)."""

    admin: str = "rag-admin"
    doc_manager: str = "rag-doc-manager"
    auditor: str = "rag-auditor"

    def roles(self, groups: Iterable[str]) -> frozenset[AdminRole]:
        names = set(groups)
        mapping = {
            AdminRole.ADMIN: self.admin,
            AdminRole.DOC_MANAGER: self.doc_manager,
            AdminRole.AUDITOR: self.auditor,
        }
        return frozenset(role for role, group in mapping.items() if group in names)
