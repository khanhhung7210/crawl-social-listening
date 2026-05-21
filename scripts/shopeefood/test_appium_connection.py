#!/usr/bin/env python3
"""
Test Appium connection to Android emulator + ShopeeFood app

Prerequisites:
1. Android emulator running: $ANDROID_HOME/emulator/emulator -avd Pixel_6_Pro_API_34 &
2. ShopeeFood app installed and logged in
3. Appium server running: appium --allow-cors

Usage:
    python3 scripts/shopeefood/test_appium_connection.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

try:
    from appium.webdriver.common.appiumby import AppiumBy
except ImportError:
    print("❌ Appium-Python-Client not installed")
    print("Install with: pip3 install Appium-Python-Client")
    sys.exit(1)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.shopeefood.simulator_utils import (
    ANDROID_DEVICE_NAME,
    SHOPEEFOOD_APP_ACTIVITY,
    SHOPEEFOOD_APP_PACKAGE,
    build_android_driver,
)


def main() -> int:
    print("🔍 Testing Appium connection to ShopeeFood...")
    print()

    try:
        print("📱 Connecting to Android emulator...")
        print(f"   package={SHOPEEFOOD_APP_PACKAGE}")
        print(f"   activity={SHOPEEFOOD_APP_ACTIVITY}")
        print(f"   device={ANDROID_DEVICE_NAME}")
        driver = build_android_driver()
        print("✅ Connected successfully!")
        print()

        # Wait for app to load
        time.sleep(3)

        # Get current activity
        current_activity = driver.current_activity
        print(f"📲 Current activity: {current_activity}")

        # Get app package
        current_package = driver.current_package
        print(f"📦 Current package: {current_package}")

        # Get page source (to verify we can inspect UI)
        print()
        print("🔍 Getting page source...")
        page_source = driver.page_source
        print(f"✅ Page source length: {len(page_source)} characters")

        # Check if we can find some elements
        print()
        print("🔍 Looking for UI elements...")
        try:
            # Try to find any TextView (common in all Android apps)
            text_views = driver.find_elements(by=AppiumBy.CLASS_NAME, value='android.widget.TextView')
            print(f"✅ Found {len(text_views)} TextViews")

            # Print first 5 text contents
            if text_views:
                print()
                print("📝 Sample text elements:")
                for i, tv in enumerate(text_views[:5], 1):
                    text = tv.text
                    if text and text.strip():
                        print(f"  {i}. {text[:50]}")

        except Exception as exc:
            print(f"⚠️  Could not find elements: {exc}")

        # Get device info
        print()
        print("📱 Device info:")
        print(f"  - Platform: {driver.capabilities.get('platformName')}")
        print(f"  - Platform version: {driver.capabilities.get('platformVersion')}")
        print(f"  - Device: {driver.capabilities.get('deviceName')}")

        print()
        print("✅ Connection test successful! Ready to crawl.")
        print()
        print("💡 Next steps:")
        print("  1. Use Appium Inspector to find review element IDs")
        print("  2. Update shopeefood_review_crawler.py with correct selectors")
        print("  3. Run the full crawler")

        driver.quit()
        return 0

    except Exception as exc:
        print(f"❌ Connection failed: {exc}")
        print()
        print("🔧 Troubleshooting:")
        print("  1. Is emulator running? Check with: adb devices")
        print("  2. Is Appium server running? Check with: lsof -i :4723")
        print("  3. Is ShopeeFood installed? Check with: adb shell pm list packages | grep foody")
        print()
        return 1


if __name__ == "__main__":
    sys.exit(main())
