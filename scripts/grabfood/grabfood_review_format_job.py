#!/usr/bin/env python3
"""
GrabFood Review Format Job - Format raw reviews to standardized structure
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

INPUT_FILE = platform_raw_dir("grabfood") / "grabfood_all_reviews.json"
OUTPUT_FILE = platform_processed_dir("grabfood") / "grabfood_formatted_reviews.jsonl"


def main() -> int:
    if not INPUT_FILE.exists():
        print(f"[grabfood-format] Input file not found: {INPUT_FILE}")
        print(f"[grabfood-format] Run grabfood_review_crawler.py first")
        return 0

    raw_reviews = json.loads(INPUT_FILE.read_text(encoding="utf-8"))
    if not isinstance(raw_reviews, list):
        raise RuntimeError("grabfood_all_reviews.json must be a JSON array")

    formatted_reviews: list[dict] = []

    for review in raw_reviews:
        if not isinstance(review, dict):
            continue

        formatted = format_review(review)
        if formatted:
            formatted_reviews.append(formatted)

    # Save as JSONL
    ensure_dir(OUTPUT_FILE.parent)
    with OUTPUT_FILE.open("w", encoding="utf-8") as f:
        for review in formatted_reviews:
            f.write(json.dumps(review, ensure_ascii=False) + "\n")

    print(f"[grabfood-format] Formatted {len(formatted_reviews)} reviews")
    print(f"[grabfood-format] Saved to: {OUTPUT_FILE}")

    return 0


def format_review(raw: dict) -> dict | None:
    """Format a single review"""

    platform = raw.get("platform", "grabfood")
    if platform != "grabfood":
        return None

    review_id = raw.get("review_id", "")
    if not review_id:
        return None

    text = str(raw.get("text") or "").strip()
    if len(text) < 10:
        return None

    # Parse date label to ISO timestamp
    created_at_label = str(raw.get("created_at_label") or "").strip()
    created_at = parse_date_label(created_at_label, raw.get("crawled_at", ""))

    return {
        "platform": "grabfood",
        "review_id": review_id,
        "external_review_id": review_id,
        "restaurant_url": raw.get("restaurant_url", ""),
        "restaurant_name": raw.get("restaurant_name", ""),
        "reviewer_name": raw.get("author", "Unknown"),
        "rating": float(raw.get("rating", 0.0)),
        "review_text": text,
        "review_created_at": created_at,
        "created_at_label": created_at_label,
        "crawled_at": raw.get("crawled_at", ""),
        "raw_payload": raw,
    }


def parse_date_label(label: str, crawled_at: str) -> str:
    """
    Parse date labels like '3 months ago' to ISO timestamp

    Returns best-effort timestamp, or empty string if can't parse
    """
    if not label:
        return ""

    text = label.lower().strip()

    # Get reference time (crawled_at or now)
    try:
        if crawled_at:
            ref_time = datetime.fromisoformat(crawled_at.replace("Z", "+00:00"))
        else:
            ref_time = datetime.now(timezone.utc)
    except Exception:
        ref_time = datetime.now(timezone.utc)

    # Ensure timezone
    if ref_time.tzinfo is None:
        ref_time = ref_time.replace(tzinfo=timezone.utc)

    # Parse relative time
    # Pattern: "3 months ago", "2 tuần trước", "5 days ago"
    patterns = [
        (r'(\d+)\s*(?:year|năm)', 365),
        (r'(\d+)\s*(?:month|tháng)', 30),
        (r'(\d+)\s*(?:week|tuần)', 7),
        (r'(\d+)\s*(?:day|ngày)', 1),
        (r'(\d+)\s*(?:hour|giờ|tiếng)', 1/24),
        (r'(\d+)\s*(?:minute|phút)', 1/1440),
    ]

    for pattern, days_multiplier in patterns:
        match = re.search(pattern, text)
        if match:
            value = int(match.group(1))
            days_ago = value * days_multiplier
            result_time = ref_time - timedelta(days=days_ago)
            return result_time.isoformat()

    # If can't parse, return empty (will be handled by import script)
    return ""


if __name__ == "__main__":
    raise SystemExit(main())
