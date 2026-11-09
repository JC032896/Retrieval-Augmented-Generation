"""검색 SQL에 붙이는 권한 필터. corpus.can_view와 같은 규칙을 SQL로 쓴 것이다.

(부서가 allowed_departments에 있음 OR 역할이 allowed_roles에 있음) AND security_level <= 열람 등급

검색한 뒤에 걸러내지 않고 WHERE 절에서 먼저 걸러낸다. 그래야 권한 없는 조각이 상위 k개 자리를
차지해서 결과가 줄어들거나, 점수 계산에 섞이는 일이 없다.
"""

from typing import Protocol

from sqlalchemy import ColumnElement, and_, or_, select

from rag_service.db.models import Chunk, Document


class Viewer(Protocol):
    @property
    def department(self) -> str: ...

    @property
    def role(self) -> str: ...

    @property
    def clearance_level(self) -> int: ...


def access_filter(viewer: Viewer) -> ColumnElement[bool]:
    return and_(
        or_(
            Chunk.allowed_departments.contains([viewer.department]),
            Chunk.allowed_roles.contains([viewer.role]),
        ),
        Chunk.security_level <= viewer.clearance_level,
    )


def scope_filter(viewer: Viewer, *, current_only: bool) -> ColumnElement[bool]:
    """권한 필터에, current_only면 현행 문서 조건을 더한다.

    문서 수명은 권한이 아니라 "지금 유효한 문서인가"의 문제다. 폐지 문서도 권한이 있으면 볼 수
    있지만, 기본 검색에서는 후보에서 빼서 구버전이 1위를 차지하지 않게 한다.
    """
    if not current_only:
        return access_filter(viewer)
    current = select(Document.id).where(Document.status == "current")
    return and_(access_filter(viewer), Chunk.document_id.in_(current))
