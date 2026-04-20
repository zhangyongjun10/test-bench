"""drop agent user_session

Revision ID: 0011_drop_agent_user_session
Revises: 0010_add_execution_batch_id
Create Date: 2026-04-20
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# 当前迁移版本号；用于从数据库层彻底移除 Agent 级 Session 字段。
revision: str = "0011_drop_agent_user_session"
# 上一个迁移版本；确保先完成 execution 级 batch 字段后再清理 Agent Session。
down_revision: Union[str, None] = "0010_add_execution_batch_id"
# Alembic 分支标签；当前项目使用线性迁移，不设置分支。
branch_labels: Union[str, Sequence[str], None] = None
# Alembic 依赖版本；当前迁移不依赖额外分支。
depends_on: Union[str, Sequence[str], None] = None


# 升级数据库结构，删除已废弃的 agents.user_session，运行时会话统一由 execution.user_session 承载。
def upgrade() -> None:
    op.drop_column("agents", "user_session")


# 回滚数据库结构时恢复 agents.user_session，仅用于历史版本兼容，不建议新代码继续使用。
def downgrade() -> None:
    op.add_column("agents", sa.Column("user_session", sa.String(length=255), nullable=True))
