from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

from selenium import webdriver
from selenium.common.exceptions import SessionNotCreatedException
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
from social_listening.crawl_state import IncrementalCrawlState
from social_listening.chromedriver_utils import resolve_chromedriver_path


DEBUGGER_ADDRESS = os.getenv("THREADS_DEBUGGER_ADDRESS", "127.0.0.1:9222")
THREAD_URL = os.getenv("THREADS_URL", "")
THREADS_INPUT_FILE = os.getenv("THREADS_INPUT_FILE", "").strip()
THREADS_USE_FILTERED_INPUT = os.getenv("THREADS_USE_FILTERED_INPUT", "1").strip().lower() in {"1", "true", "yes", "on"}
FILTERED_INPUT_FILE = platform_raw_dir("threads") / "threads_search_results_filtered.json"
INPUT_FILE = platform_raw_dir("threads") / "threads_search_results.json"
LEGACY_FILTERED_INPUT_FILE = DATA_DIR / "threads" / "raw" / "threads_search_results_filtered.json"
LEGACY_INPUT_FILE = DATA_DIR / "threads" / "raw" / "threads_search_results.json"
MAX_SCROLL_ROUNDS_PER_THREAD = int(os.getenv("THREADS_REPLY_SCROLL_ROUNDS", "12"))
SCROLL_PAUSE_SECONDS = float(os.getenv("THREADS_REPLY_SCROLL_PAUSE_SECONDS", "1.5"))
IDLE_ROUNDS_BEFORE_STOP = int(os.getenv("THREADS_REPLY_IDLE_ROUNDS", "3"))
OUTPUT_FILE = platform_raw_dir("threads") / "threads_all_threads.json"


def main() -> int:
    search_terms = collect_search_terms(load_keyword_payload())
    input_file = resolve_input_file()
    thread_urls = load_thread_urls(input_file)
    if not thread_urls and THREAD_URL.strip():
        normalized_url = normalize_thread_url(THREAD_URL.strip())
        if normalized_url:
            thread_urls = [{"keyword": "", "keywords": [], "url": normalized_url}]

    if not thread_urls:
        print("[threads-detail] No thread URLs found - nothing to crawl")
        print(f"[threads-detail] This is normal for incremental runs with no new content")
        return 0

    print(f"using thread input file: {input_file}")

    # Initialize crawl state for detail crawling
    with IncrementalCrawlState() as state:
        run_id = state.start_run("threads_detail", "incremental")

        driver = build_driver()
        try:
            ensure_dir(OUTPUT_FILE.parent)
            records = load_existing_records(OUTPUT_FILE)
            processed_urls = {normalize_thread_url(str(item.get("url") or "").strip()) for item in records if isinstance(item, dict)}

            print(f"[threads-detail] Total URLs to process: {len(thread_urls)}")
            print(f"[threads-detail] Already processed: {len(processed_urls)}")

            crawled_count = 0
            skipped_count = 0
            total = len(thread_urls)

            for index, item in enumerate(thread_urls, start=1):
                url = item["url"]
                search_keyword = item["keyword"]
                search_keywords = item.get("keywords") or ([search_keyword] if search_keyword else [])

                if url in processed_urls:
                    print(f"[{index}/{total}] skip already processed {url}")
                    skipped_count += 1
                    continue

                try:
                    record = crawl_thread(driver, url, search_keyword, search_keywords, search_terms)
                    crawled_count += 1

                    # Extract timestamp if available
                    content_timestamp = record.get("timestamp") or record.get("created_time")

                    # Mark as crawled in state
                    state.mark_crawled(
                        url,
                        "threads_detail",
                        search_keyword,
                        content_timestamp
                    )

                except Exception as exc:
                    record = {
                        "keyword": search_keyword,
                        "keywords": search_keywords,
                        "url": url,
                        "matched": False,
                        "error": str(exc),
                    }

                records.append(record)
                processed_urls.add(url)
                save_records(records, OUTPUT_FILE)
                print(f"[{index}/{total}] {url}")

            # Complete run tracking
            state.complete_run(
                run_id,
                urls_discovered=total,
                urls_crawled=crawled_count,
                urls_skipped=skipped_count,
                keywords_processed=len(set(item.get("keyword", "") for item in thread_urls))
            )

            print(f"[threads-detail] Summary:")
            print(f"  - URLs crawled: {crawled_count}")
            print(f"  - URLs skipped: {skipped_count}")
            print(f"  - Total saved: {len(records)}")
            print(f"  - Output: {OUTPUT_FILE.resolve()}")
            return 0
        finally:
            driver.quit()


def resolve_input_file() -> Path:
    if THREADS_INPUT_FILE:
        return Path(THREADS_INPUT_FILE)

    candidates = (
        (FILTERED_INPUT_FILE, INPUT_FILE, LEGACY_FILTERED_INPUT_FILE, LEGACY_INPUT_FILE)
        if THREADS_USE_FILTERED_INPUT
        else (INPUT_FILE, FILTERED_INPUT_FILE, LEGACY_INPUT_FILE, LEGACY_FILTERED_INPUT_FILE)
    )
    for path in candidates:
        if path.exists():
            return path
    return FILTERED_INPUT_FILE


def load_thread_urls(path: Path) -> list[dict]:
    if not path.exists():
        return []

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []

    if not isinstance(payload, list):
        return []

    merged: dict[str, dict] = {}
    for item in payload:
        if not isinstance(item, dict):
            continue
        url = normalize_thread_url(str(item.get("url") or "").strip())
        if not url:
            continue
        keyword = str(item.get("keyword") or item.get("search_keyword") or "").strip()
        current = merged.setdefault(
            url,
            {
                "keyword": keyword,
                "keywords": [],
                "url": url,
            },
        )
        if keyword and keyword not in current["keywords"]:
            current["keywords"].append(keyword)
        if not current["keyword"] and keyword:
            current["keyword"] = keyword
    return list(merged.values())


def load_existing_records(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return payload if isinstance(payload, list) else []


def save_records(records: list[dict], path: Path) -> None:
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def crawl_thread(
    driver: webdriver.Chrome,
    url: str,
    search_keyword: str,
    search_keywords: list[str],
    search_terms: list[str],
) -> dict:
    driver.get(url)
    time.sleep(4)

    last_height = 0
    idle_rounds = 0
    for _ in range(MAX_SCROLL_ROUNDS_PER_THREAD):
        expand_reply_buttons(driver)
        driver.execute_script("window.scrollBy(0, window.innerHeight);")
        time.sleep(SCROLL_PAUSE_SECONDS)
        current_height = int(driver.execute_script("return document.body ? document.body.scrollHeight : 0;") or 0)
        if current_height <= last_height:
            idle_rounds += 1
            if idle_rounds >= IDLE_ROUNDS_BEFORE_STOP:
                break
        else:
            idle_rounds = 0
            last_height = current_height

    articles = driver.find_elements(By.TAG_NAME, "article")
    article_payloads: list[dict] = []
    matched_on = set()

    for index, article in enumerate(articles):
        text = normalize_text(article.text)
        if not text:
            continue
        matched_terms = find_matches(text, search_terms)
        payload = {
            "index": index,
            "text": article.text,
            "html": article.get_attribute("outerHTML"),
            "matched_terms": matched_terms,
        }
        if matched_terms:
            matched_on.add("post" if index == 0 else "reply")
        article_payloads.append(payload)

    page_source = driver.page_source
    body_text = driver.execute_script("return document.body ? document.body.innerText : '';") or ""
    page_title = driver.title or ""
    current_url = driver.current_url or url
    page_matches = find_matches(normalize_text(body_text), search_terms)
    if page_matches:
        matched_on.add("page")
    canonical_urls = sorted(set(re.findall(r"https://www\.threads\.(?:net|com)/@[^\"'< ]+/post/[^\"'< ?#]+", page_source)))

    return {
        "keyword": search_keyword,
        "keywords": search_keywords,
        "url": url,
        "current_url": current_url,
        "title": page_title,
        "matched": bool(matched_on),
        "matched_on": sorted(matched_on),
        "matched_terms": page_matches,
        "body_text": body_text,
        "articles": article_payloads,
        "linked_threads": canonical_urls,
        "raw_html": page_source,
    }


def find_matches(text: str, search_terms: list[str]) -> list[str]:
    return [term for term in search_terms if contains_keyword(text, term)]


def expand_reply_buttons(driver: webdriver.Chrome) -> None:
    xpaths = (
        "//div[@role='button'][.//span[contains(normalize-space(), 'View replies')]]",
        "//div[@role='button'][.//span[contains(normalize-space(), 'View more replies')]]",
        "//div[@role='button'][.//span[contains(normalize-space(), 'View all replies')]]",
        "//div[@role='button'][.//span[contains(normalize-space(), 'Xem câu trả lời')]]",
        "//div[@role='button'][.//span[contains(normalize-space(), 'Xem thêm câu trả lời')]]",
        "//div[@role='button'][.//span[contains(normalize-space(), 'Xem tất cả câu trả lời')]]",
    )
    for xpath in xpaths:
        try:
            elements = driver.find_elements(By.XPATH, xpath)
        except Exception:
            continue
        for element in elements[:8]:
            try:
                if not element.is_displayed():
                    continue
                driver.execute_script("arguments[0].click();", element)
                time.sleep(0.4)
            except Exception:
                continue


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


def normalize_thread_url(url: str) -> str:
    match = re.search(r"https://www\.threads\.(?:net|com)/@[^/]+/post/[^/?#]+", url or "")
    return match.group(0) if match else ""


if __name__ == "__main__":
    raise SystemExit(main())
