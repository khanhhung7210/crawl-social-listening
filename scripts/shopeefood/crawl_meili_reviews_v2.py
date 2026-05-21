#!/usr/bin/env python3
"""
ShopeeFood Review Crawler V2 - Using In-App Navigation

This version:
1. Uses app search to find restaurants
2. Navigates within app (not deep links)
3. Extracts reviews from actual review section
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
    from selenium.common.exceptions import NoSuchElementException, TimeoutException
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
except ImportError:
    print("❌ Appium-Python-Client not installed")
    sys.exit(1)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from social_listening.film_paths import platform_raw_dir
from social_listening.paths import ensure_dir

OUTPUT_FILE = platform_raw_dir("shopeefood") / "shopeefood_reviews_android_v2.json"

# Restaurant names to search for
MEILI_RESTAURANTS = [
    "Meili - Mì Bò Đài Loan - Nhiêu Tứ",
    "Meili - Mì Bò Đài Loan - Ung Văn Khiêm",
    "Meili - Mì Bò Đài Loan - Mai Văn Vinh",
    "Meili - Mì Bò Đài Loan - Nguyễn Văn Khối",
]


def main() -> int:
    print("[shopeefood-v2] Starting improved crawler...")
    print(f"[shopeefood-v2] Will search for {len(MEILI_RESTAURANTS)} restaurants")

    driver = build_driver()
    wait = WebDriverWait(driver, 10)

    try:
        all_reviews: list[dict] = []

        for index, restaurant_name in enumerate(MEILI_RESTAURANTS, 1):
            print(f"\n[shopeefood-v2] {index}/{len(MEILI_RESTAURANTS)} Searching: {restaurant_name}")

            try:
                # Search for restaurant in app
                if search_restaurant(driver, wait, restaurant_name):
                    print(f"[shopeefood-v2] Found restaurant, opening...")
                    time.sleep(2)

                    # Extract reviews
                    print(f"[shopeefood-v2] Extracting reviews...")
                    reviews = extract_reviews_from_page(driver, restaurant_name)
                    print(f"[shopeefood-v2] Found {len(reviews)} reviews")

                    all_reviews.extend(reviews)

                    # Go back to home
                    print(f"[shopeefood-v2] Returning to home...")
                    go_back_to_home(driver)
                else:
                    print(f"[shopeefood-v2] Could not find restaurant: {restaurant_name}")

            except Exception as exc:
                print(f"[shopeefood-v2] Error processing {restaurant_name}: {exc}")
                # Try to recover by going back to home
                go_back_to_home(driver)
                continue

        # Save results
        ensure_dir(OUTPUT_FILE.parent)
        OUTPUT_FILE.write_text(
            json.dumps(all_reviews, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

        print(f"\n[shopeefood-v2] ✅ Saved {len(all_reviews)} total reviews to {OUTPUT_FILE}")
        return 0

    finally:
        driver.quit()


def build_driver() -> webdriver.Remote:
    print("[shopeefood-v2] Connecting to Android emulator...")

    options = UiAutomator2Options()
    options.platform_name = 'Android'
    options.device_name = 'emulator-5554'
    options.app_package = 'com.deliverynow'
    options.app_activity = 'foody.vn.deliverynow.SplashActivity'
    options.no_reset = True
    options.automation_name = 'UiAutomator2'

    driver = webdriver.Remote('http://127.0.0.1:4723', options=options)
    time.sleep(3)

    print("[shopeefood-v2] Connected successfully")
    return driver


def search_restaurant(driver: webdriver.Remote, wait: WebDriverWait, restaurant_name: str) -> bool:
    """Search for restaurant using in-app search"""
    try:
        # Look for search bar/field
        # Common search element attributes:
        # - text like "Restaurants, food and drinks"
        # - content-desc like "search"
        # - EditText elements

        print(f"[shopeefood-v2] Looking for search bar...")

        # Try to find search field by common text
        search_elements = driver.find_elements(
            by=AppiumBy.XPATH,
            value='//android.widget.EditText | //android.widget.TextView[contains(@text, "Restaurants")]'
        )

        if search_elements:
            print(f"[shopeefood-v2] Found {len(search_elements)} potential search elements")
            search_element = search_elements[0]
            search_element.click()
            time.sleep(1)

            # Type search query
            print(f"[shopeefood-v2] Typing search query: {restaurant_name}")
            search_element.send_keys("Meili")  # Search for "Meili" to find all branches
            time.sleep(2)

            # Look for search results
            print(f"[shopeefood-v2] Looking for search results...")

            # Click first result containing "Meili"
            results = driver.find_elements(
                by=AppiumBy.XPATH,
                value='//android.widget.TextView[contains(@text, "Meili")]'
            )

            if results:
                print(f"[shopeefood-v2] Found {len(results)} results, clicking first match...")

                # Try to find the specific branch
                for result in results:
                    result_text = result.text
                    if restaurant_name.split(" - ")[2] in result_text:  # Match location part
                        print(f"[shopeefood-v2] Found exact match: {result_text}")
                        result.click()
                        time.sleep(3)
                        return True

                # If no exact match, click first one
                results[0].click()
                time.sleep(3)
                return True
            else:
                print(f"[shopeefood-v2] No results found")
                return False
        else:
            print(f"[shopeefood-v2] Could not find search bar")
            return False

    except Exception as exc:
        print(f"[shopeefood-v2] Error searching: {exc}")
        return False


def extract_reviews_from_page(driver: webdriver.Remote, restaurant_name: str) -> list[dict]:
    """Extract reviews from current restaurant page"""
    reviews: list[dict] = []

    try:
        # First, try to scroll down to find reviews section
        print(f"[shopeefood-v2] Scrolling to find reviews...")

        size = driver.get_window_size()
        width = size['width']
        height = size['height']

        start_y = int(height * 0.7)
        end_y = int(height * 0.3)
        x = int(width * 0.5)

        # Scroll down several times to reach reviews
        for i in range(5):
            driver.swipe(start_x=x, start_y=start_y, end_x=x, end_y=end_y, duration=500)
            time.sleep(1)

        # Get all text elements
        all_texts = driver.find_elements(by=AppiumBy.CLASS_NAME, value='android.widget.TextView')

        print(f"[shopeefood-v2] Found {len(all_texts)} text elements on screen")

        # Look for review-like content
        # Reviews typically:
        # - Are longer texts (>30 chars)
        # - Not UI labels (Home, Menu, etc.)
        # - May contain Vietnamese characters
        # - Usually have accompanying rating/date info

        potential_reviews = []
        skip_keywords = ['home', 'menu', 'order', 'like', 'notification', 'delivery', 'restaurant']

        for elem in all_texts:
            text = elem.text
            if not text or len(text) < 30:
                continue

            # Skip common UI elements
            text_lower = text.lower()
            if any(keyword in text_lower for keyword in skip_keywords):
                continue

            # Skip URLs and error messages
            if 'http' in text_lower or 'error' in text_lower or 'connection' in text_lower:
                continue

            potential_reviews.append(text)

        print(f"[shopeefood-v2] Identified {len(potential_reviews)} potential reviews")

        # Create review objects
        for i, text in enumerate(potential_reviews[:10]):  # Limit to 10 reviews
            reviews.append({
                "platform": "shopeefood",
                "review_id": f"{restaurant_name}_{i}_{int(time.time())}",
                "restaurant_url": "",  # Not available
                "restaurant_name": restaurant_name,
                "author": "Unknown",  # Need better extraction
                "rating": 0,  # Need better extraction
                "text": text,
                "created_at": "",  # Need better extraction
                "crawled_at": datetime.now(timezone.utc).isoformat(),
            })

    except Exception as exc:
        print(f"[shopeefood-v2] Error extracting reviews: {exc}")

    return reviews


def go_back_to_home(driver: webdriver.Remote):
    """Navigate back to home screen"""
    try:
        # Press back button multiple times
        for _ in range(3):
            driver.back()
            time.sleep(1)

        # Or click Home tab if visible
        try:
            home_tab = driver.find_element(
                by=AppiumBy.XPATH,
                value='//android.widget.TextView[@text="Home"]'
            )
            home_tab.click()
            time.sleep(1)
        except NoSuchElementException:
            pass

    except Exception as exc:
        print(f"[shopeefood-v2] Error going back to home: {exc}")


if __name__ == "__main__":
    sys.exit(main())
