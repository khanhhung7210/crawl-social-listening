#!/usr/bin/env python3
"""
Explore ShopeeFood UI to find element IDs

This script will:
1. Connect to ShopeeFood
2. Try to click Retry if connection error
3. Print all UI elements on screen
4. Help identify review selectors
"""

from __future__ import annotations

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


def main() -> int:
    print("🔍 Exploring ShopeeFood UI...")

    # Connect
    options = UiAutomator2Options()
    options.platform_name = 'Android'
    options.device_name = 'emulator-5554'
    options.app_package = 'com.deliverynow'
    options.app_activity = 'foody.vn.deliverynow.SplashActivity'
    options.no_reset = True
    options.automation_name = 'UiAutomator2'

    driver = webdriver.Remote('http://127.0.0.1:4723', options=options)
    time.sleep(3)

    try:
        # Try to handle connection error
        print("\n🔄 Checking for connection error...")
        try:
            retry_button = driver.find_element(by=AppiumBy.XPATH, value='//android.widget.Button[@text="Retry"]')
            print("✅ Found Retry button, clicking...")
            retry_button.click()
            time.sleep(5)
        except Exception:
            print("ℹ️  No Retry button found (may be already on home screen)")

        # Print all text elements
        print("\n📱 Current screen elements:")
        print("=" * 60)

        text_views = driver.find_elements(by=AppiumBy.CLASS_NAME, value='android.widget.TextView')
        print(f"\n📝 Found {len(text_views)} TextViews:")
        for i, tv in enumerate(text_views[:20], 1):
            text = tv.text
            if text and text.strip():
                print(f"  {i}. {text[:80]}")

        # Print buttons
        buttons = driver.find_elements(by=AppiumBy.CLASS_NAME, value='android.widget.Button')
        print(f"\n🔘 Found {len(buttons)} Buttons:")
        for i, btn in enumerate(buttons[:10], 1):
            text = btn.text
            if text and text.strip():
                print(f"  {i}. {text[:80]}")

        # Get full page source
        print("\n📄 Getting page source XML...")
        page_source = driver.page_source

        # Save to file
        output_file = Path("/tmp/shopeefood_ui.xml")
        output_file.write_text(page_source, encoding="utf-8")
        print(f"✅ Saved UI XML to: {output_file}")
        print("   You can open this file to see full element hierarchy")

        # Current activity
        print(f"\n📲 Current activity: {driver.current_activity}")

        print("\n" + "=" * 60)
        print("✅ UI exploration complete!")
        print("\n💡 Next steps:")
        print("  1. Open /tmp/shopeefood_ui.xml to see full UI structure")
        print("  2. Search in restaurant within app")
        print("  3. Run this script again to see restaurant page elements")
        print("  4. Use Appium Inspector for visual inspection")

        input("\nPress Enter to close...")

        driver.quit()
        return 0

    except Exception as exc:
        print(f"❌ Error: {exc}")
        driver.quit()
        return 1


if __name__ == "__main__":
    sys.exit(main())
