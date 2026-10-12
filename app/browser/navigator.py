from __future__ import annotations

import logging

from app.core.events import Events
from selenium.webdriver.support.ui import WebDriverWait

log = logging.getLogger("app.browser.navigator")


class Navigator:
    """统一封装页面跳转，每次跳转后自动触发 PAGE_ENTER 事件。"""

    def __init__(self, ctx, driver) -> None:
        self.ctx = ctx
        self.driver = driver
        from app.browser.frames import FrameSwitcher
        from app.browser.tabs import TabSwitcher
        self.frames = FrameSwitcher(ctx, driver)   # ← 新增
        self.tabs = TabSwitcher(ctx, driver, frames=self.frames)   # ★

    def forward(self, times: int = 1) -> bool:
        """前进（浏览器历史）。"""
        for _ in range(times):
            try:
                self.driver.forward()
                WebDriverWait(self.driver, 10).until(
                    lambda d: d.execute_script("return document.readyState") == "complete"
                )
                self.frames.switch_to_top()
                url, title = self.current()
                self.ctx.bus.emit(Events.PAGE_ENTER, url=url, title=title, referer="")
            except Exception:
                log.exception("forward() 失败")
                return False
        return True

    def get(self, url: str, referer: str | None = None) -> None:
        log.info("打开页面: %s", url)
        prev = self.driver.current_url
        self.driver.get(url)
        # 页面跳转后帧上下文失效，自动复位
        self.frames.switch_to_default()
        title = self.driver.title
        self.ctx.bus.emit(
            Events.PAGE_ENTER, url=url, title=title, referer=referer or prev,
        )

    def current(self) -> tuple[str, str]:
        return self.driver.current_url, self.driver.title

    def quit(self) -> None:
        try:
            self.driver.quit()
            log.info("浏览器已关闭")
        except Exception:
            log.exception("关闭浏览器失败")

    def back(self, times: int = 1) -> bool:
        """返回上一页（可多次）。

        优先用 driver.back()，失败则用 history.go(-1)。
        """
        for i in range(times):
            try:
                self.driver.back()
                # 等页面稳定
                WebDriverWait(self.driver, 10).until(
                    lambda d: d.execute_script(
                        "return document.readyState") == "complete"
                )
                self.frames.switch_to_default()      # ← 新增
                url, title = self.current()
                log.info("已返回上一页: %s | %s", title, url)
                self.ctx.bus.emit(
                    Events.PAGE_ENTER, url=url, title=title, referer=""
                )
            except Exception:
                log.exception("back() 失败，尝试 history.go(-1)")
                try:
                    self.driver.execute_script(f"history.go(-{times - i})")
                except Exception:
                    log.exception("history.go 也失败了")
                    return False
        return True

    def go_to(self, url: str) -> None:
        """直接跳转到指定 URL（不压入历史时可用 JS）。"""
        self.get(url)