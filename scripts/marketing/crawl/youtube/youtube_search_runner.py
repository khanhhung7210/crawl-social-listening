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
from social_listening.paths import DATA_DIR, ensure_dir
from social_listening.crawl_state import IncrementalCrawlState
from social_listening.chromedriver_utils import resolve_chromedriver_path
from social_listening.crawl_freshness import KeywordCrawlStats, load_freshness_policy

YOUTUBE_SEARCH_URL = "https://www.youtube.com/results?search_query={query}"
DEBUGGER_ADDRESS = os.getenv("YOUTUBE_DEBUGGER_ADDRESS", "127.0.0.1:9225")
POLICY = load_freshness_policy("youtube")
DISCOVERY_LIMIT = POLICY.discovery_limit
FINAL_LIMIT = POLICY.final_limit
MAX_VIDEOS = DISCOVERY_LIMIT
MAX_SCROLL_ROUNDS = POLICY.max_scroll_rounds
IDLE_ROUNDS_BEFORE_STOP = POLICY.idle_rounds_before_stop
MAX_EMPTY_ROUNDS_BEFORE_SKIP = POLICY.empty_rounds_before_skip
SCROLL_PAUSE_SECONDS = float(os.getenv("YOUTUBE_SCROLL_PAUSE_SECONDS", "2.0"))
MAX_RUNTIME_SECONDS = POLICY.max_runtime_seconds
KEYWORD_RUNTIME_SECONDS = POLICY.keyword_runtime_seconds
OUTPUT_FILE = platform_raw_dir("youtube") / "youtube_search_results.json"


def main() -> int:
    search_terms = collect_search_terms(load_keyword_payload())
    if not search_terms:
        raise RuntimeError("No search terms found in shared keyword config")

    with IncrementalCrawlState() as state:
        is_initial = state.is_initial_run("youtube") and state.is_initial_run("youtube_detail")
        run_type = "initial" if is_initial else "incremental"
        existing_urls = state.get_known_urls("youtube", "youtube_detail")

        print(f"[youtube-search] Run type: {run_type}")
        print(f"[youtube-search] Keywords: {len(search_terms)}")
        print(f"[youtube-search] Existing URLs: {len(existing_urls)}")
        print(
            f"[youtube-search] Policy discovery={DISCOVERY_LIMIT} final={FINAL_LIMIT} "
            f"scroll={MAX_SCROLL_ROUNDS} runtime={MAX_RUNTIME_SECONDS}s"
        )
        print(
            "[youtube-search] Note: try Upload date filter (fail-soft); "
            "no early-stop on consecutive previously-seen URLs; "
            "FINAL newest sort happens after detail timestamps"
        )

        run_id = state.start_run("youtube", run_type)

        driver = build_driver()
        try:
            new_results: list[dict] = []
            global_seen: set[str] = set()
            urls_discovered = 0
            urls_new = 0

            for index, keyword in enumerate(search_terms, start=1):
                print(f"[youtube-search] {index}/{len(search_terms)} keyword={keyword}")
                try:
                    search_result = search_videos_for_keyword_incremental(
                        driver, keyword, existing_urls
                    )
                except Exception as exc:
                    print(f"[youtube-search] skip keyword={keyword} error={exc}")
                    continue

                stats: KeywordCrawlStats = search_result["stats"]
                stats.log("youtube-search")
                urls = search_result["urls"]
                urls_discovered += stats.discovered
                urls_new += len(urls)

                if not urls:
                    print(f"[youtube-search] No new URLs for keyword={keyword}")
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
                        "pending_detail": True,
                        "upload_date_filter": search_result.get("upload_date_filter"),
                    })
                    # Do not mark at search time — detail owns coverage + published_at.

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
                urls_crawled=0,
                urls_skipped=len(existing_urls),
                keywords_processed=len(search_terms)
            )

            print(f"[youtube-search] Summary:")
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
    """Scroll until idle/empty/safety. Never stop on consecutive old URLs alone."""
    driver.get(YOUTUBE_SEARCH_URL.format(query=quote_plus(keyword)))
    time.sleep(4)
    upload_filter = ensure_upload_date_filter(driver)
    print(
        f"[youtube-search] keyword={keyword} upload_date_filter="
        f"{'on' if upload_filter else 'unavailable(fail-soft)'}",
        flush=True,
    )
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
            normalized = normalize_youtube_video_url(href)
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

        if scroll_rounds % 15 == 0:
            print(
                f"[youtube-search] keyword={keyword} round={scroll_rounds} "
                f"new_urls={len(urls)} discovered={len(all_discovered)} already_seen={already_seen}"
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
        extras={"upload_date_filter": upload_filter},
    )
    status = "ok" if urls else ("partial" if all_discovered else "no_results")
    if stop_reason in {"runtime_limit", "keyword_runtime_limit"} and urls:
        status = "partial"
    return {
        "urls": urls,
        "status": status,
        "reason": stop_reason,
        "stats": stats,
        "upload_date_filter": upload_filter,
    }


def ensure_upload_date_filter(driver: webdriver.Chrome) -> bool:
    """Bộ lọc → Tải lên gần đây / Filters → Upload date. Fail-soft."""
    try:
        opened = driver.execute_script(
            """
            const labels = ['Search filters', 'Filters', 'Bộ lọc', 'Filter'];
            const nodes = Array.from(document.querySelectorAll(
              'button, yt-chip-cloud-chip-renderer, [aria-label]'
            ));
            for (const el of nodes) {
              const text = ((el.getAttribute('aria-label') || '') + ' ' + (el.innerText || '')).trim();
              if (!text) continue;
              if (labels.some((l) => text.toLowerCase().includes(l.toLowerCase()))) {
                el.click();
                return true;
              }
            }
            return false;
            """
        )
        if opened:
            time.sleep(1.0)
        clicked = driver.execute_script(
            """
            const targets = [
              'Upload date', 'Tải lên gần đây', 'Ngày tải lên',
              'This week', 'Tuần này', 'Today', 'Hôm nay'
            ];
            // Prefer exact "Upload date" / "Tải lên gần đây" as sort mode when present
            const preferred = ['Upload date', 'Tải lên gần đây', 'Ngày tải lên'];
            const nodes = Array.from(document.querySelectorAll(
              'yt-formatted-string, tp-yt-paper-item, a, yt-chip-cloud-chip-renderer, span'
            ));
            const clickMatch = (wanted) => {
              for (const el of nodes) {
                const text = (el.innerText || el.textContent || '').trim();
                if (!text) continue;
                if (wanted.some((w) => text === w || text.includes(w))) {
                  el.click();
                  return true;
                }
              }
              return false;
            };
            if (clickMatch(preferred)) return true;
            return clickMatch(targets);
            """
        )
        if clicked:
            time.sleep(2.0)
            return True
    except Exception:
        return False
    return False


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
    options.add_argument("--lang=vi-VN")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--window-size=1440,2200")
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
            "--remote-debugging-port=9225 "
            "--user-data-dir=/tmp/chrome-codex-youtube"
        ) from exc


def scroll_search_results(driver: webdriver.Chrome) -> None:
    driver.execute_script("window.scrollBy(0, window.innerHeight * 1.5);")
    body = driver.find_element(By.TAG_NAME, "body")
    body.send_keys(Keys.END)


def get_anchor_hrefs(driver: webdriver.Chrome) -> list[str]:
    try:
        hrefs = driver.execute_script(
            """
            return Array.from(document.querySelectorAll('a#video-title, a[href*="/watch?v="]'))
              .map((anchor) => anchor.href || '')
              .filter(Boolean);
            """
        )
    except WebDriverException:
        return []
    return [str(href).strip() for href in hrefs if str(href).strip()]


def normalize_youtube_video_url(url: str) -> str:
    match = re.search(r"(?:https?://)?(?:www\.)?youtube\.com/watch\?[^#]*\bv=([A-Za-z0-9_-]{6,})", url or "")
    if match:
        return f"https://www.youtube.com/watch?v={match.group(1)}"
    short_match = re.search(r"(?:https?://)?youtu\.be/([A-Za-z0-9_-]{6,})", url or "")
    if short_match:
        return f"https://www.youtube.com/watch?v={short_match.group(1)}"
    return ""


if __name__ == "__main__":
    raise SystemExit(main())
