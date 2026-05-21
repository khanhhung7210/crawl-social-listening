from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote

from selenium import webdriver
from selenium.common.exceptions import SessionNotCreatedException, WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from webdriver_manager.chrome import ChromeDriverManager

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from social_listening.keyword_config import collect_search_terms, load_keyword_payload
from social_listening.film_paths import platform_raw_dir
from social_listening.paths import DATA_DIR, ensure_dir
from social_listening.crawl_state import IncrementalCrawlState


TIKTOK_SEARCH_URL = "https://www.tiktok.com/search/video?q={query}"
DEBUGGER_ADDRESS = os.getenv("TIKTOK_DEBUGGER_ADDRESS", "127.0.0.1:9223")
MAX_VIDEOS = 200
MAX_SCROLL_ROUNDS = 240
IDLE_ROUNDS_BEFORE_STOP = 8
MAX_EMPTY_ROUNDS_BEFORE_SKIP = 5
SCROLL_PAUSE_SECONDS = 2.5
MAX_RUNTIME_SECONDS = 600
OUTPUT_FILE = platform_raw_dir("tiktok") / "tiktok_search_results.json"


def main() -> int:
    search_terms = collect_search_terms(load_keyword_payload())
    if not search_terms:
        raise RuntimeError("No search terms found in shared keyword config")

    with IncrementalCrawlState() as state:
        is_initial = state.is_initial_run("tiktok")
        run_type = "initial" if is_initial else "incremental"
        existing_urls = state.get_existing_urls("tiktok")

        print(f"[tiktok-search] Run type: {run_type}")
        print(f"[tiktok-search] Keywords: {len(search_terms)}")
        print(f"[tiktok-search] Existing URLs: {len(existing_urls)}")

        run_id = state.start_run("tiktok", run_type)

        driver = build_driver()
        try:
            new_results: list[dict] = []
            global_seen: set[str] = set()
            urls_discovered = 0
            max_consecutive_old = 999 if is_initial else 10

            for index, keyword in enumerate(search_terms, start=1):
                print(f"[tiktok-search] {index}/{len(search_terms)} keyword={keyword}")
                try:
                    search_result = search_videos_for_keyword_incremental(
                        driver, keyword, existing_urls, is_initial, max_consecutive_old
                    )
                except Exception as exc:
                    print(f"[tiktok-search] skip keyword={keyword} error={exc}")
                    continue

                urls = search_result["urls"]
                urls_discovered += len(urls)

                if not urls:
                    print(f"[tiktok-search] No new URLs for keyword={keyword}")
                    continue

                for url in urls:
                    if url in global_seen:
                        continue
                    global_seen.add(url)
                    new_results.append({
                        "keyword": keyword,
                        "url": url,
                        "status": search_result["status"],
                        "reason": search_result.get("reason", "")
                    })
                    state.mark_crawled(url, "tiktok", keyword)

            # Merge with existing
            ensure_dir(OUTPUT_FILE.parent)
            existing_results = load_existing_results()
            merged = merge_results(existing_results, new_results)

            OUTPUT_FILE.write_text(
                json.dumps(merged, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            state.complete_run(
                run_id,
                urls_discovered=urls_discovered,
                urls_crawled=len(new_results),
                urls_skipped=len(existing_urls),
                keywords_processed=len(search_terms)
            )

            print(f"[tiktok-search] Summary:")
            print(f"  - New URLs discovered: {urls_discovered}")
            print(f"  - Total URLs in state: {len(existing_urls) + urls_discovered}")
            print(f"  - Saved to: {OUTPUT_FILE.resolve()}")
            return 0
        finally:
            driver.quit()


def search_videos_for_keyword_incremental(
    driver: webdriver.Chrome,
    keyword: str,
    existing_urls: set[str],
    is_initial: bool,
    max_consecutive_old: int
) -> dict:
    """Incremental search with early stop"""
    driver.get(TIKTOK_SEARCH_URL.format(query=quote(keyword)))
    time.sleep(5)
    started_at = time.monotonic()

    urls: list[str] = []
    seen: set[str] = set()
    all_discovered: list[str] = []
    idle_rounds = 0
    empty_rounds = 0
    consecutive_old = 0
    scroll_rounds = 0

    for _ in range(MAX_SCROLL_ROUNDS):
        scroll_rounds += 1

        if time.monotonic() - started_at >= MAX_RUNTIME_SECONDS:
            print(f"[tiktok-search] keyword={keyword} stopped: runtime_limit")
            return {"urls": urls, "status": "partial" if urls else "no_results", "reason": "runtime_limit"}

        before_count = len(urls)

        for href in get_anchor_hrefs(driver):
            normalized = normalize_tiktok_video_url(href)
            if not normalized or normalized in seen:
                continue

            seen.add(normalized)
            all_discovered.append(normalized)

            if normalized in existing_urls:
                consecutive_old += 1
            else:
                consecutive_old = 0
                urls.append(normalized)

            # Early stop for incremental
            if not is_initial and consecutive_old >= max_consecutive_old:
                print(f"[tiktok-search] keyword={keyword} early stop: hit {consecutive_old} old URLs")
                return {"urls": urls, "status": "ok" if urls else "no_results", "reason": "early_stop_old_urls"}

            if len(urls) >= MAX_VIDEOS:
                print(f"[tiktok-search] keyword={keyword} stopped: max_videos")
                return {"urls": urls, "status": "ok", "reason": "max_videos_reached"}

        idle_rounds = idle_rounds + 1 if len(urls) == before_count else 0
        empty_rounds = empty_rounds + 1 if not urls else 0

        if idle_rounds >= IDLE_ROUNDS_BEFORE_STOP:
            print(f"[tiktok-search] keyword={keyword} stopped: idle_limit")
            return {"urls": urls, "status": "partial" if urls else "no_results", "reason": "idle_limit"}

        if empty_rounds >= MAX_EMPTY_ROUNDS_BEFORE_SKIP:
            print(f"[tiktok-search] keyword={keyword} stopped: empty_limit")
            return {"urls": urls, "status": "no_results", "reason": "empty_limit"}

        # Progress logging
        if scroll_rounds % 20 == 0:
            print(f"[tiktok-search] keyword={keyword} round={scroll_rounds} new_urls={len(urls)} discovered={len(all_discovered)} consecutive_old={consecutive_old}")

        scroll_search_results(driver)
        time.sleep(SCROLL_PAUSE_SECONDS)

    return {"urls": urls, "status": "ok" if urls else "no_results", "reason": "scroll_exhausted"}


def load_existing_results() -> list[dict]:
    if not OUTPUT_FILE.exists():
        return []
    try:
        content = OUTPUT_FILE.read_text(encoding="utf-8")
        results = json.loads(content)
        return results if isinstance(results, list) else []
    except Exception:
        return []


def merge_results(existing: list[dict], new: list[dict]) -> list[dict]:
    by_url: dict[str, dict] = {}
    for item in existing:
        url = item.get("url", "")
        if url:
            by_url[url] = item
    for item in new:
        url = item.get("url", "")
        if url:
            by_url[url] = item
    return sorted(by_url.values(), key=lambda x: x.get("url", ""))


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
            "--remote-debugging-port=9223 "
            "--user-data-dir=/tmp/chrome-codex-tiktok"
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
    driver.execute_script("window.scrollBy(0, window.innerHeight);")
    body = driver.find_element(By.TAG_NAME, "body")
    body.send_keys(Keys.END)


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


def normalize_tiktok_video_url(url: str) -> str:
    if not url:
        return ""
    match = re.search(r"https://www\.tiktok\.com/@[^/]+/video/\d+", url)
    if match:
        return match.group(0)
    return ""


if __name__ == "__main__":
    raise SystemExit(main())
