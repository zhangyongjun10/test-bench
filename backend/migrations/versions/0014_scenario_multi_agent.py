"""scenario multi agent refactor

Revision ID: 0014_scenario_multi_agent
Revises: 0013_add_execution_trace_index
Create Date: 2026-04-25
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# 当前迁移版本号，保持在线性迁移链中唯一。
revision: str = "0014_scenario_multi_agent"
# 上一版迁移号，确保先完成 execution trace 索引迁移再做 Case 多 Agent 改造。
down_revision: Union[str, None] = "0013_add_execution_trace_index"
# 当前项目使用线性迁移，不启用额外分支标签。
branch_labels: Union[str, Sequence[str], None] = None
# 本次迁移不依赖额外 Alembic 分支。
depends_on: Union[str, Sequence[str], None] = None


# 升级数据库结构：新增多对多关联表、合并重复 Case，并移除旧的单 agent_id 字段。
def upgrade() -> None:
    op.create_table(
        "scenario_agents",
        sa.Column("scenario_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["scenario_id"], ["scenarios.id"]),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"]),
        sa.PrimaryKeyConstraint("scenario_id", "agent_id"),
        sa.UniqueConstraint("scenario_id", "agent_id", name="uq_scenario_agents_scenario_id_agent_id"),
    )
    op.create_index("ix_scenario_agents_agent_id", "scenario_agents", ["agent_id"], unique=False)

    op.execute(
        """
        INSERT INTO scenario_agents (scenario_id, agent_id)
        SELECT id, agent_id
        FROM scenarios
        WHERE agent_id IS NOT NULL
        ON CONFLICT (scenario_id, agent_id) DO NOTHING
        """
    )

    op.execute(
        """
        WITH ranked AS (
            SELECT
                id,
                FIRST_VALUE(id) OVER (
                    PARTITION BY
                        name,
                        COALESCE(description, ''),
                        prompt,
                        COALESCE(baseline_result, ''),
                        llm_count_min,
                        llm_count_max,
                        compare_enabled
                    ORDER BY created_at ASC, id ASC
                ) AS keep_id
            FROM scenarios
            WHERE deleted_at IS NULL
        ),
        duplicates AS (
            SELECT id AS duplicate_id, keep_id
            FROM ranked
            WHERE id <> keep_id
        )
        INSERT INTO scenario_agents (scenario_id, agent_id)
        SELECT d.keep_id, sa.agent_id
        FROM duplicates d
        JOIN scenario_agents sa ON sa.scenario_id = d.duplicate_id
        ON CONFLICT (scenario_id, agent_id) DO NOTHING
        """
    )

    for table_name in ["execution_jobs", "comparison_results", "replay_tasks"]:
        op.execute(
            f"""
            WITH ranked AS (
                SELECT
                    id,
                    FIRST_VALUE(id) OVER (
                        PARTITION BY
                            name,
                            COALESCE(description, ''),
                            prompt,
                            COALESCE(baseline_result, ''),
                            llm_count_min,
                            llm_count_max,
                            compare_enabled
                        ORDER BY created_at ASC, id ASC
                    ) AS keep_id
                FROM scenarios
                WHERE deleted_at IS NULL
            ),
            duplicates AS (
                SELECT id AS duplicate_id, keep_id
                FROM ranked
                WHERE id <> keep_id
            )
            UPDATE {table_name} AS target
            SET scenario_id = duplicates.keep_id
            FROM duplicates
            WHERE target.scenario_id = duplicates.duplicate_id
            """
        )

    op.execute(
        """
        WITH ranked AS (
            SELECT
                id,
                FIRST_VALUE(id) OVER (
                    PARTITION BY
                        name,
                        COALESCE(description, ''),
                        prompt,
                        COALESCE(baseline_result, ''),
                        llm_count_min,
                        llm_count_max,
                        compare_enabled
                    ORDER BY created_at ASC, id ASC
                ) AS keep_id
            FROM scenarios
            WHERE deleted_at IS NULL
        ),
        duplicates AS (
            SELECT id AS duplicate_id, keep_id
            FROM ranked
            WHERE id <> keep_id
        )
        DELETE FROM scenario_agents AS target
        USING duplicates
        WHERE target.scenario_id = duplicates.duplicate_id
        """
    )

    op.execute(
        """
        WITH ranked AS (
            SELECT
                id,
                FIRST_VALUE(id) OVER (
                    PARTITION BY
                        name,
                        COALESCE(description, ''),
                        prompt,
                        COALESCE(baseline_result, ''),
                        llm_count_min,
                        llm_count_max,
                        compare_enabled
                    ORDER BY created_at ASC, id ASC
                ) AS keep_id
            FROM scenarios
            WHERE deleted_at IS NULL
        ),
        duplicates AS (
            SELECT id AS duplicate_id, keep_id
            FROM ranked
            WHERE id <> keep_id
        )
        DELETE FROM scenarios AS target
        USING duplicates
        WHERE target.id = duplicates.duplicate_id
        """
    )

    op.drop_column("scenarios", "agent_id")


# 回滚数据库结构：恢复旧 agent_id 字段，并从关联表选取首个 Agent 回填。
def downgrade() -> None:
    op.add_column("scenarios", sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.execute(
        """
        UPDATE scenarios AS target
        SET agent_id = source.agent_id
        FROM (
            SELECT scenario_id, MIN(agent_id) AS agent_id
            FROM scenario_agents
            GROUP BY scenario_id
        ) AS source
        WHERE target.id = source.scenario_id
        """
    )
    op.alter_column("scenarios", "agent_id", nullable=False)
    op.drop_index("ix_scenario_agents_agent_id", table_name="scenario_agents")
    op.drop_table("scenario_agents")
