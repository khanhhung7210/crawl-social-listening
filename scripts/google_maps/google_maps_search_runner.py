from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote_plus

from selenium import webdriver
from selenium.common.exceptions import SessionNotCreatedException, WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from webdriver_manager.chrome import ChromeDriverManager

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from social_listening.film_paths import platform_raw_dir
from social_listening.keyword_config import collect_config_values, collect_search_terms, load_keyword_payload
from social_listening.paths import ensure_dir


DEBUGGER_ADDRESS = os.getenv("GOOGLE_MAPS_DEBUGGER_ADDRESS", "127.0.0.1:9227")
MAX_PLACES_PER_QUERY = int(os.getenv("GOOGLE_MAPS_MAX_PLACES_PER_QUERY", "20"))
MAX_SCROLL_ROUNDS = int(os.getenv("GOOGLE_MAPS_MAX_SCROLL_ROUNDS", "24"))
SCROLL_PAUSE_SECONDS = float(os.getenv("GOOGLE_MAPS_SCROLL_PAUSE_SECONDS", "2.0"))
OUTPUT_FILE = platform_raw_dir("google_maps") / "google_maps_search_results.json"


def main() -> int:
    payload = load_keyword_payload()
    search_queries = collect_config_values(payload, "google_maps_queries")
    if not search_queries:
        search_queries = collect_search_terms(payload, include_hashtags=False)
    direct_urls = collect_config_values(payload, "google_maps_urls")

    driver = build_driver()
    try:
        results: list[dict] = []
        seen: set[str] = set()

        for position, url in enumerate(direct_urls, start=1):
            normalized = normalize_google_maps_place_url(url)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            results.append(
                {
                    "keyword": "direct_url",
                    "search_keyword": "direct_url",
                    "url": normalized,
                    "search_rank": position,
                    "status": "ok",
                    "reason": "config_url",
                }
            )

        for index, keyword in enumerate(search_queries, start=1):
            print(f"[google-maps-search] {index}/{len(search_queries)} keyword={keyword}")
            try:
                search_result = search_places_for_keyword(driver, keyword)
            except Exception as exc:
                print(f"[google-maps-search] skip keyword={keyword} error={exc}")
                results.append({"keyword": keyword, "search_keyword": keyword, "url": "", "status": "error", "error": str(exc)})
                continue

            for rank, url in enumerate(search_result["urls"], start=1):
                if url in seen:
                    continue
                seen.add(url)
                results.append(
                    {
                        "keyword": keyword,
                        "search_keyword": keyword,
                        "url": url,
                        "search_rank": rank,
                        "status": search_result["status"],
                        "reason": search_result.get("reason", ""),
                    }
                )

        ensure_dir(OUTPUT_FILE.parent)
        OUTPUT_FILE.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"saved {len(results)} google maps urls to {OUTPUT_FILE.resolve()}")
        return 0
    finally:
        driver.quit()


def search_places_for_keyword(driver: webdriver.Chrome, keyword: str) -> dict:
    driver.get(f"https://www.google.com/maps/search/{quote_plus(keyword)}")
    time.sleep(6)

    urls: list[str] = []
    seen: set[str] = set()
    idle_rounds = 0

    for _ in range(MAX_SCROLL_ROUNDS):
        before_count = len(urls)
        for href in get_anchor_hrefs(driver):
            normalized = normalize_google_maps_place_url(href)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            urls.append(normalized)
            if len(urls) >= MAX_PLACES_PER_QUERY:
                return {"urls": urls, "status": "ok", "reason": "max_places_reached"}

        idle_rounds = idle_rounds + 1 if len(urls) == before_count else 0
        if idle_rounds >= 6:
            break
        scroll_search_results(driver)
        time.sleep(SCROLL_PAUSE_SECONDS)

    return {"urls": urls, "status": "partial" if urls else "no_results", "reason": "scroll_exhausted"}


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


def scroll_search_results(driver: webdriver.Chrome) -> None:
    driver.execute_script(
        """
        const panel = Array.from(document.querySelectorAll('div[role="feed"], div[aria-label]'))
          .find((node) => node.scrollHeight > node.clientHeight + 100);
        if (panel) {
          panel.scrollTop = panel.scrollHeight;
          return;
        }
        window.scrollTo(0, document.body.scrollHeight);
        """
    )
    try:
        driver.find_element(By.TAG_NAME, "body").send_keys(Keys.END)
    except Exception:
        pass


def get_anchor_hrefs(driver: webdriver.Chrome) -> list[str]:
    try:
        hrefs = driver.execute_script(
            """
            return Array.from(document.querySelectorAll('a'))
              .map((anchor) => anchor.href || '')
              .filter(Boolean);
            """
        )
    except WebDriverException:
        return []
    return [str(href).strip() for href in hrefs if str(href).strip()]


def normalize_google_maps_place_url(url: str) -> str:
    text = str(url or "").strip()
    if not text:
        return ""
    match = re.search(r"https://www\.google\.[^/]+/maps/place/[^?#]+", text)
    if match:
        return match.group(0)
    if "/maps?cid=" in text or "/maps/place/" in text:
        return text.split("&", 1)[0]
    return ""


if __name__ == "__main__":
    raise SystemExit(main())
