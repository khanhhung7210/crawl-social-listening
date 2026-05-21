from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from selenium.common.exceptions import InvalidSessionIdException, WebDriverException

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from social_listening.film_paths import platform_raw_dir
from social_listening.paths import ensure_dir

from scripts.shopeefood.shopeefood_review_runner import (
    build_driver,
    collect_api_payloads,
    install_api_capture,
)


INPUT_FILE = Path(os.getenv("INPUT_FILE", str(platform_raw_dir("shopeefood") / "shopeefood_search_results.json")))
OUTPUT_FILE = Path(os.getenv("OUTPUT_FILE", str(platform_raw_dir("shopeefood") / "shopeefood_api_probe.json")))
MAX_SHOP_COUNT = int(os.getenv("SHOPEEFOOD_MAX_SHOP_COUNT", "20"))
POST_LOAD_WAIT_SECONDS = float(os.getenv("SHOPEEFOOD_PROBE_WAIT_SECONDS", "6"))
POST_INTERACTION_WAIT_SECONDS = float(os.getenv("SHOPEEFOOD_PROBE_INTERACTION_WAIT_SECONDS", "3"))


def main() -> int:
    if not INPUT_FILE.exists():
        raise RuntimeError(f"Missing input file: {INPUT_FILE}")

    payload = json.loads(INPUT_FILE.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise RuntimeError("shopeefood_search_results.json must be a JSON array")

    driver = create_instrumented_driver()
    try:
        records: list[dict] = []
        for entry in payload:
            if not isinstance(entry, dict):
                continue
            url = str(entry.get("url") or "").strip()
            if not url:
                continue
            print(f"[shopeefood-probe] crawl url={url}")
            try:
                driver, record = probe_single_store(driver, entry)
            except (InvalidSessionIdException, WebDriverException) as exc:
                safe_quit(driver)
                driver = create_instrumented_driver()
                records.append(
                    {
                        "url": url,
                        "search_keyword": str(entry.get("search_keyword") or entry.get("keyword") or "").strip(),
                        "crawled_at": datetime.now(timezone.utc).isoformat(),
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
            else:
                records.append(record)
            if len(records) >= MAX_SHOP_COUNT:
                break

        ensure_dir(OUTPUT_FILE.parent)
        OUTPUT_FILE.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"saved {len(records)} shopeefood api probe records to {OUTPUT_FILE.resolve()}")
        return 0
    finally:
        safe_quit(driver)


def create_instrumented_driver():
    driver = build_driver()
    install_api_capture(driver)
    return driver


def safe_quit(driver) -> None:
    try:
        driver.quit()
    except Exception:
        pass


def probe_single_store(driver, entry: dict) -> tuple[object, dict]:
    url = str(entry.get("url") or "").strip()
    driver.get(url)
    time.sleep(POST_LOAD_WAIT_SECONDS)
    base_payloads = collect_api_payloads(driver)
    browser_probe = probe_review_api(driver, base_payloads)
    click_probe = click_review_triggers(driver)
    time.sleep(POST_INTERACTION_WAIT_SECONDS)
    final_payloads = collect_api_payloads(driver)
    return driver, {
        "url": url,
        "current_url": str(driver.current_url or url),
        "search_keyword": str(entry.get("search_keyword") or entry.get("keyword") or "").strip(),
        "crawled_at": datetime.now(timezone.utc).isoformat(),
        "base_api_payloads": base_payloads,
        "browser_probe": browser_probe,
        "click_probe": click_probe,
        "final_api_payloads": final_payloads,
    }


def probe_review_api(driver, base_payloads: dict) -> dict:
    from_url_reply = (base_payloads.get("from_url") or {}).get("reply") or {}
    detail_reply = (base_payloads.get("detail") or {}).get("reply") or {}
    delivery_detail = detail_reply.get("delivery_detail") or {}
    restaurant_id = from_url_reply.get("restaurant_id") or delivery_detail.get("restaurant_id")
    delivery_id = from_url_reply.get("delivery_id") or delivery_detail.get("id")

    candidate_urls = build_candidate_urls(restaurant_id, delivery_id)
    return driver.execute_async_script(
        """
        const urls = arguments[0] || [];
        const done = arguments[arguments.length - 1];
        const run = async () => {
          const results = [];
          for (const url of urls) {
            const result = await new Promise((resolve) => {
              try {
                const xhr = new XMLHttpRequest();
                xhr.open('GET', url, true);
                xhr.withCredentials = true;
                xhr.setRequestHeader('accept', 'application/json, text/plain, */*');
                xhr.onload = () => resolve({
                  url,
                  ok: xhr.status >= 200 && xhr.status < 300,
                  status: xhr.status,
                  body_preview: String(xhr.responseText || '').slice(0, 2000)
                });
                xhr.onerror = () => resolve({
                  url,
                  ok: false,
                  status: xhr.status || 0,
                  error: 'xhr-error'
                });
                xhr.ontimeout = () => resolve({
                  url,
                  ok: false,
                  status: xhr.status || 0,
                  error: 'xhr-timeout'
                });
                xhr.send();
              } catch (error) {
                resolve({
                  url,
                  ok: false,
                  error: String(error)
                });
              }
            });
            results.push(result);
          }
          done(results);
        };
        run();
        """,
        candidate_urls,
    )


def build_candidate_urls(restaurant_id: int | str | None, delivery_id: int | str | None) -> list[str]:
    rid = str(restaurant_id or "").strip()
    did = str(delivery_id or "").strip()
    candidates: list[str] = []
    if rid:
        candidates.extend(
            [
                f"https://gappapi.deliverynow.vn/api/review/get_reviews?id={quote(rid)}",
                f"https://gappapi.deliverynow.vn/api/review/get_reviews?restaurant_id={quote(rid)}",
                f"https://gappapi.deliverynow.vn/api/review/get_reviews?restaurant_id={quote(rid)}&page=1&limit=10",
                f"https://gappapi.deliverynow.vn/api/review/get_list?restaurant_id={quote(rid)}",
                f"https://gappapi.deliverynow.vn/api/review/get_list?id={quote(rid)}",
                f"https://gappapi.deliverynow.vn/api/delivery/get_reviews?restaurant_id={quote(rid)}",
                f"https://gappapi.deliverynow.vn/api/delivery/get_reviews?id={quote(rid)}",
                f"https://gappapi.deliverynow.vn/api/delivery/get_review_list?restaurant_id={quote(rid)}",
                f"https://gappapi.deliverynow.vn/api/delivery/get_review_list?id={quote(rid)}",
            ]
        )
    if did:
        candidates.extend(
            [
                f"https://gappapi.deliverynow.vn/api/review/get_reviews?request_id={quote(did)}",
                f"https://gappapi.deliverynow.vn/api/review/get_list?request_id={quote(did)}",
                f"https://gappapi.deliverynow.vn/api/delivery/get_reviews?id_type=2&request_id={quote(did)}",
                f"https://gappapi.deliverynow.vn/api/delivery/get_review_list?id_type=2&request_id={quote(did)}",
                f"https://gappapi.deliverynow.vn/api/delivery/get_detail_reviews?id_type=2&request_id={quote(did)}",
            ]
        )
    deduped: list[str] = []
    seen: set[str] = set()
    for url in candidates:
        if url and url not in seen:
            seen.add(url)
            deduped.append(url)
    return deduped


def click_review_triggers(driver) -> dict:
    driver.execute_script("window.__capturedApi = [];")
    return driver.execute_async_script(
        """
        const done = arguments[arguments.length - 1];
        const labels = [
          'Xem thêm lượt đánh giá từ Foody',
          'đánh giá trên ShopeeFood',
          'Đánh giá',
          'Nhận xét',
          'Review',
          'Foody'
        ];
        const events = [];
        try {
          const candidates = Array.from(document.querySelectorAll('a, button, span, div'));
          for (const label of labels) {
            const node = candidates.find((element) => {
              const text = (element.textContent || '').trim();
              const rect = element.getBoundingClientRect();
              return text.includes(label) && rect.width > 0 && rect.height > 0;
            });
            if (!node) {
              continue;
            }
            node.scrollIntoView({block: 'center'});
            ['pointerdown', 'mousedown', 'mouseup', 'click'].forEach((name) => {
              node.dispatchEvent(new MouseEvent(name, {bubbles: true, cancelable: true, view: window}));
            });
            events.push({
              label,
              text: (node.textContent || '').trim().slice(0, 120)
            });
          }
          setTimeout(() => {
            done({
              clicked: events,
              captured_count: (window.__capturedApi || []).length
            });
          }, 2500);
        } catch (error) {
          done({
            clicked: events,
            error: String(error)
          });
        }
        """,
    )


if __name__ == "__main__":
    raise SystemExit(main())
