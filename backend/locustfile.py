"""Standard Locust entrypoint for TestBench concurrent execution load tests."""

from __future__ import annotations

import json
import time
from typing import Any

from locust import HttpUser, constant, events, task

from app.config import settings
from app.services.loadtest_analysis import (
    analyze_concurrency,
    calculate_model_call_metrics,
    remember_batch,
    render_batches_html,
)


def get_default_host() -> str:
    host = settings.host or "127.0.0.1"
    if host == "0.0.0.0":
        host = "127.0.0.1"
    return f"http://{host}:{settings.port}"


def fetch_trace_with_retry(
    user: HttpUser,
    execution_id: str,
    retries: int,
    retry_interval: float,
) -> tuple[dict[str, Any] | None, str | None]:
    last_trace_data = None
    for attempt in range(retries + 1):
        with user.client.get(
            f"/api/v1/execution/{execution_id}/trace",
            name="execution_trace_fetch",
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                return None, f"trace request failed: http {response.status_code}"
            body = response.json()
            if body.get("code") != 0:
                return None, f"trace request failed: {body.get('message')}"
            last_trace_data = body.get("data")
            response.success()

        spans = (last_trace_data or {}).get("spans") or []
        if spans:
            return last_trace_data, None

        if attempt < retries:
            time.sleep(max(0.0, retry_interval))

    return last_trace_data, "trace returned no spans after retries"


def collect_batch_analysis(user: HttpUser, final_status: dict[str, Any]) -> dict[str, Any]:
    options = user.environment.parsed_options
    analyzed_executions: list[dict[str, Any]] = []
    missing_trace_id = 0
    trace_request_failed = 0
    empty_spans = 0
    missing_span_start_time = 0

    for execution in final_status.get("executions", []):
        execution_id = str(execution["id"])
        trace_id = execution.get("trace_id")
        trace_data = None
        missing_reason = None

        if not trace_id:
            missing_trace_id += 1
            missing_reason = "trace_id missing"
        else:
            trace_data, fetch_reason = fetch_trace_with_retry(
                user,
                execution_id,
                max(0, int(options.max_polls // 24)),
                float(options.poll_interval),
            )
            if fetch_reason and fetch_reason.startswith("trace request failed"):
                trace_request_failed += 1
                missing_reason = fetch_reason
            elif fetch_reason == "trace returned no spans after retries":
                empty_spans += 1
                missing_reason = fetch_reason

        spans = (trace_data or {}).get("spans") or []
        span_start_times = [span.get("start_time_ms") for span in spans if span.get("start_time_ms") is not None]
        if spans and not span_start_times:
            missing_span_start_time += 1
            missing_reason = "spans found but no start_time_ms"

        model_call_time_ms, llm_span_count = calculate_model_call_metrics(trace_data)
        analyzed_executions.append(
            {
                "call_index": execution.get("call_index"),
                "execution_id": execution_id,
                "status": execution.get("status"),
                "trace_id": trace_id,
                "user_session": execution.get("user_session"),
                "started_at": execution.get("started_at"),
                "completed_at": execution.get("completed_at"),
                "duration": execution.get("duration"),
                "error_message": execution.get("error_message"),
                "span_ids": execution.get("span_ids") or [],
                "analysis_missing_reason": missing_reason,
                "first_span_start_ms": min(span_start_times) if span_start_times else None,
                "last_span_start_ms": max(span_start_times) if span_start_times else None,
                "model_call_time_ms": model_call_time_ms,
                "llm_span_count": llm_span_count,
            }
        )

    return {
        "batch_id": final_status.get("batch_id"),
        "status": final_status.get("status"),
        "total": final_status.get("total"),
        "completed": final_status.get("completed"),
        "failed": final_status.get("failed"),
        "running": final_status.get("running"),
        "avg_duration": final_status.get("avg_duration"),
        "analysis": analyze_concurrency(analyzed_executions),
        "missing_stats": {
            "missing_trace_id": missing_trace_id,
            "trace_request_failed": trace_request_failed,
            "empty_spans": empty_spans,
            "missing_span_start_time": missing_span_start_time,
        },
        "executions": analyzed_executions,
        "created_at_ms": int(time.time() * 1000),
    }


@events.init.add_listener
def _(environment, **_kwargs) -> None:
    if environment.web_ui:
        @environment.web_ui.app.route("/batch-analysis")
        def batch_analysis():
            return render_batches_html()


@events.init_command_line_parser.add_listener
def _(parser) -> None:
    parser.add_argument("--input-text", type=str, default="hello", help="Prompt sent to the TestBench concurrent API")
    parser.add_argument(
        "--openclaw-concurrency",
        type=int,
        default=1,
        help="Concurrent OpenClaw calls requested inside each TestBench batch",
    )
    parser.add_argument("--model-name", type=str, default="openclaw:main", help="Model name passed to OpenClaw")
    parser.add_argument(
        "--concurrent-mode",
        type=str,
        choices=["single_instance", "multi_instance"],
        default="single_instance",
        help="Concurrent execution mode used by TestBench",
    )
    parser.add_argument("--agent-id", type=str, default="", help="Optional TestBench agent ID")
    parser.add_argument("--llm-model-id", type=str, default="", help="Optional TestBench LLM model ID")
    parser.add_argument("--poll-interval", type=float, default=2.0, help="Polling interval in seconds")
    parser.add_argument("--max-polls", type=int, default=120, help="Maximum status polling rounds per batch")
    parser.add_argument("--wait-seconds", type=float, default=0.0, help="Wait time between completed tasks for each user")


class TestBenchConcurrentUser(HttpUser):
    host = get_default_host()
    wait_time = constant(0)

    def wait_time(self) -> float:
        return max(0.0, float(getattr(self.environment.parsed_options, "wait_seconds", 0.0)))

    def _build_payload(self) -> dict[str, Any]:
        options = self.environment.parsed_options
        payload: dict[str, Any] = {
            "input": options.input_text,
            "concurrency": options.openclaw_concurrency,
            "model": options.model_name,
            "concurrent_mode": options.concurrent_mode,
        }
        if options.agent_id:
            payload["agent_id"] = options.agent_id
        if options.llm_model_id:
            payload["llm_model_id"] = options.llm_model_id
        return payload

    def _record_e2e(self, started_at: float, payload: dict[str, Any], exception: Exception | None = None) -> None:
        self.environment.events.request.fire(
            request_type="FLOW",
            name="execution_batch_e2e",
            response_time=(time.perf_counter() - started_at) * 1000,
            response_length=len(json.dumps(payload, ensure_ascii=False)),
            exception=exception,
            context={"payload": payload},
        )

    @task
    def run_concurrent_batch(self) -> None:
        payload = self._build_payload()
        started_at = time.perf_counter()

        try:
            with self.client.post(
                "/api/v1/execution/concurrent",
                json=payload,
                headers={"Content-Type": "application/json"},
                name="execution_batch_create",
                catch_response=True,
            ) as response:
                if response.status_code != 200:
                    raise RuntimeError(f"create batch http {response.status_code}: {response.text[:300]}")

                body = response.json()
                if body.get("code") != 0:
                    raise RuntimeError(f"create batch api error: {body.get('message')}")

                batch_id = body.get("data", {}).get("batch_id")
                if not batch_id:
                    raise RuntimeError("create batch returned empty batch_id")
                response.success()

            final_status: dict[str, Any] | None = None
            for _ in range(max(1, self.environment.parsed_options.max_polls)):
                time.sleep(max(0.0, float(self.environment.parsed_options.poll_interval)))
                with self.client.get(
                    f"/api/v1/execution/concurrent/{batch_id}",
                    name="execution_batch_status",
                    catch_response=True,
                ) as status_response:
                    if status_response.status_code != 200:
                        raise RuntimeError(f"batch status http {status_response.status_code}: {status_response.text[:300]}")

                    status_body = status_response.json()
                    if status_body.get("code") != 0:
                        raise RuntimeError(f"batch status api error: {status_body.get('message')}")

                    final_status = status_body.get("data") or {}
                    status_response.success()
                    if final_status.get("status") == "completed":
                        break

            if not final_status:
                raise RuntimeError("no final batch status received")

            if final_status.get("status") != "completed":
                raise RuntimeError(
                    "batch polling timed out before completion: "
                    f"batch_id={batch_id} completed={final_status.get('completed')} "
                    f"failed={final_status.get('failed')} running={final_status.get('running')}"
                )

            if int(final_status.get("failed") or 0) > 0:
                raise RuntimeError(f"batch completed with failed executions: {final_status.get('failed')}")

            remember_batch(collect_batch_analysis(self, final_status))
            self._record_e2e(started_at, payload, exception=None)
        except Exception as exc:
            self._record_e2e(started_at, payload, exception=exc)
            raise
