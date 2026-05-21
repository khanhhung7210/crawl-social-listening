#!/usr/bin/env python3
"""
ShopeeFood simulator detail extractor.

Usage:
1. Open a restaurant page in the ShopeeFood Android app on the emulator/simulator.
2. Run: python3 scripts/shopeefood/extract_current_page.py
3. The script extracts store detail + visible menu metadata from the current page.
"""

from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    from appium.webdriver.common.appiumby import AppiumBy
except ImportError:
    print("❌ Appium-Python-Client not installed")
    sys.exit(1)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT))

from social_listening.film_paths import platform_raw_dir
from social_listening.paths import ensure_dir

from scripts.shopeefood.simulator_utils import build_android_driver, swipe_up, unique_preserve_order, visible_texts


OUTPUT_FILE = platform_raw_dir("shopeefood") / "shopeefood_simulator_details.json"
SCROLL_ROUNDS = 10
SCROLL_PAUSE_SECONDS = 0.8

PRICE_RE = re.compile(r"\b\d{1,3}(?:[.,]\d{3})+\s*đ?\b", re.IGNORECASE)
RATING_RE = re.compile(r"\b([1-5](?:[.,]\d)?)\b")
REVIEW_RE = re.compile(r"\b(\d+(?:[.,]\d+)?[kK]?\+?)\s*(?:đánh giá|reviews?|ratings?|bình luận)\b", re.IGNORECASE)
SOLD_RE = re.compile(r"\b(\d+(?:[.,]\d+)?[kK]?\+?)\s*(?:đã bán|sold)\b", re.IGNORECASE)


def main() -> int:
    print("\n" + "=" * 70)
    print("🍜 ShopeeFood - Extract Current Page From Simulator")
    print("=" * 70)

    driver = build_android_driver()
    try:
        data = extract_all_data(driver)
    finally:
        driver.quit()

    if not data:
        print("\n❌ Failed to extract data")
        return 1

    ensure_dir(OUTPUT_FILE.parent)
    existing = []
    if OUTPUT_FILE.exists():
        try:
            loaded = json.loads(OUTPUT_FILE.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                existing = loaded
        except Exception:
            existing = []

    merged = upsert_restaurant(existing, data)
    OUTPUT_FILE.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n" + "=" * 70)
    print("✅ EXTRACTION SUCCESSFUL")
    print("=" * 70)
    print(f"📝 Restaurant: {data['name']}")
    print(f"⭐ Rating: {data['rating']}")
    print(f"📊 Reviews: {data['review_count']}")
    print(f"🍜 Dishes: {len(data['dishes'])}")
    if data["dishes"]:
        print("\n📋 Sample dishes:")
        for dish in data["dishes"][:5]:
            sold = dish.get("sold_count") or "0"
            print(f"   • {dish['name'][:55]}... → {sold} sold")
    print(f"\n💾 Saved to: {OUTPUT_FILE}")
    print(f"📊 Total restaurants in file: {len(merged)}")
    print("=" * 70)
    return 0


def extract_all_data(driver) -> dict | None:
    texts = visible_texts(driver)
    if not texts:
        return None

    ordered_texts = collect_page_texts(driver)
    restaurant_name = extract_restaurant_name(texts)
    rating = extract_rating(texts)
    review_count = extract_review_count(texts)
    dishes = parse_dishes_from_texts(ordered_texts, restaurant_name)

    page_source = driver.page_source
    return {
        "platform": "shopeefood",
        "name": restaurant_name,
        "rating": rating,
        "review_count": review_count,
        "crawled_at": datetime.now(timezone.utc).isoformat(),
        "dishes": dishes,
        "raw_texts": ordered_texts,
        "page_source": page_source,
        "app_context": {
            "current_package": getattr(driver, "current_package", ""),
            "current_activity": getattr(driver, "current_activity", ""),
        },
    }


def collect_page_texts(driver) -> list[str]:
    collected: list[str] = []
    for scroll_index in range(SCROLL_ROUNDS):
        collected.extend(visible_texts(driver))
        if scroll_index < SCROLL_ROUNDS - 1:
            swipe_up(driver)
            time.sleep(SCROLL_PAUSE_SECONDS)
    return unique_preserve_order(collected)


def extract_restaurant_name(texts: list[str]) -> str:
    first_slice = [text.strip() for text in texts[:20] if text and text.strip()]
    meili_positions = [index for index, text in enumerate(first_slice) if "meili" in text.casefold()]
    if meili_positions:
        start = meili_positions[0]
        parts: list[str] = []
        for text in first_slice[start:]:
            lower = text.casefold()
            if any(stop in lower for stop in ("reviews", "review", "đánh giá", "min", "deliver", "promo", "sold")):
                break
            if PRICE_RE.search(text) or RATING_RE.fullmatch(text):
                break
            parts.append(text)
        joined = " ".join(parts).replace(" - ", "-").strip()
        joined = re.sub(r"\s+([/&-])\s+", r" \1 ", joined)
        joined = re.sub(r"\s+", " ", joined).strip()
        if joined:
            return joined

    candidates: list[str] = []
    for text in texts[:30]:
        normalized = text.strip()
        lower = normalized.casefold()
        if len(normalized) < 8 or len(normalized) > 120:
            continue
        if any(skip in lower for skip in ("trang chủ", "home", "deliver", "deal", "đặt", "giỏ hàng", "voucher")):
            continue
        if "meili" in lower:
            return normalized
        if any(token in lower for token in ("mì", "bò", "sủi cảo", "bánh bao", "tea", "coffee")):
            candidates.append(normalized)
    return candidates[0] if candidates else "Unknown"


def extract_rating(texts: list[str]) -> float:
    for index, text in enumerate(texts[:40]):
        match = RATING_RE.search(text)
        if not match:
            continue
        value = float(match.group(1).replace(",", "."))
        if not 0.0 <= value <= 5.0:
            continue
        window = " ".join(texts[max(0, index - 2): index + 3]).casefold()
        if any(token in window for token in ("phút", "km", "đánh giá", "review", "rating", "bình luận", "taiwanese", "noodle")):
            return value
    return 0.0


def extract_review_count(texts: list[str]) -> str:
    for text in texts[:80]:
        match = REVIEW_RE.search(text)
        if match:
            return match.group(1)
    return "0"


def parse_dishes_from_texts(texts: list[str], restaurant_name: str) -> list[dict]:
    dishes: list[dict] = []
    seen_names: set[str] = set()
    skip_tokens = (
        "trang chủ", "home", "deliver", "deal", "voucher", "giỏ hàng", "đánh giá", "reviews",
        "rating", "bình luận", "freeship", "ưu đãi", "đã bán", "sold", "today", "hôm nay",
    )

    for index, text in enumerate(texts):
        if not PRICE_RE.fullmatch(text):
            continue
        name = ""
        for cursor in range(index - 1, max(-1, index - 5), -1):
            candidate = texts[cursor].strip()
            if not candidate:
                continue
            lower = candidate.casefold()
            if candidate == restaurant_name or any(token in lower for token in skip_tokens):
                continue
            if PRICE_RE.search(candidate) or REVIEW_RE.search(candidate):
                continue
            if len(candidate) < 4 or len(candidate) > 140:
                continue
            name = candidate
            break
        if not name:
            continue
        key = name.casefold()
        if key in seen_names:
            continue
        seen_names.add(key)

        sold_count = "0"
        description = ""
        for cursor in range(index + 1, min(len(texts), index + 4)):
            candidate = texts[cursor].strip()
            sold_match = SOLD_RE.search(candidate)
            if sold_match:
                sold_count = sold_match.group(1)
                continue
            if not description and len(candidate) > 12 and not PRICE_RE.search(candidate):
                description = candidate

        dishes.append(
            {
                "name": name,
                "price": text,
                "sold_count": sold_count,
                "description": description,
            }
        )
    return dishes


def upsert_restaurant(rows: list[dict], current: dict) -> list[dict]:
    name_key = str(current.get("name") or "").casefold()
    if not name_key:
        return rows + [current]

    merged: list[dict] = []
    replaced = False
    for row in rows:
        row_name = str((row or {}).get("name") or "").casefold()
        if row_name == name_key:
            merged.append(current)
            replaced = True
        else:
            merged.append(row)
    if not replaced:
        merged.append(current)
    return merged


if __name__ == "__main__":
    raise SystemExit(main())
