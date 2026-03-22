"""HTTP Agent 客户端"""

import httpx
from typing import Optional
from app.config import settings


class HTTPAgentClient:
    """HTTP Agent 客户端"""

    def __init__(self, base_url: str, api_key: str, timeout: int = None, user_session: str = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout or settings.agent_timeout_seconds
        self.user_session = user_session

    def _get_headers(self, trace_id: str = None) -> dict:
        """获取请求头"""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        if trace_id:
            headers["X-Trace-ID"] = trace_id
        return headers

    async def test_connection(self) -> bool:
        """测试连接 - use exactly what user provided"""
        try:
            # Use the base_url directly - do not append /health
            import logging
            logger = logging.getLogger(__name__)
            logger.info(f"[DEBUG TEST] Request URL: {self.base_url}")
            logger.info(f"[DEBUG TEST] has user_session: {self.user_session is not None}")

            async with httpx.AsyncClient(timeout=10.0) as client:
                if self.user_session is not None and self.user_session != "":
                    # openclaw format - use POST with empty test prompt
                    payload = {
                        "model": "openclaw:main",
                        "messages": [{"role": "user", "content": "test"}],
                        "user": self.user_session
                    }
                    response = await client.post(
                        self.base_url,
                        json=payload,
                        headers=self._get_headers()
                    )
                else:
                    # original format - use GET
                    response = await client.get(self.base_url, headers=self._get_headers())

                result = 200 <= response.status_code < 300
                logger.info(f"[DEBUG TEST] Status code: {response.status_code} result: {result}")
                return result
        except Exception as e:
            logger.error(f"[DEBUG TEST] Error: {e}")
            return False

    async def invoke(self, prompt: str, trace_id: str = None) -> tuple[str, dict | None]:
        """调用 Agent
        Returns: (content, full_response_data)
        """
        # Use exactly what user provided - do not append any path
        url = self.base_url
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"[DEBUG INVOKE] Final request URL: {url}")
        logger.info(f"[DEBUG INVOKE] base_url from init: {self.base_url}")
        logger.info(f"[DEBUG INVOKE] has user_session: {self.user_session is not None}")
        logger.info(f"[DEBUG INVOKE] prompt length: {len(prompt)}")

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            if self.user_session is not None and self.user_session != "":
                # openclaw 格式: {model: "openclaw:main, messages: [{role: user, content: prompt}], user: user_session}
                payload = {
                    "model": "openclaw:main",
                    "messages": [{"role": "user", "content": prompt}],
                    "user": self.user_session
                }
            else:
                # 原始格式: {prompt: prompt}
                payload = {"prompt": prompt}

            response = await client.post(
                url,
                json=payload,
                headers=self._get_headers(trace_id)
            )
            response.raise_for_status()
            data = response.json()

            # openclaw 返回格式: {choices: [{message: {content: ...}}]}
            content: str
            if self.user_session is not None and self.user_session != "" and isinstance(data, dict) and "choices" in data:
                choices = data["choices"]
                if choices and len(choices) > 0:
                    message = choices[0].get("message", {})
                    content = message.get("content", "")
                else:
                    content = response.text
            elif isinstance(data, dict) and "response" in data:
                # 假设返回格式有 response 字段
                content = data["response"]
            else:
                content = response.text

            return content, data
