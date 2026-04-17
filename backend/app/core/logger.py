"""日志配置。"""

import asyncio
import itertools
import os
import logging
import logging.handlers
import structlog
from app.config import settings
import pytz
from datetime import datetime

# 设置日志时区为北京时间，保证终端、文件和页面排障时间一致。
BEIJING_TZ = pytz.timezone("Asia/Shanghai")

# 为 asyncio Task 分配进程内递增 ID，避免使用内存地址导致 Task 销毁后复用而混淆日志。
TASK_ID_COUNTER = itertools.count(1)

# 确保日志目录存在，避免应用启动时文件 handler 创建失败。
os.makedirs("logs", exist_ok=True)

# 使用北京时间格式化标准 logging 输出。
class BeijingFormatter(logging.Formatter):
    def converter(self, timestamp):
        dt = datetime.fromtimestamp(timestamp, BEIJING_TZ)
        return dt.timetuple()

# 配置根日志器，structlog 最终也会写入这里绑定的终端和文件 handler。
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)

# 标准 logging 的消息格式保持简洁，结构化字段由 structlog 渲染。
formatter = BeijingFormatter("%(message)s")

# 控制台 handler，用于开发和本地排查时直接在终端查看日志。
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
console_handler.setLevel(logging.INFO)
root_logger.addHandler(console_handler)

# Info 文件日志 handler，按天滚动并保留 30 天。
today = datetime.now(BEIJING_TZ).strftime("%Y-%m-%d")
info_handler = logging.handlers.TimedRotatingFileHandler(
    f"logs/info.{today}.log",
    when="midnight",
    interval=1,
    backupCount=30,
    encoding="utf-8",
    utc=False
)
info_handler.setFormatter(formatter)
info_handler.setLevel(logging.INFO)
info_handler.suffix = "%Y-%m-%d.log"
root_logger.addHandler(info_handler)

# Error 文件日志 handler，单独记录错误级别日志便于排障。
error_handler = logging.handlers.TimedRotatingFileHandler(
    f"logs/error.{today}.log",
    when="midnight",
    interval=1,
    backupCount=30,
    encoding="utf-8",
    utc=False
)
error_handler.setFormatter(formatter)
error_handler.setLevel(logging.ERROR)
error_handler.suffix = "%Y-%m-%d.log"
root_logger.addHandler(error_handler)

# 给 structlog 事件补充北京时间戳，避免依赖服务器本地时区。
def add_beijing_timestamp(_, __, event_dict):
    event_dict["timestamp"] = datetime.now(BEIJING_TZ).isoformat()
    return event_dict

# 给 structlog 事件补充稳定的 asyncio 协程 ID，用于并发执行下串联同一路请求日志。
def add_asyncio_task_context(_, __, event_dict):
    try:
        task = asyncio.current_task()
    except RuntimeError:
        task = None
    if task:
        task_id = getattr(task, "_testbench_task_id", None)
        if task_id is None:
            task_id = f"task-{next(TASK_ID_COUNTER)}"
            setattr(task, "_testbench_task_id", task_id)
        event_dict["task_id"] = task_id
    return event_dict

# 配置 structlog 默认 JSON 输出，适合在终端和文件中检索结构化字段。
structlog.configure(
    processors=[
        add_beijing_timestamp,
        add_asyncio_task_context,
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer(),
    ],
    logger_factory=structlog.stdlib.LoggerFactory(),
)

logger = structlog.get_logger()

# Debug 模式下使用可读性更强的控制台渲染，同时保留协程上下文字段。
if settings.debug:
    structlog.configure(
        processors=[
            add_beijing_timestamp,
            add_asyncio_task_context,
            structlog.processors.add_log_level,
            structlog.dev.ConsoleRenderer(),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
    )
