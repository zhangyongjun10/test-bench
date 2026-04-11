"""Add replay task support.

Revision ID: 0009
Revises: 0008
Create Date: 2026-04-10
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("execution_jobs", sa.Column("run_source", sa.String(length=50), nullable=True))
    op.add_column(
        "execution_jobs",
        sa.Column("parent_execution_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column("execution_jobs", sa.Column("request_snapshot_json", sa.Text(), nullable=True))
    op.execute("UPDATE execution_jobs SET run_source = 'normal' WHERE run_source IS NULL")
    op.alter_column("execution_jobs", "run_source", nullable=False)
    op.create_foreign_key(
        "execution_jobs_parent_execution_id_fkey",
        "execution_jobs",
        "execution_jobs",
        ["parent_execution_id"],
        ["id"],
    )
    op.create_index("ix_execution_jobs_parent_execution_id", "execution_jobs", ["parent_execution_id"])
    op.create_index("ix_execution_jobs_run_source", "execution_jobs", ["run_source"])

    op.create_table(
        "replay_tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("original_execution_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("replay_execution_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scenario_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("baseline_source", sa.String(length=50), nullable=False),
        sa.Column("baseline_snapshot_json", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("llm_model_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("comparison_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("overall_passed", sa.Boolean(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"]),
        sa.ForeignKeyConstraint(["comparison_id"], ["comparison_results.id"]),
        sa.ForeignKeyConstraint(["llm_model_id"], ["llm_models.id"]),
        sa.ForeignKeyConstraint(["original_execution_id"], ["execution_jobs.id"]),
        sa.ForeignKeyConstraint(["replay_execution_id"], ["execution_jobs.id"]),
        sa.ForeignKeyConstraint(["scenario_id"], ["scenarios.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index("ix_replay_tasks_agent_id", "replay_tasks", ["agent_id"])
    op.create_index("ix_replay_tasks_created_at", "replay_tasks", ["created_at"])
    op.create_index("ix_replay_tasks_idempotency_key", "replay_tasks", ["idempotency_key"])
    op.create_index("ix_replay_tasks_llm_model_id", "replay_tasks", ["llm_model_id"])
    op.create_index("ix_replay_tasks_original_execution_id", "replay_tasks", ["original_execution_id"])
    op.create_index("ix_replay_tasks_replay_execution_id", "replay_tasks", ["replay_execution_id"])
    op.create_index("ix_replay_tasks_scenario_id", "replay_tasks", ["scenario_id"])
    op.create_index("ix_replay_tasks_status", "replay_tasks", ["status"])

    op.add_column(
        "comparison_results",
        sa.Column("replay_task_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "comparison_results",
        sa.Column("source_type", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "comparison_results",
        sa.Column("baseline_source", sa.String(length=50), nullable=True),
    )
    op.execute("UPDATE comparison_results SET source_type = 'execution_auto' WHERE source_type IS NULL")
    op.alter_column("comparison_results", "source_type", nullable=False)
    op.create_foreign_key(
        "comparison_results_replay_task_id_fkey",
        "comparison_results",
        "replay_tasks",
        ["replay_task_id"],
        ["id"],
    )
    op.create_index("ix_comparison_results_replay_task_id", "comparison_results", ["replay_task_id"])
    op.create_index("ix_comparison_results_source_type", "comparison_results", ["source_type"])


def downgrade() -> None:
    op.drop_index("ix_comparison_results_source_type", table_name="comparison_results")
    op.drop_index("ix_comparison_results_replay_task_id", table_name="comparison_results")
    op.drop_constraint("comparison_results_replay_task_id_fkey", "comparison_results", type_="foreignkey")
    op.drop_column("comparison_results", "baseline_source")
    op.drop_column("comparison_results", "source_type")
    op.drop_column("comparison_results", "replay_task_id")

    op.drop_index("ix_replay_tasks_status", table_name="replay_tasks")
    op.drop_index("ix_replay_tasks_scenario_id", table_name="replay_tasks")
    op.drop_index("ix_replay_tasks_replay_execution_id", table_name="replay_tasks")
    op.drop_index("ix_replay_tasks_original_execution_id", table_name="replay_tasks")
    op.drop_index("ix_replay_tasks_llm_model_id", table_name="replay_tasks")
    op.drop_index("ix_replay_tasks_idempotency_key", table_name="replay_tasks")
    op.drop_index("ix_replay_tasks_created_at", table_name="replay_tasks")
    op.drop_index("ix_replay_tasks_agent_id", table_name="replay_tasks")
    op.drop_table("replay_tasks")

    op.drop_index("ix_execution_jobs_run_source", table_name="execution_jobs")
    op.drop_index("ix_execution_jobs_parent_execution_id", table_name="execution_jobs")
    op.drop_constraint("execution_jobs_parent_execution_id_fkey", "execution_jobs", type_="foreignkey")
    op.drop_column("execution_jobs", "request_snapshot_json")
    op.drop_column("execution_jobs", "parent_execution_id")
    op.drop_column("execution_jobs", "run_source")
