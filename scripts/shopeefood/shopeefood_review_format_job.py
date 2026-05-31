#!/usr/bin/env python3
"""
ShopeeFood Review Format Job - Format raw reviews to standardized structure
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from social_listening.film_paths import platform_raw_dir, platform_processed_dir
from social_listening.paths import ensure_dir

# Try mock file first (for testing), fallback to real data
INPUT_FILE_MOCK = platform_raw_dir("shopeefood") / "shopeefood_reviews_mock.json"
INPUT_FILE = platform_raw_dir("shopeefood") / "shopeefood_reviews_android.json"

# Use mock if available
if INPUT_FILE_MOCK.exists():
    INPUT_FILE = INPUT_FILE_MOCK
    print(f"[shopeefood-format] Using mock data: {INPUT_FILE_MOCK}")
OUTPUT_FILE = platform_processed_dir("shopeefood") / "shopeefood_formatted_reviews.jsonl"


def main() -> int:
    if not INPUT_FILE.exists():
        print(f"[shopeefood-format] Input file not found: {INPUT_FILE}")
        print(f"[shopeefood-format] Run shopeefood_review_crawler.py first")
        return 0

    raw_reviews = json.loads(INPUT_FILE.read_text(encoding="utf-8"))
    if not isinstance(raw_reviews, list):
        raise RuntimeError("shopeefood_reviews_android.json must be a JSON array")

    formatted_reviews: list[dict] = []

    for review in raw_reviews:
        if not isinstance(review, dict):
            continue

        # Skip error entries
        text = str(review.get("text") or "").strip()
        if "can't be reached" in text or "site can't" in text.lower():
            continue

        formatted = format_review(review)
        if formatted:
            formatted_reviews.append(formatted)

    # Save as JSONL
    ensure_dir(OUTPUT_FILE.parent)
    with OUTPUT_FILE.open("w", encoding="utf-8") as f:
        for review in formatted_reviews:
            f.write(json.dumps(review, ensure_ascii=False) + "\n")

    print(f"[shopeefood-format] Formatted {len(formatted_reviews)} reviews")
    print(f"[shopeefood-format] Saved to: {OUTPUT_FILE}")

    return 0


def format_review(raw: dict) -> dict | None:
    """Format a single review"""

    platform = raw.get("platform", "shopeefood")
    if platform != "shopeefood":
        return None

    review_id = raw.get("review_id", "")
    if not review_id:
        return None

    text = str(raw.get("text") or "").strip()
    if len(text) < 5:
        return None

    # Parse rating
    rating = float(raw.get("rating", 0))
    if rating == 0:
        # Try to infer from review_id or other fields
        pass

    # Parse date
    created_at = raw.get("created_at", "")
    if not created_at:
        # Use crawled_at as fallback
        created_at = raw.get("crawled_at", "")

    return {
        "platform": "shopeefood",
        "review_id": review_id,
        "external_review_id": review_id,
        "restaurant_url": raw.get("restaurant_url", ""),
        "restaurant_name": raw.get("restaurant_name", ""),
        "reviewer_name": raw.get("author", "Unknown"),
        "rating": rating,
        "review_text": text,
        "review_created_at": created_at,
        "crawled_at": raw.get("crawled_at", ""),
        "raw_payload": raw,
    }


if __name__ == "__main__":
    raise SystemExit(main())
