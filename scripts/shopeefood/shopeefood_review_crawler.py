#!/usr/bin/env python3
"""
ShopeeFood Review Crawler using Android Emulator + Appium

Prerequisites:
1. Android emulator running with ShopeeFood app installed
2. Appium server running
3. Logged into ShopeeFood app

Usage:
    python3 scripts/shopeefood/shopeefood_review_crawler.py
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
    print("Install with: pip3 install Appium-Python-Client")
    sys.exit(1)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from social_listening.keyword_config import load_keyword_payload
from social_listening.film_paths import platform_raw_dir
from social_listening.paths import ensure_dir

OUTPUT_FILE = platform_raw_dir("shopeefood") / "shopeefood_reviews_android.json"
MAX_SCROLL_ROUNDS = 30
SCROLL_PAUSE_SECONDS = 2.0

# TODO: Update these after using Appium Inspector
# Element selectors (placeholder values - need to be discovered)
REVIEW_CONTAINER_XPATH = '//android.widget.ListView[@resource-id="review_list"]'
REVIEW_TEXT_XPATH = '//android.widget.TextView[@resource-id="review_text"]'
REVIEW_AUTHOR_XPATH = '//android.widget.TextView[@resource-id="review_author"]'
REVIEW_RATING_XPATH = '//android.widget.RatingBar[@resource-id="review_rating"]'
REVIEW_DATE_XPATH = '//android.widget.TextView[@resource-id="review_date"]'


def main() -> int:
    keyword_payload = load_keyword_payload()
    restaurant_urls = keyword_payload.get("shopeefood_urls", [])

    if not restaurant_urls:
        print("[shopeefood] No ShopeeFood URLs found in keyword config")
        return 0

    print(f"[shopeefood] Found {len(restaurant_urls)} restaurants to crawl")

    # Connect to Appium
    driver = build_driver()

    try:
        all_reviews: list[dict] = []

        for index, url in enumerate(restaurant_urls, 1):
            print(f"\n[shopeefood] {index}/{len(restaurant_urls)} url={url}")

            try:
                reviews = crawl_restaurant_reviews(driver, url)
                all_reviews.extend(reviews)
                print(f"[shopeefood] Extracted {len(reviews)} reviews")
            except Exception as exc:
                print(f"[shopeefood] Error crawling {url}: {exc}")
                continue

        # Save results
        ensure_dir(OUTPUT_FILE.parent)
        OUTPUT_FILE.write_text(
            json.dumps(all_reviews, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

        print(f"\n[shopeefood] Saved {len(all_reviews)} total reviews to {OUTPUT_FILE}")
        return 0

    finally:
        driver.quit()


def build_driver() -> webdriver.Remote:
    """Connect to Appium server and ShopeeFood app"""
    print("[shopeefood] Connecting to Android emulator...")

    options = UiAutomator2Options()
    options.platform_name = 'Android'
    options.device_name = 'emulator-5554'
    options.app_package = 'com.deliverynow'
    options.app_activity = 'foody.vn.deliverynow.SplashActivity'
    options.no_reset = True  # Keep login state
    options.automation_name = 'UiAutomator2'

    driver = webdriver.Remote('http://127.0.0.1:4723', options=options)
    time.sleep(3)  # Wait for app to load

    print("[shopeefood] Connected successfully")
    return driver


def crawl_restaurant_reviews(driver: webdriver.Remote, restaurant_url: str) -> list[dict]:
    """
    Crawl reviews for a single restaurant

    Steps:
    1. Send deep link to open restaurant in app
    2. Navigate to Reviews tab
    3. Scroll and extract reviews
    """
    # Extract restaurant info from URL
    restaurant_slug = restaurant_url.split("/")[-1]
    restaurant_name = restaurant_slug.replace("-", " ").title()

    print(f"[shopeefood] Opening restaurant: {restaurant_name}")

    # Option 1: Use deep link (if ShopeeFood supports it)
    # deep_link = f"shopeefood://restaurant/{restaurant_slug}"
    # os.system(f'adb shell am start -a android.intent.action.VIEW -d "{deep_link}"')
    # time.sleep(5)

    # Option 2: Use web URL (if app handles http intents)
    os.system(f'adb shell am start -a android.intent.action.VIEW -d "{restaurant_url}"')
    time.sleep(5)

    # TODO: Navigate to Reviews tab
    # This depends on ShopeeFood UI structure
    # Example:
    # try:
    #     reviews_tab = driver.find_element(by=AppiumBy.XPATH, value='//android.widget.TextView[@text="Đánh giá"]')
    #     reviews_tab.click()
    #     time.sleep(2)
    # except NoSuchElementException:
    #     print("[shopeefood] Could not find Reviews tab")
    #     return []

    # Scroll and extract reviews
    reviews: list[dict] = []
    seen_review_ids: set[str] = set()

    for scroll_round in range(MAX_SCROLL_ROUNDS):
        print(f"[shopeefood] Scroll round {scroll_round + 1}/{MAX_SCROLL_ROUNDS}")

        # Extract reviews currently on screen
        current_reviews = extract_reviews_from_screen(driver, restaurant_url, restaurant_name)

        # Dedupe
        for review in current_reviews:
            review_id = review.get("review_id", "")
            if review_id and review_id not in seen_review_ids:
                seen_review_ids.add(review_id)
                reviews.append(review)

        # Check if we reached the end
        if not current_reviews:
            print("[shopeefood] No more reviews found")
            break

        # Scroll down
        scroll_down(driver)
        time.sleep(SCROLL_PAUSE_SECONDS)

    return reviews


def extract_reviews_from_screen(
    driver: webdriver.Remote,
    restaurant_url: str,
    restaurant_name: str
) -> list[dict]:
    """
    Extract all review elements currently visible on screen

    TODO: Update XPath selectors after using Appium Inspector
    """
    reviews: list[dict] = []

    try:
        # Find all review containers
        # NOTE: These XPath values are placeholders
        # Use Appium Inspector to find the correct selectors
        review_elements = driver.find_elements(
            by=AppiumBy.XPATH,
            value='//android.widget.LinearLayout[contains(@resource-id, "review")]'
        )

        print(f"[shopeefood] Found {len(review_elements)} review elements on screen")

        for elem in review_elements:
            try:
                # Extract review data
                # TODO: Update these selectors
                review_text = extract_text_from_element(elem, './/android.widget.TextView[@resource-id="review_text"]')
                author_name = extract_text_from_element(elem, './/android.widget.TextView[@resource-id="author_name"]')
                rating_text = extract_text_from_element(elem, './/android.widget.RatingBar')
                date_text = extract_text_from_element(elem, './/android.widget.TextView[@resource-id="review_date"]')

                # Parse rating
                rating = parse_rating(rating_text)

                # Generate review ID (ShopeeFood may not expose IDs)
                review_id = f"{restaurant_name}_{author_name}_{date_text}".replace(" ", "_")

                reviews.append({
                    "platform": "shopeefood",
                    "review_id": review_id,
                    "restaurant_url": restaurant_url,
                    "restaurant_name": restaurant_name,
                    "author": author_name,
                    "rating": rating,
                    "text": review_text,
                    "created_at": date_text,
                    "crawled_at": datetime.now(timezone.utc).isoformat(),
                })

            except Exception as exc:
                print(f"[shopeefood] Error extracting review: {exc}")
                continue

    except NoSuchElementException:
        print("[shopeefood] No review elements found")

    return reviews


def extract_text_from_element(parent_element, xpath: str) -> str:
    """Extract text from a child element"""
    try:
        element = parent_element.find_element(by=AppiumBy.XPATH, value=xpath)
        return element.text or ""
    except NoSuchElementException:
        return ""


def parse_rating(rating_text: str) -> int:
    """Parse rating from text (e.g., '5 stars' -> 5)"""
    try:
        # Extract first digit
        import re
        match = re.search(r'(\d+)', rating_text)
        if match:
            return int(match.group(1))
    except Exception:
        pass
    return 0


def scroll_down(driver: webdriver.Remote) -> None:
    """Scroll down the review list"""
    # Get screen size
    size = driver.get_window_size()
    width = size['width']
    height = size['height']

    # Scroll from bottom to top (80% -> 20%)
    start_y = int(height * 0.8)
    end_y = int(height * 0.2)
    x = int(width * 0.5)

    driver.swipe(start_x=x, start_y=start_y, end_x=x, end_y=end_y, duration=800)


if __name__ == "__main__":
    sys.exit(main())
