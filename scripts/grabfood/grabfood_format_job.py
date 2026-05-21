#!/usr/bin/env python3
"""
GrabFood Format Job - Normalize raw data to structured format
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from social_listening.film_paths import platform_raw_dir
from social_listening.film_paths import platform_processed_dir
from social_listening.paths import ensure_dir

# Input: latest detail file from crawler
RAW_DIR = platform_raw_dir("grabfood")

def get_latest_detail_file():
    candidates = list(RAW_DIR.glob("grabfood_details_*.json")) + list(RAW_DIR.glob("grabfood_search_*.json"))
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)

RAW_FILE = get_latest_detail_file()
OUTPUT_DIR = platform_processed_dir("grabfood")
OUTPUT_FILE = OUTPUT_DIR / "grabfood_formatted.json"


def main() -> int:
    print("[grabfood] 🔄 Formatting GrabFood data...")

    if not RAW_FILE.exists():
        print(f"[grabfood] ❌ Raw file not found: {RAW_FILE}")
        return 1

    # Load raw data
    raw_data = json.loads(RAW_FILE.read_text(encoding='utf-8'))
    print(f"[grabfood] 📂 Loaded {len(raw_data)} raw entries")

    formatted_data = []

    for entry in raw_data:
        formatted_entry = format_entry(entry)
        if formatted_entry:
            formatted_data.append(formatted_entry)

    # Save formatted data
    ensure_dir(OUTPUT_DIR)
    OUTPUT_FILE.write_text(
        json.dumps(formatted_data, ensure_ascii=False, indent=2),
        encoding='utf-8'
    )

    print(f"[grabfood] ✅ Formatted {len(formatted_data)} entries")
    print(f"[grabfood] 💾 Saved to: {OUTPUT_FILE}")

    return 0


def format_entry(raw: dict) -> dict | None:
    """Format a single raw entry"""

    try:
        # Generate unique ID
        restaurant_slug = slugify(raw['name'])
        crawled_date = raw['crawled_at'][:10].replace('-', '')
        entry_id = f"grabfood_{restaurant_slug}_{crawled_date}"

        # Parse review count
        review_count_raw = raw.get('review_count', '0')
        review_count = parse_review_count(review_count_raw)

        # Parse restaurant name to extract branch
        restaurant_name = raw.get('name', 'Unknown')
        branch = extract_branch(restaurant_name)

        formatted = {
            "id": entry_id,
            "platform": "grabfood",
            "restaurant_name": restaurant_name,
            "restaurant_name_normalized": normalize_restaurant_name(restaurant_name),
            "branch": branch,
            "rating": float(raw.get('rating', 0.0)),
            "review_count": review_count,
            "review_count_raw": review_count_raw,
            "url": raw.get("url", ""),
            "delivery_time": raw.get("delivery_time", ""),
            "distance": raw.get("distance", ""),
            "promo": raw.get("promo", ""),
            "crawled_at": raw.get('crawled_at'),
            "formatted_at": datetime.utcnow().isoformat() + 'Z',
            "dishes": []
        }

        # Format dishes
        for dish in raw.get('dishes', []):
            formatted_dish = format_dish(dish)
            if formatted_dish:
                formatted['dishes'].append(formatted_dish)

        return formatted

    except Exception as e:
        print(f"[grabfood] ⚠️  Error formatting entry: {e}")
        return None


def format_dish(raw_dish: dict) -> dict | None:
    """Format a single dish entry"""

    try:
        dish_name = raw_dish.get('name', '')
        if not dish_name:
            return None

        # Parse order count
        order_count_raw = raw_dish.get('order_count', '0')
        order_count_min = parse_order_count(order_count_raw)

        # Split bilingual names (Vietnamese / English)
        name_parts = dish_name.split('/')
        name_primary = name_parts[0].strip() if name_parts else dish_name
        name_secondary = name_parts[1].strip() if len(name_parts) > 1 else None

        formatted_dish = {
            "dish_id": slugify(name_primary),
            "name": name_primary,
            "name_full": dish_name,
            "name_secondary": name_secondary,
            "price_raw": raw_dish.get("price", ""),
            "description": raw_dish.get("description", ""),
            "image_url": raw_dish.get("image_url", ""),
            "order_count_raw": order_count_raw,
            "order_count_min": order_count_min,
            "order_count_display": order_count_raw
        }

        return formatted_dish

    except Exception as e:
        print(f"[grabfood] ⚠️  Error formatting dish: {e}")
        return None


def slugify(text: str) -> str:
    """Convert text to slug (lowercase, no spaces)"""
    text = text.lower()
    text = re.sub(r'[^a-z0-9]+', '_', text)
    text = text.strip('_')
    return text[:50]  # Limit length


def parse_review_count(text: str) -> int:
    """Parse review count from text like '200+ ratings' → 200"""
    match = re.search(r'(\d+)', text)
    if match:
        return int(match.group(1))
    return 0


def parse_order_count(text: str) -> int:
    """Parse order count from text like '500+ orders' → 500"""
    match = re.search(r'(\d+)', text)
    if match:
        return int(match.group(1))
    return 0


def normalize_restaurant_name(name: str) -> str:
    """Normalize restaurant name for matching"""
    # Remove special chars, extra spaces
    name = re.sub(r'[^\w\s-]', '', name)
    name = re.sub(r'\s+', ' ', name)
    return name.strip()


def extract_branch(name: str) -> str:
    """Extract branch name from restaurant name"""
    # Common patterns:
    # "Restaurant Name - Branch"
    # "Restaurant Name (Branch)"
    # "Restaurant Name Branch"

    # Try hyphen split
    if ' - ' in name:
        parts = name.split(' - ')
        if len(parts) > 1:
            return parts[-1].strip()

    # Try parentheses
    match = re.search(r'\((.*?)\)', name)
    if match:
        return match.group(1).strip()

    # Try common location indicators
    location_keywords = [
        'quận', 'district', 'đường', 'street',
        'phường', 'ward', 'thành phố', 'city'
    ]

    words = name.split()
    for i, word in enumerate(words):
        if any(kw in word.lower() for kw in location_keywords):
            # Branch is likely from this word onwards
            return ' '.join(words[i:])

    return ""


if __name__ == "__main__":
    sys.exit(main())
