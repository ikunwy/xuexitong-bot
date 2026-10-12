from __future__ import annotations

import logging
import queue
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable

log = logging.getLogger("app.api.hub")


@dataclass
class _Waiter:
    event: str
    predicate: Callable[[dict], bool] | None
    done: threading.Event = field(default_factory=threading.Event)
    collected: list[dict] = field(default_factory=list)
    expect_count: int = 1


class EventHub:
    """事件收集中心。

    职责：
    - 订阅 EventBus 所有事件
    - 保存最近 N 条到环形缓冲，供 REST 查询
    - 给每个 SSE 客户端一个独立 Queue 实时推送
    - 支持 wait(event) 一次性阻塞等待，供 API 请求-响应模式
    """

    def __init__(self, ctx, maxlen: int = 500) -> None:
        self.ctx = ctx
        self._buffer: deque[dict] = deque(maxlen=maxlen)
        self._subscribers: list[queue.Queue] = []
        self._waiters: list[_Waiter] = []
        self._lock = threading.RLock()
        self._seq = 0

        # 优先级最低，保证业务 handler 先跑完
        ctx.bus.on_all(self._on_event, priority=-100)

    # ------------------------------------------------------------------
    # EventBus → Hub
    # ------------------------------------------------------------------

    def _on_event(self, event: str, **payload: Any) -> None:
        record = {
            "seq": self._next_seq(), # 递增序号，用于排序
            "ts": time.time(), # 时间戳，用于排序
            "event": event, # 事件名
            "payload": self._safe_payload(payload), # 事件负载
        }

        with self._lock:
            # 1. 环形缓冲
            self._buffer.append(record)

            # 2. SSE 订阅者
            dead: list[queue.Queue] = []
            for q in self._subscribers:
                try:
                    q.put_nowait(record)
                except queue.Full:
                    try:
                        q.get_nowait()
                        q.put_nowait(record)
                    except Exception:
                        dead.append(q)
            for q in dead:
                self._subscribers.remove(q)

            # 3. one-shot waiters
            done_waiters: list[_Waiter] = []
            for w in self._waiters:
                if w.event != event:
                    continue
                if w.predicate is not None:
                    try:
                        if not w.predicate(record):
                            continue
                    except Exception:
                        log.exception("waiter predicate 异常，忽略该事件")
                        continue
                w.collected.append(record)
                if len(w.collected) >= w.expect_count:
                    w.done.set()
                    done_waiters.append(w)

            for w in done_waiters:
                if w in self._waiters:
                    self._waiters.remove(w)

    def _next_seq(self) -> int:
        with self._lock:
            self._seq += 1
            return self._seq

    @staticmethod
    def _safe_payload(payload: dict) -> dict:
        out = {}
        for k, v in payload.items():
            if isinstance(v, (str, int, float, bool, type(None), list, dict)):
                out[k] = v
            else:
                out[k] = repr(v)
        return out

    # ------------------------------------------------------------------
    # 一次性等待
    # ------------------------------------------------------------------

    def wait(
        self,
        event: str,
        timeout: float = 30.0,
        predicate: Callable[[dict], bool] | None = None,
    ) -> dict | None:
        results = self.wait_many(event, count=1, timeout=timeout, predicate=predicate)
        return results[0] if results else None

    def wait_many(
        self,
        event: str,
        count: int = 1,
        timeout: float = 30.0,
        predicate: Callable[[dict], bool] | None = None,
    ) -> list[dict]:
        if count < 1:
            return []
        w = _Waiter(event=event, predicate=predicate, expect_count=count)

        with self._lock:
            self._waiters.append(w)

        try:
            if timeout and timeout > 0:
                w.done.wait(timeout)
            else:
                w.done.wait()
        finally:
            with self._lock:
                if w in self._waiters:
                    self._waiters.remove(w)

        return list(w.collected)

    # ------------------------------------------------------------------
    # SSE 订阅
    # ------------------------------------------------------------------

    def subscribe(self, maxsize: int = 200) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=maxsize)
        with self._lock:
            self._subscribers.append(q)
        log.info("SSE 订阅者接入，当前 %d 个", len(self._subscribers))
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)
        log.info("SSE 订阅者断开，剩余 %d 个", len(self._subscribers))

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def recent(
        self,
        limit: int = 100,
        event: str | None = None,
        since_seq: int = 0,
    ) -> list[dict]:
        with self._lock:
            items = list(self._buffer)
        if since_seq:
            items = [x for x in items if x["seq"] > since_seq]
        if event:
            items = [x for x in items if x["event"] == event]
        return items[-limit:]

    def stats(self) -> dict:
        with self._lock:
            return {
                "buffer_size": len(self._buffer),
                "subscribers": len(self._subscribers),
                "waiters": len(self._waiters),
                "total_emitted": self._seq,
            }