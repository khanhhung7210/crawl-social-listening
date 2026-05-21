#!/usr/bin/env python3
"""Find exact search elements using UIAutomator"""

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

print("Connecting...")
driver = webdriver.Remote('http://127.0.0.1:4723', options=options)
time.sleep(3)

print("\n=== All clickable ViewGroups ===")
viewgroups = driver.find_elements(by=AppiumBy.CLASS_NAME, value='android.view.ViewGroup')
print(f"Found {len(viewgroups)} ViewGroups")

for i, vg in enumerate(viewgroups[:30], 1):
    clickable = vg.get_attribute('clickable')
    bounds = vg.get_attribute('bounds')
    content_desc = vg.get_attribute('content-desc')

    if clickable == 'true':
        print(f"  {i}. clickable=true bounds={bounds} desc='{content_desc}'")

print("\n=== Trying to click search area using UIAutomator ===")
try:
    # Try using UIAutomator selector for search
    search_selector = 'new UiSelector().clickable(true).instance(1)'
    el = driver.find_element(by=AppiumBy.ANDROID_UIAUTOMATOR, value=search_selector)
    print(f"Found element: bounds={el.get_attribute('bounds')}")
    el.click()
    time.sleep(2)

    print("\n=== After clicking, looking for EditText ===")
    edits = driver.find_elements(by=AppiumBy.CLASS_NAME, value='android.widget.EditText')
    print(f"Found {len(edits)} EditText elements")

    if edits:
        print("SUCCESS! EditText appeared after click")
        edit = edits[0]
        print(f"  bounds={edit.get_attribute('bounds')}")
        print(f"  hint={edit.get_attribute('hint')}")

        # Try to type
        edit.send_keys("Meili")
        time.sleep(2)
        print("Typed 'Meili'")

except Exception as e:
    print(f"Error: {e}")

driver.quit()
