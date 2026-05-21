#!/usr/bin/env python3
"""
GrabFood Detail Runner - Extract menu & order counts from restaurant pages
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("❌ Playwright not installed")
    sys.exit(1)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from social_listening.film_paths import platform_raw_dir
from social_listening.paths import ensure_dir

OUTPUT_DIR = platform_raw_dir("grabfood")
OUTPUT_FILE = OUTPUT_DIR / f"grabfood_details_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
USER_DATA_DIR = Path(os.getenv("GRABFOOD_USER_DATA_DIR", "/tmp/playwright-grabfood"))
REMOTE_DEBUGGING_PORT = int(os.getenv("GRABFOOD_REMOTE_DEBUGGING_PORT", "9229"))


def main() -> int:
    print("[grabfood] 🍽️  Starting GrabFood detail crawler...")

    # Load filtered results first (preferred), fallback to search results
    filtered_files = sorted(OUTPUT_DIR.glob("grabfood_search_filtered_*.json"), reverse=True)
    search_files = sorted(OUTPUT_DIR.glob("grabfood_search_*.json"), reverse=True)

    if filtered_files:
        input_file = filtered_files[0]
        print(f"[grabfood] 📂 Loading filtered results: {input_file.name}")
    elif search_files:
        input_file = search_files[0]
        print(f"[grabfood] 📂 Loading search results: {input_file.name}")
        print(f"[grabfood] ⚠️  Tip: Run grabfood_search_filter.py first to filter by Meili keywords")
    else:
        print("[grabfood] ❌ No search results found. Run grabfood_search_runner.py first.")
        return 1

    latest_search = input_file
    print(f"[grabfood] 📂 Loading: {latest_search.name}")

    restaurants = json.loads(latest_search.read_text(encoding='utf-8'))
    print(f"[grabfood] 📊 Found {len(restaurants)} restaurants to process")

    all_details = []

    # Use same persistent context directory as search runner
    USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[grabfood] 💾 User data dir: {USER_DATA_DIR}")
    print(f"[grabfood] 🔌 Remote debugging port: {REMOTE_DEBUGGING_PORT}")

    with sync_playwright() as p:
        # Use persistent context to reuse cookies and permissions
        browser = p.chromium.launch_persistent_context(
            user_data_dir=str(USER_DATA_DIR),
            headless=False,
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            locale='vi-VN',
            permissions=['geolocation'],
            args=[f"--remote-debugging-port={REMOTE_DEBUGGING_PORT}"],
        )

        # Get the default page
        page = browser.pages[0] if browser.pages else browser.new_page()

        for idx, restaurant in enumerate(restaurants, 1):
            print(f"\n[grabfood] [{idx}/{len(restaurants)}] Processing: {restaurant['name']}")

            url = restaurant.get('url')
            if not url:
                print(f"[grabfood]   ⚠️  No URL, skipping")
                continue

            try:
                details = extract_restaurant_details(page, restaurant)
                if details:
                    all_details.append(details)
                    print(f"[grabfood]   ✅ Extracted {len(details.get('dishes', []))} dishes")

            except Exception as e:
                print(f"[grabfood]   ❌ Error: {e}")
                continue

            time.sleep(2)  # Rate limiting

        browser.close()

    # Save results
    if all_details:
        ensure_dir(OUTPUT_DIR)
        OUTPUT_FILE.write_text(
            json.dumps(all_details, ensure_ascii=False, indent=2),
            encoding='utf-8'
        )
        print(f"\n[grabfood] 💾 Saved {len(all_details)} restaurant details to: {OUTPUT_FILE}")
    else:
        print(f"\n[grabfood] ⚠️  No details extracted")

    return 0


def extract_restaurant_details(page, restaurant: dict) -> dict | None:
    """Extract full menu and order counts from restaurant page"""

    url = normalize_grabfood_url(restaurant['url'])
    print(f"[grabfood]   📄 Loading: {url}")

    page.goto(url, wait_until='networkidle', timeout=30000)
    time.sleep(3)
    restaurant_metrics = extract_restaurant_metrics_from_page(page)

    # Scroll to load all menu items
    print(f"[grabfood]   📜 Scrolling to load menu...")
    for i in range(5):
        page.evaluate("window.scrollBy(0, window.innerHeight)")
        time.sleep(1)

    # Extract dishes
    dishes = extract_dishes(page)
    if not dishes:
        save_debug_page(page, restaurant)

    details = {
        **restaurant,  # Include search data
        "rating": restaurant_metrics.get("rating", restaurant.get("rating", 0.0)),
        "review_count": restaurant_metrics.get("review_count", restaurant.get("review_count", "0")),
        "dishes": dishes,
        "dish_count": len(dishes),
        "detail_crawled_at": datetime.now(timezone.utc).isoformat()
    }

    return details


def extract_restaurant_metrics_from_page(page) -> dict:
    html = page.content()
    metrics = extract_restaurant_metrics_from_html(html)
    if metrics.get("review_count") not in ("", "0") or metrics.get("rating", 0.0) > 0:
        return metrics

    body_text = normalize_whitespace(page.locator("body").inner_text())
    rating_match = re.search(r'(\d+(?:\.\d+)?)\s+(?:\d+\s*(?:phút|min)|Closed|Đóng cửa)', body_text, re.IGNORECASE)
    if rating_match:
        rating_val = float(rating_match.group(1))
        if 0.0 <= rating_val <= 5.0:
            metrics["rating"] = rating_val

    review_match = re.search(r'(\d+\+?)\s*(đánh giá|reviews?|ratings?)', body_text, re.IGNORECASE)
    if review_match:
        metrics["review_count"] = review_match.group(1)

    return metrics


def extract_restaurant_metrics_from_html(html: str) -> dict:
    metrics = {"rating": 0.0, "review_count": "0"}
    aggregate_match = re.search(
        r'"aggregateRating"\s*:\s*\{\s*"@type"\s*:\s*"AggregateRating"\s*,\s*"ratingValue"\s*:\s*([0-9]+(?:\.[0-9]+)?)\s*,\s*"ratingCount"\s*:\s*([0-9]+)',
        html,
        re.IGNORECASE,
    )
    if aggregate_match:
        rating_val = float(aggregate_match.group(1))
        if 0.0 <= rating_val <= 5.0:
            metrics["rating"] = rating_val
        metrics["review_count"] = aggregate_match.group(2)
        return metrics

    script_matches = re.findall(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', html, re.IGNORECASE | re.DOTALL)
    for script_text in script_matches:
        try:
            payload = json.loads(script_text.strip())
        except Exception:
            continue
        candidates = payload if isinstance(payload, list) else [payload]
        for candidate in candidates:
            aggregate = candidate.get("aggregateRating") if isinstance(candidate, dict) else None
            if not isinstance(aggregate, dict):
                continue
            rating_val = aggregate.get("ratingValue")
            rating_count = aggregate.get("ratingCount")
            try:
                rating_float = float(rating_val)
            except (TypeError, ValueError):
                rating_float = 0.0
            if 0.0 <= rating_float <= 5.0:
                metrics["rating"] = rating_float
            if rating_count is not None:
                metrics["review_count"] = str(rating_count)
            if metrics["review_count"] not in ("", "0") or metrics["rating"] > 0:
                return metrics

    return metrics


def extract_dishes(page) -> list[dict]:
    """Extract all dishes with order counts"""

    dishes = []

    # Try multiple selectors for dish items
    selectors = [
        '[class*="MenuItem"]',
        '[class*="DishCard"]',
        '[class*="dish-item"]',
        '[data-testid*="menu-item"]',
        'article',
        '[role="article"]'
    ]

    dish_elements = []
    for selector in selectors:
        elements = page.query_selector_all(selector)
        if elements and len(elements) > 3:  # Need at least a few dishes
            print(f"[grabfood]   ✓ Found {len(elements)} dish elements with: {selector}")
            dish_elements = elements
            break

    if not dish_elements:
        print(f"[grabfood]   ⚠️  No dish elements found, trying text fallback")
        return extract_dishes_from_text(page)

    for idx, elem in enumerate(dish_elements):
        try:
            dish = extract_single_dish(elem)
            if dish:
                dishes.append(dish)
        except Exception as e:
            print(f"[grabfood]      ⚠️  Error extracting dish {idx}: {e}")
            continue

    return dishes or extract_dishes_from_text(page)


def extract_single_dish(elem) -> dict | None:
    """Extract data from a single dish element"""

    try:
        text_content = elem.inner_text()

        # Extract dish name
        name_elem = (
            elem.query_selector('h3') or
            elem.query_selector('h4') or
            elem.query_selector('[class*="name"]') or
            elem.query_selector('[class*="title"]')
        )
        dish_name = name_elem.inner_text().strip() if name_elem else ""

        if not dish_name or len(dish_name) < 3:
            # Try getting from text content first line
            lines = text_content.split('\n')
            for line in lines:
                if len(line) > 3 and not line.strip().isdigit():
                    dish_name = line.strip()
                    break

        if not dish_name:
            return None

        # Extract price
        price = ""
        price_match = re.search(r'(\d{1,3}(?:[.,]\d{3})*)\s*₫', text_content)
        if price_match:
            price = price_match.group(0)

        # Extract order count
        order_count = "0"
        order_patterns = [
            r'(\d+\+?)\s*(order|đơn)',
            r'(\d+\+?)\s*sold',
            r'(\d+\+?)\s*đã\s*bán',
        ]
        for pattern in order_patterns:
            match = re.search(pattern, text_content, re.IGNORECASE)
            if match:
                order_count = match.group(0)
                break

        # Extract description
        description = ""
        desc_elem = elem.query_selector('[class*="description"]')
        if desc_elem:
            description = desc_elem.inner_text().strip()

        # Extract image URL
        image_url = ""
        img_elem = elem.query_selector('img')
        if img_elem:
            src = img_elem.get_attribute('src')
            if src:
                image_url = src

        dish = {
            "name": dish_name,
            "price": price,
            "order_count": order_count,
            "description": description,
            "image_url": image_url
        }

        return dish

    except Exception as e:
        return None


def extract_dishes_from_text(page) -> list[dict]:
    body = page.locator("body").inner_text()
    lines = [normalize_whitespace(line) for line in body.splitlines()]
    lines = [line for line in lines if line]
    dishes: list[dict] = []
    seen_names: set[str] = set()
    price_pattern = re.compile(r'(\d{1,3}(?:[.,]\d{3})*)\s*₫')
    order_pattern = re.compile(r'(\d+\+?)\s*(order|đơn|sold|đã bán)', re.IGNORECASE)
    noise_pattern = re.compile(r'^(grab|menu|ưu đãi|promo|đánh giá|ratings?|reviews?|mở cửa|đóng cửa|freeship)$', re.IGNORECASE)

    for index, line in enumerate(lines):
        if not price_pattern.search(line):
            continue
        price_match = price_pattern.search(line)
        price = price_match.group(0) if price_match else ""
        name = ""
        for cursor in range(index - 1, max(-1, index - 4), -1):
            candidate = lines[cursor]
            if not candidate or noise_pattern.search(candidate):
                continue
            if price_pattern.search(candidate) or order_pattern.search(candidate):
                continue
            if len(candidate) < 3:
                continue
            name = candidate
            break
        if not name:
            continue
        name_key = name.casefold()
        if name_key in seen_names:
            continue
        seen_names.add(name_key)
        order_count = "0"
        for cursor in range(index + 1, min(len(lines), index + 4)):
            candidate = lines[cursor]
            match = order_pattern.search(candidate)
            if match:
                order_count = normalize_whitespace(match.group(0))
                break
        description = ""
        if index + 1 < len(lines):
            candidate = lines[index + 1]
            if not order_pattern.search(candidate) and not price_pattern.search(candidate) and len(candidate) > 10:
                description = candidate
        dishes.append(
            {
                "name": name,
                "price": price,
                "order_count": order_count,
                "description": description,
                "image_url": "",
            }
        )
    print(f"[grabfood]   ✓ Text fallback extracted {len(dishes)} dishes")
    return dishes


def normalize_whitespace(text: str) -> str:
    return re.sub(r'\s+', ' ', str(text or '')).strip()


def normalize_grabfood_url(url: str) -> str:
    text = str(url or "").strip()
    if not text:
        return ""
    if text.startswith("//"):
        text = f"https:{text}"
    elif text.startswith("/"):
        text = f"https://food.grab.com{text}"

    parsed = urlparse(text)
    scheme = parsed.scheme or "https"
    netloc = parsed.netloc
    path = parsed.path or ""

    if not netloc and path.startswith("food.grab.com"):
        path = path.removeprefix("food.grab.com")
        netloc = "food.grab.com"
    elif not netloc and path.startswith("/food.grab.com"):
        path = path.removeprefix("/food.grab.com")
        netloc = "food.grab.com"

    if not netloc:
        return text

    path = re.sub(r"/{2,}", "/", path)
    path = path.replace("/vn/vi/vn/vi/", "/vn/vi/")
    if path.startswith("/restaurant/"):
        path = f"/vn/vi{path}"

    normalized = f"{scheme}://{netloc}{path}"
    if parsed.query:
        normalized = f"{normalized}?{parsed.query}"
    return normalized


def save_debug_page(page, restaurant: dict) -> None:
    ensure_dir(OUTPUT_DIR)
    slug = slugify(str(restaurant.get("name") or "unknown"))
    html_path = OUTPUT_DIR / f"grabfood_debug_{slug}.html"
    txt_path = OUTPUT_DIR / f"grabfood_debug_{slug}.txt"
    html_path.write_text(page.content(), encoding="utf-8")
    txt_path.write_text(page.locator("body").inner_text(), encoding="utf-8")
    print(f"[grabfood]   💾 Saved debug page: {html_path.name}, {txt_path.name}")


def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r'[^a-z0-9]+', '_', text)
    text = text.strip('_')
    return text[:50]


if __name__ == "__main__":
    sys.exit(main())
