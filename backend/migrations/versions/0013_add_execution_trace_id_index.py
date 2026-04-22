"""add execution trace id index

Revision ID: 0013_add_execution_trace_index
Revises: 0012_add_execution_batches
Create Date: 2026-04-22
"""

from typing import Sequence, Union

from alembic import op


# 当前迁移版本号；保持在 32 个字符以内，兼容 Alembic 默认 version_num 长度限制。
revision: str = "0013_add_execution_trace_index"
# 上一迁移版本号；确保先完成 execution_batches 相关结构，再补 trace_id 查询索引。
down_revision: Union[str, None] = "0012_add_execution_batches"
# Alembic 分支标签；当前项目采用线性迁移，不使用分支。
branch_labels: Union[str, Sequence[str], None] = None
# Alembic 依赖版本；当前迁移不依赖额外分支。
depends_on: Union[str, Sequence[str], None] = None


# 升级数据库结构；为 execution_jobs.trace_id 建立普通索引，降低列表按 trace_id 精确筛选时的扫描成本。
def upgrade() -> None:
    op.create_index("ix_execution_jobs_trace_id", "execution_jobs", ["trace_id"], unique=False)


# 回滚数据库结构；删除 execution_jobs.trace_id 索引，恢复到未优化 trace_id 查询的状态。
def downgrade() -> None:
    op.drop_index("ix_execution_jobs_trace_id", table_name="execution_jobs")
