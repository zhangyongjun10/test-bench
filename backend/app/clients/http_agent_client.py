"""HTTP client for invoking configured agents."""

import logging
import uuid
from urllib.parse import urlparse

import httpx

from app.config import settings


logger = logging.getLogger(__name__)


# 格式化异常信息，避免 ReadTimeout 等空字符串异常导致前端看不到失败原因。
def _format_exception_message(exc: Exception) -> str:
    message = str(exc).strip()
    if message:
        return f"{exc.__class__.__name__}: {message}"
    return exc.__class__.__name__


# Agent HTTP 调用客户端，负责按 OpenAI Chat Completions 兼容协议组装请求并注入 execution 级会话。
class HTTPAgentClient:
    """HTTP client for invoking OpenAI-compatible agent endpoints."""

    # 初始化 Agent 客户端；user_session 仅接收 execution 级会话，不再来源于 Agent 配置。
    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout: int | None = None,
        user_session: str | None = None,
        verify_ssl: bool = True,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout or settings.agent_timeout_seconds
        self.user_session = user_session
        self.verify_ssl = verify_ssl

    def _get_headers(self, trace_id: str | None = None) -> dict:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if trace_id:
            headers["X-Trace-ID"] = trace_id
        return headers

    def _build_request_url(self) -> str:
        parsed = urlparse(self.base_url)
        path = parsed.path.rstrip("/")
        if path.endswith("/v1/chat/completions"):
            return self.base_url
        if path in ("", "/"):
            return f"{self.base_url}/v1/chat/completions"
        return self.base_url

    # 构建 OpenClaw Chat Completions 请求体，Agent 执行默认固定使用 openclaw:main，页面选择的 LLM 模型只用于后续比对。
    def _build_payload(
        self,
        prompt: str,
        model: str = "openclaw:main",
        user_session: str | None = None,
    ) -> dict:
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
        }
        effective_user_session = user_session if user_session is not None else self.user_session
        if effective_user_session:
            payload["user"] = effective_user_session
        return payload

    # 测试 Agent 端点是否可用；缺省时生成临时 test 会话，避免污染真实执行上下文。
    async def test_connection(self, model: str = "openclaw:main", user_session: str | None = None) -> tuple[bool, str]:
        request_url = self._build_request_url()
        effective_user_session = user_session if user_session is not None else (self.user_session or f"test_{uuid.uuid4().hex}")
        try:
            async with httpx.AsyncClient(timeout=60.0, verify=self.verify_ssl) as client:
                response = await client.post(
                    request_url,
                    json=self._build_payload("test", model, user_session=effective_user_session),
                    headers=self._get_headers(),
                )

            result = 200 <= response.status_code < 300
            if result:
                logger.info("Agent connection test status=%s result=%s", response.status_code, result)
                return True, "Connection successful"

            response_preview = response.text[:500] if response.text else ""
            message = f"HTTP {response.status_code}"
            if response_preview:
                message = f"{message}: {response_preview}"
            logger.warning("Agent connection test failed: %s", message)
            return False, message
        except Exception as exc:
            message = _format_exception_message(exc)
            logger.error("Agent connection test failed: %s", message)
            return False, message

    # 调用 Agent HTTP 接口执行场景，默认 model 保持 openclaw:main，避免把比对模型误传给 Agent。
    async def invoke(
        self,
        prompt: str,
        trace_id: str | None = None,
        model: str = "openclaw:main",
        user_session: str | None = None,
    ) -> tuple[str, dict | None]:
        url = self._build_request_url()
        effective_user_session = user_session if user_session is not None else (self.user_session or f"exec_{uuid.uuid4().hex}")

        logger.info(
            "Invoking agent url=%s trace_id=%s user_session=%s prompt_length=%s",
            url,
            trace_id,
            effective_user_session,
            len(prompt),
        )

        async with httpx.AsyncClient(timeout=self.timeout, verify=self.verify_ssl) as client:
            response = await client.post(
                url,
                json=self._build_payload(prompt, model, user_session=effective_user_session),
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
