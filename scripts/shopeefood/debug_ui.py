#!/usr/bin/env python3
"""Debug UI to find clickable search elements"""

import sys
import time
from appium import webdriver
from appium.options.android import UiAutomator2Options
from appium.webdriver.common.appiumby import AppiumBy

options = UiAutomator2Options()
options.platform_name = 'Android'
options.device_name = 'emulator-5554'
options.app_package = 'com.deliverynow'
options.app_activity = 'foody.vn.deliverynow.SplashActivity'
options.no_reset = True
options.automation_name = 'UiAutomator2'

driver = webdriver.Remote('http://127.0.0.1:4723', options=options)
time.sleep(3)

print("\n=== All Elements ===")
all_elements = driver.find_elements(by=AppiumBy.XPATH, value='//*')
print(f"Total elements: {len(all_elements)}")

print("\n=== EditText Elements ===")
edits = driver.find_elements(by=AppiumBy.CLASS_NAME, value='android.widget.EditText')
print(f"Found {len(edits)} EditText elements")
for i, edit in enumerate(edits, 1):
    print(f"  {i}. text='{edit.text}' content-desc='{edit.get_attribute('content-desc')}' resource-id='{edit.get_attribute('resource-id')}'")

print("\n=== Clickable Elements at Top ===")
clickables = driver.find_elements(by=AppiumBy.XPATH, value='//*[@clickable="true"]')
print(f"Found {len(clickables)} clickable elements")
for i, elem in enumerate(clickables[:15], 1):
    bounds = elem.get_attribute('bounds')
    cls = elem.get_attribute('class')
    text = elem.text
    print(f"  {i}. {cls} text='{text}' bounds={bounds}")

print("\n=== LinearLayout Elements (top half screen) ===")
layouts = driver.find_elements(by=AppiumBy.CLASS_NAME, value='android.widget.LinearLayout')
print(f"Found {len(layouts)} LinearLayout elements")
for i, layout in enumerate(layouts[:10], 1):
    bounds = layout.get_attribute('bounds')
    clickable = layout.get_attribute('clickable')
    print(f"  {i}. bounds={bounds} clickable={clickable}")

driver.quit()
