#!/usr/bin/env python3
"""
ShopeeFood Review Crawler V3 - Working with Appium UI Automation

This version:
1. Uses Appium to interact with UI elements
2. Searches for restaurant using search bar
3. Clicks into restaurant page
4. Scrolls to find reviews
5. Extracts review content
"""

from __future__ import annotations

import json
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

OUTPUT_FILE = platform_raw_dir("shopeefood") / "shopeefood_reviews_android_v3.json"

# Search terms for restaurants
SEARCH_QUERIES = [
    "Meili Nhiêu Tứ",
    "Meili Ung Văn Khiêm",
    "Meili Mai Văn Vinh",
    "Meili Nguyễn Văn Khối",
]


def main() -> int:
    print("[shopeefood-v3] Starting crawler with Appium UI automation...")
    print(f"[shopeefood-v3] Will search for {len(SEARCH_QUERIES)} restaurants")

    driver = build_driver()

    try:
        all_reviews: list[dict] = []

        for index, search_query in enumerate(SEARCH_QUERIES, 1):
            print(f"\n[shopeefood-v3] {index}/{len(SEARCH_QUERIES)} Searching: {search_query}")

            try:
                # Go back to home first
                go_to_home(driver)
                time.sleep(2)

                # Search for restaurant
                if search_for_restaurant(driver, search_query):
                    time.sleep(3)

                    # Extract restaurant name from current page
                    restaurant_name = extract_restaurant_name(driver, search_query)
                    print(f"[shopeefood-v3] Restaurant: {restaurant_name}")

                    # Scroll to find reviews
                    print(f"[shopeefood-v3] Scrolling to find reviews...")
                    scroll_to_reviews(driver)

                    # Extract reviews
                    print(f"[shopeefood-v3] Extracting reviews...")
                    reviews = extract_reviews(driver, restaurant_name)
                    print(f"[shopeefood-v3] Found {len(reviews)} reviews")

                    all_reviews.extend(reviews)
                else:
                    print(f"[shopeefood-v3] Could not find: {search_query}")

            except Exception as exc:
                print(f"[shopeefood-v3] Error processing {search_query}: {exc}")
                continue

        # Save results
        ensure_dir(OUTPUT_FILE.parent)
        OUTPUT_FILE.write_text(
            json.dumps(all_reviews, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

        print(f"\n[shopeefood-v3] ✅ Saved {len(all_reviews)} total reviews to {OUTPUT_FILE}")
        return 0

    finally:
        driver.quit()


def build_driver() -> webdriver.Remote:
    print("[shopeefood-v3] Connecting to Android emulator...")

    options = UiAutomator2Options()
    options.platform_name = 'Android'
    options.device_name = 'emulator-5554'
    options.app_package = 'com.deliverynow'
    options.app_activity = 'foody.vn.deliverynow.SplashActivity'
    options.no_reset = True
    options.automation_name = 'UiAutomator2'

    driver = webdriver.Remote('http://127.0.0.1:4723', options=options)
    time.sleep(3)

    print("[shopeefood-v3] Connected successfully")
    return driver


def go_to_home(driver: webdriver.Remote):
    """Go back to home screen"""
    try:
        # Press back multiple times
        for _ in range(3):
            driver.back()
            time.sleep(0.5)

        # Click Home tab
        try:
            home_elements = driver.find_elements(
                by=AppiumBy.XPATH,
                value='//android.widget.TextView[@text="Home"]'
            )
            if home_elements:
                home_elements[0].click()
                time.sleep(1)
        except Exception:
            pass
    except Exception as exc:
        print(f"[shopeefood-v3] Error going to home: {exc}")


def search_for_restaurant(driver: webdriver.Remote, query: str) -> bool:
    """
    Search for restaurant using search bar
    Returns True if restaurant page opened successfully
    """
    try:
        print(f"[shopeefood-v3] Looking for search bar...")

        # ShopeeFood uses React Native - search bar is a ViewGroup
        # Click on search bar area (approximately bounds=[28,276][1412,416])
        # Center coordinates: x=720, y=346
        print(f"[shopeefood-v3] Clicking search bar at coordinates...")
        driver.tap([(720, 346)])
        time.sleep(2)

        # After clicking, EditText should appear
        print(f"[shopeefood-v3] Looking for EditText after tap...")
        search_elements = driver.find_elements(
            by=AppiumBy.XPATH,
            value='//android.widget.EditText'
        )

        if search_elements:
            print(f"[shopeefood-v3] Found search field, typing: {query}")
            search_field = search_elements[0]
            search_field.click()
            time.sleep(0.5)
            search_field.send_keys(query)
            time.sleep(2)

            # Look for search results containing restaurant name
            print(f"[shopeefood-v3] Looking for search results...")

            # Click first result that contains "Meili"
            result_elements = driver.find_elements(
                by=AppiumBy.XPATH,
                value='//android.widget.TextView[contains(@text, "Meili")]'
            )

            if result_elements:
                print(f"[shopeefood-v3] Found {len(result_elements)} results with 'Meili'")
                result_elements[0].click()
                time.sleep(3)
                return True
            else:
                print(f"[shopeefood-v3] No results found for: {query}")
                return False
        else:
            print(f"[shopeefood-v3] Could not find EditText after tapping search bar")
            return False

    except Exception as exc:
        print(f"[shopeefood-v3] Error searching: {exc}")
        import traceback
        traceback.print_exc()
        return False


def extract_restaurant_name(driver: webdriver.Remote, default_name: str) -> str:
    """Extract restaurant name from page"""
    try:
        # Look for TextViews containing "Meili"
        text_elements = driver.find_elements(
            by=AppiumBy.XPATH,
            value='//android.widget.TextView[contains(@text, "Meili")]'
        )

        for elem in text_elements[:5]:
            text = elem.text
            if text and len(text) > 5:
                return text

        return default_name
    except Exception:
        return default_name


def scroll_to_reviews(driver: webdriver.Remote):
    """Scroll down to reach reviews section"""
    size = driver.get_window_size()
    width = size['width']
    height = size['height']

    start_y = int(height * 0.7)
    end_y = int(height * 0.3)
    x = int(width * 0.5)

    # Scroll down 8 times to reach reviews
    for i in range(8):
        print(f"[shopeefood-v3] Scroll {i+1}/8...")
        driver.swipe(start_x=x, start_y=start_y, end_x=x, end_y=end_y, duration=500)
        time.sleep(1)


def extract_reviews(driver: webdriver.Remote, restaurant_name: str) -> list[dict]:
    """Extract reviews from current screen"""
    reviews: list[dict] = []

    try:
        # Get all text elements
        all_texts = driver.find_elements(
            by=AppiumBy.CLASS_NAME,
            value='android.widget.TextView'
        )

        print(f"[shopeefood-v3] Found {len(all_texts)} text elements")

        # Filter for potential review texts
        # Reviews are typically:
        # - Longer than 30 characters
        # - Not UI labels
        # - May contain Vietnamese

        skip_keywords = [
            'home', 'menu', 'order', 'like', 'notification', 'delivery',
            'restaurant', 'favorite', 'voucher', 'deal', 'shop', 'collection',
            'my orders', 'likes', 'me', 'giao hàng', 'đặt món', 'yêu thích',
            'thông báo', 'trang chủ', 'ưu đãi', 'giảm giá'
        ]

        potential_reviews = []
        for elem in all_texts:
            text = elem.text
            if not text or len(text) < 30:
                continue

            text_lower = text.lower()

            # Skip UI labels
            if any(keyword in text_lower for keyword in skip_keywords):
                continue

            # Skip URLs, errors, numbers only
            if any(x in text_lower for x in ['http', 'error', 'connection', 'www.']):
                continue

            if text.replace(' ', '').replace(',', '').replace('.', '').isdigit():
                continue

            potential_reviews.append(text)

        print(f"[shopeefood-v3] Identified {len(potential_reviews)} potential reviews")

        # Create review objects
        for i, text in enumerate(potential_reviews[:15]):  # Max 15 reviews per restaurant
            reviews.append({
                "platform": "shopeefood",
                "review_id": f"{restaurant_name}_{i}_{int(time.time())}",
                "restaurant_url": "",
                "restaurant_name": restaurant_name,
                "author": "Unknown",
                "rating": 0,
                "text": text,
                "created_at": "",
                "crawled_at": datetime.now(timezone.utc).isoformat(),
            })

    except Exception as exc:
        print(f"[shopeefood-v3] Error extracting reviews: {exc}")

    return reviews


if __name__ == "__main__":
    sys.exit(main())
