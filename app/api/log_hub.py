from __future__ import annotations

import logging
import queue
import threading
import time
from collections import deque
from typing import Any

log = logging.getLogger("app.log_hub")


class LogHub(logging.Handler):
    """日志收集中心。

    - 作为 logging.Handler 挂到根 logger 上
    - 环形缓冲保存最近 N 条
    - 每个 SSE 客户端一个独立 Queue
    - 支持级别过滤
    """

    def __init__(self, maxlen: int = 1000) -> None:
        super().__init__()
        self._buffer: deque[dict] = deque(maxlen=maxlen)
        self._subscribers: list[queue.Queue] = []
        self._lock = threading.RLock()
        self._seq = 0
        self._total = 0

    # ------------------------------------------------------------------
    # logging.Handler 接口
    # ------------------------------------------------------------------

    def emit(self, record: logging.LogRecord) -> None:
        try:
            item = self._make_item(record)
        except Exception:
            return

        with self._lock:
            self._buffer.append(item)
            self._total += 1

            dead = []
            for q in self._subscribers:
                try:
                    q.put_nowait(item)
                except queue.Full:
                    try:
                        q.get_nowait()
                        q.put_nowait(item)
                    except Exception:
                        dead.append(q)
            for q in dead:
                self._subscribers.remove(q)

    def _make_item(self, record: logging.LogRecord) -> dict:
        with self._lock:
            self._seq += 1
            seq = self._seq

        # 异常堆栈
        exc_text = ""
        if record.exc_info:
            exc_text = self.format(record) if self.formatter else ""

        return {
            "seq": seq,
            "ts": record.created,
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "filename": record.filename,
            "lineno": record.lineno,
            "thread": record.threadName,
            "exception": exc_text,
        }

    # ------------------------------------------------------------------
    # 订阅
    # ------------------------------------------------------------------

    def subscribe(self, maxsize: int = 500) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=maxsize)
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def recent(
        self,
        limit: int = 200,
        level: str | None = None,
        since_seq: int = 0,
        keyword: str | None = None,
    ) -> list[dict]:
        with self._lock:
            items = list(self._buffer)

        if since_seq:
            items = [x for x in items if x["seq"] > since_seq]
        if level:
            lv = level.upper()
            order = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}
            min_lv = order.get(lv, 0)
            items = [x for x in items if order.get(x["level"], 0) >= min_lv]
        if keyword:
            items = [x for x in items if keyword.lower() in x["message"].lower()]

        return items[-limit:]

    def stats(self) -> dict:
        with self._lock:
            return {
                "buffer_size": len(self._buffer),
                "subscribers": len(self._subscribers),
                "total_logs": self._total,
            }