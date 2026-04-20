import pytest

from app.api import system as system_api


# 验证前端运行时配置直接来自后端 settings，避免并发上限在前后端重复硬编码。
@pytest.mark.asyncio
async def test_runtime_config_returns_backend_concurrency_limit(monkeypatch):
    monkeypatch.setattr(system_api.settings, "concurrent_execution_max_concurrency", 321)

    response = await system_api.get_runtime_config()

    assert response.code == 0
    assert response.data.concurrent_execution_max_concurrency == 321
