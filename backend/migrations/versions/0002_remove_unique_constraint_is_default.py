"""remove unique constraint on is_default

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-21

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0002'
down_revision: Union[str, None] = '0001_initial'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Remove the unique partial index that causes transaction issue
    op.drop_index('idx_llm_models_is_default', table_name='llm_models')
    # Create a normal non-unique index instead
    op.create_index(
        'idx_llm_models_is_default',
        'llm_models',
        ['is_default'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index('idx_llm_models_is_default', table_name='llm_models')
    op.create_index(
        'idx_llm_models_is_default',
        'llm_models',
        ['is_default'],
        unique=True,
        postgresql_where=sa.text('is_default = TRUE'),
    )
