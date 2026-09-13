from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.common.by import By

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
from social_listening.text_utils import contains_keyword, normalize_text
from social_listening.crawl_state import IncrementalCrawlState
from social_listening.chromedriver_utils import chrome_debugger_ready, leave_chrome_open
from social_listening.crawl_reliability import (
    assert_social_session,
    attach_debugger_chrome,
    recover_stuck_debug_chrome,
)
from social_listening.crawl_freshness import (
    attach_freshness_fields,
    content_time_sort_key,
    extract_unix_create_time_from_html,
    load_freshness_policy,
    should_spend_on_comments,
)

DEBUGGER_ADDRESS = os.getenv("YOUTUBE_DEBUGGER_ADDRESS", "127.0.0.1:9225")
VIDEO_URL = ""
FILTERED_INPUT_FILE = platform_raw_dir("youtube") / "youtube_search_results_filtered.json"
INPUT_FILE = platform_raw_dir("youtube") / "youtube_search_results.json"
LEGACY_FILTERED_INPUT_FILE = DATA_DIR / "youtube" / "raw" / "youtube_search_results_filtered.json"
LEGACY_INPUT_FILE = DATA_DIR / "youtube" / "raw" / "youtube_search_results.json"
OUTPUT_FILE = platform_raw_dir("youtube") / "youtube_all_videos.json"
SCROLL_SECONDS_PER_VIDEO = 8
POLICY = load_freshness_policy("youtube")
DISCOVERY_LIMIT = POLICY.discovery_limit
FINAL_LIMIT = POLICY.final_limit
COMMENT_IDLE_ROUNDS_BEFORE_STOP = POLICY.comment_idle_rounds_before_stop
MAX_COMMENT_SCROLL_ROUNDS = POLICY.max_comment_scroll_rounds
COMMENT_SCROLL_PAUSE_SECONDS = 1.5
MAX_COMMENTS = POLICY.max_comments
DETAIL_KEYWORD_RUNTIME_SECONDS = int(
    os.getenv("YOUTUBE_DETAIL_KEYWORD_RUNTIME_SECONDS", str(POLICY.keyword_runtime_seconds))
    or str(POLICY.keyword_runtime_seconds)
)
DETAIL_MAX_URLS = int(os.getenv("YOUTUBE_DETAIL_MAX_URLS", str(max(FINAL_LIMIT, 80))) or "80")
DETAIL_MAX_RUNTIME_SECONDS = int(
    os.getenv("YOUTUBE_DETAIL_MAX_RUNTIME_SECONDS", "1500") or "1500"
)


def main() -> int:
    search_terms = collect_search_terms(load_keyword_payload())
    input_file = resolve_input_file()
    video_urls = load_video_urls(input_file)
    if not video_urls and VIDEO_URL.strip():
        video_urls = [{"keyword": "", "url": normalize_youtube_video_url(VIDEO_URL.strip())}]

    video_urls = [item for item in video_urls if item.get("url")]
    if not video_urls:
        print("[youtube-detail] No YouTube video URLs found - nothing to crawl")
        print(f"[youtube-detail] This is normal for incremental runs with no new content")
        return 0

    print(f"using youtube input file: {input_file}")

    records = load_existing_records(OUTPUT_FILE)
    existing_urls = collect_completed_video_urls(records)
    pending_urls = select_pending_urls(video_urls, existing_urls, DETAIL_MAX_URLS)
    if not pending_urls:
        print(f"no pending videos; {len(records)} records already saved in {OUTPUT_FILE.resolve()}")
        return 0

    with IncrementalCrawlState() as state:
        run_id = state.start_run("youtube_detail", "incremental")
        urls_crawled = 0
        urls_skipped = len(existing_urls)
        run_started = time.monotonic()
        stopped_for_runtime = False
        started_by_keyword: dict[str, float] = {}
        detailed_urls: set[str] = set()

        print(f"[youtube-detail] URLs to crawl this round: {len(pending_urls)} (cap={DETAIL_MAX_URLS})")
        print(f"[youtube-detail] URLs skipped (already done): {urls_skipped}")
        print(
            f"[youtube-detail] Runtime budget={DETAIL_MAX_RUNTIME_SECONDS}s "
            f"keyword_runtime={DETAIL_KEYWORD_RUNTIME_SECONDS}s"
        )
        print(
            f"[youtube-detail] Policy discovery={DISCOVERY_LIMIT} final={FINAL_LIMIT} "
            f"lookback={POLICY.lookback_days:.1f}d"
        )

        driver = build_driver()
        try:
            keyword_batches: dict[str, list[dict]] = {}
            total = len(pending_urls)
            for index, item in enumerate(pending_urls, start=1):
                if time.monotonic() - run_started >= DETAIL_MAX_RUNTIME_SECONDS:
                    print(
                        f"[youtube-detail] stop early: detail_runtime_limit "
                        f"({DETAIL_MAX_RUNTIME_SECONDS}s) at {index - 1}/{total}",
                        flush=True,
                    )
                    stopped_for_runtime = True
                    break

                url = item["url"]
                keyword = item["keyword"]
                started_by_keyword.setdefault(keyword, time.monotonic())
                if time.monotonic() - started_by_keyword[keyword] >= DETAIL_KEYWORD_RUNTIME_SECONDS:
                    print(f"[youtube-detail] skip remaining for keyword={keyword}: keyword_runtime_limit")
                    continue

                try:
                    record = crawl_video(driver, url, keyword, search_terms)
                    content_timestamp = record.get("published_at") or record.get("created_time")
                    if content_timestamp:
                        state.mark_crawled(url, "youtube", keyword, content_timestamp)
                        state.mark_crawled(url, "youtube_detail", keyword, content_timestamp)
                    else:
                        print(
                            f"[youtube-detail] no published_at for {url} — not marking crawled",
                            flush=True,
                        )
                except Exception as exc:
                    record = {
                        "keyword": keyword,
                        "url": url,
                        "matched": False,
                        "error": str(exc),
                        "freshness": "unknown",
                    }
                keyword_batches.setdefault(keyword, []).append(record)
                detailed_urls.add(url)
                print(f"[{index}/{total}] detailed {url}")

            for keyword, batch in keyword_batches.items():
                ranked = sorted(batch, key=content_time_sort_key, reverse=True)
                for rank, record in enumerate(ranked, start=1):
                    in_final = rank <= FINAL_LIMIT
                    attach_freshness_fields(
                        record,
                        record.get("published_at") or record.get("created_time"),
                        POLICY,
                        newest_rank=rank,
                        in_final_limit=in_final,
                    )
                    if not in_final and record.get("crawled_comments"):
                        record["crawled_comments"] = []
                        record["comment_count_observed"] = 0
                        record["coverage"] = False
                    if in_final and not record.get("error") and record.get("freshness") != "stale":
                        urls_crawled += 1
                    records = merge_record(records, record)
                save_records(OUTPUT_FILE, records)

            mark_search_results_detailed(input_file, detailed_urls)

            state.complete_run(
                run_id,
                urls_discovered=len(video_urls),
                urls_crawled=urls_crawled,
                urls_skipped=urls_skipped,
                keywords_processed=len(set(item["keyword"] for item in video_urls))
            )

            print(f"saved {len(records)} total youtube payloads to {OUTPUT_FILE.resolve()}")
            if stopped_for_runtime:
                print(
                    "[youtube-detail] Partial round OK (self-stopped before pipeline kill)",
                    flush=True,
                )
            return 0
        finally:
            leave_chrome_open(driver)


def resolve_input_file() -> Path:
    for path in (FILTERED_INPUT_FILE, INPUT_FILE, LEGACY_FILTERED_INPUT_FILE, LEGACY_INPUT_FILE):
        if path.exists():
            return path
    return FILTERED_INPUT_FILE


def load_video_urls(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(payload, list):
        return []

    urls: list[dict] = []
    seen: set[str] = set()
    for item in payload:
        if not isinstance(item, dict):
            continue
        url = normalize_youtube_video_url(str(item.get("url") or "").strip())
        if not url or url in seen:
            continue
        if item.get("pending_detail") is False:
            continue
        seen.add(url)
        urls.append(
            {
                "keyword": str(item.get("keyword") or "").strip(),
                "url": url,
                "pending_detail": bool(item.get("pending_detail", True)),
            }
        )
    return urls


def select_pending_urls(
    video_urls: list[dict],
    completed_urls: set[str],
    limit: int,
) -> list[dict]:
    pending = [item for item in video_urls if item["url"] not in completed_urls]
    if limit <= 0 or len(pending) <= limit:
        return pending
    flagged = [i for i in pending if i.get("pending_detail", True)]
    pool = flagged or pending
    return list(reversed(pool))[:limit]


def mark_search_results_detailed(path: Path, done_urls: set[str]) -> None:
    if not done_urls or not path.exists():
        return
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return
    if not isinstance(payload, list):
        return
    changed = False
    for item in payload:
        if not isinstance(item, dict):
            continue
        url = normalize_youtube_video_url(str(item.get("url") or ""))
        if url and url in done_urls and item.get("pending_detail", True):
            item["pending_detail"] = False
            changed = True
    if changed:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_existing_records(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def collect_completed_video_urls(records: list[dict]) -> set[str]:
    urls: set[str] = set()
    for item in records:
        if not isinstance(item, dict):
            continue
        if should_retry_record(item):
            continue
        for raw_url in (item.get("current_url"), item.get("url")):
            url = normalize_youtube_video_url(str(raw_url or "").strip())
            if url:
                urls.add(url)
    return urls


def should_retry_record(item: dict) -> bool:
    if not isinstance(item, dict):
        return True
    if item.get("stale") or item.get("freshness") == "stale" or item.get("coverage") is False:
        return False
    if not (item.get("created_time") or item.get("published_at")):
        return True
    if item.get("error"):
        return True
    return False


def merge_record(records: list[dict], new_record: dict) -> list[dict]:
    normalized_target = ""
    for raw_url in (new_record.get("current_url"), new_record.get("url")):
        normalized_target = normalize_youtube_video_url(str(raw_url or "").strip())
        if normalized_target:
            break

    if not normalized_target:
        return [*records, new_record]

    merged: list[dict] = []
    replaced = False
    for item in records:
        if not isinstance(item, dict):
            merged.append(item)
            continue
        normalized_existing = ""
        for raw_url in (item.get("current_url"), item.get("url")):
            normalized_existing = normalize_youtube_video_url(str(raw_url or "").strip())
            if normalized_existing:
                break
        if normalized_existing == normalized_target:
            if not replaced:
                merged.append(new_record)
                replaced = True
            continue
        merged.append(item)

    if not replaced:
        merged.append(new_record)
    return merged


def collect_existing_video_urls(records: list[dict]) -> set[str]:
    return collect_completed_video_urls(records)


def save_records(path: Path, records: list[dict]) -> None:
    deduped_records = dedupe_records(records)
    ensure_dir(path.parent)
    path.write_text(json.dumps(deduped_records, ensure_ascii=False, indent=2), encoding="utf-8")


def dedupe_records(records: list[dict]) -> list[dict]:
    deduped: list[dict] = []
    seen_urls: set[str] = set()
    for item in records:
        if not isinstance(item, dict):
            continue
        normalized_url = ""
        for raw_url in (item.get("current_url"), item.get("url")):
            normalized_url = normalize_youtube_video_url(str(raw_url or "").strip())
            if normalized_url:
                break
        if normalized_url:
            if normalized_url in seen_urls:
                continue
            seen_urls.add(normalized_url)
        deduped.append(item)
    return deduped


def crawl_video(driver: webdriver.Chrome, url: str, keyword: str, search_terms: list[str]) -> dict:
    driver.get(url)
    time.sleep(4)
    expand_video_page(driver)

    page_source = driver.page_source
    body_text = driver.execute_script("return document.body ? document.body.innerText : '';") or ""
    page_title = driver.title or ""
    current_url = normalize_youtube_video_url(driver.current_url or url) or url
    crawled_at = datetime.now(timezone.utc).isoformat()
    matched_terms = [term for term in search_terms if contains_keyword(normalize_text(body_text), term)]

    published_dt = extract_unix_create_time_from_html(page_source)
    published_at = published_dt.isoformat() if published_dt else ""
    freshness = "unknown"
    from social_listening.crawl_freshness import classify_detail_freshness

    freshness = classify_detail_freshness(published_at, POLICY)

    comments: list[dict] = []
    if should_spend_on_comments(freshness):
        deadline = time.time() + max(SCROLL_SECONDS_PER_VIDEO, 3)
        while time.time() < deadline:
            driver.execute_script("window.scrollBy(0, window.innerHeight);")
            time.sleep(1.2)
        comments = crawl_comments(driver, url)
        if MAX_COMMENTS > 0:
            comments = comments[:MAX_COMMENTS]

    record = {
        "keyword": keyword,
        "url": url,
        "current_url": current_url,
        "title": page_title,
        "crawled_at": crawled_at,
        "published_at": published_at,
        "created_time": published_at,
        "matched": bool(matched_terms),
        "matched_terms": matched_terms,
        "comment_count_observed": len(comments),
        "crawled_comments": comments,
        "body_text": body_text,
        "raw_html": page_source if should_spend_on_comments(freshness) else "",
    }
    attach_freshness_fields(record, published_at, POLICY)
    return record


def build_driver() -> webdriver.Chrome:
    print(f"[youtube-detail] attaching Chrome at {DEBUGGER_ADDRESS}…", flush=True)
    if not chrome_debugger_ready(DEBUGGER_ADDRESS, timeout=3.0):
        raise RuntimeError(
            f"Chrome debug not ready at {DEBUGGER_ADDRESS}. "
            "Start YouTube debug Chrome (port 9225) then retry."
        )
    # Proactive unstick — search often left DevTools wedged before detail starts.
    recover_stuck_debug_chrome(DEBUGGER_ADDRESS)
    driver = attach_debugger_chrome(DEBUGGER_ADDRESS)
    assert_social_session(driver, "youtube")
    return driver


def expand_video_page(driver: webdriver.Chrome) -> None:
    for selector in (
        "tp-yt-paper-button#expand",
        "button[aria-label*='thêm']",
        "button[aria-label*='more']",
    ):
        try:
            button = driver.find_element(By.CSS_SELECTOR, selector)
            if button.is_displayed():
                driver.execute_script("arguments[0].click();", button)
                time.sleep(0.5)
                break
        except Exception:
            continue


def crawl_comments(driver: webdriver.Chrome, video_url: str) -> list[dict]:
    load_comments_section(driver)

    comments: dict[str, dict] = {}
    idle_rounds = 0
    for _ in range(MAX_COMMENT_SCROLL_ROUNDS):
        before_count = len(comments)
        for comment in extract_comments_from_dom(driver, video_url):
            external_id = str(comment.get("external_id") or "").strip()
            if external_id:
                comments.setdefault(external_id, comment)

        driver.execute_script("window.scrollBy(0, window.innerHeight * 1.2);")
        time.sleep(COMMENT_SCROLL_PAUSE_SECONDS)

        if len(comments) > before_count:
            idle_rounds = 0
        else:
            idle_rounds += 1
        if idle_rounds >= COMMENT_IDLE_ROUNDS_BEFORE_STOP:
            break

    return list(comments.values())


def load_comments_section(driver: webdriver.Chrome) -> None:
    for _ in range(8):
        if driver.find_elements(By.CSS_SELECTOR, "ytd-comment-thread-renderer"):
            return
        driver.execute_script("window.scrollBy(0, window.innerHeight * 1.5);")
        time.sleep(1.2)


def extract_comments_from_dom(driver: webdriver.Chrome, video_url: str) -> list[dict]:
    raw_comments = driver.execute_script(
        """
        const nodes = Array.from(document.querySelectorAll('ytd-comment-thread-renderer'));
        const results = [];
        for (const node of nodes) {
            const rect = node.getBoundingClientRect();
            if (rect.width === 0 || rect.height === 0) continue;

            const authorNode = node.querySelector('#author-text span, #author-text');
            const textNode = node.querySelector('#content-text');
            const timeNode = node.querySelector('a[href*="lc="], .published-time-text a, #header-author a');
            const rawAuthor = (authorNode?.innerText || '').replace(/\\s+/g, ' ').trim();
            const rawText = (textNode?.innerText || '').replace(/\\s+/g, ' ').trim();
            const rawTime = (timeNode?.innerText || '').replace(/\\s+/g, ' ').trim();
            if (!rawText) continue;

            const href = timeNode?.getAttribute('href') || '';
            const commentIdMatch =
                href.match(/[?&]lc=([^&#]+)/) ||
                (node.id ? [null, node.id] : null) ||
                rawText.match(/^(.{1,80})$/);
            const commentId = commentIdMatch ? commentIdMatch[1] : `${rawAuthor}|${rawText.slice(0, 60)}`;

            results.push({
                external_id: `comment:${commentId}`,
                record_type: 'comment',
                author: rawAuthor,
                text: rawText,
                created_at: '',
                created_at_label: rawTime,
                parent_comment_id: '',
                keyword_match: false,
                url: href || '',
                source: 'dom',
            });
        }
        return results;
        """
    )
    comments: list[dict] = []
    if not isinstance(raw_comments, list):
        return comments

    for item in raw_comments:
        if not isinstance(item, dict):
            continue
        external_id = str(item.get("external_id") or "").strip()
        if not external_id:
            continue
        comment_url = normalize_comment_url(video_url, str(item.get("url") or ""), external_id)
        comments.append(
            {
                "external_id": external_id,
                "record_type": str(item.get("record_type") or "comment"),
                "author": str(item.get("author") or "").strip(),
                "text": str(item.get("text") or "").strip(),
                "created_at": "",
                "created_at_label": str(item.get("created_at_label") or "").strip(),
                "parent_comment_id": str(item.get("parent_comment_id") or "").strip(),
                "keyword_match": bool(item.get("keyword_match")),
                "url": comment_url,
                "source": str(item.get("source") or "dom"),
            }
        )
    return comments


def normalize_comment_url(video_url: str, href: str, external_id: str) -> str:
    if href.startswith("http"):
        return href
    if href.startswith("/watch"):
        return f"https://www.youtube.com{href}"
    comment_id = external_id.removeprefix("comment:")
    if not comment_id:
        return video_url
    separator = "&" if "?" in video_url else "?"
    return f"{video_url}{separator}lc={comment_id}"


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
