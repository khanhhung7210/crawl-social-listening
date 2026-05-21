#!/usr/bin/env python3
"""
ShopeeFood Crawler - With Reviews Section
Based on crawl_meili_auto.py but navigates to reviews page
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    from appium import webdriver
    from appium.options.android import UiAutomator2Options
    from appium.webdriver.common.appiumby import AppiumBy
except ImportError:
    print("❌ Appium-Python-Client not installed")
    sys.exit(1)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from social_listening.film_paths import platform_raw_dir
from social_listening.paths import ensure_dir

OUTPUT_FILE = platform_raw_dir("shopeefood") / "shopeefood_reviews_with_ratings.json"

RESTAURANTS = ["Meili Nhiêu Tứ", "Meili Ung Văn Khiêm", "Meili Mai Văn Vinh", "Meili Nguyễn Văn Khối"]


def main() -> int:
    print("[shopeefood-reviews] 🚀 Starting ShopeeFood reviews crawler")

    all_reviews = []

    for idx, restaurant in enumerate(RESTAURANTS, 1):
        print(f"\n[shopeefood-reviews] 📍 {idx}/{len(RESTAURANTS)} {restaurant}")

        try:
            if search_and_open_restaurant(restaurant):
                # Build driver to interact with page
                driver = build_driver_for_interaction()

                # Try to find and click reviews link
                reviews = extract_reviews_from_restaurant_page(driver, restaurant)
                all_reviews.extend(reviews)

                driver.quit()

                # Go back to home
                go_back_to_home()
            else:
                print(f"[shopeefood-reviews] ⚠️  Could not open {restaurant}")

        except Exception as exc:
            print(f"[shopeefood-reviews] ❌ Error: {exc}")
            go_back_to_home()
            continue

    # Save results
    if all_reviews:
        ensure_dir(OUTPUT_FILE.parent)
        OUTPUT_FILE.write_text(
            json.dumps(all_reviews, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        print(f"\n[shopeefood-reviews] 💾 Saved {len(all_reviews)} reviews to: {OUTPUT_FILE}")
    else:
        print(f"\n[shopeefood-reviews] ⚠️  No reviews collected")

    return 0


def search_and_open_restaurant(query: str) -> bool:
    """Search and open restaurant using ADB"""
    print(f"[shopeefood-reviews]   🔍 Searching...")

    try:
        # Start app
        os.system("adb shell am start -n com.deliverynow/foody.vn.deliverynow.SplashActivity > /dev/null 2>&1")
        time.sleep(2)

        # Tap search
        os.system("adb shell input tap 720 346")
        time.sleep(2)

        # Clear and type
        for _ in range(20):
            os.system("adb shell input keyevent KEYCODE_DEL")
        time.sleep(0.5)

        os.system(f'adb shell input text "Meili"')
        time.sleep(3)

        # Click first result at y=500 (lower to hit restaurant card body)
        os.system("adb shell input tap 300 500")
        time.sleep(5)

        print(f"[shopeefood-reviews]   ✅ Opened restaurant")
        return True

    except Exception as exc:
        print(f"[shopeefood-reviews]   ❌ Error: {exc}")
        return False


def build_driver_for_interaction() -> webdriver.Remote:
    """Build Appium driver to interact with current page"""
    options = UiAutomator2Options()
    options.platform_name = 'Android'
    options.device_name = 'emulator-5554'
    options.app_package = 'com.deliverynow'
    options.app_activity = 'foody.vn.deliverynow.SplashActivity'
    options.no_reset = True
    options.automation_name = 'UiAutomator2'

    driver = webdriver.Remote('http://127.0.0.1:4723', options=options)
    time.sleep(1)
    return driver


def extract_reviews_from_restaurant_page(driver: webdriver.Remote, restaurant_name: str) -> list[dict]:
    """Try to find and navigate to reviews section"""
    reviews = []

    try:
        # First, verify which restaurant we're on
        print(f"[shopeefood-reviews]   🔍 Checking current restaurant...")
        all_texts = driver.find_elements(by=AppiumBy.CLASS_NAME, value='android.widget.TextView')

        # Print first 20 texts to debug
        print(f"[shopeefood-reviews]   📄 Page content sample:")
        for i, elem in enumerate(all_texts[:20], 1):
            text = elem.text
            if text and len(text) > 0:
                print(f"      {i}. {text[:60]}")

        # Look for reviews link: "4.9 (50+ Reviews)" or similar
        print(f"[shopeefood-reviews]   🔍 Looking for reviews link...")

        reviews_link_found = False
        for elem in all_texts:
            text = elem.text
            if text and ('review' in text.lower() or 'đánh giá' in text.lower() or '+' in text):
                print(f"[shopeefood-reviews]   Found potential reviews link: {text}")
                try:
                    elem.click()
                    time.sleep(3)
                    reviews_link_found = True
                    print(f"[shopeefood-reviews]   ✅ Clicked reviews link")
                    break
                except Exception as e:
                    print(f"[shopeefood-reviews]   Could not click: {e}")
                    pass

        if not reviews_link_found:
            print(f"[shopeefood-reviews]   ℹ️  No reviews link found, extracting from main page")

        # Scroll to see more content
        print(f"[shopeefood-reviews]   📜 Scrolling...")
        size = driver.get_window_size()
        for _ in range(10):
            driver.swipe(
                start_x=size['width']//2,
                start_y=int(size['height']*0.7),
                end_x=size['width']//2,
                end_y=int(size['height']*0.3),
                duration=500
            )
            time.sleep(1)

        # Extract text content
        print(f"[shopeefood-reviews]   📝 Extracting content...")
        all_texts = driver.find_elements(by=AppiumBy.CLASS_NAME, value='android.widget.TextView')

        skip_kw = [
            'home', 'order', 'likes', 'notification', 'menu', 'closed',
            'km', 'min', 'off', 'discount', 'delivery', 'freeship',
            'see all', 'xem thêm', 'add to cart', 'group order'
        ]

        seen = set()
        for elem in all_texts:
            text = elem.text

            if not text or len(text) < 30 or text in seen:
                continue

            seen.add(text)
            text_lower = text.lower()

            if any(kw in text_lower for kw in skip_kw):
                continue

            if ' / ' in text and len(text) < 60:
                continue

            reviews.append({
                "platform": "shopeefood",
                "review_id": f"{restaurant_name}_{len(reviews)}_{int(time.time())}",
                "restaurant_url": "",
                "restaurant_name": restaurant_name,
                "author": "Unknown",
                "rating": 0,
                "text": text,
                "created_at": "",
                "crawled_at": datetime.now(timezone.utc).isoformat(),
            })

        print(f"[shopeefood-reviews]   ✅ Found {len(reviews)} items")

    except Exception as exc:
        print(f"[shopeefood-reviews]   ❌ Error extracting: {exc}")

    return reviews


def go_back_to_home():
    """Go back to home"""
    for _ in range(3):
        os.system("adb shell input keyevent KEYCODE_BACK")
        time.sleep(0.5)
    time.sleep(1)


if __name__ == "__main__":
    sys.exit(main())
