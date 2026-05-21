#!/usr/bin/env python3
"""
GrabFood Search Filter - Filter search results by Meili keywords before detail crawl
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from social_listening.film_paths import platform_raw_dir

RAW_DIR = platform_raw_dir("grabfood")

# Meili keywords
MEILI_KEYWORDS = {
    "restaurants": [
        "meili", "美粒", "mei li",
        "mì bò đài loan", "taiwanese", "taiwan beef"
    ],
    "exclude": [
        "melio pizza",  # Not related to Meili
        "merlion",      # Singapore restaurant
        "meizing",      # Different brand
        "meimi",        # Different brand
        "melinh",       # Pizza place
        "melideli",     # Different brand
    ]
}


def main() -> int:
    print("[grabfood] 🔍 Filtering search results for Meili...")

    # Get latest search file
    search_files = sorted(RAW_DIR.glob("grabfood_search_*.json"), reverse=True)
    if not search_files:
        print("[grabfood] ❌ No search results found")
        return 1

    input_file = search_files[0]
    print(f"[grabfood] 📂 Input: {input_file.name}")

    # Load data
    restaurants = json.loads(input_file.read_text(encoding='utf-8'))
    print(f"[grabfood] 📊 Total restaurants: {len(restaurants)}")

    # Filter
    filtered = []
    for restaurant in restaurants:
        if is_meili_restaurant(restaurant):
            filtered.append(restaurant)

    # Save filtered results
    output_file = RAW_DIR / f"grabfood_search_filtered_{input_file.stem.split('_')[-2]}_{input_file.stem.split('_')[-1]}.json"
    output_file.write_text(
        json.dumps(filtered, ensure_ascii=False, indent=2),
        encoding='utf-8'
    )

    print(f"[grabfood] ✅ Filtered: {len(filtered)} Meili restaurants (removed {len(restaurants) - len(filtered)})")
    print(f"[grabfood] 💾 Saved to: {output_file.name}")

    # Show what was kept
    print(f"\n[grabfood] 📋 Kept restaurants:")
    for idx, r in enumerate(filtered, 1):
        location = r.get('location_name', '?')
        print(f"  {idx}. [{location}] {r['name']}")

    return 0


def is_meili_restaurant(restaurant: dict) -> bool:
    """Check if restaurant is related to Meili"""

    name = restaurant.get('name', '').lower()

    # Check exclude keywords first
    for exclude in MEILI_KEYWORDS['exclude']:
        if exclude.lower() in name:
            return False

    # Check if matches Meili keywords
    for keyword in MEILI_KEYWORDS['restaurants']:
        if keyword.lower() in name:
            return True

    return False


if __name__ == "__main__":
    sys.exit(main())
