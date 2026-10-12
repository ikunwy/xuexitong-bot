from __future__ import annotations

import inspect
import logging
import threading
from collections import defaultdict
from typing import Any, Callable

log = logging.getLogger("app.bus")


class EventBus:
    """线程安全事件总线。

    - on(event, fn)    订阅指定事件
    - on_all(fn)       订阅所有事件（handler 会收到 event 参数）
    - emit(event, **kw) 广播事件
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[tuple[int, Callable]]] = defaultdict(list)
        self._all_handlers: list[tuple[int, Callable]] = []
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # 订阅
    # ------------------------------------------------------------------

    def on(self, event: str, handler: Callable | None = None, priority: int = 0):
        if handler is None:
            def deco(fn: Callable):
                self.on(event, fn, priority)
                return fn
            return deco
        with self._lock:
            self._handlers[event].append((priority, handler))
            self._handlers[event].sort(key=lambda x: -x[0])
        return handler

    def on_all(self, handler: Callable | None = None, priority: int = 0):
        if handler is None:
            def deco(fn: Callable):
                self.on_all(fn, priority)
                return fn
            return deco
        with self._lock:
            self._all_handlers.append((priority, handler))
            self._all_handlers.sort(key=lambda x: -x[0])
        return handler

    # ------------------------------------------------------------------
    # 退订
    # ------------------------------------------------------------------

    def off(self, event: str, handler: Callable) -> None:
        with self._lock:
            self._handlers[event] = [
                h for h in self._handlers[event] if h[1] is not handler
            ]

    def off_all(self, handler: Callable) -> None:
        with self._lock:
            self._all_handlers = [
                h for h in self._all_handlers if h[1] is not handler
            ]

    # ------------------------------------------------------------------
    # 广播
    # ------------------------------------------------------------------

    def emit(self, event: str, **payload: Any) -> None:
        with self._lock:
            handlers = list(self._handlers.get(event, ()))
            all_handlers = list(self._all_handlers)

        for _, fn in handlers:
            self._safe_call(fn, event, payload, with_event=False)

        for _, fn in all_handlers:
            self._safe_call(fn, event, payload, with_event=True)

    @staticmethod
    def _safe_call(fn, event: str, payload: dict, with_event: bool) -> None:
        try:
            if inspect.iscoroutinefunction(fn):
                log.warning("暂不支持 async handler: %s", fn)
                return
            if with_event:
                fn(event=event, **payload)
            else:
                fn(**payload)
        except Exception:
            log.exception("事件 %s 的 handler %s 执行失败", event, fn)