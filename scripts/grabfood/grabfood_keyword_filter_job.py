#!/usr/bin/env python3
"""
GrabFood Keyword Filter Job - Filter by keywords (Meili, etc.)
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from social_listening.film_paths import platform_processed_dir

# GrabFood keywords configuration
GRABFOOD_KEYWORDS = {
    "restaurants": ["Meili", "美粒", "meili", "MEILI"],
    "dishes": ["mì", "pao", "bánh bao", "gà", "bò", "beef noodles", "taiwanese"],
    "exclude": ["grab express", "grabmart", "grabpay"]
}

FORMATTED_FILE = platform_processed_dir("grabfood") / "grabfood_formatted.json"
OUTPUT_DIR = platform_processed_dir("grabfood")
OUTPUT_FILE = OUTPUT_DIR / "grabfood_filtered.json"


def main() -> int:
    print("[grabfood] 🔍 Filtering GrabFood data by keywords...")

    if not FORMATTED_FILE.exists():
        print(f"[grabfood] ❌ Formatted file not found: {FORMATTED_FILE}")
        return 1

    # Load formatted data
    formatted_data = json.loads(FORMATTED_FILE.read_text(encoding='utf-8'))
    print(f"[grabfood] 📂 Loaded {len(formatted_data)} formatted entries")

    # Filter by keywords
    filtered_data = []
    for entry in formatted_data:
        if matches_keywords(entry):
            filtered_data.append(entry)

    # Save filtered data
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(
        json.dumps(filtered_data, ensure_ascii=False, indent=2),
        encoding='utf-8'
    )

    print(f"[grabfood] ✅ Filtered to {len(filtered_data)} entries")
    print(f"[grabfood] 💾 Saved to: {OUTPUT_FILE}")

    return 0


def matches_keywords(entry: dict) -> bool:
    """Check if entry matches keyword criteria"""

    restaurant_name = entry.get('restaurant_name', '').lower()
    restaurant_normalized = entry.get('restaurant_name_normalized', '').lower()

    # Check restaurant keywords
    restaurant_keywords = GRABFOOD_KEYWORDS.get('restaurants', [])
    if not any(kw.lower() in restaurant_name or kw.lower() in restaurant_normalized
               for kw in restaurant_keywords):
        return False

    # Check for exclude keywords
    exclude_keywords = GRABFOOD_KEYWORDS.get('exclude', [])
    if any(kw.lower() in restaurant_name for kw in exclude_keywords):
        return False

    # Check dishes for product keywords (optional bonus)
    dish_keywords = GRABFOOD_KEYWORDS.get('dishes', [])
    dishes = entry.get('dishes', [])

    for dish in dishes:
        dish_name = dish.get('name', '').lower()
        if any(kw.lower() in dish_name for kw in dish_keywords):
            # Tag this dish as a match
            dish['keyword_match'] = True

    return True


if __name__ == "__main__":
    sys.exit(main())
