from __future__ import annotations

import logging
import queue
import threading
import time
import uuid
from typing import Any, Callable

log = logging.getLogger("app.commands")


class CommandTask:
    """一个待执行的命令。"""

    __slots__ = (
        "id", "name", "kwargs", "done", "result", "error",
        "created_at", "finished_at", "executed_by",
    )

    def __init__(self, name: str, kwargs: dict) -> None:
        self.id = uuid.uuid4().hex[:12]
        self.name = name
        self.kwargs = kwargs
        self.done = threading.Event()
        self.result: Any = None
        self.error: str | None = None
        self.created_at = time.time()
        self.finished_at: float | None = None
        self.executed_by: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "kwargs": self.kwargs,
            "done": self.done.is_set(),
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
            "elapsed": (self.finished_at or time.time()) - self.created_at,
            "executed_by": self.executed_by,
        }


class CommandQueue:
    """跨线程命令队列。

    API 线程：submit() 提交，task.done.wait() 等待
    主线程：process_pending() 在挂起点处理
    """

    def __init__(self, ctx) -> None:
        self.ctx = ctx
        self._queue: queue.Queue[CommandTask] = queue.Queue()
        self._handlers: dict[str, Callable] = {}
        self._lock = threading.RLock()
        self._pending: dict[str, CommandTask] = {}
        self._history: list[CommandTask] = []      # 最近执行过的（用于审计）
        self._history_max = 200
        self._total_submitted = 0
        self._total_executed = 0

    # ------------------------------------------------------------------
    # 注册
    # ------------------------------------------------------------------

    def register(self, name: str, handler: Callable, override: bool = False) -> None:
        with self._lock:
            if name in self._handlers and not override:
                log.warning("命令 %s 已注册，忽略", name)
                return
            self._handlers[name] = handler
            log.info("注册命令: %s", name)

    def unregister(self, name: str) -> None:
        with self._lock:
            self._handlers.pop(name, None)

    def list_commands(self) -> list[str]:
        with self._lock:
            return sorted(self._handlers.keys())

    # ------------------------------------------------------------------
    # 提交（API 线程）
    # ------------------------------------------------------------------

    def submit(self, name: str, kwargs: dict | None = None) -> CommandTask:
        with self._lock:
            if name not in self._handlers:
                raise KeyError(f"未注册的命令: {name}")
            task = CommandTask(name=name, kwargs=kwargs or {})
            self._pending[task.id] = task
            self._total_submitted += 1
        self._queue.put(task)
        log.info("[提交] 命令 %s (id=%s) kwargs=%s", name, task.id, task.kwargs)
        return task

    # ------------------------------------------------------------------
    # 执行（主线程）
    # ------------------------------------------------------------------

    def process_pending(self, max_count: int = 8) -> int:
        """在主线程的挂起点调用。返回本次处理的命令数。"""
        processed = 0
        for _ in range(max_count):
            try:
                task = self._queue.get_nowait()
            except queue.Empty:
                break

            self._execute(task)
            processed += 1
        return processed

    def _execute(self, task: CommandTask) -> None:
        with self._lock:
            handler = self._handlers.get(task.name)

        try:
            if handler is None:
                task.error = f"未注册的命令: {task.name}"
                log.warning("[执行] 命令 %s 未注册", task.name)
            else:
                log.info("[执行] 命令 %s (id=%s)", task.name, task.id)
                task.result = handler(**task.kwargs)
                task.executed_by = threading.current_thread().name

        except Exception as exc:
            task.error = f"{type(exc).__name__}: {exc}"
            log.exception("[执行] 命令 %s 失败", task.name)

        finally:
            task.finished_at = time.time()
            task.done.set()

            with self._lock:
                self._pending.pop(task.id, None)
                self._history.append(task)
                if len(self._history) > self._history_max:
                    self._history = self._history[-self._history_max:]
                self._total_executed += 1

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def get_task(self, task_id: str) -> CommandTask | None:
        with self._lock:
            if task_id in self._pending:
                return self._pending[task_id]
            for t in reversed(self._history):
                if t.id == task_id:
                    return t
        return None

    def stats(self) -> dict:
        with self._lock:
            return {
                "registered": len(self._handlers),
                "pending": len(self._pending),
                "queued": self._queue.qsize(),
                "total_submitted": self._total_submitted,
                "total_executed": self._total_executed,
                "commands": sorted(self._handlers.keys()),
            }

    def history(self, limit: int = 50) -> list[dict]:
        with self._lock:
            return [t.to_dict() for t in self._history[-limit:]]