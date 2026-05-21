from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from social_listening.film_paths import platform_processed_dir, platform_raw_dir
from social_listening.paths import ensure_dir
from social_listening.review_utils import compact_whitespace, normalize_created_at, normalize_rating, resolve_comment_created_at


INPUT_FILE = platform_raw_dir("google_maps") / "google_maps_all_places.json"
OUTPUT_FILE = platform_processed_dir("google_maps") / "google_maps_grouped_parsed.json"
SOURCE_NAME = "google_maps_format_job"


def main() -> int:
    if not INPUT_FILE.exists():
        raise RuntimeError(f"Missing input file: {INPUT_FILE}")

    payload = json.loads(INPUT_FILE.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise RuntimeError("google_maps_all_places.json must be a JSON array")

    records: list[dict] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        parsed = parse_place_record(item)
        if parsed:
            records.append(parsed)

    ensure_dir(OUTPUT_FILE.parent)
    OUTPUT_FILE.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved {len(records)} parsed google maps places to {OUTPUT_FILE.resolve()}")
    return 0


def parse_place_record(item: dict) -> dict:
    metadata = item.get("place_metadata") or {}
    current_url = str(item.get("current_url") or item.get("url") or "").strip()
    place_id = extract_place_id(current_url) or slugify_title(str(metadata.get("title") or ""))
    if not place_id:
        return {}

    title = compact_whitespace(metadata.get("title"))
    address = compact_whitespace(metadata.get("address"))
    rating = normalize_rating(metadata.get("rating_text"))
    crawled_at = normalize_created_at(item.get("crawled_at")) or datetime.now(timezone.utc).isoformat()
    reviews = build_reviews(item.get("crawled_reviews") or [], place_id, current_url, crawled_at)

    post_text = " | ".join(part for part in [title, address] if part)
    return {
        "platform": "google_maps",
        "post_id": place_id,
        "page_id": "",
        "page_name": title,
        "post_url": current_url,
        "post_created_at": crawled_at,
        "post_text": post_text,
        "post_keyword_match": False,
        "parent_keyword_match": bool(post_text or reviews),
        "source": SOURCE_NAME,
        "source_file": str(INPUT_FILE.relative_to(PROJECT_ROOT)),
        "stats": {
            "rating": rating,
            "review_count": len(reviews),
            "address": address,
            "search_keyword": str(item.get("search_keyword") or "").strip(),
        },
        "comments": reviews,
    }


def build_reviews(raw_reviews: list[dict], place_id: str, place_url: str, crawled_at: str) -> list[dict]:
    items: list[dict] = []
    seen: set[str] = set()
    for raw_review in raw_reviews:
        if not isinstance(raw_review, dict):
            continue
        external_id = compact_whitespace(raw_review.get("external_id"))
        text = compact_whitespace(raw_review.get("text"))
        if not external_id or not text or external_id in seen:
            continue
        seen.add(external_id)
        items.append(
            {
                "external_id": external_id,
                "record_type": "review",
                "author": compact_whitespace(raw_review.get("author")),
                "text": text,
                "created_at": resolve_comment_created_at(
                    raw_review.get("created_at"),
                    str(raw_review.get("created_at_label") or ""),
                    crawled_at,
                ),
                "created_at_label": compact_whitespace(raw_review.get("created_at_label")),
                "url": place_url,
                "post_id": place_id,
                "parent_comment_id": "",
                "keyword_match": False,
                "rating": normalize_rating(raw_review.get("rating_label")),
                "crawl_source": "dom",
            }
        )
    return items


def extract_place_id(url: str) -> str:
    text = str(url or "")
    for pattern in (r"[?&]cid=(\d+)", r"!1s0x([0-9a-f:]+)"):
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1)
    return ""


def slugify_title(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", compact_whitespace(text).lower()).strip("_")


if __name__ == "__main__":
    raise SystemExit(main())
