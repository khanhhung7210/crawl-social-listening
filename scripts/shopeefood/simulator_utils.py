from __future__ import annotations

import os
import time
from typing import Iterable

from appium import webdriver
from appium.options.android import UiAutomator2Options
from appium.webdriver.common.appiumby import AppiumBy
from selenium.common.exceptions import StaleElementReferenceException


APPIUM_SERVER_URL = os.getenv("APPIUM_SERVER_URL", "http://127.0.0.1:4723")
ANDROID_DEVICE_NAME = os.getenv("ANDROID_DEVICE_NAME", "emulator-5554")
SHOPEEFOOD_APP_PACKAGE = os.getenv("SHOPEEFOOD_APP_PACKAGE", "com.deliverynow")
SHOPEEFOOD_APP_ACTIVITY = os.getenv("SHOPEEFOOD_APP_ACTIVITY", "foody.vn.deliverynow.SplashActivity")
SHOPEEFOOD_APP_WAIT_ACTIVITY = os.getenv(
    "SHOPEEFOOD_APP_WAIT_ACTIVITY",
    "foody.vn.deliverynow.SplashActivity,com.foody.vn.ui.HomeActivity,*",
)


def build_android_driver() -> webdriver.Remote:
    options = UiAutomator2Options()
    options.platform_name = "Android"
    options.device_name = ANDROID_DEVICE_NAME
    options.app_package = SHOPEEFOOD_APP_PACKAGE
    options.app_activity = SHOPEEFOOD_APP_ACTIVITY
    options.app_wait_activity = SHOPEEFOOD_APP_WAIT_ACTIVITY
    options.no_reset = True
    options.automation_name = "UiAutomator2"
    driver = webdriver.Remote(APPIUM_SERVER_URL, options=options)
    time.sleep(2)
    return driver


def visible_texts(driver: webdriver.Remote) -> list[str]:
    elements = driver.find_elements(by=AppiumBy.CLASS_NAME, value="android.widget.TextView")
    texts: list[str] = []
    for element in elements:
        try:
            text = str(element.text or "").strip()
        except StaleElementReferenceException:
            continue
        if text:
            texts.append(text)
    return texts


def swipe_up(driver: webdriver.Remote, start_ratio: float = 0.78, end_ratio: float = 0.28, duration_ms: int = 450) -> None:
    size = driver.get_window_size()
    x = int(size["width"] * 0.5)
    start_y = int(size["height"] * start_ratio)
    end_y = int(size["height"] * end_ratio)
    driver.swipe(start_x=x, start_y=start_y, end_x=x, end_y=end_y, duration=duration_ms)


def unique_preserve_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered
