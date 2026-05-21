#!/usr/bin/env python3
"""
GrabFood Search Runner - Crawl restaurants from GrabFood web
Using Playwright for web scraping
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from urllib.parse import urlparse
from datetime import datetime, timezone
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
except ImportError:
    print("❌ Playwright not installed")
    print("Install: pip3 install playwright && playwright install")
    sys.exit(1)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from social_listening.film_paths import platform_raw_dir
from social_listening.paths import ensure_dir

OUTPUT_DIR = platform_raw_dir("grabfood")
CONFIG_DIR = PROJECT_ROOT / "data" / "grabfood" / "config"
CONFIG_FILE = CONFIG_DIR / "location_config.json"
USER_DATA_DIR = Path(os.getenv("GRABFOOD_USER_DATA_DIR", "/tmp/playwright-grabfood"))
REMOTE_DEBUGGING_PORT = int(os.getenv("GRABFOOD_REMOTE_DEBUGGING_PORT", "9229"))

# Base URL
GRABFOOD_ORIGIN = "https://food.grab.com"
GRABFOOD_BASE_URL = "https://food.grab.com/vn/vi"


def load_config() -> dict:
    """Load location configuration"""
    if not CONFIG_FILE.exists():
        print(f"[grabfood] ⚠️  Config not found: {CONFIG_FILE}")
        print(f"[grabfood] Using default configuration")
        return {
            "default_location": {
                "address": "Thành phố Hồ Chí Minh",
                "latitude": 10.8231,
                "longitude": 106.6297
            },
            "locations": [],
            "search_keywords": ["Meili", "美粒"],
            "crawler_settings": {
                "max_restaurants_per_search": 50,
                "scroll_count": 5,
                "delay_between_requests": 2,
                "headless": False,
                "extract_details_inline": True,
                "max_detail_restaurants": 8
            }
        }

    config = json.loads(CONFIG_FILE.read_text(encoding='utf-8'))
    print(f"[grabfood] ✅ Loaded config from: {CONFIG_FILE}")
    return config


def main() -> int:
    print("[grabfood] 🚀 Starting GrabFood web crawler...")

    # Load configuration
    config = load_config()
    search_keywords = config.get('search_keywords', ['Meili', '美粒'])
    crawler_settings = config.get('crawler_settings', {})

    # Get enabled locations
    enabled_locations = [loc for loc in config.get('locations', []) if loc.get('enabled', False)]

    # If no enabled locations, use default location
    if not enabled_locations:
        print("[grabfood] ⚠️  No enabled locations found, using default location")
        default_loc = config.get('default_location', {})
        enabled_locations = [{
            'id': 'default',
            'name': default_loc.get('address', 'Default'),
            'address': default_loc.get('address', ''),
            'latitude': default_loc.get('latitude', 10.7769),
            'longitude': default_loc.get('longitude', 106.7009)
        }]

    print(f"[grabfood] 📍 Locations to crawl: {len(enabled_locations)}")
    print(f"[grabfood] 🔍 Keywords to search: {', '.join(search_keywords)}")

    all_restaurants = []
    headless = crawler_settings.get('headless', False)

    # Create persistent context directory to save cookies and permissions
    USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[grabfood] 💾 User data dir: {USER_DATA_DIR}")
    print(f"[grabfood] 🔌 Remote debugging port: {REMOTE_DEBUGGING_PORT}")

    with sync_playwright() as p:
        # Use persistent context to save state
        browser = p.chromium.launch_persistent_context(
            user_data_dir=str(USER_DATA_DIR),
            headless=headless,
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            locale='vi-VN',
            permissions=['geolocation'],
            args=[f"--remote-debugging-port={REMOTE_DEBUGGING_PORT}"],
        )

        # Get the default page (persistent context auto-creates one)
        page = browser.pages[0] if browser.pages else browser.new_page()

        # Crawl each location
        for location in enabled_locations:
            print(f"\n[grabfood] 📍 Location: {location['name']} ({location['address']})")

            # Set geolocation for this location
            browser.set_geolocation({'latitude': location['latitude'], 'longitude': location['longitude']})
            print(f"[grabfood]   📍 Set geolocation: {location['latitude']}, {location['longitude']}")

            # Navigate to homepage first to set location cookie
            print(f"[grabfood]   🌐 Setting location on GrabFood...")
            try:
                page.goto(GRABFOOD_BASE_URL, wait_until='networkidle', timeout=30000)
                time.sleep(3)  # Wait for location to be set
            except Exception as e:
                print(f"[grabfood]   ⚠️  Could not set location: {e}")

            # Search each keyword in this location
            for keyword in search_keywords:
                print(f"\n[grabfood]   🔍 Searching for: {keyword}")

                try:
                    restaurants = search_and_extract(page, keyword, location, crawler_settings)
                    all_restaurants.extend(restaurants)
                    print(f"[grabfood]   ✅ Found {len(restaurants)} restaurants for '{keyword}'")

                except Exception as e:
                    print(f"[grabfood]   ❌ Error searching '{keyword}': {e}")
                    continue

                # Delay between requests
                delay = crawler_settings.get('delay_between_requests', 2)
                time.sleep(delay)

        browser.close()

    # Remove duplicates by restaurant ID + location
    unique_restaurants = {}
    for r in all_restaurants:
        # Create unique key: restaurant_id + location_id
        restaurant_id = r.get('restaurant_id') or r.get('name')
        location_id = r.get('location_id', 'default')
        unique_key = f"{restaurant_id}_{location_id}"

        if unique_key not in unique_restaurants:
            unique_restaurants[unique_key] = r

    final_restaurants = list(unique_restaurants.values())

    # Save results
    if final_restaurants:
        ensure_dir(OUTPUT_DIR)
        output_file = OUTPUT_DIR / f"grabfood_search_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        output_file.write_text(
            json.dumps(final_restaurants, ensure_ascii=False, indent=2),
            encoding='utf-8'
        )
        print(f"\n[grabfood] 💾 Saved {len(final_restaurants)} unique restaurants to: {output_file}")
    else:
        print(f"\n[grabfood] ⚠️  No restaurants found")

    return 0


def search_and_extract(page, keyword: str, location: dict, crawler_settings: dict) -> list[dict]:
    """Search for keyword and extract restaurant data"""

    # Navigate to search URL
    search_url = f"{GRABFOOD_BASE_URL}/restaurants?search={keyword}"
    print(f"[grabfood]   📄 Loading: {search_url}")

    page.goto(search_url, wait_until='networkidle', timeout=30000)
    time.sleep(3)  # Wait for dynamic content

    # Scroll to load more restaurants
    scroll_count = crawler_settings.get('scroll_count', 5)
    print(f"[grabfood]   📜 Scrolling to load all results... ({scroll_count} scrolls)")
    scroll_search_results(page, scroll_count)

    # Extract restaurant cards
    print(f"[grabfood]   🍽️  Extracting restaurant data...")

    restaurants = []

    # GrabFood uses various selectors, need to inspect actual HTML
    # Common patterns: article, div with restaurant data

    # Try multiple selectors
    selectors = [
        'article',
        '[class*="RestaurantListCol"]',
        '[class*="restaurant-item"]',
        '[data-testid*="restaurant"]'
    ]

    restaurant_elements = []
    selected_selector = ""
    for selector in selectors:
        elements = page.query_selector_all(selector)
        if elements:
            print(f"[grabfood]   ✓ Found {len(elements)} elements with selector: {selector}")
            restaurant_elements = elements
            selected_selector = selector
            break

    if not restaurant_elements:
        print(f"[grabfood]   ⚠️  No restaurant elements found, dumping page content...")
        # Debug: save page HTML
        debug_file = OUTPUT_DIR / f"debug_page_{keyword}.html"
        ensure_dir(OUTPUT_DIR)
        debug_file.write_text(page.content(), encoding='utf-8')
        print(f"[grabfood]   💾 Page saved to: {debug_file}")
        return []

    for idx, elem in enumerate(restaurant_elements):
        try:
            restaurant = extract_restaurant_data(elem, page, location, idx, selected_selector, keyword)
            if restaurant:
                restaurants.append(restaurant)
        except Exception as e:
            print(f"[grabfood]   ⚠️  Error extracting restaurant {idx}: {e}")
            continue

    # Apply max restaurants limit
    max_restaurants = crawler_settings.get('max_restaurants_per_search', 50)
    if len(restaurants) > max_restaurants:
        restaurants = restaurants[:max_restaurants]
        print(f"[grabfood]   ⚠️  Limited to {max_restaurants} restaurants per search")

    if crawler_settings.get("extract_details_inline", True) and selected_selector:
        restaurants = enrich_restaurants_inline(page, restaurants, search_url, selected_selector, scroll_count, crawler_settings)

    for restaurant in restaurants:
        restaurant.pop("_card_index", None)
        restaurant.pop("_selector", None)
        restaurant.pop("_search_keyword", None)

    return restaurants


def extract_restaurant_data(elem, page, location: dict, card_index: int, selector: str, keyword: str) -> dict | None:
    """Extract data from a single restaurant element"""

    try:
        # Get all text content
        text_content = elem.inner_text()

        # Try to find restaurant name
        name_elem = (
            elem.query_selector('h2') or
            elem.query_selector('h3') or
            elem.query_selector('[class*="name"]') or
            elem.query_selector('[class*="title"]')
        )
        restaurant_name = name_elem.inner_text().strip() if name_elem else "Unknown"

        # Extract rating
        rating = 0.0
        normalized_text = normalize_whitespace(text_content)

        rating_match = re.search(r'(\d+\.\d+)', normalized_text)
        if rating_match:
            rating_val = float(rating_match.group(1))
            if 0.0 <= rating_val <= 5.0:
                rating = rating_val

        # Extract review count
        review_count = extract_review_count(normalized_text)
        if not review_count:
            review_count = "0"

        # Extract delivery info
        delivery_time = extract_delivery_time(normalized_text)

        # Extract distance
        distance = ""
        distance_match = re.search(r'(\d+\.?\d*)\s*(km)', normalized_text, re.IGNORECASE)
        if distance_match:
            distance = distance_match.group(0)

        # Extract promo info
        promo = ""
        promo_keywords = ['giảm', 'off', 'voucher', 'deal', 'miễn phí']
        for line in text_content.split('\n'):
            if any(kw in line.lower() for kw in promo_keywords):
                promo = normalize_whitespace(line)
                break

        # Try to extract restaurant URL
        link_elem = elem.query_selector('a')
        restaurant_url = ""
        if link_elem:
            href = link_elem.get_attribute('href')
            if href:
                restaurant_url = build_grabfood_url(href)

        # Generate restaurant ID
        restaurant_id = slugify(restaurant_name)

        restaurant = {
            "platform": "grabfood",
            "restaurant_id": restaurant_id,
            "name": restaurant_name,
            "url": restaurant_url,
            "rating": rating,
            "review_count": review_count,
            "delivery_time": delivery_time,
            "distance": distance,
            "promo": promo,
            "location_id": location.get('id', 'default'),
            "location_name": location.get('name', ''),
            "location_address": location.get('address', ''),
            "location_latitude": location.get('latitude'),
            "location_longitude": location.get('longitude'),
            "crawled_at": datetime.now(timezone.utc).isoformat(),
            "_card_index": card_index,
            "_selector": selector,
            "_search_keyword": keyword,
        }

        return restaurant

    except Exception as e:
        print(f"[grabfood]      ⚠️  Extract error: {e}")
        return None


def normalize_whitespace(text: str) -> str:
    return re.sub(r'\s+', ' ', str(text or '')).strip()


def normalize_grabfood_url(url: str) -> str:
    text = str(url or "").strip()
    if not text:
        return ""
    if text.startswith("//"):
        text = f"https:{text}"
    elif text.startswith("/"):
        text = f"{GRABFOOD_ORIGIN}{text}"

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


def build_grabfood_url(href: str) -> str:
    text = str(href or "").strip()
    if not text:
        return ""
    if text.startswith("http://") or text.startswith("https://") or text.startswith("//"):
        return normalize_grabfood_url(text)
    return normalize_grabfood_url(f"{GRABFOOD_ORIGIN}{text if text.startswith('/') else f'/{text}'}")


def extract_review_count(text: str) -> str:
    patterns = [
        r'(\d+\+?)\s*(đánh giá|reviews?|ratings?)',
        r'\((\d+\+?)\s*(đánh giá|reviews?|ratings?)\)',
        r'(\d+\+?)\s*(?:lượt\s*)?(?:nhận xét|review)',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1)
    return ""


def extract_delivery_time(text: str) -> str:
    patterns = [
        r'(\d+)\s*-\s*(\d+)\s*(min|phút)',
        r'(\d+)\s*(min|phút)',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return normalize_whitespace(match.group(0))
    return ""


def slugify(text: str) -> str:
    """Convert text to slug"""
    text = text.lower()
    text = re.sub(r'[^a-z0-9]+', '_', text)
    text = text.strip('_')
    return text[:50]


def scroll_search_results(page, scroll_count: int) -> None:
    print(f"[grabfood]   📜 Scrolling to load all results... ({scroll_count} scrolls)")
    for _ in range(scroll_count):
        page.evaluate("window.scrollBy(0, window.innerHeight)")
        time.sleep(1)


def enrich_restaurants_inline(page, restaurants: list[dict], search_url: str, selector: str, scroll_count: int, crawler_settings: dict) -> list[dict]:
    max_detail_restaurants = int(crawler_settings.get("max_detail_restaurants", 8))
    target_rows = [row for row in restaurants if is_target_restaurant(row)]
    print(f"[grabfood]   🔬 Inline detail extraction for {min(len(target_rows), max_detail_restaurants)} restaurants")
    for restaurant in target_rows[:max_detail_restaurants]:
        try:
            details = extract_restaurant_details_inline(page, restaurant, search_url, selector, scroll_count)
            if details:
                restaurant.update(details)
                print(f"[grabfood]   ✅ Detail: {restaurant.get('name')} -> {len(restaurant.get('dishes', []))} dishes")
        except Exception as exc:
            print(f"[grabfood]   ⚠️  Detail extraction failed for {restaurant.get('name')}: {exc}")
    return restaurants


def is_target_restaurant(restaurant: dict) -> bool:
    name = str(restaurant.get("name") or "").casefold()
    keyword = str(restaurant.get("_search_keyword") or "").casefold()
    return "meili" in name or "美粒" in str(restaurant.get("name") or "") or (keyword and keyword in name)


def extract_restaurant_details_inline(page, restaurant: dict, search_url: str, selector: str, scroll_count: int) -> dict | None:
    current_url = normalize_grabfood_url(str(restaurant.get("url") or ""))
    if current_url:
        page.goto(current_url, wait_until="networkidle", timeout=30000)
        time.sleep(3)
    else:
        page.goto(search_url, wait_until="networkidle", timeout=30000)
        time.sleep(2)
        scroll_search_results(page, scroll_count)
        cards = page.query_selector_all(selector)
        card_index = int(restaurant.get("_card_index") or 0)
        if card_index >= len(cards):
            return None
        card = cards[card_index]
        link_elem = card.query_selector("a")
        if link_elem:
            link_elem.click()
        else:
            card.click()
        time.sleep(4)
    current_url = normalize_grabfood_url(page.url)
    if "không có nhà hàng nào" in page.locator("body").inner_text().casefold():
        raise RuntimeError(f"GrabFood returned empty restaurant page: {current_url}")
    restaurant_metrics = extract_restaurant_metrics_from_page(page)
    for _ in range(5):
        page.evaluate("window.scrollBy(0, window.innerHeight)")
        time.sleep(1)
    dishes = extract_dishes_from_page(page)
    if not dishes:
        save_debug_page(page, restaurant)
    return {
        "url": current_url,
        "rating": restaurant_metrics.get("rating", restaurant.get("rating", 0.0)),
        "review_count": restaurant_metrics.get("review_count", restaurant.get("review_count", "0")),
        "dishes": dishes,
        "dish_count": len(dishes),
        "detail_crawled_at": datetime.now(timezone.utc).isoformat(),
    }


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


def extract_dishes_from_page(page) -> list[dict]:
    selectors = [
        '[class*="MenuItem"]',
        '[class*="DishCard"]',
        '[class*="dish-item"]',
        '[data-testid*="menu-item"]',
        'article',
        '[role="article"]',
    ]
    for selector in selectors:
        elements = page.query_selector_all(selector)
        if elements and len(elements) > 3:
            dishes = [dish for dish in (extract_single_dish(elem) for elem in elements) if dish]
            if dishes:
                return dedupe_dishes(dishes)
    return dedupe_dishes(extract_dishes_from_text(page))


def extract_single_dish(elem) -> dict | None:
    try:
        text_content = normalize_whitespace(elem.inner_text())
        if not text_content:
            return None
        name = ""
        name_elem = (
            elem.query_selector('h3') or
            elem.query_selector('h4') or
            elem.query_selector('[class*="name"]') or
            elem.query_selector('[class*="title"]')
        )
        if name_elem:
            name = normalize_whitespace(name_elem.inner_text())
        if not name:
            lines = [normalize_whitespace(line) for line in elem.inner_text().splitlines() if normalize_whitespace(line)]
            for line in lines:
                if len(line) > 3 and "₫" not in line:
                    name = line
                    break
        if not name:
            return None
        price_match = re.search(r'(\d{1,3}(?:[.,]\d{3})*)\s*₫', text_content)
        order_match = re.search(r'(\d+\+?)\s*(order|đơn|sold|đã bán)', text_content, re.IGNORECASE)
        desc = ""
        desc_elem = elem.query_selector('[class*="description"]')
        if desc_elem:
            desc = normalize_whitespace(desc_elem.inner_text())
        return {
            "name": name,
            "price": price_match.group(0) if price_match else "",
            "order_count": normalize_whitespace(order_match.group(0)) if order_match else "0",
            "description": desc,
            "image_url": "",
        }
    except Exception:
        return None


def extract_dishes_from_text(page) -> list[dict]:
    body = page.locator("body").inner_text()
    lines = [normalize_whitespace(line) for line in body.splitlines()]
    lines = [line for line in lines if line]
    dishes: list[dict] = []
    price_pattern = re.compile(r'(\d{1,3}(?:[.,]\d{3})*)\s*₫')
    order_pattern = re.compile(r'(\d+\+?)\s*(order|đơn|sold|đã bán)', re.IGNORECASE)
    noise_pattern = re.compile(r'^(grab|menu|ưu đãi|promo|đánh giá|ratings?|reviews?|mở cửa|đóng cửa|freeship|thêm)$', re.IGNORECASE)
    for index, line in enumerate(lines):
        if not price_pattern.search(line):
            continue
        price = price_pattern.search(line).group(0)
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
        dishes.append({"name": name, "price": price, "order_count": order_count, "description": description, "image_url": ""})
    return dishes


def dedupe_dishes(dishes: list[dict]) -> list[dict]:
    seen: set[str] = set()
    cleaned: list[dict] = []
    for dish in dishes:
        name = normalize_whitespace(dish.get("name") or "")
        if len(name) < 3:
            continue
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append({**dish, "name": name})
    return cleaned


def save_debug_page(page, restaurant: dict) -> None:
    ensure_dir(OUTPUT_DIR)
    slug = slugify(str(restaurant.get("name") or "unknown"))
    html_path = OUTPUT_DIR / f"grabfood_debug_{slug}.html"
    txt_path = OUTPUT_DIR / f"grabfood_debug_{slug}.txt"
    html_path.write_text(page.content(), encoding="utf-8")
    txt_path.write_text(page.locator("body").inner_text(), encoding="utf-8")
    print(f"[grabfood]   💾 Saved debug page: {html_path.name}, {txt_path.name}")


if __name__ == "__main__":
    sys.exit(main())
