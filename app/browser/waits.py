from __future__ import annotations

from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


def wait_visible(driver, by, locator, timeout: float = 10.0):
    return WebDriverWait(driver, timeout).until(
        EC.visibility_of_element_located((by, locator))
    )


def wait_present(driver, by, locator, timeout: float = 10.0):
    return WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located((by, locator))
    )


def wait_clickable(driver, by, locator, timeout: float = 10.0):
    return WebDriverWait(driver, timeout).until(
        EC.element_to_be_clickable((by, locator))
    )