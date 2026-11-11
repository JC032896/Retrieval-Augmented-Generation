"""증분 수집: 문서를 수집한 코퍼스 폴더와 마지막 동기화 시각

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-11

- corpus_root: 문서를 수집한 코퍼스 폴더 (절대 경로, / 구분). `--prune`은 이번 실행에 넘긴
  폴더의 문서만 지우고, 다른 폴더에서 수집한 문서는 건드리지 않는다. 0006 이전 행은 비어 있고,
  같은 source_path로 다시 수집하면 채워진다. 비어 있는 행은 어느 폴더의 것도 아니라서
  --prune으로 지우지 않는다.
- synced_at: 수집 명령이 이 문서를 원문과 마지막으로 맞춰 본 시각 (/health의 마지막 수집 시각).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("corpus_root", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("documents", "synced_at")
    op.drop_column("documents", "corpus_root")
