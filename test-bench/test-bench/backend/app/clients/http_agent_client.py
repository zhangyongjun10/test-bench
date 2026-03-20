"""HTTP Agent 客户端"""

import httpx
from typing import Optional
from app.config import settings


class HTTPAgentClient:
    """HTTP Agent 客户端"""

    def __init__(self, base_url: str, api_key: str, timeout: int = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout or settings.agent_timeout_seconds

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
        """测试连接"""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"{self.base_url}/health", headers=self._get_headers())
                return 200 <= response.status_code < 300
        except Exception:
            return False

    async def invoke(self, prompt: str, trace_id: str = None) -> str:
        """调用 Agent"""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/chat",
                json={"prompt": prompt},
                headers=self._get_headers(trace_id)
            )
            response.raise_for_status()
            data = response.json()
            # 假设返回格式有 response 字段
            if isinstance(data, dict) and "response" in data:
                return data["response"]
            return response.text
