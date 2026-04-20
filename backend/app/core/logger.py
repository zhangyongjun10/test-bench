"""日志配置。"""

import asyncio
import itertools
import os
import logging
import structlog
from structlog.stdlib import ProcessorFormatter
from app.config import settings
import pytz
from datetime import datetime

# 设置日志时区为北京时间，保证终端、文件和页面排障时间一致。
BEIJING_TZ = pytz.timezone("Asia/Shanghai")

# 为 asyncio Task 分配进程内递增 ID，避免使用内存地址导致 Task 销毁后复用而混淆日志。
TASK_ID_COUNTER = itertools.count(1)

# 确保日志目录存在，避免应用启动时文件 handler 创建失败。
os.makedirs("logs", exist_ok=True)


# 按北京时间日期动态写入文件的日志 handler；避免服务长时间运行时仍写入启动日文件。
class BeijingDailyFileHandler(logging.Handler):
    # 初始化按天写入的文件 handler，prefix 用于区分 info/error 两类日志文件。
    def __init__(self, prefix: str, log_dir: str = "logs", encoding: str = "utf-8"):
        super().__init__()
        self.prefix = prefix
        self.log_dir = log_dir
        self.encoding = encoding

    # 根据当前北京时间生成目标日志文件路径，确保每天写入独立文件。
    def _current_log_path(self) -> str:
        current_day = datetime.now(BEIJING_TZ).strftime("%Y-%m-%d")
        return os.path.join(self.log_dir, f"{self.prefix}.{current_day}.log")

    # 写入单条日志；每次 emit 都重新计算日期，跨天无需依赖进程重启或 handler rollover。
    def emit(self, record: logging.LogRecord) -> None:
        try:
            os.makedirs(self.log_dir, exist_ok=True)
            message = self.format(record)
            with open(self._current_log_path(), "a", encoding=self.encoding) as log_file:
                log_file.write(message + self.terminator)
        except Exception:
            self.handleError(record)

    # 文件日志换行符，保持与标准 StreamHandler 行为一致。
    terminator = "\n"

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

# 配置根日志器，structlog 最终也会写入这里绑定的终端和文件 handler。
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
root_logger.handlers.clear()

# structlog 通用预处理链，控制台和文件都会补齐北京时间、协程 ID 和日志级别。
shared_processors = [
    add_beijing_timestamp,
    add_asyncio_task_context,
    structlog.processors.add_log_level,
]

# 控制台日志格式化器；debug 模式保留彩色输出，便于本地终端排查。
console_formatter = ProcessorFormatter(
    processors=[
        ProcessorFormatter.remove_processors_meta,
        structlog.dev.ConsoleRenderer(colors=settings.debug),
    ],
    foreign_pre_chain=shared_processors,
)

# 文件日志格式化器；强制关闭颜色，避免 ANSI 控制字符写入日志文件造成乱码。
file_formatter = ProcessorFormatter(
    processors=[
        ProcessorFormatter.remove_processors_meta,
        structlog.dev.ConsoleRenderer(colors=False),
    ],
    foreign_pre_chain=shared_processors,
)

# 控制台 handler，用于开发和本地排查时直接在终端查看日志。
console_handler = logging.StreamHandler()
console_handler.setFormatter(console_formatter)
console_handler.setLevel(logging.INFO)
root_logger.addHandler(console_handler)

# Info 文件日志 handler，按北京时间日期直接写入 logs/info.YYYY-MM-DD.log。
info_handler = BeijingDailyFileHandler("info")
info_handler.setFormatter(file_formatter)
info_handler.setLevel(logging.INFO)
root_logger.addHandler(info_handler)

# Error 文件日志 handler，单独记录错误级别日志到 logs/error.YYYY-MM-DD.log 便于排障。
error_handler = BeijingDailyFileHandler("error")
error_handler.setFormatter(file_formatter)
error_handler.setLevel(logging.ERROR)
root_logger.addHandler(error_handler)

# 配置 structlog 交给 logging handler 渲染，使控制台和文件可以分别使用彩色/无彩色格式。
structlog.configure(
    processors=[
        *shared_processors,
        ProcessorFormatter.wrap_for_formatter,
    ],
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()
