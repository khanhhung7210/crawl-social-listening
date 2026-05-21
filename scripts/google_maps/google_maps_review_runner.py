from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from selenium import webdriver
from selenium.common.exceptions import SessionNotCreatedException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from social_listening.film_paths import platform_raw_dir
from social_listening.paths import ensure_dir


DEBUGGER_ADDRESS = os.getenv("GOOGLE_MAPS_DEBUGGER_ADDRESS", "127.0.0.1:9227")
INPUT_FILE = platform_raw_dir("google_maps") / "google_maps_search_results.json"
OUTPUT_FILE = platform_raw_dir("google_maps") / "google_maps_all_places.json"
MAX_PLACE_COUNT = int(os.getenv("GOOGLE_MAPS_MAX_PLACE_COUNT", "20"))
MAX_SCROLL_ROUNDS = int(os.getenv("GOOGLE_MAPS_REVIEW_SCROLL_ROUNDS", "20"))
SCROLL_PAUSE_SECONDS = float(os.getenv("GOOGLE_MAPS_REVIEW_SCROLL_PAUSE_SECONDS", "1.75"))


def main() -> int:
    if not INPUT_FILE.exists():
        raise RuntimeError(f"Missing input file: {INPUT_FILE}")

    payload = json.loads(INPUT_FILE.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise RuntimeError("google_maps_search_results.json must be a JSON array")

    driver = build_driver()
    try:
        items: list[dict] = []
        for entry in payload:
            if not isinstance(entry, dict):
                continue
            url = str(entry.get("url") or "").strip()
            if not url:
                continue
            print(f"[google-maps-review] crawl url={url}")
            driver.get(url)
            time.sleep(6)
            open_reviews_panel(driver)
            scroll_reviews_panel(driver)
            items.append(
                {
                    "url": url,
                    "current_url": str(driver.current_url or url),
                    "search_keyword": str(entry.get("search_keyword") or entry.get("keyword") or "").strip(),
                    "crawled_at": datetime.now(timezone.utc).isoformat(),
                    "raw_html": driver.page_source,
                    "crawled_reviews": extract_reviews(driver),
                    "place_metadata": extract_place_metadata(driver),
                }
            )
            if len(items) >= MAX_PLACE_COUNT:
                break

        ensure_dir(OUTPUT_FILE.parent)
        OUTPUT_FILE.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"saved {len(items)} google maps places to {OUTPUT_FILE.resolve()}")
        return 0
    finally:
        driver.quit()


def build_driver() -> webdriver.Chrome:
    options = Options()
    options.debugger_address = DEBUGGER_ADDRESS
    driver_path = resolve_chromedriver_path()
    try:
        if driver_path:
            return webdriver.Chrome(service=Service(driver_path), options=options)
        return webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    except SessionNotCreatedException as exc:
        raise RuntimeError(
            "Cannot connect to Chrome remote debugging at "
            f"{DEBUGGER_ADDRESS}. Start Chrome first with:\n"
            "/Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome "
            "--remote-debugging-port=9227 "
            "--user-data-dir=/tmp/chrome-codex-google-maps"
        ) from exc


def resolve_chromedriver_path() -> str:
    cache_root = Path.home() / ".wdm" / "drivers" / "chromedriver" / "mac64"
    if not cache_root.exists():
        return ""
    candidates = sorted(cache_root.glob("*/chromedriver-mac-arm64/chromedriver"), reverse=True)
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return ""


def open_reviews_panel(driver: webdriver.Chrome) -> None:
    driver.execute_script(
        """
        const labels = ['Reviews', 'Bài đánh giá', 'Xếp hạng và bài đánh giá'];
        const candidates = Array.from(document.querySelectorAll('button, [role="tab"], a'));
        for (const element of candidates) {
          const text = (element.getAttribute('aria-label') || element.textContent || '').trim();
          if (labels.some((label) => text.includes(label))) {
            element.click();
            return true;
          }
        }
        return false;
        """
    )
    time.sleep(3)


def scroll_reviews_panel(driver: webdriver.Chrome) -> None:
    for _ in range(MAX_SCROLL_ROUNDS):
        driver.execute_script(
            """
            const panel = Array.from(document.querySelectorAll('div[role="feed"], div[aria-label]'))
              .find((node) => node.scrollHeight > node.clientHeight + 100);
            if (panel) {
              panel.scrollTop = panel.scrollHeight;
            }
            """
        )
        time.sleep(SCROLL_PAUSE_SECONDS)


def extract_place_metadata(driver: webdriver.Chrome) -> dict:
    return driver.execute_script(
        """
        const title = document.querySelector('h1')?.textContent?.trim() || document.title || '';
        const chips = Array.from(document.querySelectorAll('button, div, span'))
          .map((node) => (node.textContent || '').trim())
          .filter(Boolean);
        const ratingText = chips.find((text) => /\\b\\d([.,]\\d)?\\b/.test(text) && text.includes('(')) || '';
        const address = chips.find((text) => /\\d|Phường|Quận|District|Street|Ward/i.test(text)) || '';
        return {title, rating_text: ratingText, address};
        """
    )


def extract_reviews(driver: webdriver.Chrome) -> list[dict]:
    raw_items = driver.execute_script(
        """
        const cards = Array.from(document.querySelectorAll('div[data-review-id], div.jftiEf, div[role="article"]'));
        return cards.slice(0, 200).map((card, index) => {
          const textNodes = Array.from(card.querySelectorAll('span, div, button'))
            .map((node) => (node.textContent || '').trim())
            .filter(Boolean);
          const author = textNodes[0] || '';
          const ratingLabel = Array.from(card.querySelectorAll('[aria-label]'))
            .map((node) => node.getAttribute('aria-label') || '')
            .find((text) => /star/i.test(text)) || '';
          const text = textNodes.find((value) => value.length > 20) || textNodes.slice(1).join(' ').trim();
          const createdAt = textNodes.find((value) => /(ago|trước|week|day|month|year)/i.test(value)) || '';
          const reviewId = card.getAttribute('data-review-id') || `gmaps_review_${index}`;
          return {external_id: reviewId, author, rating_label: ratingLabel, text, created_at_label: createdAt};
        });
        """
    )
    reviews: list[dict] = []
    for item in raw_items or []:
        if not isinstance(item, dict):
            continue
        text = re.sub(r"\s+", " ", str(item.get("text") or "")).strip()
        if not text:
            continue
        reviews.append(
            {
                "external_id": f"review:{item.get('external_id')}",
                "record_type": "review",
                "author": str(item.get("author") or "").strip(),
                "text": text,
                "created_at_label": str(item.get("created_at_label") or "").strip(),
                "rating_label": str(item.get("rating_label") or "").strip(),
            }
        )
    return reviews


if __name__ == "__main__":
    raise SystemExit(main())
