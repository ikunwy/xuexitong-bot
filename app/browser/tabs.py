from __future__ import annotations

import logging
import time

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from app.core.events import Events

log = logging.getLogger("app.browser.tabs")


class TabSwitcher:
    def __init__(self, ctx, driver, frames=None) -> None:
        self.ctx = ctx
        self.driver = driver
        self.frames = frames
        self._history: list[str] = []

    # ---------------- 查询 ----------------

    def count(self) -> int:
        return len(self.driver.window_handles)

    def list_tabs(self) -> list[dict]:
        current = self.driver.current_window_handle
        out = []
        for h in self.driver.window_handles:
            try:
                self.driver.switch_to.window(h)
                out.append({
                    "handle": h,
                    "url": self.driver.current_url,
                    "title": self.driver.title,
                    "current": h == current,
                })
            except Exception:
                out.append({"handle": h, "url": "", "title": "", "current": h == current})
        self.driver.switch_to.window(current)
        return out

    def current(self) -> dict:
        return {
            "handle": self.driver.current_window_handle,
            "url": self.driver.current_url,
            "title": self.driver.title,
            "target_id": self._get_current_target_id(),      # ★
        }

    # ---------------- 切换 ----------------

    def switch_to(self, handle: str) -> bool:
        if handle == self.driver.current_window_handle:
            return True
        prev = self.driver.current_window_handle
        try:
            self.driver.switch_to.window(handle)
        except Exception:
            log.exception("切换到标签页失败: %s", handle)
            return False

        if prev and (not self._history or self._history[-1] != prev):
            self._history.append(prev)

        self._on_switched(handle)
        return True

    def switch_to_index(self, index: int) -> bool:
        handles = self.driver.window_handles
        if not handles or index >= len(handles) or index < -len(handles):
            log.warning("标签页索引越界: %d (共 %d 个)", index, len(handles))
            return False
        return self.switch_to(handles[index])

    def switch_to_last(self) -> bool:
        handles = self.driver.window_handles
        return self.switch_to(handles[-1]) if handles else False

    def switch_to_first(self) -> bool:
        handles = self.driver.window_handles
        return self.switch_to(handles[0]) if handles else False

    def switch_to_url(self, keyword: str, timeout: float = 10.0) -> bool:
        return self._switch_by(lambda: self._scan_url(keyword), timeout, f"url~{keyword}")

    def switch_to_title(self, keyword: str, timeout: float = 10.0) -> bool:
        return self._switch_by(lambda: self._scan_title(keyword), timeout, f"title~{keyword}")

    def switch_back(self) -> bool:
        if not self._history:
            return False
        target = self._history.pop()
        if target == self.driver.current_window_handle:
            return self.switch_back()
        try:
            self.driver.switch_to.window(target)
            self._on_switched(target)
            return True
        except Exception:
            log.exception("回退标签页失败")
            return False

    # ---------------- 关闭 ----------------

    def close_current(self) -> dict:
        handles = self.driver.window_handles
        if len(handles) <= 1:
            return {"ok": False, "reason": "last_tab"}
        closed = self.driver.current_window_handle
        self.driver.close()
        remaining = self.driver.window_handles
        if remaining:
            self.driver.switch_to.window(remaining[0])
            self._on_switched(remaining[0])
        return {"ok": True, "closed": closed, "current": self.driver.current_url}

    def close_by_handle(self, handle: str) -> dict:
        handles = self.driver.window_handles
        if len(handles) <= 1:
            return {"ok": False, "reason": "last_tab"}
        if handle not in handles:
            return {"ok": False, "reason": "not_found"}
        current = self.driver.current_window_handle
        self.driver.switch_to.window(handle)
        self.driver.close()
        remaining = self.driver.window_handles
        if current in remaining:
            self.driver.switch_to.window(current)
        elif remaining:
            self.driver.switch_to.window(remaining[0])
        self._on_switched(self.driver.current_window_handle)
        return {"ok": True, "closed": handle}

    def close_by_index(self, index: int) -> dict:
        handles = self.driver.window_handles
        if index >= len(handles) or index < -len(handles):
            return {"ok": False, "reason": "index_out_of_range"}
        return self.close_by_handle(handles[index])

    def close_by_url(self, keyword: str) -> dict:
        h = self._scan_url(keyword)
        if not h:
            return {"ok": False, "reason": "not_found"}
        return self.close_by_handle(h)

    def close_others(self) -> dict:
        current = self.driver.current_window_handle
        closed = []
        for h in list(self.driver.window_handles):
            if h == current:
                continue
            try:
                self.driver.switch_to.window(h)
                self.driver.close()
                closed.append(h)
            except Exception:
                log.exception("关闭标签页失败: %s", h)
        self.driver.switch_to.window(current)
        self._on_switched(current)
        return {"ok": True, "closed": closed, "remaining": len(self.driver.window_handles)}

    # ---------------- 打开 ----------------

    def open_new(self, url: str = "about:blank", switch: bool = True) -> str:
        old = set(self.driver.window_handles)
        self.driver.execute_script(f"window.open('{url}', '_blank');")
        WebDriverWait(self.driver, 10).until(
            lambda d: len(set(d.window_handles) - old) > 0
        )
        new_handle = (set(self.driver.window_handles) - old).pop()
        if switch:
            self.switch_to(new_handle)
        return new_handle

    def wait_new_tab(self, timeout: float = 10.0, switch: bool = True) -> str | None:
        old = set(self.driver.window_handles)
        try:
            WebDriverWait(self.driver, timeout).until(
                lambda d: len(set(d.window_handles) - old) > 0
            )
        except Exception:
            return None
        new_handle = (set(self.driver.window_handles) - old).pop()
        if switch:
            self.switch_to(new_handle)
        return new_handle

    # ---------------- 内部 ----------------

    def _on_switched(self, handle: str) -> None:
        """切换窗口后：复位 iframe + 广播事件（带 targetId）。"""
        if self.frames is not None:
            self.frames.switch_to_default()

        # ★ 通过 CDP 拿到当前活跃 target 的 id
        target_id = self._get_current_target_id()

        try:
            url = self.driver.current_url
            title = self.driver.title
        except Exception:
            url, title = "", ""

        self.ctx.bus.emit(
            Events.TAB_SWITCH,
            handle=handle,
            url=url,
            title=title,
            target_id=target_id,      # ★ 关键
        )

    def _get_current_target_id(self) -> str | None:
        """通过 CDP 拿到当前活跃 page target 的 id。"""
        # 优先 CDP 精准拿
        try:
            info = self.driver.execute_cdp_cmd("Target.getTargetInfo", {})
            tid = info.get("targetInfo", {}).get("targetId")
            if tid:
                return tid
        except Exception:
            log.debug("Target.getTargetInfo 失败，回退到 /json 匹配")

        # 兜底：按 URL 匹配 /json
        try:
            import requests
            current_url = self.driver.current_url
            r = requests.get("http://127.0.0.1:9222/json", timeout=3)
            for t in r.json():
                if t.get("type") == "page" and t.get("url") == current_url:
                    return t.get("id")
        except Exception:
            pass

        return None

    def _switch_by(self, scanner, timeout, tag) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            h = scanner()
            if h:
                return self.switch_to(h)
            time.sleep(0.5)
        log.warning("切换标签页超时 (%s)", tag)
        return False

    def _scan_url(self, keyword: str) -> str | None:
        kw = keyword.lower()
        current = self.driver.current_window_handle
        try:
            for h in self.driver.window_handles:
                self.driver.switch_to.window(h)
                if kw in (self.driver.current_url or "").lower():
                    self.driver.switch_to.window(current)
                    return h
        finally:
            self.driver.switch_to.window(current)
        return None

    def _scan_title(self, keyword: str) -> str | None:
        kw = keyword.lower()
        current = self.driver.current_window_handle
        try:
            for h in self.driver.window_handles:
                self.driver.switch_to.window(h)
                if kw in (self.driver.title or "").lower():
                    self.driver.switch_to.window(current)
                    return h
        finally:
            self.driver.switch_to.window(current)
        return None