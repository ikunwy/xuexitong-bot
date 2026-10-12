import sys

from app.context import AppContext
from app.core.engine import Engine
from app.core.events import Events
from app.plugins.loader import PluginLoader


def main() -> int:
    ctx = AppContext.build()

    # 建表
    from app.db.base import engine
    from app.db.models import Base
    Base.metadata.create_all(engine)

    # Engine 内部会订阅控制事件
    ctx.engine = Engine(ctx)

    # 插件
    ctx.plugins = PluginLoader(ctx)
    ctx.plugins.load_all()

    # 启动 API 子线程
    from app.api.server import start_api
    start_api(ctx)

    ctx.bus.emit(Events.APP_START, ctx=ctx)

    try:
        ctx.engine.run()
    except KeyboardInterrupt:
        ctx.logger.info("用户中断")
        ctx.bus.emit(Events.CONTROL_STOP)
    finally:
        ctx.bus.emit(Events.APP_EXIT, ctx=ctx)
        ctx.engine.shutdown()

    return 0


if __name__ == "__main__":
    sys.exit(main())