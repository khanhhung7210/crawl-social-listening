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

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from social_listening.keyword_config import collect_search_terms, load_keyword_payload
from social_listening.film_paths import platform_raw_dir
from social_listening.paths import DATA_DIR, ensure_dir
from social_listening.text_utils import contains_keyword, normalize_text


DEBUGGER_ADDRESS = os.getenv("THREADS_DEBUGGER_ADDRESS", "127.0.0.1:9222")
THREAD_URL = "https://www.threads.com/@lottecinema_vietnam/post/DVj9I9wkoDh"
FILTERED_INPUT_FILE = platform_raw_dir("threads") / "threads_search_results_filtered.json"
INPUT_FILE = platform_raw_dir("threads") / "threads_search_results.json"
LEGACY_FILTERED_INPUT_FILE = DATA_DIR / "threads" / "raw" / "threads_search_results_filtered.json"
LEGACY_INPUT_FILE = DATA_DIR / "threads" / "raw" / "threads_search_results.json"
SCROLL_SECONDS_PER_THREAD = 4
OUTPUT_FILE = platform_raw_dir("threads") / "threads_all_threads.json"


def main() -> int:
    search_terms = collect_search_terms(load_keyword_payload())
    input_file = resolve_input_file()
    thread_urls = load_thread_urls(input_file)
    if not thread_urls and THREAD_URL.strip():
        thread_urls = [{"keyword": "", "url": THREAD_URL.strip()}]

    if not thread_urls:
        raise RuntimeError("No thread URLs found.")

    print(f"using thread input file: {input_file}")

    driver = build_driver()
    try:
        ensure_dir(OUTPUT_FILE.parent)
        records = load_existing_records(OUTPUT_FILE)
        processed_urls = {normalize_thread_url(str(item.get("url") or "").strip()) for item in records if isinstance(item, dict)}
        total = len(thread_urls)
        for index, item in enumerate(thread_urls, start=1):
            url = item["url"]
            search_keyword = item["keyword"]
            if url in processed_urls:
                print(f"[{index}/{total}] skip already processed {url}")
                continue
            try:
                record = crawl_thread(driver, url, search_keyword, search_terms)
            except Exception as exc:
                record = {
                    "keyword": search_keyword,
                    "url": url,
                    "matched": False,
                    "error": str(exc),
                }
            records.append(record)
            processed_urls.add(url)
            save_records(records, OUTPUT_FILE)
            print(f"[{index}/{total}] {url}")

        print(f"saved {len(records)} thread payloads to {OUTPUT_FILE.resolve()}")
        return 0
    finally:
        driver.quit()


def resolve_input_file() -> Path:
    for path in (FILTERED_INPUT_FILE, INPUT_FILE, LEGACY_FILTERED_INPUT_FILE, LEGACY_INPUT_FILE):
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

    urls: list[dict] = []
    seen: set[str] = set()
    for item in payload:
        if not isinstance(item, dict):
            continue
        url = normalize_thread_url(str(item.get("url") or "").strip())
        if not url or url in seen:
            continue
        seen.add(url)
        urls.append(
            {
                "keyword": str(item.get("keyword") or "").strip(),
                "url": url,
            }
        )
    return urls


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


def crawl_thread(driver: webdriver.Chrome, url: str, search_keyword: str, search_terms: list[str]) -> dict:
    driver.get(url)
    time.sleep(4)

    deadline = time.time() + max(SCROLL_SECONDS_PER_THREAD, 3)
    while time.time() < deadline:
        driver.execute_script("window.scrollBy(0, window.innerHeight);")
        time.sleep(1.5)

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


def normalize_thread_url(url: str) -> str:
    match = re.search(r"https://www\.threads\.(?:net|com)/@[^/]+/post/[^/?#]+", url or "")
    return match.group(0) if match else ""


if __name__ == "__main__":
    raise SystemExit(main())
