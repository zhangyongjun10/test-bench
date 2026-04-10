"""Add llm-only comparison fields.

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-09
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


DEFAULT_COMPARISON_PROMPT = """请判断下面【基线输出】和【实际输出】的核心语义是否一致：

基线输出:
{{baseline_result}}

实际输出:
{{actual_result}}

要求：
1. 核心语义一致（回答结论相同、解决同一个问题、满足相同需求）时返回 consistent = true
2. 核心语义不一致时返回 consistent = false
3. 简要说明判断原因
4. 只输出 JSON：{"consistent": boolean, "reason": string}
"""


def upgrade() -> None:
    op.add_column(
        "scenarios",
        sa.Column("llm_count_min", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "scenarios",
        sa.Column("llm_count_max", sa.Integer(), nullable=False, server_default=sa.text("999")),
    )
    op.add_column(
        "llm_models",
        sa.Column("comparison_prompt", sa.Text(), nullable=True),
    )

    connection = op.get_bind()
    connection.execute(
        sa.text(
            "UPDATE llm_models "
            "SET comparison_prompt = :prompt "
            "WHERE comparison_prompt IS NULL OR comparison_prompt = ''"
        ),
        {"prompt": DEFAULT_COMPARISON_PROMPT},
    )


def downgrade() -> None:
    op.drop_column("llm_models", "comparison_prompt")
    op.drop_column("scenarios", "llm_count_max")
    op.drop_column("scenarios", "llm_count_min")
