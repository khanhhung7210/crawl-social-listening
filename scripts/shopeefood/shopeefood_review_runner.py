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


DEBUGGER_ADDRESS = os.getenv("SHOPEEFOOD_DEBUGGER_ADDRESS", "127.0.0.1:9228")
INPUT_FILE = Path(os.getenv("INPUT_FILE", str(platform_raw_dir("shopeefood") / "shopeefood_search_results.json")))
OUTPUT_FILE = Path(os.getenv("OUTPUT_FILE", str(platform_raw_dir("shopeefood") / "shopeefood_all_shops.json")))
MAX_SHOP_COUNT = int(os.getenv("SHOPEEFOOD_MAX_SHOP_COUNT", "20"))
MAX_SCROLL_ROUNDS = int(os.getenv("SHOPEEFOOD_REVIEW_SCROLL_ROUNDS", "20"))
SCROLL_PAUSE_SECONDS = float(os.getenv("SHOPEEFOOD_REVIEW_SCROLL_PAUSE_SECONDS", "1.5"))


def main() -> int:
    if not INPUT_FILE.exists():
        raise RuntimeError(f"Missing input file: {INPUT_FILE}")

    payload = json.loads(INPUT_FILE.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise RuntimeError("shopeefood_search_results.json must be a JSON array")

    driver = build_driver()
    try:
        install_api_capture(driver)
        items: list[dict] = []
        for entry in payload:
            if not isinstance(entry, dict):
                continue
            url = str(entry.get("url") or "").strip()
            if not url:
                continue
            print(f"[shopeefood-review] crawl url={url}")
            driver.get(url)
            time.sleep(6)
            api_payloads = collect_api_payloads(driver)
            review_section_opened = open_reviews_section(driver)
            if review_section_opened:
                scroll_reviews(driver)
            review_status = detect_review_status(driver, review_section_opened)
            items.append(
                {
                    "url": url,
                    "current_url": str(driver.current_url or url),
                    "search_keyword": str(entry.get("search_keyword") or entry.get("keyword") or "").strip(),
                    "crawled_at": datetime.now(timezone.utc).isoformat(),
                    "raw_html": driver.page_source,
                    "crawled_reviews": extract_reviews(driver),
                    "shop_metadata": extract_shop_metadata(driver),
                    "menu_items": extract_menu_items(driver),
                    "api_hints": collect_api_hints(driver),
                    "api_payloads": api_payloads,
                    "review_status": review_status,
                }
            )
            if len(items) >= MAX_SHOP_COUNT:
                break

        ensure_dir(OUTPUT_FILE.parent)
        OUTPUT_FILE.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"saved {len(items)} shopeefood shops to {OUTPUT_FILE.resolve()}")
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
            "--remote-debugging-port=9228 "
            "--user-data-dir=/tmp/chrome-codex-shopeefood"
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


def install_api_capture(driver: webdriver.Chrome) -> None:
    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {
            "source": r"""
(() => {
  window.__capturedApi = [];
  const pushCapture = (entry) => {
    try {
      window.__capturedApi.push(entry);
    } catch (e) {}
  };
  const origOpen = XMLHttpRequest.prototype.open;
  const origSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function(method, url) {
    this.__captureMeta = {method, url};
    return origOpen.apply(this, arguments);
  };
  XMLHttpRequest.prototype.send = function() {
    this.addEventListener('load', function() {
      try {
        const url = (this.__captureMeta && this.__captureMeta.url) || this.responseURL || '';
        if (/gappapi\.deliverynow\.vn\/api\//i.test(url)) {
          pushCapture({
            kind: 'xhr',
            url,
            status: this.status,
            body: (this.responseText || '').slice(0, 500000),
          });
        }
      } catch (e) {}
    });
    return origSend.apply(this, arguments);
  };
  const origFetch = window.fetch;
  window.fetch = async function() {
    const res = await origFetch.apply(this, arguments);
    try {
      const url = String(arguments[0] || '');
      if (/gappapi\.deliverynow\.vn\/api\//i.test(url) || /gappapi\.deliverynow\.vn\/api\//i.test(res.url || '')) {
        const clone = res.clone();
        const text = await clone.text();
        pushCapture({
          kind: 'fetch',
          url: res.url || url,
          status: res.status,
          body: text.slice(0, 500000),
        });
      }
    } catch (e) {}
    return res;
  };
})();
""",
        },
    )


def collect_api_payloads(driver: webdriver.Chrome) -> dict:
    captured = driver.execute_script("return window.__capturedApi || [];") or []
    payloads: dict[str, dict] = {
        "from_url": {},
        "detail": {},
        "dishes": {},
        "raw_endpoints": [],
    }
    for item in captured:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "")
        body = str(item.get("body") or "")
        if not url or not body:
            continue
        payloads["raw_endpoints"].append(url)
        parsed = parse_json_body(body)
        if not parsed:
            continue
        if "/api/delivery/get_from_url" in url:
            payloads["from_url"] = parsed
        elif "/api/delivery/get_detail" in url:
            payloads["detail"] = parsed
        elif "/api/dish/get_delivery_dishes" in url:
            payloads["dishes"] = parsed
    return payloads


def parse_json_body(body: str) -> dict:
    try:
        payload = json.loads(body)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def open_reviews_section(driver: webdriver.Chrome) -> bool:
    clicked = driver.execute_script(
        """
        const labels = ['Đánh giá', 'Bình luận', 'Reviews', 'Review', 'Nhận xét'];
        const candidates = Array.from(document.querySelectorAll('button, a, div[role="tab"], span'));
        for (const element of candidates) {
          const text = (element.textContent || '').trim();
          if (labels.some((label) => text.includes(label))) {
            element.click();
            return true;
          }
        }
        return false;
        """
    )
    time.sleep(2)
    return bool(clicked)


def scroll_reviews(driver: webdriver.Chrome) -> None:
    for _ in range(MAX_SCROLL_ROUNDS):
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(SCROLL_PAUSE_SECONDS)


def extract_shop_metadata(driver: webdriver.Chrome) -> dict:
    return driver.execute_script(
        """
        const title =
          document.querySelector('.name-restaurant')?.textContent?.trim() ||
          document.querySelector('h1')?.textContent?.trim() ||
          document.title || '';
        const nodes = Array.from(document.querySelectorAll('div, span'))
          .map((node) => (node.textContent || '').trim())
          .filter(Boolean);
        const ratingText =
          document.querySelector('.rating .number')?.textContent?.trim() ||
          nodes.find((text) => /\\b\\d([.,]\\d)?\\b/.test(text) && /đánh giá|review|rating/i.test(text)) || '';
        const address =
          document.querySelector('.address-restaurant')?.textContent?.trim() ||
          nodes.find((text) => /quận|phường|đường|district|ward|street/i.test(text)) || '';
        const serviceText = nodes.find((text) => /ShopeeFood|Dịch vụ bởi/i.test(text)) || '';
        const categoryText = nodes.find((text) => /QUÁN ĂN|Đồ ăn|Thực phẩm/i.test(text)) || '';
        return {title, rating_text: ratingText, address, service_text: serviceText, category_text: categoryText};
        """
    )


def extract_menu_items(driver: webdriver.Chrome) -> list[dict]:
    raw_items = driver.execute_script(
        """
        const rows = Array.from(document.querySelectorAll('.item-restaurant-row, .item-dish, [class*="item-restaurant"]'));
        return rows.slice(0, 300).map((row, index) => {
          const name =
            row.querySelector('.item-restaurant-name, .name, h3, h4')?.textContent?.trim() ||
            Array.from(row.querySelectorAll('div, span')).map((node) => (node.textContent || '').trim()).find((text) => text.length >= 5) ||
            '';
          const desc =
            row.querySelector('.item-restaurant-desc, .desc, .description')?.textContent?.trim() ||
            '';
          const price =
            row.querySelector('.current-price, .price, [class*="price"]')?.textContent?.trim() ||
            Array.from(row.querySelectorAll('div, span')).map((node) => (node.textContent || '').trim()).find((text) => /\\d[\\d.]*\\s*đ/.test(text)) ||
            '';
          return {external_id: `menu_${index}`, name, description: desc, price_text: price};
        }).filter((item) => item.name);
        """
    )
    return [item for item in raw_items or [] if isinstance(item, dict)]


def collect_api_hints(driver: webdriver.Chrome) -> dict:
    return driver.execute_script(
        """
        const entries = performance.getEntriesByType('resource')
          .map((entry) => ({name: entry.name, initiatorType: entry.initiatorType}))
          .filter((entry) => /gappapi\\.deliverynow\\.vn\\/api\\//i.test(entry.name));

        const requestIdMatch = entries
          .map((entry) => {
            const match = entry.name.match(/[?&]request_id=(\\d+)/i);
            return match ? match[1] : '';
          })
          .find(Boolean) || '';

        const byType = {
          get_from_url: entries.find((entry) => /\\/api\\/delivery\\/get_from_url/i.test(entry.name))?.name || '',
          get_detail: entries.find((entry) => /\\/api\\/delivery\\/get_detail/i.test(entry.name))?.name || '',
          get_dishes: entries.find((entry) => /\\/api\\/dish\\/get_delivery_dishes/i.test(entry.name))?.name || '',
        };

        return {
          request_id: requestIdMatch,
          endpoints: byType,
          all_api_urls: entries.slice(0, 20),
        };
        """
    )


def extract_reviews(driver: webdriver.Chrome) -> list[dict]:
    raw_items = driver.execute_script(
        """
        const cards = Array.from(document.querySelectorAll(
          '[class*="review"], [class*="Review"], [class*="comment"], [class*="Comment"], [data-review-id], li, article, div'
        ));
        return cards.slice(0, 200).map((card, index) => {
          const texts = Array.from(card.querySelectorAll('span, div'))
            .map((node) => (node.textContent || '').trim())
            .filter(Boolean);
          const text = texts.find((value) => value.length > 20) || '';
          if (!text) return null;
          const author = texts[0] || '';
          const createdAt = texts.find((value) => /(ago|trước|day|week|month|year)/i.test(value)) || '';
          const rating = texts.find((value) => /\\d([.,]\\d)?\\/?5/.test(value)) || '';
          return {external_id: `shop_review_${index}`, author, text, created_at_label: createdAt, rating_label: rating};
        }).filter(Boolean);
        """
    )
    return [item for item in raw_items or [] if isinstance(item, dict)]


def detect_review_status(driver: webdriver.Chrome, review_section_opened: bool) -> dict:
    return driver.execute_script(
        """
        const bodyText = (document.body?.innerText || '').trim();
        const hasReviewLabel = /đánh giá|review|nhận xét|bình luận/i.test(bodyText);
        const hasReviewItems = Boolean(
          document.querySelector('[class*="review"]') ||
          document.querySelector('[class*="Review"]') ||
          document.querySelector('[data-review-id]')
        );
        return {
          review_section_opened: arguments[0],
          has_review_label: hasReviewLabel,
          has_review_items: hasReviewItems,
          status: hasReviewItems ? 'reviews_present' : (hasReviewLabel ? 'review_labels_only' : 'no_review_section'),
        };
        """,
        review_section_opened,
    )


if __name__ == "__main__":
    raise SystemExit(main())
