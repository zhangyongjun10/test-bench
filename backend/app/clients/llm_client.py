"""LLM 客户端"""

from abc import ABC, abstractmethod
import json
import httpx
from typing import Tuple
from app.domain.entities.llm import LLMModel


class LLMClient(ABC):
    @abstractmethod
    async def test_connection(self, model: LLMModel) -> tuple[bool, str]:
        """测试连接是否正常"""
        pass

    @abstractmethod
    async def compare(
        self,
        prompt: str,
        actual: str,
        baseline: str
    ) -> tuple[float, bool, str]:
        """返回：(比对分数 0-1, 是否通过, 解释)"""
        pass


class OpenAICompatibleLLMClient(LLMClient):
    """OpenAI 兼容格式的 LLM 客户端"""

    def __init__(
        self,
        api_key: str,
        model_id: str,
        base_url: str = None,
        temperature: float = 0.0,
        max_tokens: int = 1024
    ):
        self.api_key = api_key
        self.model_id = model_id
        self.base_url = base_url or "https://api.openai.com/v1"
        self.base_url = self.base_url.rstrip("/")
        self.temperature = temperature
        self.max_tokens = max_tokens

    def _get_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    async def test_connection(self, model: LLMModel) -> tuple[bool, str]:
        """测试连接 - 使用 OpenAI 标准 /models 端点"""
        try:
            # OpenAI 标准：GET /v1/models 用来验证认证和端点可用性
            test_url = f"{self.base_url}/models"
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(test_url, headers=self._get_headers())
                if 200 <= response.status_code < 300:
                    return True, "Connection successful"
                else:
                    return False, f"HTTP {response.status_code}: {response.text}"
        except Exception as e:
            return False, str(e)

    async def compare(
        self,
        prompt: str,
        actual: str,
        baseline: str
    ) -> tuple[float, bool, str]:
        """调用 LLM 进行比对 - 使用 OpenAI 标准 /chat/completions 端点"""
        # OpenAI 标准：POST /v1/chat/completions
        url = f"{self.base_url}/chat/completions"

        messages = [
            {"role": "user", "content": prompt}
        ]

        payload = {
            "model": self.model_id,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                url,
                json=payload,
                headers=self._get_headers()
            )
            response.raise_for_status()
            data = response.json()

        # 解析响应
        content = data["choices"][0]["message"]["content"].strip()

        # 尝试解析 JSON
        try:
            # 清理可能的 markdown 格式
            content = content.strip()
            if content.startswith("```json"):
                content = content[7:-3]
            elif content.startswith("```"):
                content = content[3:-3]

            result = json.loads(content)
            score = float(result.get("score", 0.0))
            consistent = bool(result.get("consistent", False))
            reason = str(result.get("reason", ""))

            # clamp score
            score = max(0.0, min(1.0, score))

            return score, consistent, reason
        except Exception as e:
            # 如果解析失败，默认认为失败
            return 0.0, False, f"Failed to parse LLM response: {content}"
