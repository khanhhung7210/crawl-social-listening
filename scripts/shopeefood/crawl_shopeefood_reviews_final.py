#!/usr/bin/env python3
"""
ShopeeFood Review Crawler - Final Version
100% Appium automation, no ADB mixing
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
    from selenium.common.exceptions import NoSuchElementException
except ImportError:
    print("❌ Appium-Python-Client not installed")
    sys.exit(1)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from social_listening.film_paths import platform_raw_dir
from social_listening.paths import ensure_dir

OUTPUT_FILE = platform_raw_dir("shopeefood") / "shopeefood_reviews_final.json"

SEARCH_QUERY = "Meili"


def main() -> int:
    print("[shopeefood] 🚀 Starting ShopeeFood crawler (final version)")

    driver = build_driver()

    try:
        all_reviews = []

        # Search for Meili restaurants
        print(f"\n[shopeefood] 🔍 Searching for: {SEARCH_QUERY}")
        if not perform_search(driver, SEARCH_QUERY):
            print("[shopeefood] ❌ Search failed")
            return 1

        # Get list of restaurants from search results
        print(f"\n[shopeefood] 📋 Getting restaurant list...")
        restaurants = get_restaurant_list(driver)
        print(f"[shopeefood] Found {len(restaurants)} Meili restaurants")

        # Crawl each restaurant
        for idx, restaurant_info in enumerate(restaurants[:4], 1):  # Limit to 4
            print(f"\n[shopeefood] 📍 {idx}/{len(restaurants[:4])} Processing: {restaurant_info['name']}")

            try:
                # Tap restaurant using coordinates
                coords = restaurant_info['tap_coords']
                print(f"[shopeefood]   👆 Tapping at: {coords}")
                driver.tap([coords])
                time.sleep(4)

                # Crawl restaurant page
                reviews = crawl_restaurant_page(driver, restaurant_info['name'])
                all_reviews.extend(reviews)
                print(f"[shopeefood] ✅ Collected {len(reviews)} reviews")

                # Go back
                driver.back()
                time.sleep(2)

            except Exception as exc:
                print(f"[shopeefood] ❌ Error: {exc}")
                # Try to recover
                driver.back()
                time.sleep(2)
                continue

        # Save results
        if all_reviews:
            ensure_dir(OUTPUT_FILE.parent)
            OUTPUT_FILE.write_text(
                json.dumps(all_reviews, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
            print(f"\n[shopeefood] 💾 Saved {len(all_reviews)} reviews to: {OUTPUT_FILE}")
        else:
            print(f"\n[shopeefood] ⚠️  No reviews collected")

        return 0

    finally:
        driver.quit()


def build_driver() -> webdriver.Remote:
    print("[shopeefood] 📱 Connecting to emulator...")

    # Force restart app for clean state
    os.system("adb shell am force-stop com.deliverynow")
    time.sleep(1)

    options = UiAutomator2Options()
    options.platform_name = 'Android'
    options.device_name = 'emulator-5554'
    options.app_package = 'com.deliverynow'
    options.app_activity = 'foody.vn.deliverynow.SplashActivity'
    options.no_reset = True
    options.automation_name = 'UiAutomator2'

    driver = webdriver.Remote('http://127.0.0.1:4723', options=options)
    time.sleep(4)  # Give more time for app to fully load
    print("[shopeefood] ✅ Connected")
    return driver


def perform_search(driver: webdriver.Remote, query: str) -> bool:
    """Search using Appium tap + send_keys"""
    try:
        # Tap search bar at known coordinates (from previous tests: y=346)
        print("[shopeefood]   👆 Tapping search bar...")
        driver.tap([(720, 346)])
        time.sleep(2)

        # Find EditText
        print("[shopeefood]   ⌨️  Typing query...")
        edit_texts = driver.find_elements(by=AppiumBy.CLASS_NAME, value='android.widget.EditText')
        if not edit_texts:
            print(f"[shopeefood]   ❌ No EditText found")
            return False

        print(f"[shopeefood]   Found {len(edit_texts)} EditText elements")

        # Type search query
        edit_texts[0].send_keys(query)
        time.sleep(1)

        # Press Enter to execute search
        print("[shopeefood]   ⏎ Pressing Enter to search...")
        driver.press_keycode(66)  # 66 = Enter key
        time.sleep(4)  # Wait for search results to load

        print("[shopeefood]   ✅ Search completed")
        return True

    except Exception as exc:
        print(f"[shopeefood]   ❌ Search error: {exc}")
        import traceback
        traceback.print_exc()
        return False


def get_restaurant_list(driver: webdriver.Remote) -> list[dict]:
    """Get list of restaurant elements from search results"""
    restaurants = []

    try:
        # Wait a bit more for results
        time.sleep(2)

        # Look for TextViews containing "Meili" or "MeiLi"
        all_texts = driver.find_elements(by=AppiumBy.CLASS_NAME, value='android.widget.TextView')
        print(f"[shopeefood]   Found {len(all_texts)} TextViews total")

        # Debug: print first 20 texts to see what's on screen
        print(f"[shopeefood]   Sample texts on screen:")
        for i, elem in enumerate(all_texts[:20], 1):
            text = elem.text
            if text and len(text) > 0:
                print(f"      {i}. {text[:50]}")

        for text_elem in all_texts:
            text = text_elem.text
            if text and ('meili' in text.lower() or 'mei' in text.lower()):
                # Skip short matches like just "Meili" (tab name)
                if len(text) < 15:
                    continue

                print(f"[shopeefood]   Found match: {text}")

                # Get bounds of this element to tap later
                try:
                    bounds = text_elem.get_attribute('bounds')
                    # Parse bounds string: "[x1,y1][x2,y2]"
                    import re
                    match = re.findall(r'\[(\d+),(\d+)\]', bounds)
                    if match:
                        x1, y1 = map(int, match[0])
                        x2, y2 = map(int, match[1])
                        # Calculate center
                        center_x = (x1 + x2) // 2
                        center_y = (y1 + y2) // 2

                        restaurants.append({
                            'name': text,
                            'tap_coords': (center_x, center_y)
                        })
                except Exception as e:
                    print(f"[shopeefood]   Could not get bounds: {e}")
                    pass

        # Dedupe by name
        seen = set()
        unique_restaurants = []
        for r in restaurants:
            if r['name'] not in seen:
                seen.add(r['name'])
                unique_restaurants.append(r)

        return unique_restaurants

    except Exception as exc:
        print(f"[shopeefood]   ❌ Error getting restaurants: {exc}")
        import traceback
        traceback.print_exc()
        return []


def crawl_restaurant_page(driver: webdriver.Remote, restaurant_name: str) -> list[dict]:
    """Crawl reviews from restaurant page"""
    print(f"[shopeefood]   📜 Scrolling to find reviews...")

    reviews = []

    try:
        # Scroll down to find content
        size = driver.get_window_size()
        width = size['width']
        height = size['height']
        start_y = int(height * 0.7)
        end_y = int(height * 0.3)
        x = int(width * 0.5)

        # Scroll 15 times
        for i in range(15):
            driver.swipe(start_x=x, start_y=start_y, end_x=x, end_y=end_y, duration=500)
            time.sleep(1)

        # Extract reviews
        print(f"[shopeefood]   📝 Extracting reviews...")
        all_texts = driver.find_elements(by=AppiumBy.CLASS_NAME, value='android.widget.TextView')

        skip_keywords = [
            'home', 'order', 'likes', 'notification', 'menu', 'closed',
            'schedule', 'km', 'min', 'off', 'discount', 'delivery',
            'freeship', 'combo', 'see all', 'xem thêm', 'add to cart'
        ]

        seen_texts = set()

        for elem in all_texts:
            text = elem.text

            # Reviews should be at least 40 chars
            if not text or len(text) < 40 or text in seen_texts:
                continue

            seen_texts.add(text)
            text_lower = text.lower()

            # Skip UI elements
            if any(kw in text_lower for kw in skip_keywords):
                continue

            # Skip menu items (have / for translations)
            if ' / ' in text and len(text) < 100:
                continue

            # This looks like a review
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
            sample = reviews[0]['text'][:70] + "..."
            print(f"[shopeefood]   📄 Sample: {sample}")

    except Exception as exc:
        print(f"[shopeefood]   ❌ Crawl error: {exc}")

    return reviews


if __name__ == "__main__":
    sys.exit(main())
