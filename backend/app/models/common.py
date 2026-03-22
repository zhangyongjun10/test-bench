"""通用响应模型"""

from __future__ import annotations
from typing import Generic, TypeVar, Optional
from pydantic import BaseModel

T = TypeVar("T")


class Response(BaseModel, Generic[T]):
    """统一响应格式"""

    code: int = 0
    message: str = "success"
    data: Optional[T] = None


class ListResponse(BaseModel, Generic[T]):
    """列表响应"""

    total: int
    items: list[T]
