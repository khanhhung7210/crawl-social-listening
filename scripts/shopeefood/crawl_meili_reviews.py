#!/usr/bin/env python3
"""
Crawl ShopeeFood reviews for Meili restaurants

This is a simplified version that:
1. Opens restaurant via deep link
2. Scrolls to find reviews section
3. Extracts reviews
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

from social_listening.keyword_config import load_keyword_payload
from social_listening.film_paths import platform_raw_dir
from social_listening.paths import ensure_dir

OUTPUT_FILE = platform_raw_dir("shopeefood") / "shopeefood_reviews_android.json"

# Restaurant URLs from config
MEILI_RESTAURANTS = [
    "https://shopeefood.vn/ho-chi-minh/meili-mi-bo-dai-loan-nhieu-tu",
    "https://shopeefood.vn/ho-chi-minh/meili-mi-bo-dai-loan-ung-van-khiem",
    "https://shopeefood.vn/ho-chi-minh/meili-mi-bo-dai-loan-mai-van-vinh",
    "https://shopeefood.vn/ho-chi-minh/meili-mi-bo-dai-loan-nguyen-van-khoi",
]


def main() -> int:
    print("[shopeefood] Starting crawler...")
    print(f"[shopeefood] Will crawl {len(MEILI_RESTAURANTS)} restaurants")

    driver = build_driver()

    try:
        all_reviews: list[dict] = []

        for index, url in enumerate(MEILI_RESTAURANTS, 1):
            print(f"\n[shopeefood] {index}/{len(MEILI_RESTAURANTS)} Crawling: {url}")

            try:
                # Open restaurant in app via deep link
                print(f"[shopeefood] Opening restaurant in app...")
                os.system(f'adb shell am start -a android.intent.action.VIEW -d "{url}"')
                time.sleep(5)

                # Wait for page to load
                print(f"[shopeefood] Waiting for page to load...")
                time.sleep(3)

                # Extract restaurant info
                restaurant_name = extract_restaurant_name(driver)
                print(f"[shopeefood] Restaurant: {restaurant_name}")

                # Scroll down to find reviews section
                print(f"[shopeefood] Looking for reviews section...")
                scroll_to_reviews(driver)

                # Extract reviews
                print(f"[shopeefood] Extracting reviews...")
                reviews = extract_reviews(driver, url, restaurant_name)
                print(f"[shopeefood] Found {len(reviews)} reviews")

                all_reviews.extend(reviews)

            except Exception as exc:
                print(f"[shopeefood] Error crawling {url}: {exc}")
                continue

        # Save results
        ensure_dir(OUTPUT_FILE.parent)
        OUTPUT_FILE.write_text(
            json.dumps(all_reviews, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

        print(f"\n[shopeefood] ✅ Saved {len(all_reviews)} total reviews to {OUTPUT_FILE}")
        return 0

    finally:
        driver.quit()


def build_driver() -> webdriver.Remote:
    print("[shopeefood] Connecting to Android emulator...")

    options = UiAutomator2Options()
    options.platform_name = 'Android'
    options.device_name = 'emulator-5554'
    options.app_package = 'com.deliverynow'
    options.app_activity = 'foody.vn.deliverynow.SplashActivity'
    options.no_reset = True
    options.automation_name = 'UiAutomator2'

    driver = webdriver.Remote('http://127.0.0.1:4723', options=options)
    time.sleep(2)

    print("[shopeefood] Connected successfully")
    return driver


def extract_restaurant_name(driver: webdriver.Remote) -> str:
    """Try to extract restaurant name from page"""
    try:
        # Look for restaurant name (usually in a large TextView at top)
        name_elements = driver.find_elements(
            by=AppiumBy.XPATH,
            value='//android.widget.TextView'
        )

        for elem in name_elements[:10]:  # Check first 10 TextViews
            text = elem.text
            if text and 'meili' in text.lower():
                return text

        return "Meili Restaurant"
    except Exception:
        return "Meili Restaurant"


def scroll_to_reviews(driver: webdriver.Remote):
    """Scroll down to find reviews section"""
    size = driver.get_window_size()
    width = size['width']
    height = size['height']

    start_y = int(height * 0.7)
    end_y = int(height * 0.3)
    x = int(width * 0.5)

    # Scroll down 5 times to reach reviews section
    for i in range(5):
        print(f"[shopeefood] Scroll {i+1}/5...")
        driver.swipe(start_x=x, start_y=start_y, end_x=x, end_y=end_y, duration=500)
        time.sleep(1)


def extract_reviews(driver: webdriver.Remote, url: str, restaurant_name: str) -> list[dict]:
    """Extract all visible reviews on screen"""
    reviews: list[dict] = []

    try:
        # Get all TextViews
        all_texts = driver.find_elements(by=AppiumBy.CLASS_NAME, value='android.widget.TextView')

        print(f"[shopeefood] Found {len(all_texts)} text elements on screen")

        # Try to identify review texts
        # Reviews usually have:
        # - Author name
        # - Rating (5 stars, 4 stars, etc.)
        # - Review text (longer paragraph)
        # - Date

        review_texts = []
        for elem in all_texts:
            text = elem.text
            if text and len(text) > 20:  # Reviews are usually longer
                # Skip common UI texts
                if text in ['Home', 'My Orders', 'Likes', 'Notification', 'Me']:
                    continue
                if 'menu' in text.lower() or 'delivery' in text.lower():
                    continue

                review_texts.append(text)

        print(f"[shopeefood] Identified {len(review_texts)} potential review texts")

        # Create review objects
        for i, text in enumerate(review_texts[:10]):  # Limit to 10 reviews per restaurant
            reviews.append({
                "platform": "shopeefood",
                "review_id": f"{restaurant_name}_{i}_{int(time.time())}",
                "restaurant_url": url,
                "restaurant_name": restaurant_name,
                "author": "Unknown",  # Need to identify author
                "rating": 0,  # Need to identify rating
                "text": text,
                "created_at": "",  # Need to identify date
                "crawled_at": datetime.now(timezone.utc).isoformat(),
            })

    except Exception as exc:
        print(f"[shopeefood] Error extracting reviews: {exc}")

    return reviews


if __name__ == "__main__":
    sys.exit(main())
