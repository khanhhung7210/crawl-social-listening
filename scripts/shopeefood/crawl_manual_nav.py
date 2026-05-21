#!/usr/bin/env python3
"""
ShopeeFood Crawler - Manual Navigation + Automated Extraction

WORKFLOW:
1. You manually search and open a Meili restaurant in ShopeeFood app
2. Press ENTER in terminal when ready
3. Script extracts: restaurant name, rating, review count, all dishes with sold counts
4. Script waits for you to navigate to next restaurant
5. Repeat for all restaurants

This hybrid approach ensures accuracy while automating tedious extraction.
"""

from __future__ import annotations

import json
import re
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

OUTPUT_FILE = platform_raw_dir("shopeefood") / "shopeefood_manual_extraction.json"

RESTAURANTS = [
    "Meili Nhiêu Tứ",
    "Meili Ung Văn Khiêm",
    "Meili Mai Văn Vinh",
    "Meili Nguyễn Văn Khối"
]


def main() -> int:
    print("\n" + "="*70)
    print("🍜 ShopeeFood Manual Navigation + Automated Extraction")
    print("="*70)
    print("\nWORKFLOW:")
    print("  1. Open ShopeeFood app on emulator")
    print("  2. Search for 'Meili' and click on a restaurant")
    print("  3. Press ENTER in terminal when restaurant page loads")
    print("  4. Script extracts all data automatically")
    print("  5. Navigate to next restaurant and repeat")
    print("\n" + "="*70)

    all_data = []

    for idx, restaurant in enumerate(RESTAURANTS, 1):
        print(f"\n\n📍 [{idx}/{len(RESTAURANTS)}] {restaurant}")
        print("-" * 70)
        print(f"👉 Please navigate to: {restaurant}")
        print(f"   (Search 'Meili' → Click on {restaurant})")

        input(f"\n✋ Press ENTER when {restaurant} page is loaded... ")

        try:
            # Build driver to read current page
            driver = build_driver()
            print("✅ Connected to app")

            # Extract data from current page
            restaurant_data = extract_all_data(driver, restaurant)

            if restaurant_data:
                all_data.append(restaurant_data)
                print(f"\n✅ Extracted data for {restaurant_data['name']}")
                print(f"   ⭐ Rating: {restaurant_data['rating']}")
                print(f"   📊 Reviews: {restaurant_data['review_count']}")
                print(f"   🍜 Dishes: {len(restaurant_data['dishes'])}")

                # Show sample dishes
                for dish in restaurant_data['dishes'][:3]:
                    print(f"      • {dish['name'][:50]}... → {dish['sold_count']} sold")
                if len(restaurant_data['dishes']) > 3:
                    print(f"      ... and {len(restaurant_data['dishes']) - 3} more dishes")

            driver.quit()

        except Exception as exc:
            print(f"❌ Error: {exc}")
            import traceback
            traceback.print_exc()

            retry = input("\n🔄 Try again for this restaurant? (y/n): ")
            if retry.lower() == 'y':
                continue
            else:
                print("⏭️  Skipping this restaurant")

    # Save results
    if all_data:
        ensure_dir(OUTPUT_FILE.parent)
        OUTPUT_FILE.write_text(
            json.dumps(all_data, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        print("\n" + "="*70)
        print(f"💾 Saved {len(all_data)} restaurants to:")
        print(f"   {OUTPUT_FILE}")
        print("="*70)

        # Print summary
        print("\n📊 SUMMARY:")
        total_dishes = sum(len(r['dishes']) for r in all_data)
        print(f"   • Restaurants: {len(all_data)}")
        print(f"   • Total Dishes: {total_dishes}")
        for r in all_data:
            print(f"   • {r['name']}: {r['rating']}⭐ ({r['review_count']}), {len(r['dishes'])} dishes")
    else:
        print("\n⚠️  No data collected")

    return 0


def build_driver() -> webdriver.Remote:
    """Connect to already-running ShopeeFood app"""
    options = UiAutomator2Options()
    options.platform_name = 'Android'
    options.device_name = 'emulator-5554'
    options.app_package = 'com.deliverynow'
    options.app_activity = 'foody.vn.deliverynow.SplashActivity'
    options.no_reset = True
    options.automation_name = 'UiAutomator2'
    return webdriver.Remote('http://127.0.0.1:4723', options=options)


def extract_all_data(driver: webdriver.Remote, expected_name: str) -> dict | None:
    """Extract restaurant info + all dishes from current page"""

    print("\n🔍 Extracting restaurant information...")

    data = {
        "platform": "shopeefood",
        "name": "Unknown",
        "rating": 0.0,
        "review_count": "0",
        "crawled_at": datetime.now(timezone.utc).isoformat(),
        "dishes": []
    }

    try:
        # Get initial page content
        all_texts = driver.find_elements(by=AppiumBy.CLASS_NAME, value='android.widget.TextView')

        # Extract restaurant name (should contain "Meili")
        for elem in all_texts:
            text = elem.text
            if text and 'meili' in text.lower() and len(text) > 10:
                data['name'] = text.strip()
                print(f"   📝 Found name: {data['name']}")
                break

        # Extract rating and review count
        # Pattern: "4.9 (50+ Reviews)" or "4.9" and "50+ Reviews" separately
        rating_pattern = re.compile(r'(\d+\.\d+)')
        review_pattern = re.compile(r'(\d+\+?)\s*[Rr]eview', re.IGNORECASE)

        for elem in all_texts:
            text = elem.text
            if not text:
                continue

            # Check for rating (must be <= 5.0 and look like a rating)
            rating_match = rating_pattern.search(text)
            if rating_match:
                rating_val = float(rating_match.group(1))
                if 0.0 <= rating_val <= 5.0 and data['rating'] == 0.0:
                    data['rating'] = rating_val
                    print(f"   ⭐ Found rating: {data['rating']}")

            # Check for review count
            review_match = review_pattern.search(text)
            if review_match:
                data['review_count'] = review_match.group(0)
                print(f"   📊 Found reviews: {data['review_count']}")

        # Scroll to see full menu
        print("\n📜 Scrolling to extract dishes...")
        size = driver.get_window_size()

        # Collect all text across scrolls
        all_collected_texts = set()
        for scroll_idx in range(8):
            # Get texts on current screen
            texts = driver.find_elements(by=AppiumBy.CLASS_NAME, value='android.widget.TextView')
            for elem in texts:
                if elem.text:
                    all_collected_texts.add(elem.text)

            # Scroll down
            driver.swipe(
                start_x=size['width']//2,
                start_y=int(size['height']*0.7),
                end_x=size['width']//2,
                end_y=int(size['height']*0.3),
                duration=400
            )
            time.sleep(0.8)

        # Parse dishes from collected texts
        print("   🔍 Parsing dish names and sold counts...")
        data['dishes'] = parse_dishes_from_texts(all_collected_texts)

        print(f"   ✅ Extracted {len(data['dishes'])} dishes")

        return data

    except Exception as exc:
        print(f"   ❌ Extraction error: {exc}")
        import traceback
        traceback.print_exc()
        return None


def parse_dishes_from_texts(texts: set[str]) -> list[dict]:
    """Parse dish names and sold counts from collected texts"""

    dishes = []

    # Pattern for sold count: "500+ sold", "1000 sold", etc.
    sold_pattern = re.compile(r'^(\d+\+?)\s+sold$', re.IGNORECASE)

    # Convert to list and sort by length (longer texts likely dish names)
    texts_list = sorted(texts, key=len, reverse=True)

    # Create mapping of potential dishes
    potential_dishes = []
    sold_counts = []

    for text in texts_list:
        # Check if it's a sold count
        sold_match = sold_pattern.match(text.strip())
        if sold_match:
            sold_counts.append(sold_match.group(1))
            continue

        # Check if it looks like a dish name
        # Vietnamese dish names often contain: mì, pao, gà, bò, bánh, cơm, phở, xôi, etc.
        # Or contain "/" for bilingual names
        # Or are reasonably long descriptions
        if len(text) > 15 and (
            '/' in text or
            any(kw in text.lower() for kw in [
                'mì', 'pao', 'gà', 'bò', 'bánh', 'cơm', 'phở', 'xôi',
                'canh', 'súp', 'salad', 'kem', 'trà', 'nước', 'combo',
                'sườn', 'thịt', 'cá', 'tôm', 'rau', 'mala'
            ])
        ):
            # Skip if it's a UI element
            if any(skip in text.lower() for skip in [
                'home', 'order', 'like', 'notification', 'delivery',
                'add to cart', 'xem thêm', 'see all', 'freeship'
            ]):
                continue

            potential_dishes.append(text)

    # Match dishes with sold counts
    # Strategy: assume sold counts appear after dish names in UI
    # If we have N dishes and M sold counts, try to pair them

    for i, dish_name in enumerate(potential_dishes):
        if i < len(sold_counts):
            dishes.append({
                "name": dish_name,
                "sold_count": sold_counts[i]
            })
        else:
            # No sold count available for this dish
            dishes.append({
                "name": dish_name,
                "sold_count": "0"
            })

    return dishes


if __name__ == "__main__":
    sys.exit(main())
