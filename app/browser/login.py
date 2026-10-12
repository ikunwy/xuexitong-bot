from __future__ import annotations

import logging
import time

from selenium.webdriver.common.by import By

from app.core.events import Events

log = logging.getLogger("app.browser.login")


class LoginPage:
    """学习通登录页封装。所有地址、选择器从配置读取。"""

    def __init__(self, ctx, navigator) -> None:
        self.ctx = ctx
        self.nav = navigator
        self.driver = navigator.driver

        self.cfg = ctx.config.get("login", {})
        self.url: str = self.cfg.get("url", "https://v8.chaoxing.com/")
        self.wait_seconds: float = float(self.cfg.get("wait_seconds", 15))
        self.poll_interval: float = float(self.cfg.get("poll_interval", 0.5))
        self.redirect_timeout: float = float(self.cfg.get("redirect_timeout", 20))

        sels = self.cfg.get("selectors", {})
        self.BY_PHONE     = self._parse_selector(sels.get("phone"))
        self.BY_PWD       = self._parse_selector(sels.get("pwd"))
        self.BY_LOGIN_BTN = self._parse_selector(sels.get("login_btn"))
        self.BY_SUCCESS_SELECTOR = self._parse_selector(sels.get("success_selector"))

    # ---------- 打开登录页 ----------

    def open(self) -> None:
        log.info("打开登录页: %s", self.url)
        self.nav.get(self.url)  

    # ---------- 等待输入 + 监听 ----------

    def login(self) -> bool:
        self.open()
        log.info("请在 %.0f 秒内完成输入（自动检测输入后提交）", self.wait_seconds)

        deadline = time.time() + self.wait_seconds
        submitted = False
        username = self.cfg.get("username", "")
        password = self.cfg.get("password", "")
        if username and password:
            self._autofill(username, password)
        while time.time() < deadline:
            phone_val = self._read_value(self.BY_PHONE)
            pwd_val = self._read_value(self.BY_PWD)

            # 检测验证码容器
            captcha = self.driver.find_elements(By.CSS_SELECTOR, ".captcha-img, #captcha")
            if captcha and not getattr(self, "_captcha_warned", False):
                log.warning("检测到验证码，请在浏览器中手动完成，程序将继续等待")
                self._captcha_warned = True
            
            if phone_val and pwd_val:
                self._click_login()
                submitted = True
                break

            time.sleep(self.poll_interval)

        if not submitted:
            log.warning("等待超时，尝试强制点击登录")
            self._click_login()

        return self.wait_logged_in()

    # ---------- 辅助 ----------

    def _autofill(self, username: str, password: str) -> None:
        try:
            self.driver.find_element(*self.BY_PHONE).send_keys(username)
            self.driver.find_element(*self.BY_PWD).send_keys(password)
            log.info("已自动填充账号密码")
        except Exception:
            log.exception("自动填充失败")

    def _read_value(self, by_locator) -> str:
        try:
            el = self.driver.find_element(*by_locator)
            return (el.get_attribute("value") or "").strip()
        except Exception:
            return ""

    def _click_login(self) -> None:
        try:
            self.driver.find_element(*self.BY_LOGIN_BTN).click()
            log.info("已点击登录按钮")
        except Exception:
            log.exception("点击登录按钮失败")

    def wait_logged_in(self) -> bool:
        log.info("等待登录跳转...")
        deadline = time.time() + (self.redirect_timeout * 1000)
        while time.time() < deadline:
            url = self.driver.current_url
            success_selector_ele = self.driver.find_elements(*self.BY_SUCCESS_SELECTOR)
            if success_selector_ele:
                log.info("登录成功，当前页面: %s", url)
                success_selector_ele[0].click() # 进入首页
                self.ctx.bus.emit(Events.LOGIN_SUCCESS, url=url)
                return True
            time.sleep(1)
        log.warning("等待登录跳转超时，当前 URL: %s", self.driver.current_url)
        return False
    
    def _parse_selector(self, raw: str) -> tuple:
        """支持 'id:phone' / 'css:#phone' / 'xpath://input[@id=\"phone\"]' 三种写法。
        不写前缀时默认按 id。"""
        if ":" in raw:
            kind, _, value = raw.partition(":")
            kind = kind.strip().lower()
            mapping = {
                "id": By.ID,
                "css": By.CSS_SELECTOR,
                "xpath": By.XPATH,
                "name": By.NAME,
                "class": By.CLASS_NAME,
                "tag": By.TAG_NAME,
            }
            return (mapping.get(kind, By.ID), value)
        return (By.ID, raw)