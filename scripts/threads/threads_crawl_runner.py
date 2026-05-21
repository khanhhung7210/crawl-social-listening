from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote

from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.common.exceptions import SessionNotCreatedException
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


DEBUGGER_ADDRESS = os.getenv("THREADS_DEBUGGER_ADDRESS", "127.0.0.1:9222")
MAX_THREADS = int(os.getenv("THREADS_MAX_URLS_PER_KEYWORD", "40"))
MAX_SCROLL_ROUNDS = 240
IDLE_ROUNDS_BEFORE_STOP = 8
MAX_EMPTY_ROUNDS_BEFORE_SKIP = 5
SCROLL_PAUSE_SECONDS = 2.5
MAX_RUNTIME_SECONDS = 600
OUTPUT_FILE = platform_raw_dir("threads") / "threads_search_results.json"
SPECIAL_SEARCH_URLS = {
    "bts live viewing": [
        "https://www.threads.com/search?q=BTS%20LIVE%20VIEWING&filter=recent",
        "https://www.threads.com/search?q=bts%20live%20viewing&serp_type=tags&filter=recent",
    ],
    "cgv bts": [
        "https://www.threads.com/search?q=cgv%20bts&serp_type=default&filter=recent",
    ],
    "lotte bts": [
        "https://www.threads.com/search?q=lotte%20bts&serp_type=default&filter=recent",
    ],
    "galaxy bts": [
        "https://www.threads.com/search?q=galaxy%20bts&serp_type=default&filter=recent",
    ],
}


def main() -> int:
    keyword_payload = load_keyword_payload()
    search_terms = collect_search_terms(keyword_payload)
    if not search_terms:
        raise RuntimeError("No search terms found in shared keyword config")

    # Initialize crawl state
    with IncrementalCrawlState() as state:
        # Determine if initial or incremental run
        is_initial = state.is_initial_run("threads")
        run_type = "initial" if is_initial else "incremental"

        print(f"[threads-search] Run type: {run_type}")
        print(f"[threads-search] Keywords: {len(search_terms)}")

        # Get existing URLs for deduplication
        existing_urls = state.get_existing_urls("threads")
        print(f"[threads-search] Existing URLs in state: {len(existing_urls)}")

        # Start run tracking
        run_id = state.start_run("threads", run_type)

        driver = build_driver()
        try:
            new_results: list[dict] = []
            urls_discovered = 0
            urls_skipped = 0

            for index, keyword in enumerate(search_terms, start=1):
                print(f"[threads-search] {index}/{len(search_terms)} keyword={keyword}")
                try:
                    search_result = search_threads_for_keyword_incremental(
                        driver,
                        keyword,
                        existing_urls,
                        state,
                        is_initial
                    )
                except Exception as exc:
                    print(f"[threads-search] skip keyword={keyword} error={exc}")
                    new_results.append(
                        {
                            "keyword": keyword,
                            "url": "",
                            "status": "error",
                            "error": str(exc),
                        }
                    )
                    continue

                urls = search_result["urls"]
                status = search_result["status"]
                reason = search_result.get("reason", "")

                urls_discovered += len(urls)

                if not urls:
                    print(f"[threads-search] No new URLs for keyword={keyword}")
                    continue

                for position, url in enumerate(urls, start=1):
                    new_results.append(
                        {
                            "keyword": keyword,
                            "search_keyword": keyword,
                            "url": url,
                            "search_rank": position,
                            "status": status,
                            "reason": reason,
                        }
                    )
                    # Mark URL as crawled in state
                    state.mark_crawled(url, "threads", keyword)

            # Load existing results and merge
            ensure_dir(OUTPUT_FILE.parent)
            existing_results = load_existing_results()
            merged_results = merge_results(existing_results, new_results)

            # Save merged results
            OUTPUT_FILE.write_text(
                json.dumps(merged_results, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )

            urls_skipped = len(existing_urls)

            # Complete run tracking
            state.complete_run(
                run_id,
                urls_discovered=urls_discovered,
                urls_crawled=len(new_results),
                urls_skipped=urls_skipped,
                keywords_processed=len(search_terms)
            )

            print(f"[threads-search] Summary:")
            print(f"  - New URLs discovered: {urls_discovered}")
            print(f"  - Total URLs in state: {len(existing_urls) + urls_discovered}")
            print(f"  - Saved to: {OUTPUT_FILE.resolve()}")
            return 0
        finally:
            driver.quit()


def search_threads_for_keyword(driver: webdriver.Chrome, keyword: str) -> dict:
    """Legacy search function - kept for backward compatibility"""
    urls: list[str] = []
    seen: set[str] = set()
    last_reason = "no_results"
    for search_url in resolve_search_urls(keyword):
        driver.get(search_url)
        time.sleep(5)
        started_at = time.monotonic()
        idle_rounds = 0
        empty_rounds = 0

        for _ in range(MAX_SCROLL_ROUNDS):
            if time.monotonic() - started_at >= MAX_RUNTIME_SECONDS:
                return {
                    "urls": urls,
                    "status": "partial" if urls else "no_results",
                    "reason": "runtime_limit",
                }
            before_count = len(urls)
            for href in get_anchor_hrefs(driver):
                normalized = normalize_thread_url(href)
                if not normalized or normalized in seen:
                    continue
                seen.add(normalized)
                urls.append(normalized)
                if len(urls) >= MAX_THREADS:
                    return {
                        "urls": urls,
                        "status": "ok",
                        "reason": "max_threads_reached",
                    }

            idle_rounds = idle_rounds + 1 if len(urls) == before_count else 0
            empty_rounds = empty_rounds + 1 if not urls else 0
            if idle_rounds >= IDLE_ROUNDS_BEFORE_STOP:
                last_reason = "idle_limit"
                break
            if empty_rounds >= MAX_EMPTY_ROUNDS_BEFORE_SKIP:
                last_reason = "empty_limit"
                print(f"[threads-search] no results for keyword={keyword}, skipping url={search_url}")
                break

            scroll_search_results(driver)
            time.sleep(SCROLL_PAUSE_SECONDS)

    return {
        "urls": urls,
        "status": "partial" if urls else "no_results",
        "reason": last_reason,
    }


def search_threads_for_keyword_incremental(
    driver: webdriver.Chrome,
    keyword: str,
    existing_urls: set[str],
    state: IncrementalCrawlState,
    is_initial: bool
) -> dict:
    """
    Incremental search with early stopping.

    For initial runs: Scroll until max limit or idle
    For incremental runs: Stop early when hitting old URLs (already crawled)
    """
    urls: list[str] = []
    seen: set[str] = set()
    all_discovered: list[str] = []  # Track all URLs for early stop detection
    last_reason = "no_results"
    consecutive_old = 0
    max_consecutive_old = 999 if is_initial else 10  # Stricter for incremental

    for search_url in resolve_search_urls(keyword):
        driver.get(search_url)
        time.sleep(5)
        started_at = time.monotonic()
        idle_rounds = 0
        empty_rounds = 0
        scroll_rounds = 0

        for _ in range(MAX_SCROLL_ROUNDS):
            scroll_rounds += 1

            # Runtime limit
            if time.monotonic() - started_at >= MAX_RUNTIME_SECONDS:
                print(f"[threads-search] keyword={keyword} stopped: runtime_limit")
                return {
                    "urls": urls,
                    "status": "partial" if urls else "no_results",
                    "reason": "runtime_limit",
                }

            before_count = len(urls)
            new_in_round = 0

            for href in get_anchor_hrefs(driver):
                normalized = normalize_thread_url(href)
                if not normalized or normalized in seen:
                    continue

                seen.add(normalized)
                all_discovered.append(normalized)

                # Check if URL already crawled
                if normalized in existing_urls:
                    consecutive_old += 1
                else:
                    consecutive_old = 0  # Reset counter
                    urls.append(normalized)
                    new_in_round += 1

                # Early stop for incremental runs
                if not is_initial and consecutive_old >= max_consecutive_old:
                    print(
                        f"[threads-search] keyword={keyword} early stop: "
                        f"hit {consecutive_old} old URLs in a row"
                    )
                    return {
                        "urls": urls,
                        "status": "ok" if urls else "no_results",
                        "reason": "early_stop_old_urls",
                    }

                # Max limit
                if len(urls) >= MAX_THREADS:
                    print(f"[threads-search] keyword={keyword} stopped: max_threads")
                    return {
                        "urls": urls,
                        "status": "ok",
                        "reason": "max_threads_reached",
                    }

            # Idle/empty detection
            idle_rounds = idle_rounds + 1 if len(urls) == before_count else 0
            empty_rounds = empty_rounds + 1 if not urls else 0

            if idle_rounds >= IDLE_ROUNDS_BEFORE_STOP:
                last_reason = "idle_limit"
                print(
                    f"[threads-search] keyword={keyword} stopped after {scroll_rounds} rounds: "
                    f"idle_limit (new={len(urls)})"
                )
                break

            if empty_rounds >= MAX_EMPTY_ROUNDS_BEFORE_SKIP:
                last_reason = "empty_limit"
                print(
                    f"[threads-search] keyword={keyword} skipping url={search_url}: "
                    f"no results after {scroll_rounds} rounds"
                )
                break

            # Progress logging every 20 rounds
            if scroll_rounds % 20 == 0:
                print(
                    f"[threads-search] keyword={keyword} round={scroll_rounds} "
                    f"new_urls={len(urls)} discovered={len(all_discovered)} "
                    f"consecutive_old={consecutive_old}"
                )

            scroll_search_results(driver)
            time.sleep(SCROLL_PAUSE_SECONDS)

    return {
        "urls": urls,
        "status": "ok" if urls else "no_results",
        "reason": last_reason,
    }


def load_existing_results() -> list[dict]:
    """Load existing search results from OUTPUT_FILE"""
    if not OUTPUT_FILE.exists():
        return []

    try:
        content = OUTPUT_FILE.read_text(encoding="utf-8")
        results = json.loads(content)
        if not isinstance(results, list):
            return []
        return results
    except Exception as exc:
        print(f"[threads-search] Warning: Could not load existing results: {exc}")
        return []


def merge_results(existing: list[dict], new: list[dict]) -> list[dict]:
    """
    Merge existing and new results, deduplicating by URL.

    New results take precedence over existing ones with same URL.
    """
    by_url: dict[str, dict] = {}

    # Add existing first
    for item in existing:
        url = item.get("url", "")
        if url:
            by_url[url] = item

    # Overwrite/add with new
    for item in new:
        url = item.get("url", "")
        if url:
            by_url[url] = item

    # Return as list, sorted by URL for consistency
    return sorted(by_url.values(), key=lambda x: x.get("url", ""))


def resolve_search_urls(keyword: str) -> list[str]:
    normalized = " ".join(str(keyword or "").strip().lower().split())
    if normalized in SPECIAL_SEARCH_URLS:
        return SPECIAL_SEARCH_URLS[normalized]
    return [f"https://www.threads.com/search?q={quote(keyword)}&filter=recent"]


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
            "--remote-debugging-port=9222 "
            "--user-data-dir=/tmp/chrome-codex-threads"
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
    scroll_target = driver.execute_script(
        """
        const elements = [document.scrollingElement, ...document.querySelectorAll('*')];
        let best = document.scrollingElement || document.documentElement;
        let bestHeight = 0;
        for (const el of elements) {
            if (!el) continue;
            const style = window.getComputedStyle(el);
            const canScroll = /(auto|scroll)/.test(style.overflowY || '') && el.scrollHeight > el.clientHeight;
            if (canScroll && el.scrollHeight > bestHeight) {
                best = el;
                bestHeight = el.scrollHeight;
            }
        }
        best.scrollTop = best.scrollHeight;
        return best === document.scrollingElement ? 'window' : 'container';
        """
    )
    if scroll_target == "window":
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")

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


def normalize_thread_url(url: str) -> str:
    if not url:
        return ""
    match = re.search(r"https://www\.threads\.(?:net|com)/@[^/]+/post/[^/?#]+", url)
    if match:
        return match.group(0)
    return ""


if __name__ == "__main__":
    raise SystemExit(main())
