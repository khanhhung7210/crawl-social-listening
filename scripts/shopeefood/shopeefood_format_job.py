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


DEFAULT_INPUT_FILE = platform_raw_dir("shopeefood") / "shopeefood_all_shops.json"
SIMULATOR_INPUT_FILE = platform_raw_dir("shopeefood") / "shopeefood_simulator_full.json"
OUTPUT_FILE = platform_processed_dir("shopeefood") / "shopeefood_grouped_parsed.json"
SOURCE_NAME = "shopeefood_format_job"


def main() -> int:
    input_file = resolve_input_file()
    if not input_file.exists():
        raise RuntimeError(f"Missing input file: {DEFAULT_INPUT_FILE} or {SIMULATOR_INPUT_FILE}")

    payload = json.loads(input_file.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise RuntimeError(f"{input_file.name} must be a JSON array")

    records: list[dict] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        parsed = parse_simulator_record(item, input_file) if input_file == SIMULATOR_INPUT_FILE else parse_shop_record(item, input_file)
        if parsed:
            records.append(parsed)

    ensure_dir(OUTPUT_FILE.parent)
    OUTPUT_FILE.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved {len(records)} parsed shopeefood shops to {OUTPUT_FILE.resolve()}")
    return 0


def resolve_input_file() -> Path:
    return DEFAULT_INPUT_FILE if DEFAULT_INPUT_FILE.exists() else SIMULATOR_INPUT_FILE


def parse_shop_record(item: dict, input_file: Path) -> dict:
    metadata = item.get("shop_metadata") or {}
    api_payloads = item.get("api_payloads") or {}
    from_url_reply = (api_payloads.get("from_url") or {}).get("reply") or {}
    detail_reply = (api_payloads.get("detail") or {}).get("reply") or {}
    delivery_detail = detail_reply.get("delivery_detail") or {}
    rating_payload = delivery_detail.get("rating") or {}
    current_url = str(item.get("current_url") or item.get("url") or "").strip()
    shop_id = extract_shop_id(current_url) or slugify_title(str(metadata.get("title") or ""))
    if not shop_id:
        return {}

    title = compact_whitespace(delivery_detail.get("name")) or compact_whitespace(metadata.get("title"))
    address = compact_whitespace(delivery_detail.get("address")) or compact_whitespace(metadata.get("address"))
    rating = normalize_rating(rating_payload.get("avg")) or normalize_rating(metadata.get("rating_text"))
    crawled_at = normalize_created_at(item.get("crawled_at")) or datetime.now(timezone.utc).isoformat()
    reviews = build_reviews(item.get("crawled_reviews") or [], shop_id, current_url, crawled_at)
    menu_items = build_menu_items_from_api(api_payloads.get("dishes") or {}) or build_menu_items(item.get("menu_items") or [])
    review_status = item.get("review_status") or {}
    api_hints = item.get("api_hints") or {}
    review_count = extract_review_count(reviews, rating_payload)

    post_text = " | ".join(part for part in [title, address] if part)
    return {
        "platform": "shopeefood",
        "post_id": shop_id,
        "page_id": "",
        "page_name": title,
        "post_url": current_url,
        "post_created_at": crawled_at,
        "post_text": post_text,
        "post_keyword_match": False,
        "parent_keyword_match": bool(post_text or reviews),
        "source": SOURCE_NAME,
        "source_file": str(input_file.relative_to(PROJECT_ROOT)),
        "stats": {
            "rating": rating,
            "review_count": review_count,
            "review_count_label": compact_whitespace(rating_payload.get("display_total_review")),
            "address": address,
            "search_keyword": str(item.get("search_keyword") or "").strip(),
            "menu_item_count": len(menu_items),
            "restaurant_id": from_url_reply.get("restaurant_id"),
            "delivery_id": from_url_reply.get("delivery_id") or api_hints.get("request_id"),
            "review_status": review_status,
            "api_hints": api_hints,
        },
        "menu_items": menu_items,
        "comments": reviews,
    }


def parse_simulator_record(item: dict, input_file: Path) -> dict:
    if item.get("error"):
        return {}

    title = compact_whitespace(item.get("name")) or compact_whitespace(item.get("search_query"))
    if not title:
        return {}

    crawled_at = normalize_created_at(item.get("crawled_at")) or normalize_created_at(item.get("finished_at")) or datetime.now(timezone.utc).isoformat()
    shop_id = slugify_title(title)
    post_text = " | ".join(
        part
        for part in [
            title,
            compact_whitespace(item.get("review_count")),
            " | ".join(compact_whitespace(text) for text in (item.get("raw_texts") or [])[:20] if compact_whitespace(text)),
        ]
        if part
    )
    reviews = build_simulator_reviews(item.get("reviews") or [], shop_id, crawled_at)
    menu_items = build_simulator_menu_items(item.get("dishes") or [])

    return {
        "platform": "shopeefood",
        "post_id": shop_id,
        "page_id": "",
        "page_name": title,
        "post_url": "",
        "post_created_at": crawled_at,
        "post_text": post_text,
        "post_keyword_match": False,
        "parent_keyword_match": bool(post_text or reviews),
        "source": SOURCE_NAME,
        "source_file": str(input_file.relative_to(PROJECT_ROOT)),
        "stats": {
            "rating": normalize_rating(item.get("rating")),
            "review_count": parse_review_count_label(item.get("review_count")) or len(reviews),
            "review_count_label": compact_whitespace(item.get("review_count")),
            "address": "",
            "search_keyword": str(item.get("search_query") or "").strip(),
            "menu_item_count": len(menu_items),
            "review_screen_opened": bool(item.get("review_screen_opened")),
        },
        "menu_items": menu_items,
        "comments": reviews,
    }


def build_simulator_reviews(raw_reviews: list[dict], shop_id: str, crawled_at: str) -> list[dict]:
    items: list[dict] = []
    seen: set[str] = set()
    for index, raw_review in enumerate(raw_reviews, start=1):
        if not isinstance(raw_review, dict):
            continue
        text = compact_whitespace(raw_review.get("text"))
        if not text:
            continue
        author = compact_whitespace(raw_review.get("author"))
        key = f"{author.casefold()}|{text.casefold()}"
        if key in seen:
            continue
        seen.add(key)
        items.append(
            {
                "external_id": f"review:{shop_id}:{index}",
                "record_type": "review",
                "author": author,
                "text": text,
                "created_at": resolve_comment_created_at(
                    raw_review.get("created_at"),
                    compact_whitespace(raw_review.get("created_at")),
                    crawled_at,
                ),
                "created_at_label": compact_whitespace(raw_review.get("created_at")),
                "url": "",
                "post_id": shop_id,
                "parent_comment_id": "",
                "keyword_match": False,
                "rating": normalize_rating(raw_review.get("star_bucket")),
                "crawl_source": "appium",
            }
        )
    return items


def build_simulator_menu_items(raw_items: list[dict]) -> list[dict]:
    items: list[dict] = []
    seen: set[str] = set()
    for index, raw_item in enumerate(raw_items, start=1):
        if not isinstance(raw_item, dict):
            continue
        name = compact_whitespace(raw_item.get("name"))
        if not name or name in seen:
            continue
        seen.add(name)
        items.append(
            {
                "external_id": compact_whitespace(raw_item.get("external_id")) or f"menu:{index}",
                "name": name,
                "description": compact_whitespace(raw_item.get("description")),
                "price_text": compact_whitespace(raw_item.get("price") or raw_item.get("price_text")),
                "sold_count": compact_whitespace(raw_item.get("sold_count")),
            }
        )
    return items


def parse_review_count_label(value: object) -> int:
    text = compact_whitespace(value)
    if not text:
        return 0
    match = re.search(r"\d[\d.,]*", text)
    if not match:
        return 0
    number = match.group(0)
    if "." in number and "," in number:
        number = number.replace(".", "").replace(",", ".")
    elif "," in number:
        number = number.replace(",", "." if "k" in text.casefold() else "")
    multiplier = 1000 if "k" in text.casefold() else 1
    return int(float(number) * multiplier)


def build_reviews(raw_reviews: list[dict], shop_id: str, shop_url: str, crawled_at: str) -> list[dict]:
    items: list[dict] = []
    seen: set[str] = set()
    for raw_review in raw_reviews:
        if not isinstance(raw_review, dict):
            continue
        external_id = compact_whitespace(raw_review.get("external_id"))
        text = compact_whitespace(raw_review.get("text"))
        author = compact_whitespace(raw_review.get("author"))
        created_at_label = compact_whitespace(raw_review.get("created_at_label"))
        rating_label = compact_whitespace(raw_review.get("rating_label"))
        if (
            not external_id
            or not text
            or external_id in seen
            or not is_likely_review_text(text, author, created_at_label, rating_label)
        ):
            continue
        seen.add(external_id)
        items.append(
            {
                "external_id": f"review:{external_id}",
                "record_type": "review",
                "author": author,
                "text": text,
                "created_at": resolve_comment_created_at(
                    raw_review.get("created_at"),
                    created_at_label,
                    crawled_at,
                ),
                "created_at_label": created_at_label,
                "url": shop_url,
                "post_id": shop_id,
                "parent_comment_id": "",
                "keyword_match": False,
                "rating": normalize_rating(rating_label),
                "crawl_source": "dom",
            }
        )
    return items


def build_menu_items(raw_items: list[dict]) -> list[dict]:
    items: list[dict] = []
    seen: set[str] = set()
    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            continue
        name = compact_whitespace(raw_item.get("name"))
        if not name or name in seen:
            continue
        seen.add(name)
        items.append(
            {
                "external_id": compact_whitespace(raw_item.get("external_id")) or f"menu:{len(items)+1}",
                "name": name,
                "description": compact_whitespace(raw_item.get("description")),
                "price_text": compact_whitespace(raw_item.get("price_text")),
            }
        )
    return items


def build_menu_items_from_api(payload: dict) -> list[dict]:
    reply = payload.get("reply") or {}
    menu_infos = reply.get("menu_infos") or []
    items: list[dict] = []
    seen: set[str] = set()
    for menu in menu_infos:
        if not isinstance(menu, dict):
            continue
        for dish in menu.get("dishes") or []:
            if not isinstance(dish, dict):
                continue
            name = compact_whitespace(dish.get("name"))
            if not name or name in seen:
                continue
            seen.add(name)
            price = compact_whitespace(
                dish.get("display_price")
                or ((dish.get("price") or {}).get("text"))
                or str((dish.get("price") or {}).get("value") or "")
            )
            items.append(
                {
                    "external_id": compact_whitespace(dish.get("id")) or f"menu:{len(items)+1}",
                    "name": name,
                    "description": compact_whitespace(dish.get("description")),
                    "price_text": price,
                }
            )
    return items


def extract_review_count(reviews: list[dict], rating_payload: dict) -> int:
    total_review = rating_payload.get("total_review")
    if isinstance(total_review, int):
        return total_review
    if isinstance(total_review, str) and total_review.isdigit():
        return int(total_review)
    return len(reviews)


def is_likely_review_text(text: str, author: str, created_at_label: str, rating_label: str) -> bool:
    normalized_text = compact_whitespace(text)
    if len(normalized_text) < 8 or len(normalized_text) > 500:
        return False
    blocked_patterns = [
        r"địa điểm",
        r"copy code",
        r"mã giảm",
        r"phí vận chuyển",
        r"quán đối tác",
        r"dịch vụ bởi",
        r"đặt đồ ăn",
        r"thực đơn",
        r"home credit",
        r"tp\. hcm",
    ]
    lowered = normalized_text.lower()
    if any(re.search(pattern, lowered) for pattern in blocked_patterns):
        return False
    signals = 0
    if created_at_label and re.search(r"(ago|trước|ngày|tuần|tháng|năm|hour|minute)", created_at_label, re.I):
        signals += 1
    if author and 1 <= len(author) <= 40 and not re.search(r"địa điểm|copy code|dịch vụ|mã giảm|home credit", author, re.I):
        signals += 1
    normalized_rating = normalize_rating(rating_label)
    if normalized_rating is not None and 0 <= normalized_rating <= 5:
        signals += 1
    return signals >= 2


def extract_shop_id(url: str) -> str:
    text = str(url or "")
    match = re.search(r"-([0-9]+)(?:\?|$)", text)
    return match.group(1) if match else ""


def slugify_title(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", compact_whitespace(text).lower()).strip("_")


if __name__ == "__main__":
    raise SystemExit(main())
