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
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

def _project_root() -> Path:
    current = Path(__file__).resolve().parent
    for cand in [current, *current.parents]:
        if (cand / "src" / "social_listening").is_dir():
            return cand
    raise RuntimeError(f"Cannot find project root from {__file__}")


PROJECT_ROOT = _project_root()
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from social_listening.keyword_config import collect_search_terms, load_keyword_payload
from social_listening.film_paths import platform_raw_dir
from social_listening.paths import ensure_dir
from social_listening.crawl_state import IncrementalCrawlState
from social_listening.chromedriver_utils import build_debugger_driver
from social_listening.crawl_freshness import KeywordCrawlStats, load_freshness_policy


TIKTOK_SEARCH_URL = "https://www.tiktok.com/search/video?q={query}"
DEBUGGER_ADDRESS = os.getenv("TIKTOK_DEBUGGER_ADDRESS", "127.0.0.1:9223")
POLICY = load_freshness_policy("tiktok")
MAX_VIDEOS = POLICY.max_new_urls_per_keyword
MAX_SCROLL_ROUNDS = POLICY.max_scroll_rounds
IDLE_ROUNDS_BEFORE_STOP = POLICY.idle_rounds_before_stop
MAX_EMPTY_ROUNDS_BEFORE_SKIP = POLICY.empty_rounds_before_skip
SCROLL_PAUSE_SECONDS = float(os.getenv("TIKTOK_SCROLL_PAUSE_SECONDS", "2.5"))
MAX_RUNTIME_SECONDS = POLICY.max_runtime_seconds
KEYWORD_RUNTIME_SECONDS = POLICY.keyword_runtime_seconds
OUTPUT_FILE = platform_raw_dir("tiktok") / "tiktok_search_results.json"


def main() -> int:
    search_terms = collect_search_terms(load_keyword_payload())
    if not search_terms:
        raise RuntimeError("No search terms found in shared keyword config")

    with IncrementalCrawlState() as state:
        is_initial = state.is_initial_run("tiktok") and state.is_initial_run("tiktok_detail")
        run_type = "initial" if is_initial else "incremental"
        # Dedup against both search-era and detail-era marks; do NOT mark at search time.
        existing_urls = state.get_known_urls("tiktok", "tiktok_detail")

        print(f"[tiktok-search] Run type: {run_type}")
        print(f"[tiktok-search] Keywords: {len(search_terms)}")
        print(f"[tiktok-search] Existing URLs: {len(existing_urls)}")
        print(
            f"[tiktok-search] Policy lookback={POLICY.lookback_days:.1f}d "
            f"max_new={MAX_VIDEOS} scroll={MAX_SCROLL_ROUNDS} "
            f"runtime={MAX_RUNTIME_SECONDS}s keyword_runtime={KEYWORD_RUNTIME_SECONDS}s"
        )
        print(
            "[tiktok-search] Note: search ranking is NOT assumed chronological; "
            "no early-stop on consecutive previously-seen URLs"
        )

        run_id = state.start_run("tiktok", run_type)

        driver = build_driver()
        try:
            new_results: list[dict] = []
            global_seen: set[str] = set()
            urls_discovered = 0
            urls_new = 0

            for index, keyword in enumerate(search_terms, start=1):
                print(f"[tiktok-search] {index}/{len(search_terms)} keyword={keyword}")
                try:
                    search_result = search_videos_for_keyword_incremental(
                        driver, keyword, existing_urls
                    )
                except Exception as exc:
                    print(f"[tiktok-search] skip keyword={keyword} error={exc}")
                    continue

                stats: KeywordCrawlStats = search_result["stats"]
                stats.log("tiktok-search")
                urls = search_result["urls"]
                urls_discovered += stats.discovered
                urls_new += len(urls)

                if not urls:
                    continue

                for url in urls:
                    if url in global_seen:
                        continue
                    global_seen.add(url)
                    new_results.append({
                        "keyword": keyword,
                        "url": url,
                        "status": search_result["status"],
                        "reason": search_result.get("reason", ""),
                        # Not marked in crawl_state until detail confirms freshness.
                        "pending_detail": True,
                    })

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
                urls_crawled=0,  # detail stage owns successful crawl marks
                urls_skipped=len(existing_urls),
                keywords_processed=len(search_terms),
            )

            print(f"[tiktok-search] Summary:")
            print(f"  - Discovered (all keywords): {urls_discovered}")
            print(f"  - New URLs queued for detail: {urls_new}")
            print(f"  - Saved to: {OUTPUT_FILE.resolve()}")
            return 0
        finally:
            driver.quit()


def search_videos_for_keyword_incremental(
    driver: webdriver.Chrome,
    keyword: str,
    existing_urls: set[str],
) -> dict:
    """Scroll until idle/empty/safety limits. Never stop on consecutive old URLs alone."""
    driver.get(TIKTOK_SEARCH_URL.format(query=quote(keyword)))
    time.sleep(5)
    started_at = time.monotonic()

    urls: list[str] = []
    seen: set[str] = set()
    all_discovered: list[str] = []
    idle_rounds = 0
    empty_rounds = 0
    already_seen = 0
    scroll_rounds = 0
    stop_reason = "scroll_exhausted"

    for _ in range(MAX_SCROLL_ROUNDS):
        scroll_rounds += 1
        elapsed = time.monotonic() - started_at

        if elapsed >= KEYWORD_RUNTIME_SECONDS:
            stop_reason = "keyword_runtime_limit"
            break
        if elapsed >= MAX_RUNTIME_SECONDS:
            stop_reason = "runtime_limit"
            break

        before_count = len(urls)

        for href in get_anchor_hrefs(driver):
            normalized = normalize_tiktok_video_url(href)
            if not normalized or normalized in seen:
                continue

            seen.add(normalized)
            all_discovered.append(normalized)

            if normalized in existing_urls:
                already_seen += 1
                continue

            urls.append(normalized)
            if len(urls) >= MAX_VIDEOS:
                stop_reason = "max_videos_reached"
                break

        if stop_reason == "max_videos_reached":
            break

        idle_rounds = idle_rounds + 1 if len(urls) == before_count else 0
        empty_rounds = empty_rounds + 1 if not urls and not already_seen else 0

        if idle_rounds >= IDLE_ROUNDS_BEFORE_STOP:
            stop_reason = "idle_limit"
            break

        if empty_rounds >= MAX_EMPTY_ROUNDS_BEFORE_SKIP:
            stop_reason = "empty_limit"
            break

        if scroll_rounds % 20 == 0:
            print(
                f"[tiktok-search] keyword={keyword} round={scroll_rounds} "
                f"new_urls={len(urls)} discovered={len(all_discovered)} "
                f"already_seen={already_seen}"
            )

        scroll_search_results(driver)
        time.sleep(SCROLL_PAUSE_SECONDS)

    stats = KeywordCrawlStats(
        keyword=keyword,
        discovered=len(all_discovered),
        new=len(urls),
        already_seen=already_seen,
        runtime_seconds=time.monotonic() - started_at,
        stop_reason=stop_reason,
    )
    status = "ok" if urls else ("partial" if all_discovered else "no_results")
    if stop_reason in {"runtime_limit", "keyword_runtime_limit"} and urls:
        status = "partial"
    return {"urls": urls, "status": status, "reason": stop_reason, "stats": stats}


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
    return build_debugger_driver(DEBUGGER_ADDRESS)


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
