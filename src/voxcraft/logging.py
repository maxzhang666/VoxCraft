"""structlog 配置。调用 setup_logging(level) 后即可用 structlog.get_logger()。"""
from __future__ import annotations

import logging
import sys

import structlog


# 与下载 / HTTP 链路相关的第三方 logger；DEBUG 级别会暴露底层请求 URL、
# 重试、状态码等关键诊断信息（默认 WARNING 看不到）
_THIRD_PARTY_LOGGERS = (
    "huggingface_hub",
    "modelscope",
    "httpx",
    "httpcore",
    "urllib3",
    "requests",
    "alembic",
)


def setup_logging(level: str = "INFO") -> None:
    lv = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=lv,
    )
    # 让下载链路相关的第三方库 logger 跟随主 level；用户调到 DEBUG 时
    # 才能看到 huggingface_hub / httpx 的实际 HTTP 请求细节
    for name in _THIRD_PARTY_LOGGERS:
        logging.getLogger(name).setLevel(lv)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(lv),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
