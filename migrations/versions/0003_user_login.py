"""users.login: 로그인 id (API가 요청한 사용자를 찾는 키)

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("login", sa.Text(), nullable=True))
    # 이미 있던 행은 id로 임시 로그인을 만든다. 다음 수집(org.yaml 동기화) 때 정리된다
    op.execute("UPDATE users SET login = 'legacy-' || id WHERE login IS NULL")
    op.alter_column("users", "login", nullable=False)
    op.create_unique_constraint("uq_users_login", "users", ["login"])


def downgrade() -> None:
    op.drop_constraint("uq_users_login", "users", type_="unique")
    op.drop_column("users", "login")
