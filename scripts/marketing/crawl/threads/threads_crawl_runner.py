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
from social_listening.chromedriver_utils import resolve_chromedriver_path
from social_listening.crawl_freshness import (
    KeywordCrawlStats,
    load_freshness_policy,
    should_stop_for_validated_stale_content,
)


DEBUGGER_ADDRESS = os.getenv("THREADS_DEBUGGER_ADDRESS", "127.0.0.1:9222")
POLICY = load_freshness_policy("threads")
MAX_THREADS = POLICY.max_new_urls_per_keyword
MAX_SCROLL_ROUNDS = POLICY.max_scroll_rounds
IDLE_ROUNDS_BEFORE_STOP = POLICY.idle_rounds_before_stop
MAX_EMPTY_ROUNDS_BEFORE_SKIP = POLICY.empty_rounds_before_skip
SCROLL_PAUSE_SECONDS = float(os.getenv("THREADS_SCROLL_PAUSE_SECONDS", "2.5"))
MAX_RUNTIME_SECONDS = POLICY.max_runtime_seconds
KEYWORD_RUNTIME_SECONDS = POLICY.keyword_runtime_seconds
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

    with IncrementalCrawlState() as state:
        is_initial = state.is_initial_run("threads") and state.is_initial_run("threads_detail")
        run_type = "initial" if is_initial else "incremental"
        existing_urls = state.get_known_urls("threads", "threads_detail")

        print(f"[threads-search] Run type: {run_type}")
        print(f"[threads-search] Keywords: {len(search_terms)}")
        print(f"[threads-search] Existing URLs in state: {len(existing_urls)}")
        print(
            f"[threads-search] Policy lookback={POLICY.lookback_days:.1f}d "
            f"max_new={MAX_THREADS} scroll={MAX_SCROLL_ROUNDS} "
            f"runtime={MAX_RUNTIME_SECONDS}s keyword_runtime={KEYWORD_RUNTIME_SECONDS}s "
            f"content_stale_stop={POLICY.consecutive_stale_content_stop}"
        )
        print(
            "[threads-search] Note: do NOT stop on consecutive previously-seen URLs; "
            "content-time stop only when timestamps are validated"
        )

        run_id = state.start_run("threads", run_type)

        driver = build_driver()
        try:
            new_results: list[dict] = []
            urls_discovered = 0
            urls_new = 0

            for index, keyword in enumerate(search_terms, start=1):
                print(f"[threads-search] {index}/{len(search_terms)} keyword={keyword}")
                try:
                    search_result = search_threads_for_keyword_incremental(
                        driver,
                        keyword,
                        existing_urls,
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

                stats: KeywordCrawlStats = search_result["stats"]
                stats.log("threads-search")
                urls = search_result["urls"]
                status = search_result["status"]
                reason = search_result.get("reason", "")
                urls_discovered += stats.discovered
                urls_new += len(urls)

                if not urls:
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
                            "pending_detail": True,
                        }
                    )

            ensure_dir(OUTPUT_FILE.parent)
            existing_results = load_existing_results()
            merged_results = merge_results(existing_results, new_results)

            OUTPUT_FILE.write_text(
                json.dumps(merged_results, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            state.complete_run(
                run_id,
                urls_discovered=urls_discovered,
                urls_crawled=0,
                urls_skipped=len(existing_urls),
                keywords_processed=len(search_terms),
            )

            print(f"[threads-search] Summary:")
            print(f"  - Discovered (all keywords): {urls_discovered}")
            print(f"  - New URLs queued for detail: {urls_new}")
            print(f"  - Saved to: {OUTPUT_FILE.resolve()}")
            return 0
        finally:
            driver.quit()


def search_threads_for_keyword_incremental(
    driver: webdriver.Chrome,
    keyword: str,
    existing_urls: set[str],
) -> dict:
    """
    Incremental search without URL-history early-stop.

    With filter=recent, optional stop only when search cards expose validated
    content timestamps that are outside the lookback window.
    """
    urls: list[str] = []
    seen: set[str] = set()
    all_discovered: list[str] = []
    already_seen = 0
    consecutive_stale_content = 0
    last_reason = "no_results"
    keyword_started = time.monotonic()

    for search_url in resolve_search_urls(keyword):
        if time.monotonic() - keyword_started >= KEYWORD_RUNTIME_SECONDS:
            last_reason = "keyword_runtime_limit"
            break

        driver.get(search_url)
        time.sleep(5)
        started_at = time.monotonic()
        idle_rounds = 0
        empty_rounds = 0
        scroll_rounds = 0

        for _ in range(MAX_SCROLL_ROUNDS):
            scroll_rounds += 1
            elapsed_keyword = time.monotonic() - keyword_started
            elapsed_url = time.monotonic() - started_at

            if elapsed_keyword >= KEYWORD_RUNTIME_SECONDS:
                last_reason = "keyword_runtime_limit"
                break
            if elapsed_url >= MAX_RUNTIME_SECONDS:
                last_reason = "runtime_limit"
                break

            before_count = len(urls)
            card_rows = extract_search_cards(driver)

            for row in card_rows:
                normalized = row["url"]
                if not normalized or normalized in seen:
                    continue

                seen.add(normalized)
                all_discovered.append(normalized)

                if normalized in existing_urls:
                    already_seen += 1
                    continue

                # Validated content-time boundary (only when timestamp present)
                content_ts = row.get("content_timestamp")
                if content_ts is not None:
                    from social_listening.crawl_freshness import is_stale

                    stale = is_stale(content_ts, POLICY)
                    if stale is True:
                        consecutive_stale_content += 1
                        # Do not queue stale cards for detail; do not mark successful crawl.
                        if should_stop_for_validated_stale_content(consecutive_stale_content, POLICY):
                            last_reason = "freshness_boundary"
                            stats = KeywordCrawlStats(
                                keyword=keyword,
                                discovered=len(all_discovered),
                                new=len(urls),
                                stale=consecutive_stale_content,
                                already_seen=already_seen,
                                runtime_seconds=time.monotonic() - keyword_started,
                                stop_reason=last_reason,
                            )
                            return {
                                "urls": urls,
                                "status": "ok" if urls else "no_results",
                                "reason": last_reason,
                                "stats": stats,
                            }
                        continue
                    if stale is False:
                        consecutive_stale_content = 0

                urls.append(normalized)
                if len(urls) >= MAX_THREADS:
                    last_reason = "max_threads_reached"
                    stats = KeywordCrawlStats(
                        keyword=keyword,
                        discovered=len(all_discovered),
                        new=len(urls),
                        already_seen=already_seen,
                        runtime_seconds=time.monotonic() - keyword_started,
                        stop_reason=last_reason,
                    )
                    return {
                        "urls": urls,
                        "status": "ok",
                        "reason": last_reason,
                        "stats": stats,
                    }

            # Fallback if card extractor found nothing: raw href scan
            if not card_rows:
                for href in get_anchor_hrefs(driver):
                    normalized = normalize_thread_url(href)
                    if not normalized or normalized in seen:
                        continue
                    seen.add(normalized)
                    all_discovered.append(normalized)
                    if normalized in existing_urls:
                        already_seen += 1
                        continue
                    urls.append(normalized)
                    if len(urls) >= MAX_THREADS:
                        last_reason = "max_threads_reached"
                        break

            if last_reason == "max_threads_reached":
                break

            idle_rounds = idle_rounds + 1 if len(urls) == before_count else 0
            empty_rounds = empty_rounds + 1 if not urls and not already_seen else 0

            if idle_rounds >= IDLE_ROUNDS_BEFORE_STOP:
                last_reason = "idle_limit"
                break

            if empty_rounds >= MAX_EMPTY_ROUNDS_BEFORE_SKIP:
                last_reason = "empty_limit"
                break

            if scroll_rounds % 20 == 0:
                print(
                    f"[threads-search] keyword={keyword} round={scroll_rounds} "
                    f"new_urls={len(urls)} discovered={len(all_discovered)} "
                    f"already_seen={already_seen}"
                )

            scroll_search_results(driver)
            time.sleep(SCROLL_PAUSE_SECONDS)

        if last_reason in {
            "keyword_runtime_limit",
            "runtime_limit",
            "max_threads_reached",
            "freshness_boundary",
        }:
            break

    stats = KeywordCrawlStats(
        keyword=keyword,
        discovered=len(all_discovered),
        new=len(urls),
        already_seen=already_seen,
        runtime_seconds=time.monotonic() - keyword_started,
        stop_reason=last_reason,
    )
    status = "ok" if urls else ("partial" if all_discovered else "no_results")
    if last_reason in {"runtime_limit", "keyword_runtime_limit"} and urls:
        status = "partial"
    return {"urls": urls, "status": status, "reason": last_reason, "stats": stats}


def extract_search_cards(driver: webdriver.Chrome) -> list[dict]:
    """Best-effort URL + relative/absolute time labels from Threads search cards."""
    try:
        rows = driver.execute_script(
            """
            const out = [];
            const seen = new Set();
            const anchors = Array.from(document.querySelectorAll('a[href*="/post/"]'));
            for (const a of anchors) {
              const href = a.href || '';
              const m = href.match(/https:\\/\\/www\\.threads\\.(?:net|com)\\/@[^/]+\\/post\\/[^/?#]+/);
              if (!m || seen.has(m[0])) continue;
              seen.add(m[0]);
              let timeLabel = '';
              const root = a.closest('div') || a.parentElement;
              if (root) {
                const timeNode = root.querySelector('time[datetime], time');
                if (timeNode) {
                  timeLabel = timeNode.getAttribute('datetime') || timeNode.getAttribute('title') || timeNode.innerText || '';
                }
                if (!timeLabel) {
                  const aria = root.querySelector('[aria-label]');
                  if (aria) timeLabel = aria.getAttribute('aria-label') || '';
                }
              }
              out.push({ url: m[0], time_label: (timeLabel || '').trim() });
            }
            return out;
            """
        )
    except WebDriverException:
        return []

    if not isinstance(rows, list):
        return []

    from social_listening.review_utils import parse_facebook_datetime_label

    results: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        url = normalize_thread_url(str(row.get("url") or ""))
        if not url:
            continue
        label = str(row.get("time_label") or "").strip()
        content_ts = None
        if label:
            # ISO first
            from social_listening.crawl_freshness import parse_content_timestamp

            content_ts = parse_content_timestamp(label)
            if content_ts is None:
                parsed = parse_facebook_datetime_label(label)
                if parsed is not None:
                    content_ts = parsed
        results.append({"url": url, "content_timestamp": content_ts, "time_label": label})
    return results


def load_existing_results() -> list[dict]:
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
