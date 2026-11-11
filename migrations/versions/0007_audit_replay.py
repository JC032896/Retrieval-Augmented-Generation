"""감사 재현: 프롬프트 템플릿 버전, LLM 파라미터, 요청에 넣은 조각 목록, 요청 해시

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-11

- 요청 본문 전체가 아니라 재현에 필요한 요소만 남긴다. 조각 본문은 chunk_snapshots에 내용 해시당
  한 번 저장하고, 감사 기록에는 순서대로 (chunk_key, content_sha256, 제목, 섹션, 페이지)만 둔다.
- request_sha256은 LLM에 보낸 요청(모델·파라미터, 시스템 프롬프트, 사용자 메시지)의 해시다.
  scripts/replay.py가 감사 기록과 스냅샷으로 요청을 다시 만들어 이 값과 비교한다.
- 0007 이전 기록은 모두 비어 있다 (재현할 수 없음).
- 권한: rag_app은 audit_log에 테이블 단위 INSERT 권한이 있어 새 컬럼에도 쓸 수 있다.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("audit_log", sa.Column("prompt_template_version", sa.Text(), nullable=True))
    op.add_column("audit_log", sa.Column("model_params", JSONB(), nullable=True))
    op.add_column("audit_log", sa.Column("context_chunks", JSONB(), nullable=True))
    op.add_column("audit_log", sa.Column("request_sha256", sa.Text(), nullable=True))


def downgrade() -> None:
    for column in ("request_sha256", "context_chunks", "model_params", "prompt_template_version"):
        op.drop_column("audit_log", column)
