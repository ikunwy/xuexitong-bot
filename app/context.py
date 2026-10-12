from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.core.event_bus import EventBus
from app.db.base import SessionFactory
from app.db.repo import Repository
from app.utils.config import load_config
from app.utils.logger import setup_logging
from app.api.control import ControlChannel
from app.api.events_hub import EventHub
from app.core.commands import CommandQueue
from app.api.screencast import CDPScreencaster
from app.api.log_hub import LogHub

@dataclass
class AppContext:
    config: dict
    bus: EventBus
    logger: Any
    repo: Repository
    commands: CommandQueue = None      # ★ 新增
    control: ControlChannel = field(default_factory=ControlChannel)   # ← 新增
    engine: Any = None
    plugins: Any = None
    hub: EventHub = None      # ★ 新增
    log_hub: LogHub = None                # ★ 新增
    screencast: CDPScreencaster = None
    @classmethod
    def build(cls, config_path=None) -> "AppContext":
        cfg = load_config(config_path)

        # ★ 先建 LogHub，再初始化 logging，让日志从一开始就被捕获
        log_hub = LogHub(maxlen=2000)

        cfg["running"] = True # 刷课运行中
        cfg["paused"] = True # 刷课运行中
        cfg["step"] = None # 刷课步骤
        import logging
        level = getattr(logging, str(cfg.get("log_level", "INFO")).upper(), logging.INFO)
        logger = setup_logging(level, log_hub=log_hub)   # ★ 不传 db
        bus = EventBus()
        repo = Repository(SessionFactory)
        ctx = cls(
            config=cfg, bus=bus, logger=logger,
            repo=repo,
        )
        ctx.commands = CommandQueue(ctx)      # ★
        ctx.hub = EventHub(ctx)    # ★ 构造时立刻开始监听
        ctx.log_hub = log_hub                # ★ 存进 ctx
        ctx.screencast = CDPScreencaster(ctx, debug_port=9222)
        return ctx