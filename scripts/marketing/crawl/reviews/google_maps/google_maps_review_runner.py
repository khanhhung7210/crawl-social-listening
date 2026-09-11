from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from selenium import webdriver
from selenium.common.exceptions import InvalidSessionIdException, WebDriverException

def _project_root() -> Path:
    current = Path(__file__).resolve().parent
    for cand in [current, *current.parents]:
        if (cand / "src" / "social_listening").is_dir():
            return cand
    raise RuntimeError(f"Cannot find project root from {__file__}")


PROJECT_ROOT = _project_root()
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from social_listening.film_paths import platform_raw_dir
from social_listening.paths import ensure_dir
from social_listening.chromedriver_utils import build_attached_chrome, leave_chrome_open
from social_listening.maps_locale import is_galaxy_cinema_place_url, maps_url_with_hl


DEBUGGER_ADDRESS = os.getenv("GOOGLE_MAPS_DEBUGGER_ADDRESS", "127.0.0.1:9227")
INPUT_FILE = platform_raw_dir("google_maps") / "google_maps_search_results.json"
OUTPUT_FILE = platform_raw_dir("google_maps") / "google_maps_all_places.json"
MAX_PLACE_COUNT = int(os.getenv("GOOGLE_MAPS_MAX_PLACE_COUNT", "30"))
MAX_SCROLL_ROUNDS = int(os.getenv("GOOGLE_MAPS_REVIEW_SCROLL_ROUNDS", "8"))
SCROLL_PAUSE_SECONDS = float(os.getenv("GOOGLE_MAPS_REVIEW_SCROLL_PAUSE_SECONDS", "1.8"))


def main() -> int:
    if not INPUT_FILE.exists():
        raise RuntimeError(f"Missing input file: {INPUT_FILE}")

    payload = json.loads(INPUT_FILE.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise RuntimeError("google_maps_search_results.json must be a JSON array")

    payload = [
        entry
        for entry in payload
        if isinstance(entry, dict)
        and is_galaxy_cinema_place_url(str(entry.get("url") or "").strip())
    ]
    print(f"[google-maps-review] galaxy places queued={len(payload)} cap={MAX_PLACE_COUNT}")

    driver = build_attached_chrome(DEBUGGER_ADDRESS)
    try:
        items: list[dict] = []
        for idx, entry in enumerate(payload):
            if not isinstance(entry, dict):
                continue
            url = str(entry.get("url") or "").strip()
            if not url:
                continue
            print(f"[google-maps-review] [{idx+1}/{len(payload)}] crawl url={url}")

            try:
                driver.get(maps_url_with_hl(url))
                time.sleep(6)
                open_reviews_panel(driver)
                sort_ok = select_review_sort(driver, "Most recent")
                print(
                    f"[google-maps-review] sort_most_recent="
                    f"{'on' if sort_ok else 'unavailable(fail-soft)'}"
                )
                reveal_original_vietnamese_reviews(driver)
                scroll_reviews_panel(driver)
                reveal_original_vietnamese_reviews(driver)
                items.append(
                    {
                        "url": url,
                        "current_url": str(driver.current_url or url),
                        "search_keyword": str(entry.get("search_keyword") or entry.get("keyword") or "").strip(),
                        "crawled_at": datetime.now(timezone.utc).isoformat(),
                        "review_sort": "most_recent" if sort_ok else "default",
                        "raw_html": driver.page_source,
                        "crawled_reviews": extract_reviews(driver),
                        "place_metadata": extract_place_metadata(driver),
                    }
                )
                print(f"[google-maps-review] ✓ Successfully crawled {len(items[-1].get('crawled_reviews', []))} reviews")

            except (WebDriverException, InvalidSessionIdException) as e:
                print(f"[google-maps-review] ✗ ERROR crawling {url}: {e}")
                print("[google-maps-review] Browser session lost. Attempting to reconnect...")
                try:
                    driver = build_attached_chrome(DEBUGGER_ADDRESS)
                    print("[google-maps-review] ✓ Reconnected to browser")
                except Exception as reconnect_error:
                    print(f"[google-maps-review] ✗ Failed to reconnect: {reconnect_error}")
                    print(f"[google-maps-review] Saving {len(items)} items collected so far...")
                    break

            if len(items) >= MAX_PLACE_COUNT:
                break

        ensure_dir(OUTPUT_FILE.parent)
        OUTPUT_FILE.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"saved {len(items)} google maps places to {OUTPUT_FILE.resolve()}")
        return 0
    finally:
        leave_chrome_open(driver)


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


def select_review_sort(driver: webdriver.Chrome, mode: str = "Most recent") -> bool:
    """
    Open Reviews → sort → Most recent / Mới nhất.
    Fail-soft: returns False if controls are missing.
    """
    # Click the sort dropdown (often shows current mode e.g. "Most relevant")
    opened = driver.execute_script(
        """
        const labels = [
          'Sort', 'Sắp xếp', 'Most relevant', 'Liên quan nhất',
          'Most recent', 'Mới nhất', 'Newest'
        ];
        const nodes = Array.from(document.querySelectorAll(
          'button, [role="button"], [aria-haspopup="listbox"], [jsaction*="sort"]'
        ));
        for (const el of nodes) {
          const text = ((el.getAttribute('aria-label') || '') + ' ' + (el.innerText || '')).trim();
          if (!text) continue;
          if (labels.some((l) => text.includes(l))) {
            el.click();
            return true;
          }
        }
        return false;
        """
    )
    if not opened:
        return False
    time.sleep(1.0)

    targets = ["Most recent", "Newest", "Mới nhất", "Gần đây nhất"]
    if mode.strip().lower() not in {"most recent", "newest", ""}:
        targets = [mode] + targets

    clicked = driver.execute_script(
        """
        const targets = arguments[0];
        const nodes = Array.from(document.querySelectorAll(
          '[role="menuitemradio"], [role="option"], [role="menuitem"], button, li, div'
        ));
        for (const el of nodes) {
          const text = ((el.getAttribute('aria-label') || '') + ' ' + (el.innerText || '')).trim();
          if (!text) continue;
          if (targets.some((t) => text === t || text.includes(t))) {
            // Prefer exact newest labels over "Most relevant"
            if (/relevant|liên quan/i.test(text) && !/recent|mới|newest/i.test(text)) continue;
            el.click();
            return true;
          }
        }
        return false;
        """,
        targets,
    )
    time.sleep(2.0)
    return bool(clicked)


def reveal_original_vietnamese_reviews(driver: webdriver.Chrome) -> None:
    """Click 'Xem bản gốc' / expand 'Thêm' so we scrape Vietnamese, not Google Translate."""
    driver.execute_script(
        """
        const clickIf = (el) => {
          const text = ((el.getAttribute('aria-label') || '') + ' ' + (el.innerText || el.textContent || '')).trim();
          if (!text) return false;
          if (/(xem bản gốc|see original|hiển thị bản gốc|show original)/i.test(text)) {
            el.click();
            return true;
          }
          if (/^(thêm|more)$/i.test(text) || /^thêm$/i.test(text)) {
            el.click();
            return true;
          }
          return false;
        };
        const nodes = Array.from(document.querySelectorAll('button, [role="button"], span[jsaction], a'));
        let n = 0;
        for (const el of nodes) {
          if (clickIf(el)) n += 1;
          if (n >= 80) break;
        }
        return n;
        """
    )
    time.sleep(1.2)


def scroll_reviews_panel(driver: webdriver.Chrome) -> None:
    from selenium.common.exceptions import WebDriverException, InvalidSessionIdException

    for i in range(MAX_SCROLL_ROUNDS):
        try:
            # Check if session is still alive
            driver.current_url  # This will throw if session is dead

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
        except (WebDriverException, InvalidSessionIdException) as e:
            print(f"[google-maps-review] WARNING: Scroll round {i+1} failed: {e}")
            print(f"[google-maps-review] Browser may have closed. Stopping scroll early.")
            break


def extract_place_metadata(driver: webdriver.Chrome) -> dict:
    return driver.execute_script(
        """
        const titleEl = document.querySelector('h1.DUwDvf, h1');
        let title = (titleEl?.textContent || '').trim();
        if (!title) {
          title = (document.title || '').replace(/\\s*-\\s*Google Maps\\s*$/i, '').trim();
        }
        const ratingEl = document.querySelector('div.F7nice span[aria-hidden="true"], span[aria-label*="star" i], span[aria-label*="sao" i]');
        const ratingText = (ratingEl?.getAttribute('aria-label') || ratingEl?.textContent || '').trim();
        const addressSelectors = [
          'button[data-item-id="address"]',
          'button[data-item-id^="address"]',
          '[data-item-id="address"] .Io6YTe',
          'button[aria-label*="Address" i]',
          'button[aria-label*="Địa chỉ" i]',
        ];
        let address = '';
        for (const sel of addressSelectors) {
          const node = document.querySelector(sel);
          const raw = (node?.getAttribute('aria-label') || node?.textContent || '').trim();
          if (!raw) continue;
          address = raw.replace(/^(Address|Địa chỉ)\\s*:?\\s*/i, '').trim();
          if (address && !/drag to change|click to remove|search|close/i.test(address)) break;
          address = '';
        }
        return {title, rating_text: ratingText, address};
        """
    )


def extract_reviews(driver: webdriver.Chrome) -> list[dict]:
    from social_listening.review_utils import (
        clean_google_maps_author,
        clean_google_maps_review_text,
        is_google_maps_ui_junk,
    )

    raw_items = driver.execute_script(
        """
        const cards = Array.from(document.querySelectorAll('div[data-review-id], div.jftiEf'));
        return cards.slice(0, 200).map((card, index) => {
          const author = (card.querySelector('.d4r55, button[aria-label]')?.textContent || '').trim();
          const ratingLabel = Array.from(card.querySelectorAll('[aria-label]'))
            .map((node) => node.getAttribute('aria-label') || '')
            .find((text) => /star|sao/i.test(text)) || '';
          const original = (card.querySelector('span[jsname="fbQN7e"]')?.innerText || '').trim();
          const shown = (
            card.querySelector('span[jsname="bN97Pc"]')?.innerText ||
            card.querySelector('.wiI7pd')?.innerText ||
            card.querySelector('.MyEned')?.innerText ||
            ''
          ).trim();
          const body = original.length >= 8 ? original : shown;
          const createdAt = Array.from(card.querySelectorAll('span.rsqaWe, span'))
            .map((node) => (node.textContent || '').trim())
            .find((value) => /(ago|trước|week|day|month|year|ngày|tuần|tháng)/i.test(value)) || '';
          const reviewId = card.getAttribute('data-review-id') || `gmaps_review_${index}`;
          return {external_id: reviewId, author, rating_label: ratingLabel, text: body, created_at_label: createdAt};
        });
        """
    )
    reviews: list[dict] = []
    for item in raw_items or []:
        if not isinstance(item, dict):
            continue
        text = clean_google_maps_review_text(item.get("text"))
        if not text or is_google_maps_ui_junk(text):
            continue
        reviews.append(
            {
                "external_id": f"review:{item.get('external_id')}",
                "record_type": "review",
                "author": clean_google_maps_author(item.get("author")),
                "text": text,
                "created_at_label": re.sub(r"\s+", " ", str(item.get("created_at_label") or "")).strip(),
                "rating_label": str(item.get("rating_label") or "").strip(),
            }
        )
    return reviews


if __name__ == "__main__":
    raise SystemExit(main())
