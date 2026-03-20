"""initial

Revision ID: 0001
Revises:
Create Date: 2026-03-20

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0001_initial'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 创建 agents 表
    op.create_table(
        'agents',
        sa.Column('id', sa.UUID(), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('base_url', sa.String(length=2048), nullable=False),
        sa.Column('api_key_encrypted', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_agents_deleted_at', 'agents', ['deleted_at'], unique=False)
    op.create_index('idx_agents_name', 'agents', ['name'], unique=False)

    # 创建 llm_models 表
    op.create_table(
        'llm_models',
        sa.Column('id', sa.UUID(), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('provider', sa.String(length=50), nullable=False),
        sa.Column('model_id', sa.String(length=255), nullable=False),
        sa.Column('base_url', sa.String(length=2048), nullable=True),
        sa.Column('api_key_encrypted', sa.Text(), nullable=False),
        sa.Column('temperature', sa.Double(), nullable=False, server_default=sa.text('0.0')),
        sa.Column('max_tokens', sa.Integer(), nullable=False, server_default=sa.text('1024')),
        sa.Column('is_default', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_llm_models_deleted_at', 'llm_models', ['deleted_at'], unique=False)
    # Unique partial index: only one default model can exist
    op.create_index(
        'idx_llm_models_is_default',
        'llm_models',
        ['is_default'],
        unique=True,
        postgresql_where=sa.text('is_default = TRUE')
    )

    # 创建 scenarios 表
    op.create_table(
        'scenarios',
        sa.Column('id', sa.UUID(), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('agent_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('prompt', sa.Text(), nullable=False),
        sa.Column('baseline_result', sa.Text(), nullable=True),
        sa.Column('compare_result', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('compare_process', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ),
    )
    op.create_index('idx_scenarios_deleted_at', 'scenarios', ['deleted_at'], unique=False)
    op.create_index('idx_scenarios_agent_id', 'scenarios', ['agent_id'], unique=False)
    op.create_index('idx_scenarios_name', 'scenarios', ['name'], unique=False)

    # 创建 execution_jobs 表
    op.create_table(
        'execution_jobs',
        sa.Column('id', sa.UUID(), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('agent_id', sa.UUID(), nullable=False),
        sa.Column('scenario_id', sa.UUID(), nullable=False),
        sa.Column('llm_model_id', sa.UUID(), nullable=True),
        sa.Column('trace_id', sa.String(length=255), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column('original_request', sa.Text(), nullable=True),
        sa.Column('original_response', sa.Text(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('comparison_score', sa.Double(), nullable=True),
        sa.Column('comparison_passed', sa.Boolean(), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ),
        sa.ForeignKeyConstraint(['scenario_id'], ['scenarios.id'], ),
        sa.ForeignKeyConstraint(['llm_model_id'], ['llm_models.id'], ),
    )
    op.create_index('idx_execution_jobs_agent_id', 'execution_jobs', ['agent_id'], unique=False)
    op.create_index('idx_execution_jobs_scenario_id', 'execution_jobs', ['scenario_id'], unique=False)
    op.create_index('idx_execution_jobs_status', 'execution_jobs', ['status'], unique=False)
    op.create_index('idx_execution_jobs_created_at', 'execution_jobs', ['created_at'], unique=False)

    # 创建 system_clickhouse_config 表
    op.create_table(
        'system_clickhouse_config',
        sa.Column('id', sa.Integer(), nullable=False, server_default=sa.text('1')),
        sa.Column('endpoint', sa.String(length=2048), nullable=False),
        sa.Column('database', sa.String(length=255), nullable=False),
        sa.Column('username', sa.String(length=255), nullable=True),
        sa.Column('password_encrypted', sa.Text(), nullable=True),
        sa.Column('source_type', sa.String(length=50), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('system_clickhouse_config')
    op.drop_table('execution_jobs')
    op.drop_table('scenarios')
    op.drop_table('llm_models')
    op.drop_table('agents')
