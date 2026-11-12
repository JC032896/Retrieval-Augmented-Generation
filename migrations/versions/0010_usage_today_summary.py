"""관리 화면 대시보드: 회사 전체의 질문 수·질문한 사람 수·비용 합계만 돌려주는 함수

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-12

- 앱 계정(rag_app)은 audit_log를 읽을 수 없다 (질문·답변 원문 보호, 0005).
  대시보드의 '오늘 질문'에는 숫자 세 개만 필요하므로 0008과 같은 방식
  (SECURITY DEFINER, search_path 고정, 실행 권한만)으로 집계 함수를 둔다.
  사용자별 숫자나 원문은 돌려주지 않는다.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0010"
down_revision: str | Sequence[str] | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "rag_app"
SIGNATURE = "llm_usage_summary_since(timestamptz)"


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION llm_usage_summary_since(p_since timestamptz)
        RETURNS TABLE (requests bigint, users bigint, total_cost_usd double precision)
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
            SELECT count(*), count(DISTINCT user_login), coalesce(sum(cost_usd), 0)
            FROM public.audit_log
            WHERE created_at >= p_since
        $$
        """
    )
    op.execute(f"REVOKE ALL ON FUNCTION {SIGNATURE} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {SIGNATURE} TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"DROP FUNCTION {SIGNATURE}")
