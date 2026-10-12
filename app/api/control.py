from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field


@dataclass
class RunState:
    """主线程写入、API 读取的运行状态快照（只读）。"""
    running: bool = False
    paused: bool = False
    mode: str = ""
    current_url: str = ""
    current_course: str = ""
    started_at: float = 0.0
    finished_at: float = 0.0
    extra: dict = field(default_factory=dict)


class ControlChannel:
    """线程间控制通道。

    - 主线程（Engine）读：should_stop() / wait_if_paused()
    - API 线程写：pause() / resume() / stop()
    - 状态快照：主线程 set_state()，API 线程 get_state()
    """

    def __init__(self) -> None:
        self._pause_event = threading.Event()
        self._pause_event.set()          # 默认不暂停
        self._stop_event = threading.Event()
        self._state_lock = threading.Lock()
        self._state = RunState()

    # ---- 主线程调用 ----

    def should_stop(self) -> bool:
        return self._stop_event.is_set()

    def wait_if_paused(self, poll: float = 0.5) -> None:
        """在暂停状态下阻塞，直到 resume 或 stop。"""
        while not self._pause_event.is_set():
            if self._stop_event.is_set():
                return
            time.sleep(poll)

    def set_state(self, **kwargs) -> None:
        with self._state_lock:
            for k, v in kwargs.items():
                if hasattr(self._state, k):
                    setattr(self._state, k, v)

    # ---- API 线程调用 ----

    def pause(self) -> None:
        self._pause_event.clear()

    def resume(self) -> None:
        self._pause_event.set()

    def stop(self) -> None:
        self._stop_event.set()
        self._pause_event.set()          # 避免卡在暂停里

    def reset(self) -> None:
        self._stop_event.clear()
        self._pause_event.set()

    def get_state(self) -> dict:
        with self._state_lock:
            s = self._state
            return {
                "running": s.running,
                "paused": not self._pause_event.is_set(),
                "stopping": self._stop_event.is_set(),
                "mode": s.mode,
                "current_url": s.current_url,
                "current_course": s.current_course,
                "started_at": s.started_at,
                "finished_at": s.finished_at,
                "elapsed": (time.time() - s.started_at) if s.started_at else 0,
                "extra": dict(s.extra),
            }