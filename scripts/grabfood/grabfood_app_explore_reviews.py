#!/usr/bin/env python3
"""
Explore GrabFood app to find reviews functionality
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

def build_android_driver():
    """Build Appium driver for Android"""
    options = UiAutomator2Options()
    options.platform_name = "Android"
    options.device_name = "emulator-5554"
    options.app_package = "com.grab.food.pax"
    options.no_reset = True
    options.automation_name = "UiAutomator2"
    return webdriver.Remote("http://127.0.0.1:4723", options=options)


def visible_texts(driver):
    """Get all visible text from current screen"""
    try:
        elements = driver.find_elements(AppiumBy.XPATH, "//*[@text!='']")
        return [elem.text for elem in elements if elem.text and elem.text.strip()]
    except Exception:
        return []


def main():
    print("\n" + "=" * 70)
    print("🔍 GrabFood App - Explore Reviews")
    print("=" * 70)

    driver = build_android_driver()

    try:
        # Wait for app to load
        print("\n⏳ Waiting for app to load...")
        time.sleep(5)

        # Get all visible text
        texts = visible_texts(driver)
        print(f"\n📋 Found {len(texts)} text elements")

        # Check for reviews-related keywords
        review_keywords = ['review', 'đánh giá', 'rating', 'bình luận', 'nhận xét']
        found_keywords = []
        for text in texts:
            text_lower = text.lower()
            for keyword in review_keywords:
                if keyword in text_lower:
                    found_keywords.append(text)
                    break

        if found_keywords:
            print(f"\n✅ Found {len(found_keywords)} review-related texts:")
            for text in found_keywords[:10]:
                print(f"   • {text[:100]}")
        else:
            print("\n❌ No review keywords found")

        # Print sample of all texts
        print(f"\n📄 Sample texts (first 30):")
        for text in texts[:30]:
            print(f"   • {text[:80]}")

        # Get page source
        page_source = driver.page_source

        # Check if reviews exist in page source
        page_lower = page_source.lower()
        has_reviews = any(kw in page_lower for kw in review_keywords)

        print(f"\n📱 Page source analysis:")
        print(f"   Has 'review' keywords: {has_reviews}")
        print(f"   Current activity: {driver.current_activity}")
        print(f"   Current package: {driver.current_package}")

        # Save page source for analysis
        output_file = Path(__file__).parent / "grabfood_app_page_source.xml"
        output_file.write_text(page_source, encoding='utf-8')
        print(f"   💾 Saved page source to: {output_file.name}")

    finally:
        print("\n👋 Keeping app open for manual exploration...")
        print("   Please manually:")
        print("   1. Search for 'Meili'")
        print("   2. Open a restaurant")
        print("   3. Look for Reviews/Đánh giá tab")
        print("   4. Take screenshot if reviews exist")
        print("\n   Driver will stay open for 60 seconds...")
        time.sleep(60)
        driver.quit()

    print("\n" + "=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
