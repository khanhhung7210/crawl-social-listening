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

    driver = build_driver()
    try:
        results: list[dict] = []
        seen: set[str] = set()

        for index, keyword in enumerate(search_terms, start=1):
            print(f"[tiktok-search] {index}/{len(search_terms)} keyword={keyword}")
            try:
                search_result = search_videos_for_keyword(driver, keyword)
            except Exception as exc:
                print(f"[tiktok-search] skip keyword={keyword} error={exc}")
                results.append({"keyword": keyword, "url": "", "status": "error", "error": str(exc)})
                continue

            urls = search_result["urls"]
            status = search_result["status"]
            reason = search_result.get("reason", "")

            if not urls:
                results.append({"keyword": keyword, "url": "", "status": status, "reason": reason})
                continue

            for url in urls:
                if url in seen:
                    continue
                seen.add(url)
                results.append({"keyword": keyword, "url": url, "status": status, "reason": reason})

        ensure_dir(OUTPUT_FILE.parent)
        OUTPUT_FILE.write_text(
            json.dumps(results, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"saved {len(results)} video urls to {OUTPUT_FILE.resolve()}")
        return 0
    finally:
        driver.quit()


def search_videos_for_keyword(driver: webdriver.Chrome, keyword: str) -> dict:
    driver.get(TIKTOK_SEARCH_URL.format(query=quote(keyword)))
    time.sleep(5)
    started_at = time.monotonic()

    urls: list[str] = []
    seen: set[str] = set()
    idle_rounds = 0
    empty_rounds = 0

    for _ in range(MAX_SCROLL_ROUNDS):
        if time.monotonic() - started_at >= MAX_RUNTIME_SECONDS:
            return {"urls": urls, "status": "partial" if urls else "no_results", "reason": "runtime_limit"}

        before_count = len(urls)
        for href in get_anchor_hrefs(driver):
            normalized = normalize_tiktok_video_url(href)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            urls.append(normalized)
            if len(urls) >= MAX_VIDEOS:
                return {"urls": urls, "status": "ok", "reason": "max_videos_reached"}

        idle_rounds = idle_rounds + 1 if len(urls) == before_count else 0
        empty_rounds = empty_rounds + 1 if not urls else 0
        if idle_rounds >= IDLE_ROUNDS_BEFORE_STOP:
            return {"urls": urls, "status": "partial" if urls else "no_results", "reason": "idle_limit"}
        if empty_rounds >= MAX_EMPTY_ROUNDS_BEFORE_SKIP:
            print(f"[tiktok-search] no results for keyword={keyword}, skipping")
            return {"urls": urls, "status": "partial" if urls else "no_results", "reason": "empty_limit"}

        scroll_search_results(driver)
        time.sleep(SCROLL_PAUSE_SECONDS)

    return {"urls": urls, "status": "ok" if urls else "no_results", "reason": "scroll_exhausted"}


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
