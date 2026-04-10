"""HTTP client for invoking configured agents."""

import logging
import uuid

import httpx

from app.config import settings


logger = logging.getLogger(__name__)


class HTTPAgentClient:
    """HTTP Agent client.

    All invocations use the OpenClaw-compatible chat completion payload so every
    execution can be isolated by its own `user` value.
    """

    def __init__(self, base_url: str, api_key: str, timeout: int = None, user_session: str = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout or settings.agent_timeout_seconds
        self.user_session = user_session

    def _get_headers(self, trace_id: str = None) -> dict:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if trace_id:
            headers["X-Trace-ID"] = trace_id
        return headers

    def _build_payload(self, prompt: str, user_session: str) -> dict:
        return {
            "model": "openclaw:main",
            "messages": [{"role": "user", "content": prompt}],
            "user": user_session,
        }

    async def test_connection(self) -> bool:
        """Test the configured agent endpoint with an isolated temporary user."""
        try:
            user_session = self.user_session or f"test_{uuid.uuid4().hex}"
            payload = self._build_payload("test", user_session)

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    self.base_url,
                    json=payload,
                    headers=self._get_headers(),
                )

            result = 200 <= response.status_code < 300
            logger.info("Agent connection test status=%s result=%s", response.status_code, result)
            return result
        except Exception as exc:
            logger.error("Agent connection test failed: %s", exc)
            return False

    async def invoke(self, prompt: str, trace_id: str = None) -> tuple[str, dict | None]:
        """Invoke the agent and return `(assistant_content, raw_response)`."""
        user_session = self.user_session or f"exec_{uuid.uuid4().hex}"
        payload = self._build_payload(prompt, user_session)

        logger.info(
            "Invoking agent url=%s trace_id=%s user_session=%s prompt_length=%s",
            self.base_url,
            trace_id,
            user_session,
            len(prompt),
        )

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                self.base_url,
                json=payload,
                headers=self._get_headers(trace_id),
            )
            response.raise_for_status()
            data = response.json()

        if isinstance(data, dict) and "choices" in data:
            choices = data["choices"]
            if choices:
                message = choices[0].get("message", {})
                return message.get("content", ""), data
            return response.text, data

        if isinstance(data, dict) and "response" in data:
            return data["response"], data

        return response.text, data
