from __future__ import annotations

import logging
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

from app.utils.paths import CHROME_PROFILE_DIR, DRIVER_DIR

log = logging.getLogger("app.browser.driver")


def _build_options(cfg: dict) -> Options:
    opts = Options()
    # ★ 必须项，解决 Chrome 111+ 空白页/挂起
    opts.add_argument("--remote-allow-origins=*")
    # 常用稳定性参数
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")

    opts.add_argument("--remote-allow-origins=*")
    # ★ 关键：调试端口 + user-data-dir 必须成对出现
    opts.add_argument("--remote-debugging-port=9222")
    opts.add_argument("--remote-debugging-address=127.0.0.1")

    opts.add_argument("--disable-gpu")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)

    if cfg.get("headless"):
        opts.add_argument("--headless=new")

    size = cfg.get("window_size") or [0, 0]
    if size.lower().strip() == "max":
        opts.add_argument("--start-maximized")
    elif size.strip() == "":
        opts.add_argument(f"--window-size=1280,900")
    elif size[0] and size[1]:
        opts.add_argument(f"--window-size={size[0]},{size[1]}")

    profile = cfg.get("user_data_dir") or str(CHROME_PROFILE_DIR)
    opts.add_argument(f"--user-data-dir={profile}")
    return opts


def _build_service(cfg: dict) -> Service:
    """优先用本地 driver；没有则交给 webdriver-manager。"""
    local = cfg.get("driver_path") or ""
    candidates: list[Path] = []
    if local:
        candidates.append(Path(local))
    candidates.append(DRIVER_DIR / "chromedriver.exe")
    candidates.append(DRIVER_DIR / "chromedriver")

    for c in candidates:
        if c.exists():
            log.info("使用本地 driver: %s", c)
            return Service(executable_path=str(c))

    try:
        from webdriver_manager.chrome import ChromeDriverManager
        path = ChromeDriverManager().install()
        log.info("webdriver-manager 提供 driver: %s", path)
        return Service(executable_path=path)
    except Exception:
        log.exception("无法获取 chromedriver，请手动放到 %s", DRIVER_DIR)
        raise


def create_driver(cfg: dict) -> webdriver.Chrome:
    opts = _build_options(cfg)
    service = _build_service(cfg)
    driver = webdriver.Chrome(service=service, options=opts)
    
    driver.set_page_load_timeout(int(cfg.get("page_load_timeout", 30)))
    driver.implicitly_wait(int(cfg.get("implicit_wait", 0)))
    return driver