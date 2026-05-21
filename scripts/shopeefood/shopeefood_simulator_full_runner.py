#!/usr/bin/env python3
"""
ShopeeFood full simulator runner.

Flow per query:
1. Cold launch app
2. Open search
3. Type query
4. Submit query
5. Open best matching result
6. Extract restaurant detail
7. Try to open ratings/reviews screen and extract visible reviews
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import unicodedata
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
from social_listening.keyword_config import collect_config_values, load_keyword_payload
from social_listening.paths import ensure_dir

from scripts.shopeefood.extract_current_page import extract_all_data
from scripts.shopeefood.simulator_utils import (
    SHOPEEFOOD_APP_ACTIVITY,
    SHOPEEFOOD_APP_PACKAGE,
    build_android_driver,
    swipe_up,
    visible_texts,
)


OUTPUT_FILE = platform_raw_dir("shopeefood") / "shopeefood_simulator_full.json"
DEFAULT_QUERIES = [
    "Meili Ung Văn Khiêm",
    "Meili Mai Văn Vinh",
    "Meili Nguyễn Văn Khối",
    "Meili Nhiêu Tứ",
]
QUERY_ATTEMPTS = 3
QUERY_RETRY_PAUSE_SECONDS = 3
SEARCH_RESULT_WAIT_SECONDS = 4
DETAIL_WAIT_SECONDS = 5
REVIEW_SCROLL_ROUNDS = 8
REVIEW_SCROLL_PAUSE_SECONDS = 0.8

DATE_RE = re.compile(r"\b\d{2}[-/]\d{2}[-/]\d{4}(?:\s+\d{2}:\d{2})?\b")


def main() -> int:
    queries = resolve_queries()
    print(f"[shopeefood-full] starting full simulator runner queries={len(queries)}")

    records: list[dict] = []
    for index, query in enumerate(queries, start=1):
        print(f"\n[shopeefood-full] {index}/{len(queries)} query={query}")
        records.append(run_query_with_retries(query))

    ensure_dir(OUTPUT_FILE.parent)
    OUTPUT_FILE.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[shopeefood-full] saved {len(records)} records to {OUTPUT_FILE}")
    return 0


def resolve_queries() -> list[str]:
    env_queries = str(os.getenv("SHOPEEFOOD_SIM_QUERIES") or "").strip()
    if env_queries:
        return [part.strip() for part in env_queries.split("|") if part.strip()]
    payload = load_keyword_payload()
    queries = collect_config_values(payload, "shopeefood_queries")
    if queries:
        return [str(query).strip() for query in queries if str(query).strip()]
    return DEFAULT_QUERIES


def launch_clean_home() -> None:
    run_adb(["shell", "am", "force-stop", SHOPEEFOOD_APP_PACKAGE])
    run_adb(["shell", "am", "start", "-n", f"{SHOPEEFOOD_APP_PACKAGE}/{SHOPEEFOOD_APP_ACTIVITY}"])
    time.sleep(4)


def run_adb(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["adb", *args], check=False, capture_output=True, text=True)


def wait_for_home(driver, timeout_seconds: int = 45) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        texts = visible_texts(driver)
        if texts:
            return
        edit_fields = driver.find_elements(by=AppiumBy.CLASS_NAME, value="android.widget.EditText")
        if edit_fields:
            return
        view_groups = driver.find_elements(by=AppiumBy.CLASS_NAME, value="android.view.ViewGroup")
        if len(view_groups) >= 5:
            return
        time.sleep(1)
    raise RuntimeError("home screen did not expose visible texts in time")


def open_search(driver):
    for _ in range(3):
        edit_fields = driver.find_elements(by=AppiumBy.CLASS_NAME, value="android.widget.EditText")
        if edit_fields:
            return edit_fields[0]

        candidates = driver.find_elements(by=AppiumBy.CLASS_NAME, value="android.view.ViewGroup")
        scored = []
        for element in candidates:
            try:
                if element.get_attribute("clickable") != "true":
                    continue
                rect = element.rect
            except Exception:
                continue
            if rect["y"] < 240 or rect["y"] > 520:
                continue
            if rect["width"] < 700:
                continue
            scored.append((rect["width"], abs(rect["y"] - 320), element))
        scored.sort(key=lambda item: (-item[0], item[1]))
        if scored:
            try:
                scored[0][2].click()
            except Exception:
                tap_center(scored[0][2].rect)
            time.sleep(2)
            edit_fields = driver.find_elements(by=AppiumBy.CLASS_NAME, value="android.widget.EditText")
            if edit_fields:
                return edit_fields[0]

        fallback = tap_search_fallback(driver)
        if fallback is not None:
            return fallback
        time.sleep(1)
    return None


def tap_search_fallback(driver):
    for x, y in ((720, 346), (720, 320), (720, 290)):
        run_adb(["shell", "input", "tap", str(x), str(y)])
        time.sleep(2)
        edit_fields = driver.find_elements(by=AppiumBy.CLASS_NAME, value="android.widget.EditText")
        if edit_fields:
            return edit_fields[0]
    return None


def type_and_submit_query(driver, edit_field, query: str) -> None:
    try:
        edit_field.click()
        edit_field.clear()
    except Exception:
        pass
    edit_field.send_keys(query)
    time.sleep(1)
    run_adb(["shell", "input", "keyevent", "66"])
    time.sleep(2)


def open_best_result(driver, query: str) -> str:
    tokens = normalize_tokens(query)
    scored = []
    for text in visible_texts(driver):
        if not text:
            continue
        text_tokens = normalize_tokens(text)
        overlap = len(tokens & text_tokens)
        if overlap == 0:
            continue
        score = overlap * 100 + min(len(text), 120) * 0.01
        scored.append((score, text))
    scored.sort(key=lambda item: item[0], reverse=True)
    for _, text in scored[:5]:
        element = find_text_element(driver, text)
        if element is None:
            continue
        try:
            rect = element.rect
            if rect["y"] < 250:
                continue
            element.click()
            print(f"[shopeefood-full] opened result text={text}")
            return text
        except Exception:
            rect = element.rect
            tap_center(rect)
            print(f"[shopeefood-full] tapped result text={text}")
            return text
    run_adb(["shell", "input", "tap", "720", "650"])
    time.sleep(3)
    print("[shopeefood-full] fallback tapped first result card")
    return query


def tap_center(rect: dict) -> None:
    center_x = int(rect["x"] + rect["width"] / 2)
    center_y = int(rect["y"] + rect["height"] / 2)
    run_adb(["shell", "input", "tap", str(center_x), str(center_y)])
    time.sleep(2)


def find_text_element(driver, text: str):
    escaped = escape_xpath_text(text)
    candidates = [
        f"//android.widget.TextView[@text={escaped}]",
        f"//*[contains(@text, {escaped})]",
    ]
    for xpath in candidates:
        try:
            matches = driver.find_elements(by=AppiumBy.XPATH, value=xpath)
        except Exception:
            matches = []
        for match in matches:
            try:
                rect = match.rect
            except Exception:
                continue
            if rect["y"] < 200:
                continue
            return match
    return None


def escape_xpath_text(text: str) -> str:
    if "'" not in text:
        return f"'{text}'"
    if '"' not in text:
        return f'"{text}"'
    parts = text.split("'")
    quoted = ", \"'\", ".join(f"'{part}'" for part in parts)
    return f"concat({quoted})"


def collect_review_snapshot(driver, fallback_name: str) -> dict:
    if not open_reviews_screen(driver):
        return {"opened": False, "reviews": [], "texts": []}
    bucket_texts: list[str] = []
    all_reviews: list[dict] = []
    for star_bucket in [1, 2, 3, 4, 5]:
        opened_bucket = open_star_bucket(driver, star_bucket)
        texts = collect_review_texts(driver)
        bucket_texts.extend(texts)
        reviews = parse_reviews_from_texts(texts, fallback_name, star_bucket=star_bucket if opened_bucket else None)
        all_reviews.extend(reviews)
    return {"opened": True, "reviews": dedupe_reviews(all_reviews), "texts": dedupe_texts(bucket_texts)}


def open_reviews_screen(driver) -> bool:
    texts = visible_texts(driver)
    if is_review_screen(texts):
        return True

    text_views = driver.find_elements(by=AppiumBy.CLASS_NAME, value="android.widget.TextView")
    review_summary_pattern = re.compile(r"[1-5](?:[.,]\d)?\s*\(\s*\d+\+?\s*Reviews?\s*\)", re.IGNORECASE)
    for element in text_views:
        try:
            text = str(element.text or "").strip()
        except Exception:
            continue
        if not text:
            continue
        if review_summary_pattern.search(text):
            try:
                element.click()
            except Exception:
                tap_center(element.rect)
            time.sleep(3)
            if is_review_screen(visible_texts(driver)):
                return True

    for element in text_views:
        try:
            text = str(element.text or "").strip()
        except Exception:
            continue
        if not text:
            continue
        lower = text.casefold()
        if any(label in lower for label in ("rating", "ratings", "đánh giá", "review", "bình luận")):
            try:
                element.click()
            except Exception:
                tap_center(element.rect)
            time.sleep(3)
            return is_review_screen(visible_texts(driver))

    for element in text_views:
        try:
            text = str(element.text or "").strip()
        except Exception:
            continue
        if re.fullmatch(r"[1-5](?:[.,]\d)?", text):
            rect = element.rect
            if rect["y"] > 900:
                continue
            tap_center(rect)
            time.sleep(3)
            return is_review_screen(visible_texts(driver))
    return False


def is_review_screen(texts: list[str]) -> bool:
    joined = " | ".join(texts).casefold()
    return "ratings" in joined or "with comment" in joined or "food delivery (" in joined


def open_star_bucket(driver, star_bucket: int) -> bool:
    texts = visible_texts(driver)
    if not is_review_screen(texts):
        return False

    count_elements = []
    for element in driver.find_elements(by=AppiumBy.CLASS_NAME, value="android.widget.TextView"):
        text = str(element.text or "").strip()
        if not re.fullmatch(r"\(\d+\)", text):
            continue
        rect = element.rect
        if rect["y"] > 900:
            continue
        count_elements.append((rect["x"], rect, text))
    if len(count_elements) < 5:
        return False

    count_elements.sort(key=lambda item: item[0])
    # UI order on screen is 5,4,3,2,1 from left to right
    ordered = list(reversed(count_elements[:5]))
    target = ordered[star_bucket - 1][1]
    tap_center(target)
    time.sleep(2)
    return True


def collect_review_texts(driver) -> list[str]:
    collected: list[str] = []
    for _ in range(REVIEW_SCROLL_ROUNDS):
        collected.extend(visible_texts(driver))
        swipe_up(driver, start_ratio=0.82, end_ratio=0.30, duration_ms=500)
        time.sleep(REVIEW_SCROLL_PAUSE_SECONDS)
    deduped = []
    seen: set[str] = set()
    for text in collected:
        value = str(text or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def parse_reviews_from_texts(texts: list[str], restaurant_name: str, star_bucket: int | None = None) -> list[dict]:
    reviews: list[dict] = []
    skip_tokens = (
        "ratings", "food delivery", "foody", "all", "with comment", "with photo",
        "relevance", "nearby", "top sales",
    )
    cleaned = [text.strip() for text in texts if text and not any(token in text.casefold() for token in skip_tokens)]

    index = 0
    while index < len(cleaned):
        text = cleaned[index]
        if len(text) < 20:
            index += 1
            continue
        if DATE_RE.search(text):
            index += 1
            continue

        author = ""
        created_at = ""
        if index > 0 and len(cleaned[index - 1]) < 40 and not DATE_RE.search(cleaned[index - 1]):
            author = cleaned[index - 1]
        if index + 1 < len(cleaned) and DATE_RE.search(cleaned[index + 1]):
            created_at = cleaned[index + 1]
        if len(text) < 30:
            index += 1
            continue
        reviews.append(
            {
                "platform": "shopeefood",
                "restaurant_name": restaurant_name,
                "author": author,
                "text": text,
                "created_at": created_at,
                "star_bucket": star_bucket or 0,
                "crawled_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        index += 1
    return dedupe_reviews(reviews)


def dedupe_reviews(rows: list[dict]) -> list[dict]:
    seen: set[str] = set()
    deduped: list[dict] = []
    for row in rows:
        key = f"{row.get('author','').casefold()}|{row.get('text','').casefold()}"
        if not row.get("text") or key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def dedupe_texts(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        deduped.append(text)
    return deduped


def normalize_tokens(text: str) -> set[str]:
    normalized = unicodedata.normalize("NFD", str(text or ""))
    ascii_text = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
    ascii_text = re.sub(r"[^a-zA-Z0-9]+", " ", ascii_text).lower()
    return {token for token in ascii_text.split() if token}


def looks_like_store_name(text: str) -> bool:
    lower = str(text or "").casefold()
    if any(token in lower for token in ("relevance", "nearby", "top sales", "freeship", "rating")):
        return False
    if "meili" in lower:
        return True
    if any(token in lower for token in ("ung văn khiêm", "mai văn vinh", "nguyễn văn khối", "nhiêu tứ")):
        return True
    return False


def run_query_with_retries(query: str) -> dict:
    last_error = ""
    for attempt in range(1, QUERY_ATTEMPTS + 1):
        try:
            if attempt > 1:
                print(f"[shopeefood-full] retry query={query} attempt={attempt}/{QUERY_ATTEMPTS}")
            return process_query(query)
        except Exception as exc:
            last_error = str(exc)
            print(f"[shopeefood-full] attempt failed query={query} attempt={attempt} error={exc}")
            time.sleep(QUERY_RETRY_PAUSE_SECONDS)
    return {
        "platform": "shopeefood",
        "search_query": query,
        "error": last_error or "unknown error",
        "failed_at": datetime.now(timezone.utc).isoformat(),
    }


def process_query(query: str) -> dict:
    driver = None
    try:
        launch_clean_home()
        driver = build_android_driver()
        wait_for_home(driver)
        search_field = open_search(driver)
        if search_field is None:
            raise RuntimeError("could not open search field")
        type_and_submit_query(driver, search_field, query)
        time.sleep(SEARCH_RESULT_WAIT_SECONDS)
        opened_result_text = open_best_result(driver, query)
        if not opened_result_text:
            raise RuntimeError("no matching result opened")
        time.sleep(DETAIL_WAIT_SECONDS)

        review_snapshot = collect_review_snapshot(driver, opened_result_text or query)
        if review_snapshot.get("opened"):
            run_adb(["shell", "input", "keyevent", "4"])
            time.sleep(2)

        detail = extract_all_data(driver) or {
            "platform": "shopeefood",
            "name": query,
            "rating": 0.0,
            "review_count": "0",
            "crawled_at": datetime.now(timezone.utc).isoformat(),
            "dishes": [],
            "raw_texts": [],
            "page_source": "",
            "app_context": {},
        }
        if not looks_like_store_name(str(detail.get("name") or "")):
            detail["name"] = opened_result_text or query

        record = {
            **detail,
            "search_query": query,
            "review_screen_opened": bool(review_snapshot.get("opened")),
            "reviews": review_snapshot.get("reviews", []),
            "review_debug_texts": review_snapshot.get("texts", []),
            "finished_at": datetime.now(timezone.utc).isoformat(),
        }
        print(
            f"[shopeefood-full] ok name={record.get('name')} rating={record.get('rating')} "
            f"reviews={len(record.get('reviews', []))} dishes={len(record.get('dishes', []))}"
        )
        return record
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
