"""错误处理中间件"""

from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from app.core.logger import logger
from app.models.common import Response


async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """参数验证错误处理"""
    errors = exc.errors()
    error_msg = "; ".join([f"{err['loc']}: {err['msg']}" for err in errors])
    logger.warning(f"Request validation error: {error_msg}")
    return JSONResponse(
        status_code=200,
        content=Response(code=400, message=f"Validation error: {error_msg}", data=None).model_dump()
    )
