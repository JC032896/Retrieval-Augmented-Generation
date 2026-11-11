"""LLM 사용 한도: 감사 기록에서 오늘 사용량만 집계해 주는 함수

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-11

- 앱 계정(rag_app)은 audit_log를 읽을 수 없다 (질문·답변 원문 보호, 0005). 한도 판단에는 사용자의
  질문 수와 전사 비용 합계만 필요하므로, 그 두 숫자만 돌려주는 함수를 만들고 실행 권한만 준다.
- SECURITY DEFINER: 함수는 소유자(마이그레이션 계정) 권한으로 audit_log를 읽는다. 다른 스키마의
  같은 이름 객체로 바꿔치기하지 못하게 search_path를 고정한다.
- 집계에는 0004의 인덱스 ix_audit_log_user_login(user_login, created_at)과
  ix_audit_log_created_at을 쓴다.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "rag_app"
SIGNATURE = "llm_usage_since(text, timestamptz)"


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION llm_usage_since(p_login text, p_since timestamptz)
        RETURNS TABLE (user_requests bigint, total_cost_usd double precision)
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
            SELECT
                (SELECT count(*) FROM public.audit_log
                 WHERE user_login = p_login AND created_at >= p_since),
                (SELECT coalesce(sum(cost_usd), 0) FROM public.audit_log
                 WHERE created_at >= p_since)
        $$
        """
    )
    op.execute(f"REVOKE ALL ON FUNCTION {SIGNATURE} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {SIGNATURE} TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"DROP FUNCTION {SIGNATURE}")
