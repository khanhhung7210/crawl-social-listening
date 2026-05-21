#!/usr/bin/env python3
"""
Use Appium to click on restaurant directly (no coordinates)
"""

import sys
import time
from pathlib import Path

try:
    from appium import webdriver
    from appium.options.android import UiAutomator2Options
    from appium.webdriver.common.appiumby import AppiumBy
except ImportError:
    print("❌ Appium-Python-Client not installed")
    sys.exit(1)


def main():
    print("\n🔌 Connecting to ShopeeFood...")

    options = UiAutomator2Options()
    options.platform_name = 'Android'
    options.device_name = 'emulator-5554'
    options.app_package = 'com.deliverynow'
    options.app_activity = 'foody.vn.deliverynow.SplashActivity'
    options.no_reset = True
    options.automation_name = 'UiAutomator2'

    driver = webdriver.Remote('http://127.0.0.1:4723', options=options)
    print("✅ Connected")

    try:
        # Find all clickable elements
        print("\n🔍 Finding clickable elements on page...")

        # Try to find restaurant by text containing "Meili" and "Nguyễn Văn Khối"
        all_texts = driver.find_elements(by=AppiumBy.CLASS_NAME, value='android.widget.TextView')

        print(f"📄 Found {len(all_texts)} text elements")

        # Find the restaurant title element
        target = None
        for elem in all_texts:
            text = elem.text
            if text and 'meili' in text.lower() and 'nguyễn' in text.lower():
                print(f"✓ Found target: {text}")
                target = elem
                break

        if target:
            print("🖱️  Attempting to click...")
            try:
                target.click()
                print("✅ Clicked!")
                time.sleep(5)

                # Take screenshot
                import os
                os.system("adb exec-out screencap -p > /tmp/shopeefood_after_appium_click.png")
                print("📸 Screenshot saved")

            except Exception as e:
                print(f"❌ Click failed: {e}")

                # Try clicking parent
                print("🔄 Trying to click parent element...")
                try:
                    # Get parent by finding a clickable ancestor
                    clickables = driver.find_elements(by=AppiumBy.XPATH,
                        value="//android.view.ViewGroup[@clickable='true']")

                    print(f"   Found {len(clickables)} clickable ViewGroups")

                    # Try clicking the first few
                    for i, elem in enumerate(clickables[:5]):
                        print(f"   Trying clickable #{i+1}...")
                        try:
                            elem.click()
                            time.sleep(3)
                            print(f"   ✅ Clicked #{i+1}")
                            break
                        except:
                            pass

                except Exception as e2:
                    print(f"   ❌ Parent click also failed: {e2}")
        else:
            print("❌ Could not find Meili Nguyễn Văn Khối restaurant")
            print("\n📋 Available restaurants:")
            for elem in all_texts[:30]:
                if elem.text and len(elem.text) > 10:
                    print(f"   • {elem.text}")

    finally:
        driver.quit()
        print("\n✅ Done")


if __name__ == "__main__":
    main()
