"""LLM 模型服务"""

from typing import List, Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from app.domain.entities.llm import LLMModel
from app.domain.repositories.llm_repo import LLMRepository, SQLAlchemyLLMRepository
from app.core.encryption import encryption_service
from app.models.llm import DEFAULT_COMPARISON_PROMPT, LLMCreate, LLMUpdate
from app.core.logger import logger
from app.clients.llm_client import LLMClient, OpenAICompatibleLLMClient


class LLMService:
    def __init__(self, session: AsyncSession):
        self.repo: LLMRepository = SQLAlchemyLLMRepository(session)
        self.session = session

    @staticmethod
    def _normalize_comparison_prompt(prompt: str | None) -> str:
        prompt = (prompt or "").strip()
        return prompt or DEFAULT_COMPARISON_PROMPT

    async def create_llm(self, request: LLMCreate) -> LLMModel:
        """创建 LLM 模型"""
        llm = LLMModel(
            name=request.name,
            provider=request.provider,
            model_id=request.model_id,
            base_url=request.base_url,
            api_key_encrypted=encryption_service.encrypt(request.api_key),
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            comparison_prompt=self._normalize_comparison_prompt(request.comparison_prompt),
            is_default=False
        )
        result = await self.repo.create(llm)
        logger.info(f"Created LLM model: {result.id} name={result.name}")
        return result

    async def update_llm(self, model_id: UUID, request: LLMUpdate) -> Optional[LLMModel]:
        """更新 LLM 模型"""
        model = await self.repo.get_by_id(model_id)
        if not model:
            return None

        if request.name is not None:
            model.name = request.name
        if request.provider is not None:
            model.provider = request.provider
        if request.model_id is not None:
            model.model_id = request.model_id
        if request.base_url is not None:
            model.base_url = request.base_url
        if request.api_key is not None:
            model.api_key_encrypted = encryption_service.encrypt(request.api_key)
        if request.temperature is not None:
            model.temperature = request.temperature
        if request.max_tokens is not None:
            model.max_tokens = request.max_tokens
        if request.comparison_prompt is not None:
            model.comparison_prompt = self._normalize_comparison_prompt(request.comparison_prompt)

        result = await self.repo.update(model)
        logger.info(f"Updated LLM model: {model_id}")
        return result

    async def delete_llm(self, model_id: UUID) -> tuple[bool, str]:
        """删除 LLM 模型"""
        model = await self.repo.get_by_id(model_id)
        if not model:
            return False, "Model not found"
        await self.repo.delete(model_id)
        logger.info(f"Deleted LLM model: {model_id}")
        return True, "Deleted"

    async def get_llm(self, model_id: UUID) -> Optional[LLMModel]:
        """获取 LLM 模型"""
        return await self.repo.get_by_id(model_id)

    async def list_llms(self, keyword: Optional[str] = None) -> List[LLMModel]:
        """列出 LLM 模型"""
        return await self.repo.list_all(keyword)

    async def test_connection(self, model_id: UUID) -> tuple[bool, str]:
        """测试 LLM 连接"""
        model = await self.repo.get_by_id(model_id)
        if not model:
            return False, "Model not found"

        api_key = encryption_service.decrypt(model.api_key_encrypted)
        client = OpenAICompatibleLLMClient(
            base_url=model.base_url,
            api_key=api_key,
            model_id=model.model_id,
            temperature=model.temperature,
            max_tokens=model.max_tokens
        )
        try:
            success, message = await client.test_connection(model)
            if success:
                logger.info(f"LLM connection test succeeded: {model_id}")
            else:
                logger.warning(f"LLM connection test failed: {model_id} {message}")
            return success, message
        except Exception as e:
            logger.error(f"LLM connection test error: {model_id} error={e}")
            return False, f"Connection error: {str(e)}"

    def get_client(self, model: LLMModel) -> LLMClient:
        """获取 LLM 客户端"""
        api_key = encryption_service.decrypt(model.api_key_encrypted)
        return OpenAICompatibleLLMClient(
            base_url=model.base_url,
            api_key=api_key,
            model_id=model.model_id,
            temperature=model.temperature,
            max_tokens=model.max_tokens
        )
