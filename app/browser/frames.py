from __future__ import annotations

import logging
import time
from typing import Iterable

from selenium.common.exceptions import (
    NoSuchFrameException,
    TimeoutException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from app.core.events import Events

log = logging.getLogger("app.browser.frames")


class FrameSwitcher:
    """iframe 切换工具。

    用法::

        fs = FrameSwitcher(ctx, driver)
        fs.switch_to(id="frame_content")            # 按 id
        fs.switch_to(name="frame_content")          # 按 name
        fs.switch_to(index=0)                       # 按序号
        fs.switch_to(css="iframe.xxx")              # 按 CSS
        fs.switch_to(xpath="//iframe[@id='x']")     # 按 XPath
        fs.switch_to(contains="course")             # 按 src/name/id 关键字
        fs.switch_back()                            # 回上一层
        fs.switch_to_default()                      # 回最外层
    """

    def __init__(self, ctx, driver: WebDriver) -> None:
        self.ctx = ctx
        self.driver = driver
        # 记录切换路径，每个元素是 (by, value) 或 ('index', n)
        self._stack: list[tuple[str, object]] = []

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------

    def switch_to(
        self,
        *,
        id: str | None = None,
        name: str | None = None,
        index: int | None = None,
        css: str | None = None,
        xpath: str | None = None,
        element: WebElement | None = None,
        contains: str | None = None,
        timeout: float = 10.0,
        poll: float = 0.3,
    ) -> bool:
        locator = self._resolve_locator(
            id=id, name=name, index=index,
            css=css, xpath=xpath, element=element, contains=contains,
        )
        if locator is None:
            log.error("switch_to 未提供任何有效定位参数")
            return False

        by, value = locator
        try:
            if by == "index":
                self._wait_frame_count_at_least(int(value) + 1, timeout, poll)
                self.driver.switch_to.frame(int(value))
            elif by == "element":
                self._wait_element_ready(value, timeout)   # type: ignore[arg-type]
                self.driver.switch_to.frame(value)         # type: ignore[arg-type]
            elif by == "css-list":
                # ★ 多选择器：任一命中即可
                matched = self._wait_any_css(list(value), timeout, poll)  # type: ignore[arg-type]
                if matched is None:
                    log.warning("多个 CSS 选择器均未命中: %s", value)
                    return False
                self.driver.switch_to.frame(matched)
            else:
                # ★ 这里直接完成"等待 + 切换"，不再额外 switch
                WebDriverWait(self.driver, timeout, poll_frequency=poll).until(
                    EC.frame_to_be_available_and_switch_to_it((by, value))
                )

            self._stack.append((by, value))
            # log.info("已切入 iframe: %s=%s (深度 %d)", by, value, len(self._stack))
            self.ctx.bus.emit(
                Events.FRAME_ENTER,
                by=by, value=str(value), depth=len(self._stack),
            )
            return True

        except TimeoutException:
            log.warning("切换 iframe 超时: %s=%s", by, value)
        except NoSuchFrameException:
            log.warning("iframe 不存在: %s=%s", by, value)
        except Exception:
            log.exception("切换 iframe 异常: %s=%s", by, value)

        self.ctx.bus.emit(
            Events.FRAME_ERROR, by=by, value=str(value), action="switch_to",
        )
        return False

    # ------------------------------------------------------------------
    # 返回 / 复位
    # ------------------------------------------------------------------

    def switch_back(self) -> bool:
        """回退到上一层 iframe（相对于当前上下文）。"""
        try:
            self.driver.switch_to.parent_frame()
            if self._stack:
                self._stack.pop()
            log.info("已返回上一层 iframe (当前深度 %d)", len(self._stack))
            self.ctx.bus.emit(Events.FRAME_EXIT, depth=len(self._stack))
            return True
        except Exception:
            log.exception("返回上一层 iframe 失败")
            return False

    def switch_to_default(self) -> None:
        """回到最外层（默认文档上下文）。"""
        self.driver.switch_to.default_content()
        self._stack.clear()
        self.ctx.bus.emit(Events.FRAME_EXIT, depth=0)

    @property
    def depth(self) -> int:
        """当前嵌套深度。"""
        return len(self._stack)

    # ------------------------------------------------------------------
    # 上下文管理器（推荐用法）
    # ------------------------------------------------------------------

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.switch_to_default()
        return False

    # ------------------------------------------------------------------
    # 内部：定位解析
    # ------------------------------------------------------------------

    def _resolve_locator(
    self,
    id=None, name=None, index=None, css=None, xpath=None,
    element=None, contains=None,
    ) -> tuple[str, object] | None:
        if element is not None:
            return ("element", element)
        if id:
            return (By.ID, id)
        if name:
            return (By.NAME, name)
        if css:
            # ★ 支持 css 传列表
            if isinstance(css, (list, tuple)):
                return ("css-list", list(css))
            return (By.CSS_SELECTOR, css)
        if xpath:
            return (By.XPATH, xpath)
        if index is not None:
            return ("index", index)
        if contains:
            return self._locate_by_contains(contains)
        return None

    def _locate_by_contains(self, keyword: str) -> tuple[str, object] | None:
        """在页面上找 src/name/id 里含关键字的 iframe。"""
        kw = keyword.lower()
        try:
            frames = self.driver.find_elements(By.TAG_NAME, "iframe")
        except Exception:
            return None

        for f in frames:
            for attr in ("src", "name", "id"):
                val = (f.get_attribute(attr) or "").lower()
                if kw in val:
                    log.info("按关键字 '%s' 命中 iframe: %s=%s",
                             keyword, attr, val[:80])
                    return ("element", f)
        log.warning("按关键字 '%s' 未找到匹配的 iframe", keyword)
        return None

    def reset_to(
        self,
        *,
        id: str | None = None,
        name: str | None = None,
        index: int | None = None,
        css: str | None = None,
        xpath: str | None = None,
        contains: str | None = None,
        timeout: float = 10.0,
    ) -> bool:
        """从任意嵌套深度直接回到顶层，再切入指定 iframe。

        等价于：switch_to_default() + switch_to(...)。
        不传任何定位参数时，效果等同 switch_to_default()。
        """
        self.switch_to_default()

        if not any((id, name, index is not None, css, xpath, contains)):
            log.info("reset_to 无定位参数，已停留在顶层")
            return True

        return self.switch_to(
            id=id, name=name, index=index,
            css=css, xpath=xpath, contains=contains,
            timeout=timeout,
        )

    # ------------------------------------------------------------------
    # 内部：等待
    # ------------------------------------------------------------------
        WebDriverWait(self.driver, timeout, poll_frequency=poll).until(
            EC.frame_to_be_available_and_switch_to_it((by, value))
        )
        # ⚠️ 上面的 EC 会直接切换，所以下面切一次是冗余但安全的做法
        # 为保持结构统一，这里改用只等待的方式：
        # 实际上 EC.frame_to_be_available_and_switch_to_it 已经切了，
        # 因此我们把切换也放在这里完成。
        # 为了避免重复切换，让上层不再执行 switch_to.frame
        # —— 见下方改造说明。

    def _wait_frame_count_at_least(self, n: int, timeout: float, poll: float) -> None:
        WebDriverWait(self.driver, timeout, poll_frequency=poll).until(
            lambda d: len(d.find_elements(By.TAG_NAME, "iframe")) >= n
        )

    def _wait_element_ready(self, el: WebElement, timeout: float) -> None:
        WebDriverWait(self.driver, timeout).until(
            lambda d: el.is_displayed() or True
        )

    def _wait_any_css(self, selectors: list[str], timeout: float, poll: float) -> WebElement | None:
        """在 timeout 内轮询，返回第一个命中的 iframe 元素。

        - 支持多个 CSS 选择器
        - 一个都没命中则返回 None
        - 命中即返回，不再等其它
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            for sel in selectors:
                try:
                    els = self.driver.find_elements(By.CSS_SELECTOR, sel)
                except Exception:
                    continue
                if els:
                    # log.info("多选择器命中: %s", sel)
                    return els[0]
            time.sleep(poll)
        return None