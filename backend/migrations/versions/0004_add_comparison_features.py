"""Add comparison features

Revision ID: 0004
Revises: 0003
Create Date: 2026-03-27

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision: str = '0004'
down_revision: Union[str, None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create comparison_results table
    op.create_table(
        'comparison_results',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('execution_id', UUID(as_uuid=True), sa.ForeignKey('execution_jobs.id'), nullable=False),
        sa.Column('scenario_id', UUID(as_uuid=True), sa.ForeignKey('scenarios.id'), nullable=False),
        sa.Column('trace_id', sa.String(length=255), nullable=True),
        sa.Column('process_score', sa.Double(), nullable=True),
        sa.Column('result_score', sa.Double(), nullable=True),
        sa.Column('overall_passed', sa.Boolean(), nullable=True),
        sa.Column('details_json', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=False, server_default=sa.text("'pending'")),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('retry_count', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    )

    # Create indexes
    op.create_index('ix_comparison_results_execution_id', 'comparison_results', ['execution_id'])
    op.create_index('ix_comparison_results_scenario_id', 'comparison_results', ['scenario_id'])

    # Add columns to scenarios table
    op.add_column('scenarios', sa.Column('baseline_tool_calls', sa.Text(), nullable=True))
    op.add_column('scenarios', sa.Column('process_threshold', sa.Double(), nullable=False, server_default=sa.text('60.0')))
    op.add_column('scenarios', sa.Column('result_threshold', sa.Double(), nullable=False, server_default=sa.text('60.0')))
    op.add_column('scenarios', sa.Column('tool_count_tolerance', sa.Integer(), nullable=False, server_default=sa.text('0')))
    op.add_column('scenarios', sa.Column('compare_enabled', sa.Boolean(), nullable=False, server_default=sa.text('true')))
    op.add_column('scenarios', sa.Column('enable_llm_verification', sa.Boolean(), nullable=False, server_default=sa.text('true')))


def downgrade() -> None:
    # Drop columns from scenarios table
    op.drop_column('scenarios', 'enable_llm_verification')
    op.drop_column('scenarios', 'compare_enabled')
    op.drop_column('scenarios', 'tool_count_tolerance')
    op.drop_column('scenarios', 'result_threshold')
    op.drop_column('scenarios', 'process_threshold')
    op.drop_column('scenarios', 'baseline_tool_calls')

    # Drop comparison_results table
    op.drop_table('comparison_results')
