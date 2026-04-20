"""add execution batches

Revision ID: 0012_add_execution_batches
Revises: 0011_drop_agent_user_session
Create Date: 2026-04-20
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# 当前迁移版本号；用于新增并发执行批次表，持久化批次级请求数量和失败统计。
revision: str = "0012_add_execution_batches"
# 上一迁移版本号；确保先完成 Agent Session 下沉到 execution 后再新增批次状态表。
down_revision: Union[str, None] = "0011_drop_agent_user_session"
# Alembic 分支标签；当前项目使用线性迁移，不设置分支。
branch_labels: Union[str, Sequence[str], None] = None
# Alembic 依赖版本；当前迁移不依赖额外分支。
depends_on: Union[str, Sequence[str], None] = None


# 升级数据库结构；创建 execution_batches 表保存并发批次级状态，避免准备阶段失败无法查询。
def upgrade() -> None:
    op.create_table(
        "execution_batches",
        sa.Column("id", sa.String(length=255), primary_key=True),
        sa.Column("requested_concurrency", sa.Integer(), nullable=False),
        sa.Column("prepared_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("started_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("prepare_failed_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("start_mark_failed_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="queued"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("agent_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


# 回滚数据库结构；删除并发批次表，回退到仅依赖 execution.batch_id 的历史行为。
def downgrade() -> None:
    op.drop_table("execution_batches")
