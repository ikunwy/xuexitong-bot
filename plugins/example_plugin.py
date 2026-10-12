"""示例插件：把关键事件写库 + 打印。"""
from app.core.events import Events


def setup(ctx):
    @ctx.bus.on(Events.APP_START, priority=10)
    def _on_start(**_):
        ctx.logger.info("[插件] 程序启动")

    @ctx.bus.on(Events.PAGE_ENTER)
    def _on_page(url, title, referer, **_):
        ctx.logger.info("[插件] 进入页面: %s | %s", title, url)
        ctx.repo.add_record(event="page.enter", message=title[:80])

    @ctx.bus.on(Events.VIDEO_PROGRESS)
    def _on_progress(percent, current, total, **_):
        ctx.logger.info(
            "[插件] 播放进度 %.1f%% (%.1f/%.1f)", percent * 100, current, total
        )

    @ctx.bus.on(Events.VIDEO_FINISH)
    def _on_finish(status, percent, **_):
        ctx.repo.add_record(event="video.finish", message=f"{status} {percent}")

    @ctx.bus.on(Events.TASK_ERROR)
    def _on_error(task, exc, retry, **_):
        ctx.logger.error("[插件] 任务 %s 出错 (retry=%s): %s", task, retry, exc)