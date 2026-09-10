from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
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
from social_listening.text_utils import contains_keyword, normalize_text
from social_listening.instagram_comment_parser import extract_instagram_comments_from_body_text
from social_listening.crawl_state import IncrementalCrawlState
from social_listening.chromedriver_utils import resolve_chromedriver_path
from social_listening.crawl_freshness import (
    KeywordCrawlStats,
    classify_detail_freshness,
    extract_unix_create_time_from_html,
    load_freshness_policy,
    should_stop_keyword_details,
)


DEBUGGER_ADDRESS = os.getenv("INSTAGRAM_DEBUGGER_ADDRESS", "127.0.0.1:9224")
POST_URL = ""
INPUT_FILE = platform_raw_dir("instagram") / "instagram_search_results.json"
OUTPUT_FILE = platform_raw_dir("instagram") / "instagram_all_posts.json"
SCROLL_SECONDS_PER_POST = 8
POLICY = load_freshness_policy("instagram")
COMMENT_IDLE_ROUNDS_BEFORE_STOP = POLICY.comment_idle_rounds_before_stop
MAX_COMMENT_SCROLL_ROUNDS = POLICY.max_comment_scroll_rounds
MAX_COMMENTS = POLICY.max_comments
COMMENT_SCROLL_PAUSE_SECONDS = float(os.getenv("INSTAGRAM_COMMENT_SCROLL_PAUSE_SECONDS", "1.5"))
DETAIL_KEYWORD_RUNTIME_SECONDS = int(
    os.getenv("INSTAGRAM_DETAIL_KEYWORD_RUNTIME_SECONDS", str(POLICY.keyword_runtime_seconds))
)


def main() -> int:
    search_terms = collect_search_terms(load_keyword_payload())
    post_urls = load_post_urls(INPUT_FILE)
    if not post_urls and POST_URL.strip():
        post_urls = [{"keyword": "", "url": normalize_instagram_post_url(POST_URL.strip())}]

    post_urls = [item for item in post_urls if item.get("url")]
    if not post_urls:
        print("[instagram-detail] No Instagram post URLs found - nothing to crawl")
        print(f"[instagram-detail] This is normal for incremental runs with no new content")
        return 0

    records = load_existing_records(OUTPUT_FILE)
    existing_urls = collect_existing_post_urls(records)
    pending_urls = [item for item in post_urls if item["url"] not in existing_urls]

    print(f"[instagram-detail] Total URLs: {len(post_urls)}")
    print(f"[instagram-detail] Already crawled: {len(existing_urls)}")
    print(f"[instagram-detail] Pending: {len(pending_urls)}")

    if not pending_urls:
        print(f"no pending posts; {len(records)} records already saved in {OUTPUT_FILE.resolve()}")
        return 0

    with IncrementalCrawlState() as state:
        run_id = state.start_run("instagram_detail", "incremental")
        stale_by_keyword: dict[str, int] = {}
        started_by_keyword: dict[str, float] = {}
        stats_by_keyword: dict[str, KeywordCrawlStats] = {}

        driver = build_driver()
        try:
            total = len(pending_urls)
            crawled_count = 0
            stale_count = 0
            failed_count = 0

            print(
                f"[instagram-detail] Policy lookback={POLICY.lookback_days:.1f}d "
                f"max_comment_scroll={MAX_COMMENT_SCROLL_ROUNDS} max_comments={MAX_COMMENTS}"
            )

            for index, item in enumerate(pending_urls, start=1):
                url = item["url"]
                keyword = item["keyword"]
                kw_stats = stats_by_keyword.setdefault(keyword, KeywordCrawlStats(keyword=keyword or "(none)"))
                started_by_keyword.setdefault(keyword, time.monotonic())

                if should_stop_keyword_details(stale_by_keyword.get(keyword, 0), POLICY):
                    print(f"[instagram-detail] skip remaining for keyword={keyword}: max_stale_details")
                    continue
                if time.monotonic() - started_by_keyword[keyword] >= DETAIL_KEYWORD_RUNTIME_SECONDS:
                    print(f"[instagram-detail] skip remaining for keyword={keyword}: keyword_runtime_limit")
                    continue

                try:
                    record = crawl_post(driver, url, keyword, search_terms)
                except Exception as exc:
                    record = {
                        "keyword": keyword,
                        "url": url,
                        "matched": False,
                        "error": str(exc),
                        "freshness": "unknown",
                    }

                if record.get("error"):
                    failed_count += 1
                    kw_stats.detail_failed += 1
                    records.append(record)
                    save_records(OUTPUT_FILE, records)
                    print(f"[{index}/{total}] failed {url}")
                    continue

                content_timestamp = record.get("created_time") or record.get("timestamp") or record.get("taken_at_timestamp")
                freshness = record.get("freshness") or classify_detail_freshness(content_timestamp, POLICY)
                record["freshness"] = freshness

                state.mark_crawled(url, "instagram", keyword, content_timestamp)
                state.mark_crawled(url, "instagram_detail", keyword, content_timestamp)

                kw_stats.comments_found += int(record.get("comments_found") or 0)
                kw_stats.comments_crawled += int(record.get("comments_crawled") or 0)

                if freshness == "stale":
                    stale_count += 1
                    kw_stats.stale += 1
                    stale_by_keyword[keyword] = stale_by_keyword.get(keyword, 0) + 1
                    records.append(
                        {
                            "keyword": keyword,
                            "url": url,
                            "freshness": "stale",
                            "stale": True,
                            "coverage": False,
                            "created_time": content_timestamp,
                            "crawled_at": record.get("crawled_at"),
                            "crawled_comments": [],
                            "comments_crawled": 0,
                        }
                    )
                    save_records(OUTPUT_FILE, records)
                    print(f"[{index}/{total}] stale-skip {url} created_time={content_timestamp}")
                    continue

                crawled_count += 1
                kw_stats.detail_success += 1
                records.append(record)
                save_records(OUTPUT_FILE, records)
                print(
                    f"[{index}/{total}] saved {url} freshness={freshness} "
                    f"comments_crawled={record.get('comments_crawled', 0)}"
                )

            for kw, kw_stats in stats_by_keyword.items():
                kw_stats.runtime_seconds = time.monotonic() - started_by_keyword.get(kw, time.monotonic())
                kw_stats.log("instagram-detail")

            state.complete_run(
                run_id,
                urls_discovered=len(post_urls),
                urls_crawled=crawled_count,
                urls_skipped=len(existing_urls) + stale_count,
                keywords_processed=len(set(item.get("keyword", "") for item in post_urls)),
            )

            print(f"[instagram-detail] Summary:")
            print(f"  - Fresh coverage saved: {crawled_count}")
            print(f"  - Stale skipped: {stale_count}")
            print(f"  - Failed: {failed_count}")
            print(f"  - Total saved: {len(records)}")
            print(f"  - Output: {OUTPUT_FILE.resolve()}")
            return 0
        finally:
            driver.quit()


def load_post_urls(path: Path) -> list[dict]:
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
        url = normalize_instagram_post_url(str(item.get("url") or "").strip())
        if not url or url in seen:
            continue
        seen.add(url)
        urls.append({"keyword": str(item.get("keyword") or "").strip(), "url": url})
    return urls


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


def collect_existing_post_urls(records: list[dict]) -> set[str]:
    urls: set[str] = set()
    for item in records:
        if not isinstance(item, dict):
            continue
        for raw_url in (item.get("current_url"), item.get("url")):
            url = normalize_instagram_post_url(str(raw_url or "").strip())
            if url:
                urls.add(url)
    return urls


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
            normalized_url = normalize_instagram_post_url(str(raw_url or "").strip())
            if normalized_url:
                break
        if normalized_url:
            if normalized_url in seen_urls:
                continue
            seen_urls.add(normalized_url)
        deduped.append(item)
    return deduped


def crawl_post(driver: webdriver.Chrome, url: str, keyword: str, search_terms: list[str]) -> dict:
    driver.get(url)
    time.sleep(5)

    started_at = time.time()
    while time.time() - started_at < max(SCROLL_SECONDS_PER_POST, 3):
        click_expand_buttons(driver)
        driver.execute_script("window.scrollBy(0, window.innerHeight);")
        time.sleep(1.2)

    page_source = driver.page_source
    body_text = driver.execute_script("return document.body ? document.body.innerText : '';") or ""
    current_url = normalize_instagram_post_url(driver.current_url or url) or url
    page_title = driver.title or ""
    crawled_at = datetime.now(timezone.utc).isoformat()
    matched_terms = [term for term in search_terms if contains_keyword(normalize_text(body_text), term)]

    created_dt = extract_unix_create_time_from_html(page_source)
    created_time = created_dt.isoformat() if created_dt else ""
    freshness = classify_detail_freshness(created_time, POLICY)

    comments: list[dict] = []
    if freshness != "stale":
        comments = crawl_comments(driver, current_url, body_text)
        if MAX_COMMENTS > 0:
            comments = comments[:MAX_COMMENTS]

    return {
        "keyword": keyword,
        "url": url,
        "current_url": current_url,
        "title": page_title,
        "crawled_at": crawled_at,
        "created_time": created_time,
        "timestamp": created_time,
        "taken_at_timestamp": int(created_dt.timestamp()) if created_dt else None,
        "freshness": freshness,
        "coverage": freshness != "stale",
        "stale": freshness == "stale",
        "matched": bool(matched_terms),
        "matched_terms": matched_terms,
        "comment_count_observed": len(comments),
        "comments_found": len(comments),
        "comments_crawled": len(comments),
        "crawled_comments": comments,
        "body_text": body_text,
        "raw_html": page_source if freshness != "stale" else "",
    }


def build_driver() -> webdriver.Chrome:
    options = Options()
    options.debugger_address = DEBUGGER_ADDRESS
    driver_path = resolve_chromedriver_path()
    if driver_path:
        return webdriver.Chrome(service=Service(driver_path), options=options)
    return webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)


def click_expand_buttons(driver: webdriver.Chrome) -> None:
    try:
        buttons = driver.find_elements(By.TAG_NAME, "button")
    except Exception:
        return
    for button in buttons:
        try:
            text = (button.text or "").strip().casefold()
        except Exception:
            continue
        if text in {"more", "see more", "xem thêm", "view all comments", "view more comments"}:
            try:
                driver.execute_script("arguments[0].click();", button)
                time.sleep(0.3)
            except Exception:
                continue


def crawl_comments(driver: webdriver.Chrome, post_url: str, body_text: str) -> list[dict]:
    comments: dict[str, dict] = {}
    idle_rounds = 0
    for _ in range(MAX_COMMENT_SCROLL_ROUNDS):
        before_count = len(comments)
        click_expand_buttons(driver)
        for comment in extract_comments_from_dom(driver, post_url):
            external_id = str(comment.get("external_id") or "").strip()
            if external_id:
                comments.setdefault(external_id, comment)

        driver.execute_script("window.scrollBy(0, window.innerHeight * 0.8);")
        time.sleep(COMMENT_SCROLL_PAUSE_SECONDS)

        if len(comments) > before_count:
            idle_rounds = 0
        else:
            idle_rounds += 1
        if idle_rounds >= COMMENT_IDLE_ROUNDS_BEFORE_STOP:
            break
        if MAX_COMMENTS > 0 and len(comments) >= MAX_COMMENTS:
            break
    if comments:
        values = list(comments.values())
        if MAX_COMMENTS > 0:
            return values[:MAX_COMMENTS]
        return values
    return extract_instagram_comments_from_body_text(body_text, post_url)


def extract_comments_from_dom(driver: webdriver.Chrome, post_url: str) -> list[dict]:
    raw_comments = driver.execute_script(
        """
        const nodes = Array.from(document.querySelectorAll('ul ul, article ul ul, [role="dialog"] ul ul'));
        const results = [];
        for (const node of nodes) {
            const text = (node.innerText || '').trim();
            if (!text) continue;
            const lines = text
                .split('\\n')
                .map((line) => line.trim())
                .filter(Boolean);
            if (lines.length < 2) continue;

            const author = lines[0];
            const createdAtLabel = lines.find((line) => /ago|trước|d|h|m|w/i.test(line)) || '';
            const textLines = lines.filter((line) => line !== author && line !== createdAtLabel);
            const commentText = textLines.join(' ').trim();
            if (!commentText) continue;

            const commentLink = node.querySelector('a[href*="/p/"], a[href*="/reel/"]');
            const href = commentLink ? commentLink.getAttribute('href') || '' : '';
            const rawId = node.getAttribute('data-id') || node.id || `${author}|${commentText.slice(0, 80)}`;
            results.push({
                external_id: `comment:${rawId}`,
                record_type: 'comment',
                author,
                text: commentText,
                created_at: '',
                created_at_label: createdAtLabel,
                parent_comment_id: '',
                keyword_match: false,
                url: href,
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
        comment_url = normalize_comment_url(post_url, str(item.get("url") or ""), external_id)
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


def normalize_comment_url(post_url: str, href: str, external_id: str) -> str:
    if href.startswith("http"):
        return href
    if href.startswith("/"):
        return f"https://www.instagram.com{href}"
    comment_id = external_id.removeprefix("comment:")
    if not comment_id:
        return post_url
    return f"{post_url}#comment-{comment_id}"


def normalize_instagram_post_url(url: str) -> str:
    if not url:
        return ""
    match = re.search(r"https://www\.instagram\.com/(?:p|reel|reels)/([^/?#]+)/?", url)
    if not match:
        return ""
    kind = "reel" if "/reel/" in url or "/reels/" in url else "p"
    return f"https://www.instagram.com/{kind}/{match.group(1)}/"


if __name__ == "__main__":
    raise SystemExit(main())
