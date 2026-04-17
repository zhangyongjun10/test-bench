"""Reusable helpers for concurrent load-test batch analysis."""

from __future__ import annotations

import json
from collections import deque
from html import escape
from typing import Any


RECENT_BATCHES: deque[dict[str, Any]] = deque(maxlen=100)


def analyze_concurrency(executions: list[dict[str, Any]]) -> dict[str, Any]:
    successful = [item for item in executions if item.get("first_span_start_ms") is not None]
    client_concurrency = len(executions)
    if not successful:
        return {
            "client_concurrency": client_concurrency,
            "analysis_sample_count": 0,
            "sample_coverage_ratio": 0.0,
            "openclaw_actual_concurrency": 0,
            "queue_detected": None,
            "reason": "No successful traces with span start times were available.",
        }

    start_times = sorted(item["first_span_start_ms"] for item in successful)
    first_start = start_times[0]
    start_offsets_ms = [value - first_start for value in start_times]
    queue_threshold_ms = 5000
    immediate_starts = sum(1 for offset in start_offsets_ms if offset <= queue_threshold_ms)
    queue_detected = any(offset > queue_threshold_ms for offset in start_offsets_ms)

    return {
        "client_concurrency": client_concurrency,
        "analysis_sample_count": len(successful),
        "sample_coverage_ratio": len(successful) / client_concurrency if client_concurrency else 0.0,
        "openclaw_actual_concurrency": immediate_starts,
        "queue_detected": queue_detected,
        "queue_threshold_ms": queue_threshold_ms,
        "first_span_start_offsets_ms": start_offsets_ms,
        "max_start_gap_ms": max(start_offsets_ms) if start_offsets_ms else 0,
    }


def calculate_model_call_metrics(trace_data: dict[str, Any] | None) -> tuple[float | None, int]:
    if not trace_data:
        return None, 0

    spans = trace_data.get("spans") or []
    llm_durations = [
        span.get("duration_ms")
        for span in spans
        if span.get("span_type") == "llm" and span.get("duration_ms") is not None
    ]
    if not llm_durations:
        return None, 0
    return float(sum(llm_durations)), len(llm_durations)


def remember_batch(batch_analysis: dict[str, Any]) -> None:
    RECENT_BATCHES.append(batch_analysis)


def get_recent_batches() -> list[dict[str, Any]]:
    return list(RECENT_BATCHES)


def render_batches_html() -> str:
    rows: list[str] = []
    for batch in list(RECENT_BATCHES)[::-1]:
        analysis = batch["analysis"]
        for execution in batch["executions"]:
            rows.append(
                "<tr>"
                f"<td>{escape(str(batch['batch_id']))}</td>"
                f"<td>{escape(str(execution.get('call_index')))}</td>"
                f"<td>{escape(str(execution.get('execution_id')))}</td>"
                f"<td>{escape(str(execution.get('trace_id')))}</td>"
                f"<td>{escape(str(execution.get('user_session')))}</td>"
                f"<td>{escape(str(execution.get('status')))}</td>"
                f"<td>{escape(str(execution.get('duration')))}</td>"
                f"<td>{escape(str(execution.get('model_call_time_ms')))}</td>"
                f"<td>{escape(str(analysis.get('openclaw_actual_concurrency')))}</td>"
                f"<td>{escape(str(analysis.get('queue_detected')))}</td>"
                f"<td>{escape(json.dumps(analysis.get('first_span_start_offsets_ms'), ensure_ascii=False))}</td>"
                f"<td>{escape(str(execution.get('analysis_missing_reason')))}</td>"
                "</tr>"
            )

    table_rows = "\n".join(rows) or (
        "<tr><td colspan='12'>No analyzed batches yet. Run load first, then refresh this page.</td></tr>"
    )
    return f"""
    <html>
      <head>
        <title>Locust Batch Analysis</title>
        <style>
          body {{ font-family: Arial, sans-serif; margin: 24px; }}
          table {{ border-collapse: collapse; width: 100%; font-size: 12px; }}
          th, td {{ border: 1px solid #ddd; padding: 8px; vertical-align: top; }}
          th {{ background: #f5f5f5; position: sticky; top: 0; }}
          .meta {{ margin-bottom: 16px; color: #444; }}
        </style>
      </head>
      <body>
        <h2>Batch Analysis</h2>
        <div class="meta">
          Open <a href="/stats/requests">Locust Stats</a> |
          Refresh this page after batches complete to inspect batch_id / trace_id / user_session / queue state.
        </div>
        <table>
          <thead>
            <tr>
              <th>batch_id</th>
              <th>call_index</th>
              <th>execution_id</th>
              <th>trace_id</th>
              <th>user_session</th>
              <th>status</th>
              <th>duration_s</th>
              <th>model_call_ms</th>
              <th>actual_concurrency</th>
              <th>queue_detected</th>
              <th>start_offsets_ms</th>
              <th>missing_reason</th>
            </tr>
          </thead>
          <tbody>{table_rows}</tbody>
        </table>
      </body>
    </html>
    """
