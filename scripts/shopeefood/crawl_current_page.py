#!/usr/bin/env python3
"""
ShopeeFood Manual Crawler - Crawl from current page

Usage:
1. Manually search and open restaurant in ShopeeFood app
2. Run this script to crawl reviews from that page
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
except ImportError:
    print("❌ Appium-Python-Client not installed")
    sys.exit(1)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from social_listening.film_paths import platform_raw_dir
from social_listening.paths import ensure_dir

OUTPUT_FILE = platform_raw_dir("shopeefood") / "shopeefood_manual_crawl.json"


def main() -> int:
    print("[shopeefood-manual] 🔍 Starting manual crawler...")
    print("[shopeefood-manual] Make sure you're on a restaurant page!")
    print()

    driver = build_driver()

    try:
        # Get current restaurant name
        restaurant_name = extract_restaurant_name(driver)
        print(f"[shopeefood-manual] 🏪 Restaurant: {restaurant_name}")
        print()

        # Scroll down to reviews section
        print(f"[shopeefood-manual] 📜 Scrolling to find reviews...")
        scroll_to_reviews(driver, num_scrolls=10)
        print()

        # Extract reviews from screen
        print(f"[shopeefood-manual] 📝 Extracting reviews...")
        reviews = extract_reviews(driver, restaurant_name)

        if reviews:
            print(f"[shopeefood-manual] ✅ Found {len(reviews)} reviews!")

            # Save results
            ensure_dir(OUTPUT_FILE.parent)

            # Load existing reviews if any
            existing_reviews = []
            if OUTPUT_FILE.exists():
                try:
                    existing_reviews = json.loads(OUTPUT_FILE.read_text(encoding="utf-8"))
                except Exception:
                    pass

            # Append new reviews
            all_reviews = existing_reviews + reviews

            OUTPUT_FILE.write_text(
                json.dumps(all_reviews, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )

            print(f"[shopeefood-manual] 💾 Saved to: {OUTPUT_FILE}")
            print(f"[shopeefood-manual] 📊 Total reviews in file: {len(all_reviews)}")
        else:
            print(f"[shopeefood-manual] ⚠️  No reviews found on current screen")
            print(f"[shopeefood-manual] 💡 Make sure you scrolled to reviews section")

        print()
        print("[shopeefood-manual] ✨ Done!")
        return 0

    except Exception as exc:
        print(f"[shopeefood-manual] ❌ Error: {exc}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        driver.quit()


def build_driver() -> webdriver.Remote:
    print("[shopeefood-manual] 📱 Connecting to Android emulator...")

    options = UiAutomator2Options()
    options.platform_name = 'Android'
    options.device_name = 'emulator-5554'
    options.app_package = 'com.deliverynow'
    options.app_activity = 'foody.vn.deliverynow.SplashActivity'
    options.no_reset = True
    options.automation_name = 'UiAutomator2'

    driver = webdriver.Remote('http://127.0.0.1:4723', options=options)
    time.sleep(2)

    print("[shopeefood-manual] ✅ Connected!")
    return driver


def extract_restaurant_name(driver: webdriver.Remote) -> str:
    """Try to extract restaurant name from current page"""
    try:
        # Look for large TextViews at top (restaurant name is usually large)
        all_texts = driver.find_elements(
            by=AppiumBy.CLASS_NAME,
            value='android.widget.TextView'
        )

        # First few TextViews usually contain restaurant name
        for elem in all_texts[:15]:
            text = elem.text
            if text and len(text) > 5 and len(text) < 100:
                # Skip common UI texts
                if any(x in text.lower() for x in ['home', 'deliver', 'deal', 'order', 'like']):
                    continue
                # This might be the restaurant name
                if 'meili' in text.lower() or 'mì' in text.lower():
                    return text

        return "Unknown Restaurant"
    except Exception:
        return "Unknown Restaurant"


def scroll_to_reviews(driver: webdriver.Remote, num_scrolls: int = 10):
    """Scroll down to reach reviews section"""
    size = driver.get_window_size()
    width = size['width']
    height = size['height']

    start_y = int(height * 0.7)
    end_y = int(height * 0.3)
    x = int(width * 0.5)

    for i in range(num_scrolls):
        print(f"  Scroll {i+1}/{num_scrolls}...")
        driver.swipe(start_x=x, start_y=start_y, end_x=x, end_y=end_y, duration=500)
        time.sleep(1.5)


def extract_reviews(driver: webdriver.Remote, restaurant_name: str) -> list[dict]:
    """Extract all text that looks like reviews from current screen"""
    reviews: list[dict] = []

    try:
        # Get all text elements
        all_texts = driver.find_elements(
            by=AppiumBy.CLASS_NAME,
            value='android.widget.TextView'
        )

        print(f"  Found {len(all_texts)} text elements on screen")

        # Filter for review-like texts
        skip_keywords = [
            'home', 'menu', 'my orders', 'likes', 'notification', 'me',
            'delivery', 'restaurant', 'favorite', 'voucher', 'deal',
            'shop', 'collection', 'giao hàng', 'đặt món', 'yêu thích',
            'thông báo', 'trang chủ', 'ưu đãi', 'giảm giá', 'freeship',
            'combo', 'see all', 'xem thêm', 'order now', 'đặt ngay',
            'add to cart', 'thêm vào giỏ', 'price', 'giá', 'đ', 'vnd'
        ]

        potential_reviews = []
        seen_texts = set()

        for elem in all_texts:
            text = elem.text

            # Skip empty or short texts
            if not text or len(text) < 20:
                continue

            # Skip duplicates
            if text in seen_texts:
                continue
            seen_texts.add(text)

            text_lower = text.lower()

            # Skip UI labels
            if any(keyword in text_lower for keyword in skip_keywords):
                continue

            # Skip URLs, errors, prices
            if any(x in text_lower for x in ['http', 'www.', 'error', 'connection']):
                continue

            # Skip if mostly numbers (prices, ratings)
            if text.replace(' ', '').replace(',', '').replace('.', '').replace('đ', '').isdigit():
                continue

            # Skip very short reviews
            if len(text) < 30:
                continue

            potential_reviews.append(text)

        print(f"  Identified {len(potential_reviews)} potential reviews")

        # Create review objects
        timestamp = int(time.time())
        for i, text in enumerate(potential_reviews):
            reviews.append({
                "platform": "shopeefood",
                "review_id": f"{restaurant_name}_{i}_{timestamp}",
                "restaurant_url": "",
                "restaurant_name": restaurant_name,
                "author": "Unknown",
                "rating": 0,
                "text": text,
                "created_at": "",
                "crawled_at": datetime.now(timezone.utc).isoformat(),
            })

        # Print sample of what we found
        if reviews:
            print()
            print("  📄 Sample reviews found:")
            for i, review in enumerate(reviews[:3], 1):
                preview = review['text'][:80] + "..." if len(review['text']) > 80 else review['text']
                print(f"    {i}. {preview}")

    except Exception as exc:
        print(f"  ❌ Error extracting: {exc}")

    return reviews


if __name__ == "__main__":
    sys.exit(main())
