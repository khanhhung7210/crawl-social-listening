from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

def _project_root() -> Path:
    current = Path(__file__).resolve().parent
    for cand in [current, *current.parents]:
        if (cand / "src" / "social_listening").is_dir():
            return cand
    raise RuntimeError(f"Cannot find project root from {__file__}")


PROJECT_ROOT = _project_root()
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from social_listening.film_paths import platform_processed_dir, platform_raw_dir
from social_listening.paths import ensure_dir
from social_listening.review_utils import (
    clean_google_maps_author,
    clean_google_maps_place_title,
    clean_google_maps_review_text,
    compact_whitespace,
    is_google_maps_ui_junk,
    normalize_created_at,
    normalize_rating,
    resolve_comment_created_at,
)


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


def parse_compact_int(value: object) -> int | None:
    text = compact_whitespace(value)
    if not text:
        return None
    # VN: 9.363 ; EN: 9,363
    digits = re.sub(r"[^\d]", "", text.replace(" ", ""))
    if not digits:
        return None
    try:
        return int(digits)
    except Exception:
        return None


def parse_place_record(item: dict) -> dict:
    metadata = item.get("place_metadata") or {}
    current_url = str(item.get("current_url") or item.get("url") or "").strip()
    place_id = extract_place_id(current_url) or slugify_title(str(metadata.get("title") or ""))
    if not place_id:
        return {}

    title = clean_google_maps_place_title(metadata.get("title")) or clean_google_maps_place_title(
        item.get("search_keyword")
    )
    address = compact_whitespace(metadata.get("address"))
    if is_google_maps_ui_junk(address):
        address = ""
    place_rating = normalize_rating(metadata.get("rating_text"))
    place_review_count = parse_compact_int(metadata.get("review_count_text"))
    crawled_at = normalize_created_at(item.get("crawled_at")) or datetime.now(timezone.utc).isoformat()
    reviews = build_reviews(item.get("crawled_reviews") or [], place_id, current_url, crawled_at)

    # Place shell is only a container for reviews — never surface Maps chrome as "comment".
    post_text = title
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
        "skip_post_mention": True,
        "stats": {
            # Official Google place rating / total reviews (not sample size).
            "rating": place_rating,
            "place_rating": place_rating,
            "place_review_count": place_review_count,
            "review_count": place_review_count if place_review_count is not None else len(reviews),
            "sample_review_count": len(reviews),
            "comment_count": place_review_count if place_review_count is not None else len(reviews),
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
        text = clean_google_maps_review_text(raw_review.get("text"))
        if not external_id or not text or external_id in seen:
            continue
        seen.add(external_id)
        items.append(
            {
                "external_id": external_id,
                "record_type": "review",
                "author": clean_google_maps_author(raw_review.get("author")),
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
