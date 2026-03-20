"""主入口"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import make_asgi_app
from prometheus_client import CollectorRegistry
from app.config import settings
from app.core.logger import logger
from app.api.agent import router as agent_router
from app.api.llm import router as llm_router
from app.api.scenario import router as scenario_router
from app.api.execution import router as execution_router
from app.api.system import router as system_router
from app.middleware.logging import logging_middleware
from app.middleware.error_handler import validation_exception_handler
from fastapi.exceptions import RequestValidationError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.ext.asyncio import AsyncSession
from app.domain.repositories.execution_repo import SQLAlchemyExecutionRepository
from app.core.db import AsyncSessionLocal
import asyncio


# 创建 FastAPI 应用
app = FastAPI(
    title="TestBench - Agent 验证平台",
    description="Agent 标准化验证平台，支持性能指标采集和 LLM 结果比对",
    version="1.0.0"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 日志中间件
app.middleware("http")(logging_middleware)

# 错误处理
app.add_exception_handler(RequestValidationError, validation_exception_handler)

# Prometheus 指标
from prometheus_client import make_asgi_app
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)

# 注册路由
app.include_router(agent_router)
app.include_router(llm_router)
app.include_router(scenario_router)
app.include_router(execution_router)
app.include_router(system_router)


# 定时任务：自动清理旧数据
async def clean_old_data():
    """每天凌晨清理超过 30 天的旧数据"""
    logger.info("Starting scheduled clean of old data")
    try:
        async with AsyncSessionLocal() as session:
            repo = SQLAlchemyExecutionRepository(session)
            deleted = await repo.delete_old_data(settings.data_retention_days)
            logger.info(f"Cleaned up {deleted} old execution records older than {settings.data_retention_days} days")
    except Exception as e:
        logger.error(f"Failed to clean old data: {e}")


# 启动调度器
if not settings.debug:
    scheduler = AsyncIOScheduler()
    # 每天凌晨 2 点执行
    scheduler.add_job(
        clean_old_data,
        CronTrigger(hour=2, minute=0),
        misfire_grace_time=300
    )
    scheduler.start()
    logger.info("Started scheduled data cleanup job")


@app.get("/health")
async def health():
    """健康检查"""
    return {"status": "ok"}


logger.info("TestBench application started")
