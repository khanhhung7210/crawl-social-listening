from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

from pymongo import UpdateOne
from selenium import webdriver
from selenium.common.exceptions import SessionNotCreatedException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from social_listening.film_paths import platform_processed_dir, platform_raw_dir
from social_listening.keyword_config import collect_search_terms, film_title, load_keyword_payload
from social_listening.mongodb_sync import build_mongo_client, build_mongo_document, describe_mongo_target
from social_listening.paths import DATA_DIR, ensure_dir
from social_listening.text_utils import contains_keyword, normalize_text


DEBUGGER_ADDRESS = os.getenv("THREADS_DEBUGGER_ADDRESS", "127.0.0.1:9222")
THREAD_URL = os.getenv("THREADS_URL", "").strip()
THREADS_INPUT_FILE = os.getenv("THREADS_INPUT_FILE", "").strip()
THREADS_USE_FILTERED_INPUT = os.getenv("THREADS_USE_FILTERED_INPUT", "0").strip().lower() in {"1", "true", "yes", "on"}
FILTERED_INPUT_FILE = platform_raw_dir("threads") / "threads_search_results_filtered.json"
INPUT_FILE = platform_raw_dir("threads") / "threads_search_results.json"
LEGACY_FILTERED_INPUT_FILE = DATA_DIR / "threads" / "raw" / "threads_search_results_filtered.json"
LEGACY_INPUT_FILE = DATA_DIR / "threads" / "raw" / "threads_search_results.json"
RAW_OUTPUT_FILE = platform_raw_dir("threads") / "threads_all_threads.json"
PARSED_OUTPUT_FILE = platform_processed_dir("threads") / "threads_grouped_parsed.json"
STATE_FILE = platform_raw_dir("threads") / "threads_sequential_sync_state.json"
SOURCE_NAME = "threads_sequential_sync"
MAX_SCROLL_ROUNDS_PER_THREAD = int(os.getenv("THREADS_REPLY_SCROLL_ROUNDS", "12"))
SCROLL_PAUSE_SECONDS = float(os.getenv("THREADS_REPLY_SCROLL_PAUSE_SECONDS", "1.5"))
IDLE_ROUNDS_BEFORE_STOP = int(os.getenv("THREADS_REPLY_IDLE_ROUNDS", "3"))

NOISE_LINES = {
    "Thread",
    "Translate",
    "Top",
    "Hàng đầu",
    "View activity",
    "Xem hoạt động",
    "Pinned",
    "Tác giả",
    "Author",
    "·",
}
TOP_MARKERS = {"Top", "Hàng đầu"}
ACTIVITY_MARKERS = {"View activity", "Xem hoạt động"}


def main() -> int:
    keyword_payload = load_keyword_payload()
    search_terms = collect_search_terms(keyword_payload)
    active_film_title = os.getenv("FILM_TITLE", film_title())
    db_name = os.getenv("MONGO_DB", "CRM")
    collection_name = os.getenv("MONGO_COLLECTION", "social")
    mongo_target = describe_mongo_target()
    mongo_target["collection"] = collection_name

    input_file = resolve_input_file()
    thread_urls = load_thread_urls(input_file)
    if not thread_urls and THREAD_URL:
        normalized_url = normalize_thread_url(THREAD_URL)
        if normalized_url:
            thread_urls = [{"keyword": "", "keywords": [], "url": normalized_url}]
    if not thread_urls:
        raise RuntimeError("No thread URLs found.")

    print(f"using thread input file: {input_file}")
    print(f"using mongo target: {json.dumps(mongo_target, ensure_ascii=False)}")

    ensure_dir(RAW_OUTPUT_FILE.parent)
    ensure_dir(PARSED_OUTPUT_FILE.parent)
    raw_records = load_json_array(RAW_OUTPUT_FILE)
    parsed_records = load_json_array(PARSED_OUTPUT_FILE)
    state = load_state(STATE_FILE)
    processed_urls = set(state.get("processed_urls") or [])

    client = build_mongo_client()
    collection = client[db_name][collection_name]
    driver = build_driver()
    try:
        total = len(thread_urls)
        synced = 0
        skipped = 0
        for index, item in enumerate(thread_urls, start=1):
            url = item["url"]
            search_keyword = item["keyword"]
            search_keywords = item.get("keywords") or ([search_keyword] if search_keyword else [])
            if url in processed_urls:
                skipped += 1
                print(f"[{index}/{total}] skip already synced {url}")
                continue

            print(f"[{index}/{total}] crawl {url}")
            try:
                raw_record = crawl_thread(driver, url, search_keyword, search_keywords, search_terms)
                parsed_record = parse_thread_record(raw_record)
                if not parsed_record:
                    raise RuntimeError("Unable to parse crawled thread payload")

                mongo_result = sync_record(collection, parsed_record, active_film_title)
                upsert_record(raw_records, raw_record, "url")
                upsert_record(parsed_records, parsed_record, "post_id")
                processed_urls.add(url)
                state["processed_urls"] = sorted(processed_urls)
                state["last_processed_url"] = url
                state["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                save_json_array(RAW_OUTPUT_FILE, raw_records)
                save_json_array(PARSED_OUTPUT_FILE, parsed_records)
                STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
                synced += 1
                print(
                    f"[{index}/{total}] synced post_id={parsed_record.get('post_id') or ''} "
                    f"url={url} mongo={mongo_result}"
                )
            except Exception as exc:
                print(f"[{index}/{total}] error url={url} error={exc}")

        print(
            f"threads sequential sync finished: total={total} synced={synced} skipped={skipped} "
            f"db={db_name} collection={collection_name}"
        )
        return 0
    finally:
        driver.quit()
        client.close()


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
    return INPUT_FILE


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
        current = merged.setdefault(url, {"keyword": keyword, "keywords": [], "url": url})
        if keyword and keyword not in current["keywords"]:
            current["keywords"].append(keyword)
        if not current["keyword"] and keyword:
            current["keyword"] = keyword
    return list(merged.values())


def load_json_array(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return payload if isinstance(payload, list) else []


def save_json_array(path: Path, payload: list[dict]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_state(path: Path) -> dict:
    if not path.exists():
        return {"processed_urls": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"processed_urls": []}
    return payload if isinstance(payload, dict) else {"processed_urls": []}


def upsert_record(records: list[dict], record: dict, key: str) -> None:
    target = str(record.get(key) or "").strip()
    if not target:
        records.append(record)
        return
    for index, item in enumerate(records):
        if not isinstance(item, dict):
            continue
        if str(item.get(key) or "").strip() == target:
            records[index] = record
            return
    records.append(record)


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
        matched_terms = [term for term in search_terms if contains_keyword(text, term)]
        article_payloads.append(
            {
                "index": index,
                "text": article.text,
                "html": article.get_attribute("outerHTML"),
                "matched_terms": matched_terms,
            }
        )
        if matched_terms:
            matched_on.add("post" if index == 0 else "reply")

    page_source = driver.page_source
    body_text = driver.execute_script("return document.body ? document.body.innerText : '';") or ""
    page_title = driver.title or ""
    current_url = driver.current_url or url
    page_matches = [term for term in search_terms if contains_keyword(normalize_text(body_text), term)]
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


def parse_thread_record(item: dict) -> dict:
    body_text = str(item.get("body_text") or "")
    lines = [line.strip() for line in body_text.splitlines() if line.strip()]
    if len(lines) < 5:
        return {}

    post_url = normalize_thread_url(str(item.get("current_url") or "") or first_linked_thread(item.get("linked_threads")))
    page_name = extract_username(post_url)
    post_id = extract_post_code(post_url)
    post_created_at = ""
    post_text = ""
    top_index = find_comments_start_index(lines)

    if len(lines) >= 4:
        if is_date_line(lines[3]):
            post_created_at = lines[3]
            post_text = collect_post_text(lines[4:top_index])
        elif len(lines) >= 5 and is_date_line(lines[4]):
            post_created_at = lines[4]
            post_text = collect_post_text(lines[5:top_index])
        else:
            post_text = collect_post_text(lines[3:top_index])

    comments = parse_comments(lines, top_index, post_id)
    return {
        "platform": "threads",
        "post_id": post_id,
        "page_id": "",
        "page_name": page_name,
        "post_url": post_url,
        "post_created_at": post_created_at,
        "post_text": post_text,
        "post_keyword_match": False,
        "parent_keyword_match": bool(post_text or comments),
        "search_keyword": str(item.get("keyword") or "").strip(),
        "search_keywords": normalize_keywords(item.get("keywords")),
        "source": SOURCE_NAME,
        "source_file": str(RAW_OUTPUT_FILE),
        "comments": comments,
    }


def sync_record(collection, record: dict, active_film_title: str) -> dict:
    document = build_mongo_document(record, active_film_title)
    if not document:
        raise RuntimeError("No document produced for Mongo sync")
    result = collection.bulk_write(
        [
            UpdateOne(
                {"platform": document["platform"], "post_id": document["post_id"]},
                {"$set": document},
                upsert=True,
            )
        ],
        ordered=False,
    )
    return {
        "upserted": result.upserted_count,
        "matched": result.matched_count,
        "modified": result.modified_count,
    }


def normalize_keywords(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    terms: list[str] = []
    for item in value:
        term = str(item or "").strip()
        if term and term not in terms:
            terms.append(term)
    return terms


def parse_comments(lines: list[str], top_index: int, post_id: str) -> list[dict]:
    comments: list[dict] = []
    if top_index >= len(lines):
        return comments

    index = top_index
    while index < len(lines) and lines[index] in TOP_MARKERS | ACTIVITY_MARKERS:
        index += 1

    comment_counter = 0
    while index < len(lines):
        if looks_like_username(lines[index]):
            username = lines[index]
            created_at, content_start = extract_comment_header(lines, index)
            if created_at:
                index = content_start
                text_lines: list[str] = []
                while index < len(lines):
                    line = lines[index]
                    if line in NOISE_LINES:
                        index += 1
                        continue
                    next_created_at, _ = extract_comment_header(lines, index)
                    if looks_like_username(line) and next_created_at:
                        break
                    if is_metric_line(line):
                        index += 1
                        continue
                    text_lines.append(line)
                    index += 1

                text = " ".join(text_lines).strip()
                if text:
                    comment_counter += 1
                    comments.append(
                        {
                            "external_id": f"comment:{post_id}:{comment_counter}",
                            "record_type": "comment",
                            "author": username,
                            "text": text,
                            "created_at": created_at,
                            "parent_comment_id": "",
                            "keyword_match": False,
                        }
                    )
                continue
        index += 1
    return comments


def collect_post_text(lines: list[str]) -> str:
    text_lines: list[str] = []
    for line in lines:
        if line in NOISE_LINES or is_metric_line(line):
            continue
        text_lines.append(line)
    return " ".join(text_lines).strip()


def find_comments_start_index(lines: list[str]) -> int:
    explicit_marker = next((index for index, value in enumerate(lines) if value in TOP_MARKERS), -1)
    if explicit_marker >= 0:
        return explicit_marker
    for index in range(4, len(lines) - 1):
        if looks_like_username(lines[index]):
            created_at, _ = extract_comment_header(lines, index)
            if created_at:
                return index
    return len(lines)


def extract_comment_header(lines: list[str], index: int) -> tuple[str, int]:
    if index >= len(lines) or not looks_like_username(lines[index]):
        return "", index
    probe = index + 1
    while probe < len(lines) and lines[probe] in NOISE_LINES:
        probe += 1
    if probe < len(lines) and is_date_line(lines[probe]):
        return lines[probe], probe + 1
    if probe + 1 < len(lines) and is_date_line(lines[probe + 1]):
        return lines[probe + 1], probe + 2
    return "", index


def looks_like_username(value: str) -> bool:
    if not value or " " in value:
        return False
    if value.startswith("@"):
        return True
    return bool(re.fullmatch(r"[A-Za-z0-9._]+", value))


def is_date_line(value: str) -> bool:
    return (
        bool(re.fullmatch(r"\d{2}/\d{2}/\d{2}", value))
        or bool(re.fullmatch(r"\d{2}/\d{2}/\d{4}", value))
        or bool(re.fullmatch(r"\d+[dhmw]d?", value))
    )


def is_metric_line(value: str) -> bool:
    return bool(re.fullmatch(r"[\d./KMBkmmb]+", value.strip()))


def first_linked_thread(value: object) -> str:
    if isinstance(value, list) and value:
        return str(value[0] or "")
    return ""


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


def extract_username(url: str) -> str:
    match = re.search(r"https://www\.threads\.(?:net|com)/@([^/]+)/post/", url or "")
    return match.group(1) if match else ""


def extract_post_code(url: str) -> str:
    match = re.search(r"/post/([^/?#]+)", url or "")
    return match.group(1) if match else ""


if __name__ == "__main__":
    raise SystemExit(main())
