"""日志中间件"""

import time
from fastapi import Request
from app.core.logger import logger


async def logging_middleware(request: Request, call_next):
    """日志中间件，记录请求处理时间"""
    start_time = time.time()
    response = await call_next(request)
    duration = time.time() - start_time

    logger.info(
        "request processed",
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        duration_ms=int(duration * 1000)
    )

    return response
