"""数据库连接"""

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import settings

# SQLAlchemy ORM 基类，所有实体模型统一继承该 Base。
Base = declarative_base()

# 异步数据库引擎；连接池参数配置化，避免并发执行时依赖 SQLAlchemy 默认 5+10 的小连接池。
engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_pre_ping=True,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_timeout=settings.db_pool_timeout,
    pool_recycle=settings.db_pool_recycle_seconds,
)
# 异步 Session 工厂；expire_on_commit=False 避免提交后再次访问实体字段触发额外懒加载。
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncSession:
    """获取数据库会话"""
    async with AsyncSessionLocal() as session:
        yield session
