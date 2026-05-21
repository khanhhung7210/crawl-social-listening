#!/usr/bin/env python3
"""
ShopeeFood Auto Crawler - Fully automated search and crawl

This script:
1. Opens ShopeeFood app
2. Clicks search bar using ADB
3. Types search query
4. Clicks first result
5. Crawls reviews
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

OUTPUT_FILE = platform_raw_dir("shopeefood") / "shopeefood_reviews_auto.json"

# Restaurants to search
RESTAURANTS = [
    "Meili Nhiêu Tứ",
    "Meili Ung Văn Khiêm",
    "Meili Mai Văn Vinh",
    "Meili Nguyễn Văn Khối",
]


def main() -> int:
    print("[shopeefood-auto] 🚀 Starting fully automated crawler...")

    all_reviews = []

    for idx, restaurant in enumerate(RESTAURANTS, 1):
        print(f"\n[shopeefood-auto] 📍 {idx}/{len(RESTAURANTS)} Processing: {restaurant}")

        try:
            # Search and open restaurant
            if search_and_open_restaurant(restaurant):
                # Crawl reviews
                reviews = crawl_current_restaurant(restaurant)
                all_reviews.extend(reviews)
                print(f"[shopeefood-auto] ✅ Collected {len(reviews)} reviews from {restaurant}")

                # Go back to home
                go_back_to_home()
            else:
                print(f"[shopeefood-auto] ⚠️  Could not open {restaurant}")

        except Exception as exc:
            print(f"[shopeefood-auto] ❌ Error processing {restaurant}: {exc}")
            # Try to recover
            go_back_to_home()
            continue

    # Save all reviews
    if all_reviews:
        ensure_dir(OUTPUT_FILE.parent)
        OUTPUT_FILE.write_text(
            json.dumps(all_reviews, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        print(f"\n[shopeefood-auto] 💾 Saved {len(all_reviews)} total reviews to: {OUTPUT_FILE}")
    else:
        print(f"\n[shopeefood-auto] ⚠️  No reviews collected")

    return 0


def search_and_open_restaurant(query: str) -> bool:
    """
    Search for restaurant and open it
    Uses ADB commands for interaction
    """
    print(f"[shopeefood-auto]   🔍 Searching for: {query}")

    try:
        # Step 1: Make sure app is running
        os.system("adb shell am start -n com.deliverynow/foody.vn.deliverynow.SplashActivity > /dev/null 2>&1")
        time.sleep(2)

        # Step 2: Tap search bar (coordinates from screenshot)
        # Search bar is at approximately y=346 (center of "Deal Cú Đêm" area)
        print(f"[shopeefood-auto]   👆 Tapping search bar...")
        os.system("adb shell input tap 720 346")
        time.sleep(2)

        # Step 3: Clear any existing text and type search query
        print(f"[shopeefood-auto]   ⌨️  Typing: {query}")
        # Clear first
        for _ in range(20):
            os.system("adb shell input keyevent KEYCODE_DEL")
        time.sleep(0.5)

        # Type search - use just "Meili" to find all locations
        search_term = "Meili"
        os.system(f'adb shell input text "{search_term}"')
        time.sleep(3)  # Wait for search results

        # Step 4: Take screenshot to see search results
        os.system("adb exec-out screencap -p > /tmp/shopeefood_search_debug.png")

        # Step 5: Click first search result
        # Restaurant card appears around y=380 (center of the card)
        print(f"[shopeefood-auto]   👆 Clicking first result...")
        os.system("adb shell input tap 360 380")
        time.sleep(4)  # Wait for restaurant page to load

        # Step 6: Verify we're on restaurant page by taking screenshot
        os.system("adb exec-out screencap -p > /tmp/shopeefood_restaurant_debug.png")

        print(f"[shopeefood-auto]   ✅ Opened restaurant")
        return True

    except Exception as exc:
        print(f"[shopeefood-auto]   ❌ Error in search: {exc}")
        return False


def crawl_current_restaurant(restaurant_name: str) -> list[dict]:
    """Crawl reviews from current restaurant page using Appium"""
    print(f"[shopeefood-auto]   📜 Scrolling to reviews...")

    reviews = []

    try:
        # Connect to Appium
        driver = build_driver()

        # Extract actual restaurant name from page
        actual_name = extract_restaurant_name(driver)
        if actual_name and "meili" in actual_name.lower():
            restaurant_name = actual_name

        print(f"[shopeefood-auto]   🏪 Restaurant: {restaurant_name}")

        # Scroll down to find reviews (need more scrolls to reach review section)
        scroll_to_reviews(driver, num_scrolls=20)

        # Extract reviews
        print(f"[shopeefood-auto]   📝 Extracting reviews...")
        reviews = extract_reviews(driver, restaurant_name)

        driver.quit()

    except Exception as exc:
        print(f"[shopeefood-auto]   ❌ Error crawling: {exc}")

    return reviews


def go_back_to_home():
    """Go back to home screen"""
    print(f"[shopeefood-auto]   🏠 Returning to home...")
    # Press back button several times
    for _ in range(3):
        os.system("adb shell input keyevent KEYCODE_BACK")
        time.sleep(0.5)
    time.sleep(1)


def build_driver() -> webdriver.Remote:
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


def extract_restaurant_name(driver: webdriver.Remote) -> str:
    """Extract restaurant name from page"""
    try:
        all_texts = driver.find_elements(
            by=AppiumBy.CLASS_NAME,
            value='android.widget.TextView'
        )

        for elem in all_texts[:15]:
            text = elem.text
            if text and 5 < len(text) < 100:
                if any(x in text.lower() for x in ['home', 'deliver', 'deal', 'order']):
                    continue
                if 'meili' in text.lower() or 'mì' in text.lower():
                    return text

        return "Meili Restaurant"
    except Exception:
        return "Meili Restaurant"


def scroll_to_reviews(driver: webdriver.Remote, num_scrolls: int):
    """Scroll down to reach reviews"""
    size = driver.get_window_size()
    width = size['width']
    height = size['height']

    start_y = int(height * 0.7)
    end_y = int(height * 0.3)
    x = int(width * 0.5)

    for i in range(num_scrolls):
        driver.swipe(start_x=x, start_y=start_y, end_x=x, end_y=end_y, duration=500)
        time.sleep(1)


def extract_reviews(driver: webdriver.Remote, restaurant_name: str) -> list[dict]:
    """Extract reviews from screen"""
    reviews = []

    try:
        all_texts = driver.find_elements(
            by=AppiumBy.CLASS_NAME,
            value='android.widget.TextView'
        )

        skip_keywords = [
            'home', 'menu', 'my orders', 'likes', 'notification', 'me',
            'delivery', 'restaurant', 'favorite', 'voucher', 'deal',
            'shop', 'collection', 'giao hàng', 'đặt món', 'yêu thích',
            'thông báo', 'trang chủ', 'ưu đãi', 'giảm giá', 'freeship',
            'combo', 'see all', 'xem thêm', 'order now', 'đặt ngay',
            'add to cart', 'thêm vào giỏ', 'price', 'giá', 'closed',
            'schedule for', 'min', 'km', 'off', 'discount'
        ]

        seen_texts = set()

        for elem in all_texts:
            text = elem.text

            # Accept shorter texts (20 chars minimum instead of 50)
            if not text or len(text) < 20 or text in seen_texts:
                continue

            seen_texts.add(text)
            text_lower = text.lower()

            if any(kw in text_lower for kw in skip_keywords):
                continue

            if any(x in text_lower for x in ['http', 'www.', 'error']):
                continue

            # Only skip very obvious menu items (short with /)
            if ' / ' in text and len(text) < 60:
                continue

            # Allow some Chinese (dishes, descriptions can have Chinese)
            # Only skip if MOSTLY Chinese (>70%)
            chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
            if chinese_chars > len(text) * 0.7:
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

        if reviews:
            print(f"[shopeefood-auto]   ✅ Found {len(reviews)} reviews")
            # Show sample
            if len(reviews) > 0:
                sample = reviews[0]['text'][:60] + "..."
                print(f"[shopeefood-auto]   📄 Sample: {sample}")

    except Exception as exc:
        print(f"[shopeefood-auto]   ❌ Error extracting: {exc}")

    return reviews


if __name__ == "__main__":
    sys.exit(main())
