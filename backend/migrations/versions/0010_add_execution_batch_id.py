"""add execution batch_id

Revision ID: 0010_add_execution_batch_id
Revises: 0009
Create Date: 2026-04-14
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0010_add_execution_batch_id"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("execution_jobs", sa.Column("batch_id", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("execution_jobs", "batch_id")
