"""Add comparison LLM model reference.

Revision ID: 0008
Revises: 0007
Create Date: 2026-04-10
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "comparison_results",
        sa.Column("llm_model_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "ix_comparison_results_llm_model_id",
        "comparison_results",
        ["llm_model_id"],
    )
    op.create_foreign_key(
        "comparison_results_llm_model_id_fkey",
        "comparison_results",
        "llm_models",
        ["llm_model_id"],
        ["id"],
    )
    op.execute(
        """
        UPDATE comparison_results AS comparison
        SET llm_model_id = execution.llm_model_id
        FROM execution_jobs AS execution
        WHERE comparison.execution_id = execution.id
          AND comparison.llm_model_id IS NULL
        """
    )


def downgrade() -> None:
    op.drop_constraint(
        "comparison_results_llm_model_id_fkey",
        "comparison_results",
        type_="foreignkey",
    )
    op.drop_index("ix_comparison_results_llm_model_id", table_name="comparison_results")
    op.drop_column("comparison_results", "llm_model_id")
