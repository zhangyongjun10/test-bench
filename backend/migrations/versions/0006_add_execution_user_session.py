"""Add execution-level user session.

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-10
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "execution_jobs",
        sa.Column("user_session", sa.String(length=255), nullable=True),
    )
    op.execute(
        "UPDATE execution_jobs "
        "SET user_session = 'exec_' || replace(id::text, '-', '') "
        "WHERE user_session IS NULL OR user_session = ''"
    )
    op.alter_column("execution_jobs", "user_session", nullable=False)


def downgrade() -> None:
    op.drop_column("execution_jobs", "user_session")
