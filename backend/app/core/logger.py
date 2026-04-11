"""日志配置"""

import os
import logging
import logging.handlers
import structlog
from app.config import settings
import pytz
from datetime import datetime

# 设置时区为北京时间
BEIJING_TZ = pytz.timezone("Asia/Shanghai")

# 确保日志目录存在
os.makedirs("logs", exist_ok=True)

# 自定义 formatter 使用北京时间
class BeijingFormatter(logging.Formatter):
    def converter(self, timestamp):
        dt = datetime.fromtimestamp(timestamp, BEIJING_TZ)
        return dt.timetuple()

# 配置根日志
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)

formatter = BeijingFormatter("%(message)s")

# 控制台处理器
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
console_handler.setLevel(logging.INFO)
root_logger.addHandler(console_handler)

# info 日志 - 按天滚动，每天一个文件，保留 30 天
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

# error 日志 - 按天滚动，每天一个文件，保留 30 天
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

# 添加北京时间戳到 structlog 事件
def add_beijing_timestamp(_, __, event_dict):
    event_dict["timestamp"] = datetime.now(BEIJING_TZ).isoformat()
    return event_dict

# 配置 structlog
structlog.configure(
    processors=[
        add_beijing_timestamp,
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer(),
    ],
    logger_factory=structlog.stdlib.LoggerFactory(),
)

logger = structlog.get_logger()

if settings.debug:
    structlog.configure(
        processors=[
            add_beijing_timestamp,
            structlog.processors.add_log_level,
            structlog.dev.ConsoleRenderer(),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
    )
