#!/usr/bin/env python3
"""
GrabFood Review Crawler using Selenium + Chrome Remote Debugging

Prerequisites:
1. Start Chrome with remote debugging:
   /Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
     --remote-debugging-port=9229 \
     --user-data-dir=/tmp/chrome-grabfood

2. Login to GrabFood manually in that browser
3. Navigate to any restaurant to verify you're logged in

Usage:
    python3 scripts/grabfood/grabfood_review_crawler.py
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from selenium import webdriver
from selenium.common.exceptions import SessionNotCreatedException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from social_listening.keyword_config import load_keyword_payload
from social_listening.film_paths import platform_raw_dir
from social_listening.paths import ensure_dir

DEBUGGER_ADDRESS = os.getenv("GRABFOOD_DEBUGGER_ADDRESS", "127.0.0.1:9229")
OUTPUT_FILE = platform_raw_dir("grabfood") / "grabfood_all_reviews.json"
MAX_RESTAURANT_COUNT = int(os.getenv("GRABFOOD_MAX_RESTAURANT_COUNT", "20"))
MAX_SCROLL_ROUNDS = int(os.getenv("GRABFOOD_REVIEW_SCROLL_ROUNDS", "15"))
SCROLL_PAUSE_SECONDS = float(os.getenv("GRABFOOD_REVIEW_SCROLL_PAUSE", "2.0"))


def main() -> int:
    keyword_payload = load_keyword_payload()
    restaurant_urls = []

    # Get restaurant URLs from keyword config or search results
    if "grabfood_urls" in keyword_payload:
        restaurant_urls = keyword_payload["grabfood_urls"]
    else:
        search_file = latest_grabfood_search_file()
        if search_file and search_file.exists():
            search_data = json.loads(search_file.read_text(encoding="utf-8"))
            if isinstance(search_data, list):
                restaurant_urls = [
                    item.get("url")
                    for item in search_data
                    if item.get("url") and is_meili_branch_result(item)
                ]

    if not restaurant_urls:
        print("[grabfood] No restaurant URLs found")
        print("[grabfood] Add 'grabfood_urls' to your keyword config or run search/filter crawler first")
        return 1

    print(f"[grabfood] Found {len(restaurant_urls)} restaurants to crawl")

    driver = build_driver()
    try:
        all_reviews: list[dict] = []

        for idx, url in enumerate(restaurant_urls[:MAX_RESTAURANT_COUNT], 1):
            print(f"\n[grabfood] {idx}/{len(restaurant_urls[:MAX_RESTAURANT_COUNT])} url={url}")

            try:
                driver.get(url)
                time.sleep(5)

                # Extract restaurant metadata
                restaurant_name = extract_restaurant_name(driver)
                print(f"[grabfood] Restaurant: {restaurant_name}")

                # Try to find and click Reviews tab
                reviews_clicked = click_reviews_tab(driver)
                if reviews_clicked:
                    print("[grabfood] Clicked Reviews tab")
                    time.sleep(3)
                else:
                    print("[grabfood] Could not find Reviews tab, trying to scroll anyway...")

                # Scroll to load reviews
                scroll_reviews_section(driver)

                # Extract reviews
                reviews = extract_reviews_from_page(driver, url, restaurant_name)
                all_reviews.extend(reviews)
                print(f"[grabfood] Extracted {len(reviews)} reviews")

            except Exception as exc:
                print(f"[grabfood] Error crawling {url}: {exc}")
                continue

        # Save results
        ensure_dir(OUTPUT_FILE.parent)
        OUTPUT_FILE.write_text(
            json.dumps(all_reviews, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

        print(f"\n[grabfood] Saved {len(all_reviews)} total reviews to {OUTPUT_FILE}")
        return 0

    finally:
        driver.quit()


def latest_grabfood_search_file() -> Path | None:
    raw_dir = platform_raw_dir("grabfood")
    candidates = sorted(
        list(raw_dir.glob("grabfood_search_filtered_*.json")) + list(raw_dir.glob("grabfood_search_*.json")),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def is_meili_branch_result(item: dict) -> bool:
    name = str(item.get("name") or item.get("restaurant_name") or "").casefold()
    if "meili" not in name and "mei li" not in name:
        return False
    return any(
        term in name
        for term in (
            "mì bò đài loan",
            "mi bo dai loan",
            "mì sủi cảo",
            "mi sui cao",
            "bánh bao kẹp",
            "banh bao kep",
            "nguyễn văn khối",
            "nguyen van khoi",
            "nhiêu tứ",
            "nhieu tu",
            "ung văn khiêm",
            "ung van khiem",
            "mai văn vĩnh",
            "mai van vinh",
        )
    )
def build_driver() -> webdriver.Chrome:
    """Build Chrome driver with remote debugging connection"""
    options = Options()
    options.debugger_address = DEBUGGER_ADDRESS

    driver_path = resolve_chromedriver_path()

    try:
        if driver_path:
            return webdriver.Chrome(service=Service(driver_path), options=options)
        return webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    except SessionNotCreatedException as exc:
        raise RuntimeError(
            f"Cannot connect to Chrome at {DEBUGGER_ADDRESS}. Start Chrome with:\n"
            "/Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome "
            "--remote-debugging-port=9229 "
            "--user-data-dir=/tmp/chrome-grabfood\n\n"
            "Then login to GrabFood manually in that browser."
        ) from exc


def resolve_chromedriver_path() -> str:
    """Find ChromeDriver in webdriver_manager cache"""
    cache_root = Path.home() / ".wdm" / "drivers" / "chromedriver" / "mac64"
    if not cache_root.exists():
        return ""
    candidates = sorted(cache_root.glob("*/chromedriver-mac-arm64/chromedriver"), reverse=True)
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return ""


def extract_restaurant_name(driver: webdriver.Chrome) -> str:
    """Extract restaurant name from page"""
    return driver.execute_script("""
        const h1 = document.querySelector('h1');
        if (h1) return h1.textContent.trim();

        const title = document.querySelector('[data-testid="merchant-name"], .merchant-name, .restaurant-name');
        if (title) return title.textContent.trim();

        return document.title || 'Unknown Restaurant';
    """)


def click_reviews_tab(driver: webdriver.Chrome) -> bool:
    """Find and click Reviews tab"""
    return driver.execute_script("""
        // Try various selectors for Reviews tab
        const selectors = [
            'button:contains("Reviews")',
            'button:contains("Đánh giá")',
            '[role="tab"]:contains("Reviews")',
            '[role="tab"]:contains("Đánh giá")',
            'a:contains("Reviews")',
            'a:contains("Đánh giá")',
            '[data-testid*="review"]',
            '.review-tab',
            '.reviews-tab',
        ];

        // Manual search for text content
        const allButtons = Array.from(document.querySelectorAll('button, [role="tab"], a, div[class*="tab"]'));
        for (const btn of allButtons) {
            const text = (btn.textContent || '').toLowerCase();
            if (text.includes('review') || text.includes('đánh giá') || text.includes('danh gia')) {
                btn.click();
                return true;
            }
        }

        return false;
    """)


def scroll_reviews_section(driver: webdriver.Chrome) -> None:
    """Scroll to load more reviews"""
    for round_num in range(MAX_SCROLL_ROUNDS):
        driver.execute_script("""
            // Find scrollable container with reviews
            const containers = Array.from(document.querySelectorAll('div[role="feed"], div[class*="review"], div[class*="scroll"]'));
            const scrollable = containers.find(c => c.scrollHeight > c.clientHeight + 50);

            if (scrollable) {
                scrollable.scrollTop = scrollable.scrollHeight;
            } else {
                // Scroll window
                window.scrollBy(0, 500);
            }
        """)
        time.sleep(SCROLL_PAUSE_SECONDS)

        # Check if new content loaded
        if round_num % 3 == 0:
            review_count = driver.execute_script("""
                return document.querySelectorAll('[data-testid*="review"], .review-card, div[class*="Review"]').length;
            """)
            print(f"[grabfood] Scroll round {round_num + 1}, reviews visible: {review_count}")


def extract_reviews_from_page(driver: webdriver.Chrome, restaurant_url: str, restaurant_name: str) -> list[dict]:
    """Extract all review elements from current page"""

    raw_reviews = driver.execute_script("""
        // Try multiple selectors to find review cards
        const reviewSelectors = [
            '[data-testid*="review"]',
            '.review-card',
            'div[class*="Review"]',
            'div[class*="review"]',
            '[class*="ReviewCard"]',
            '[class*="review-item"]',
        ];

        let reviewElements = [];
        for (const selector of reviewSelectors) {
            reviewElements = Array.from(document.querySelectorAll(selector));
            if (reviewElements.length > 0) break;
        }

        // If still no reviews, try to find by structure
        if (reviewElements.length === 0) {
            // Look for div with author name + rating + text pattern
            const allDivs = Array.from(document.querySelectorAll('div'));
            reviewElements = allDivs.filter(div => {
                const text = div.textContent || '';
                // Heuristic: has star icon and some text
                return div.querySelector('[aria-label*="star"]') && text.length > 20;
            });
        }

        console.log(`Found ${reviewElements.length} review elements`);

        return reviewElements.slice(0, 200).map((card, idx) => {
            // Extract all text nodes
            const allText = Array.from(card.querySelectorAll('span, div, p'))
                .map(el => (el.textContent || '').trim())
                .filter(Boolean);

            // Find author (usually first short text)
            const author = allText.find(text => text.length < 50 && text.length > 2) || 'Unknown';

            // Find rating
            const ratingEl = card.querySelector('[aria-label*="star"], [class*="rating"], [class*="Rating"]');
            const ratingLabel = ratingEl ? (ratingEl.getAttribute('aria-label') || ratingEl.textContent || '') : '';

            // Find review text (usually longest text)
            const reviewText = allText.reduce((longest, current) =>
                current.length > longest.length ? current : longest
            , '');

            // Find date (text with "ago" or Vietnamese time indicators)
            const dateText = allText.find(text =>
                /(ago|trước|week|day|month|year|tuần|ngày|tháng|năm)/i.test(text)
            ) || '';

            return {
                index: idx,
                author: author,
                rating_label: ratingLabel,
                text: reviewText,
                date_label: dateText,
                all_text: allText,
            };
        });
    """)

    reviews: list[dict] = []
    crawled_at = datetime.now(timezone.utc).isoformat()

    for raw in raw_reviews or []:
        if not isinstance(raw, dict):
            continue

        text = re.sub(r"\s+", " ", str(raw.get("text") or "")).strip()
        author = re.sub(r"\s+", " ", str(raw.get("author") or "")).strip()

        # Skip if no meaningful text
        if len(text) < 10:
            continue

        # Skip if text same as author (probably not a review)
        if text == author:
            continue

        # Parse rating from label
        rating = parse_rating_label(raw.get("rating_label", ""))

        review_id = f"grabfood_{sanitize_filename(restaurant_name)}_{raw.get('index', 0)}_{crawled_at[:10]}"

        reviews.append({
            "platform": "grabfood",
            "review_id": review_id,
            "restaurant_url": restaurant_url,
            "restaurant_name": restaurant_name,
            "author": author,
            "rating": rating,
            "text": text,
            "created_at_label": raw.get("date_label", ""),
            "crawled_at": crawled_at,
            "raw_data": raw,
        })

    return reviews


def parse_rating_label(label: str) -> float:
    """Parse rating from various label formats"""
    text = str(label).lower()

    # Try to find number followed by "star" or "sao"
    match = re.search(r'(\d+(?:\.\d+)?)\s*(?:star|sao)', text)
    if match:
        return float(match.group(1))

    # Try to find just a number 1-5
    match = re.search(r'([1-5])(?:\.\d+)?', text)
    if match:
        value = float(match.group(0))
        if 0 <= value <= 5:
            return value

    return 0.0


def sanitize_filename(text: str) -> str:
    """Convert text to safe filename"""
    return re.sub(r'[^a-z0-9]+', '_', text.lower()).strip('_')[:50]


if __name__ == "__main__":
    raise SystemExit(main())
