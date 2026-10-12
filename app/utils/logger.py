from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from app.utils.paths import LOG_DIR

# 日志格式
_FMT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
_DATEFMT = "%H:%M:%S"


def setup_logging(level: int = logging.INFO, log_hub=None) -> logging.Logger:
    """配置日志系统。

    - 文件：data/logs/app.log，5MB 轮转，保留 3 份
    - 控制台：标准输出
    - LogHub：内存缓冲 + SSE 推送（可选）

    不写数据库。
    """
    logger = logging.getLogger("app")
    logger.setLevel(level)

    # 已配置过：只补 LogHub
    if logger.handlers:
        if log_hub is not None and log_hub not in logger.handlers:
            log_hub.setLevel(level)
            log_hub.setFormatter(logging.Formatter(_FMT, datefmt=_DATEFMT))
            logger.addHandler(log_hub)
        return logger

    fmt = logging.Formatter(_FMT, datefmt=_DATEFMT)

    # ---- 文件 handler ----
    fh = RotatingFileHandler(
        LOG_DIR / "app.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    fh.setFormatter(fmt)
    fh.setLevel(level)

    # ---- 控制台 handler ----
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    sh.setLevel(level)

    logger.addHandler(fh)
    logger.addHandler(sh)

    # ---- 内存 Hub handler（给 SSE 用，可选）----
    if log_hub is not None:
        log_hub.setLevel(level)
        log_hub.setFormatter(fmt)
        logger.addHandler(log_hub)

    # 禁止向 root logger 传播，避免重复输出
    logger.propagate = False

    return logger


def get_logger(name: str = "app") -> logging.Logger:
    """便捷获取子 logger。

    用法::

        log = get_logger(__name__)
        log.info("...")
    """
    if not name.startswith("app"):
        name = f"app.{name}"
    return logging.getLogger(name)