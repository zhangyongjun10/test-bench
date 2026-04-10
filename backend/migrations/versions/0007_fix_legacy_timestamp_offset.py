"""Fix legacy timestamp offset.

Revision ID: 0007
Revises: 0006
Create Date: 2026-04-10
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Older code wrote naive datetime.utcnow() into timezone-aware PostgreSQL
    # columns. In the current deployment that stored values 8 hours earlier than
    # intended, so normalize existing rows once and keep new writes UTC-aware.
    for table in ("agents", "llm_models", "scenarios", "comparison_results"):
        op.execute(
            f"""
            UPDATE {table}
            SET
                created_at = created_at + INTERVAL '8 hours',
                updated_at = updated_at + INTERVAL '8 hours'
            """
        )

    op.execute(
        """
        UPDATE comparison_results
        SET completed_at = completed_at + INTERVAL '8 hours'
        WHERE completed_at IS NOT NULL
        """
    )

    op.execute(
        """
        UPDATE execution_jobs
        SET created_at = created_at + INTERVAL '8 hours'
        WHERE started_at IS NOT NULL
          AND started_at - created_at BETWEEN INTERVAL '7 hours 30 minutes' AND INTERVAL '8 hours 30 minutes'
        """
    )

    op.execute(
        """
        UPDATE system_clickhouse_config
        SET updated_at = updated_at + INTERVAL '8 hours'
        """
    )


def downgrade() -> None:
    for table in ("agents", "llm_models", "scenarios", "comparison_results"):
        op.execute(
            f"""
            UPDATE {table}
            SET
                created_at = created_at - INTERVAL '8 hours',
                updated_at = updated_at - INTERVAL '8 hours'
            """
        )

    op.execute(
        """
        UPDATE comparison_results
        SET completed_at = completed_at - INTERVAL '8 hours'
        WHERE completed_at IS NOT NULL
        """
    )

    op.execute(
        """
        UPDATE execution_jobs
        SET created_at = created_at - INTERVAL '8 hours'
        """
    )

    op.execute(
        """
        UPDATE system_clickhouse_config
        SET updated_at = updated_at - INTERVAL '8 hours'
        """
    )
