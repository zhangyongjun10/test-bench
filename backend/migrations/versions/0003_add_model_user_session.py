"""add user_session to agent

Revision ID: 0003
Revises: 0002
Create Date: 2026-03-21

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0003'
down_revision: Union[str, None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add user_session column to agents table
    op.add_column('agents', sa.Column('user_session', sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column('agents', 'user_session')
