"""Prometheus 指标定义"""

from prometheus_client import Counter, Histogram

# 执行计数
EXECUTIONS_TOTAL = Counter(
    "testbench_executions_total",
    "Total number of test executions",
    ["status"]
)

# 执行耗时分布
EXECUTION_DURATION_SECONDS = Histogram(
    "testbench_execution_duration_seconds",
    "Execution duration in seconds"
)

# 比对分数分布
COMPARISON_SCORE = Histogram(
    "testbench_comparison_score",
    "Distribution of comparison scores"
)

# ClickHouse 查询耗时
CLICKHOUSE_QUERY_DURATION_SECONDS = Histogram(
    "testbench_clickhouse_query_duration_seconds",
    "ClickHouse query duration in seconds"
)

# LLM 比对耗时
LLM_COMPARE_DURATION_SECONDS = Histogram(
    "testbench_llm_compare_duration_seconds",
    "LLM comparison duration in seconds"
)


def increment_executions_total(status: str) -> None:
    """增加执行计数"""
    EXECUTIONS_TOTAL.labels(status=status).inc()


def observe_execution_duration(duration: float) -> None:
    """记录执行耗时"""
    EXECUTION_DURATION_SECONDS.observe(duration)


def observe_comparison_score(score: float) -> None:
    """记录比对分数"""
    COMPARISON_SCORE.observe(score)


def observe_clickhouse_query_duration(duration: float) -> None:
    """记录 ClickHouse 查询耗时"""
    CLICKHOUSE_QUERY_DURATION_SECONDS.observe(duration)


def observe_llm_compare_duration(duration: float) -> None:
    """记录 LLM 比对耗时"""
    LLM_COMPARE_DURATION_SECONDS.observe(duration)
