from __future__ import annotations

import abc
import logging
import time

class BaseTask(abc.ABC):
    """所有任务必须继承此类。"""

    name: str = "base"

    def __init__(self, ctx, navigator) -> None:
        self.ctx = ctx
        self.nav = navigator
        self.driver = navigator.driver
        self.log = logging.getLogger(f"app.task.{self.name}")

    @abc.abstractmethod
    def run(self, **kwargs) -> dict:
        """执行任务，返回结果 dict。"""
        raise NotImplementedError

    def emit(self, event: str, **payload) -> None:
        self.ctx.bus.emit(event, task=self.name, **payload)

    def check_control(self) -> bool:
        """在任务长循环里调用。返回 False 表示应终止。"""
        try:
            self.ctx.commands.process_pending()
        except Exception:
            self.log.exception("处理命令异常")

        eng = self.ctx.engine
        while eng.paused and eng.running:
            try:
                self.ctx.commands.process_pending()
            except Exception:
                pass
            time.sleep(0.5)
        return eng.running