#!/usr/bin/env python3
"""
ShopeeFood Crawler - Extract Reviews Count & Sold Counts
"""

from __future__ import annotations

import json
import os
import re
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

OUTPUT_FILE = platform_raw_dir("shopeefood") / "shopeefood_reviews_and_sold.json"

RESTAURANTS = ["Meili"]


def main() -> int:
    print("[shopeefood] 🚀 Extracting reviews & sold counts")

    all_data = []

    for idx, search_term in enumerate(RESTAURANTS, 1):
        print(f"\n[shopeefood] 📍 {idx}/{len(RESTAURANTS)} Searching: {search_term}")

        try:
            # Search and open
            if search_and_open(search_term):
                driver = build_driver()

                # Extract all info
                restaurant_info = extract_restaurant_info(driver)
                print(f"[shopeefood] ✅ Restaurant: {restaurant_info['name']}")
                print(f"[shopeefood] ⭐ Rating: {restaurant_info['rating']}")
                print(f"[shopeefood] 📊 Reviews: {restaurant_info['review_count']}")

                # Get dishes with sold counts
                dishes = extract_dishes_with_sold(driver)
                print(f"[shopeefood] 🍜 Found {len(dishes)} dishes with sold info")

                restaurant_info['dishes'] = dishes
                all_data.append(restaurant_info)

                driver.quit()
                go_back_to_home()

        except Exception as exc:
            print(f"[shopeefood] ❌ Error: {exc}")
            import traceback
            traceback.print_exc()
            continue

    # Save
    if all_data:
        ensure_dir(OUTPUT_FILE.parent)
        OUTPUT_FILE.write_text(
            json.dumps(all_data, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        print(f"\n[shopeefood] 💾 Saved {len(all_data)} restaurants to: {OUTPUT_FILE}")

    return 0


def search_and_open(query: str) -> bool:
    """Search and open first Meili restaurant"""
    try:
        os.system("adb shell am start -n com.deliverynow/foody.vn.deliverynow.SplashActivity > /dev/null 2>&1")
        time.sleep(2)

        # Search
        os.system("adb shell input tap 720 346")
        time.sleep(2)
        for _ in range(20):
            os.system("adb shell input keyevent KEYCODE_DEL")
        time.sleep(0.5)
        os.system(f'adb shell input text "{query}"')
        time.sleep(2)
        os.system("adb shell input keyevent 66")  # Enter
        time.sleep(4)

        # Click first MeiLi restaurant (y=500)
        os.system("adb shell input tap 300 500")
        time.sleep(5)

        return True
    except Exception:
        return False


def build_driver() -> webdriver.Remote:
    options = UiAutomator2Options()
    options.platform_name = 'Android'
    options.device_name = 'emulator-5554'
    options.app_package = 'com.deliverynow'
    options.app_activity = 'foody.vn.deliverynow.SplashActivity'
    options.no_reset = True
    options.automation_name = 'UiAutomator2'
    return webdriver.Remote('http://127.0.0.1:4723', options=options)


def extract_restaurant_info(driver: webdriver.Remote) -> dict:
    """Extract restaurant name, rating, review count"""
    info = {
        "platform": "shopeefood",
        "name": "Unknown",
        "rating": 0.0,
        "review_count": "0",
        "crawled_at": datetime.now(timezone.utc).isoformat()
    }

    try:
        all_texts = driver.find_elements(by=AppiumBy.CLASS_NAME, value='android.widget.TextView')

        # Find restaurant name (contains "MeiLi" or "Meili")
        for elem in all_texts:
            text = elem.text
            if text and 'meili' in text.lower() and len(text) > 15:
                info['name'] = text.strip()
                break

        # Find rating and reviews: "4.9 (50+ Reviews)" or "4.9"
        rating_pattern = re.compile(r'(\d+\.\d+)')
        review_pattern = re.compile(r'(\d+\+?\s*[Rr]eviews?)', re.IGNORECASE)

        for elem in all_texts:
            text = elem.text
            if not text:
                continue

            # Check for rating
            rating_match = rating_pattern.search(text)
            if rating_match and float(rating_match.group(1)) <= 5.0:
                info['rating'] = float(rating_match.group(1))

            # Check for review count
            review_match = review_pattern.search(text)
            if review_match:
                info['review_count'] = review_match.group(1)

    except Exception as exc:
        print(f"[shopeefood] ⚠️  Error extracting info: {exc}")

    return info


def extract_dishes_with_sold(driver: webdriver.Remote) -> list[dict]:
    """Extract dishes with their sold counts"""
    dishes = []

    try:
        # Scroll to see menu
        print(f"[shopeefood] 📜 Scrolling to see menu...")
        size = driver.get_window_size()
        for _ in range(5):
            driver.swipe(
                start_x=size['width']//2,
                start_y=int(size['height']*0.7),
                end_x=size['width']//2,
                end_y=int(size['height']*0.3),
                duration=500
            )
            time.sleep(1)

        # Get all text elements
        all_texts = driver.find_elements(by=AppiumBy.CLASS_NAME, value='android.widget.TextView')

        sold_pattern = re.compile(r'(\d+\+?)\s*sold', re.IGNORECASE)

        current_dish = None
        for elem in all_texts:
            text = elem.text
            if not text:
                continue

            # Check if this is a sold count
            sold_match = sold_pattern.search(text)
            if sold_match:
                if current_dish:
                    current_dish['sold_count'] = sold_match.group(1)
                    dishes.append(current_dish)
                    current_dish = None
                continue

            # Check if this looks like a dish name (has / for translation or Vietnamese food terms)
            if len(text) > 15 and (
                ' / ' in text or
                any(word in text.lower() for word in ['mì', 'pao', 'gà', 'bò', 'bánh', 'cơm', 'phở'])
            ):
                # Save previous dish if any
                if current_dish:
                    dishes.append(current_dish)

                # Start new dish
                current_dish = {
                    "name": text,
                    "sold_count": "0"
                }

        # Add last dish
        if current_dish:
            dishes.append(current_dish)

    except Exception as exc:
        print(f"[shopeefood] ⚠️  Error extracting dishes: {exc}")

    return dishes


def go_back_to_home():
    for _ in range(3):
        os.system("adb shell input keyevent KEYCODE_BACK")
        time.sleep(0.5)


if __name__ == "__main__":
    sys.exit(main())
