from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote

from selenium import webdriver
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


INSTAGRAM_SEARCH_URL = "https://www.instagram.com/explore/search/keyword/?q={query}"
DEBUGGER_ADDRESS = os.getenv("INSTAGRAM_DEBUGGER_ADDRESS", "127.0.0.1:9224")
MAX_POSTS = 100
MAX_SCROLL_ROUNDS = 120
IDLE_ROUNDS_BEFORE_STOP = 8
SCROLL_PAUSE_SECONDS = 2.5
MAX_RUNTIME_SECONDS = 420
OUTPUT_FILE = platform_raw_dir("instagram") / "instagram_search_results.json"


def main() -> int:
    search_terms = collect_search_terms(load_keyword_payload())
    if not search_terms:
        raise RuntimeError("No search terms found in shared keyword config")

    driver = build_driver()
    try:
        results: list[dict] = []
        seen: set[str] = set()

        for keyword in search_terms:
            driver.get(INSTAGRAM_SEARCH_URL.format(query=quote(keyword)))
            time.sleep(6)
            started_at = time.monotonic()

            urls: list[str] = []
            local_seen: set[str] = set()
            idle_rounds = 0

            for _ in range(MAX_SCROLL_ROUNDS):
                if time.monotonic() - started_at >= MAX_RUNTIME_SECONDS:
                    break

                before_count = len(urls)
                for anchor in driver.find_elements(By.TAG_NAME, "a"):
                    href = (anchor.get_attribute("href") or "").strip()
                    normalized = normalize_instagram_post_url(href)
                    if not normalized or normalized in local_seen:
                        continue
                    local_seen.add(normalized)
                    urls.append(normalized)
                    if len(urls) >= MAX_POSTS:
                        break

                if len(urls) >= MAX_POSTS:
                    break

                idle_rounds = idle_rounds + 1 if len(urls) == before_count else 0
                if idle_rounds >= IDLE_ROUNDS_BEFORE_STOP:
                    break

                scroll_search_results(driver)
                time.sleep(SCROLL_PAUSE_SECONDS)

            if not urls:
                results.append({"keyword": keyword, "url": "", "status": "no_results"})
                continue

            for url in urls:
                if url in seen:
                    continue
                seen.add(url)
                results.append({"keyword": keyword, "url": url, "status": "ok"})

        ensure_dir(OUTPUT_FILE.parent)
        OUTPUT_FILE.write_text(
            json.dumps(results, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"saved {len(results)} instagram urls to {OUTPUT_FILE.resolve()}")
        return 0
    finally:
        driver.quit()


def build_driver() -> webdriver.Chrome:
    options = Options()
    options.debugger_address = DEBUGGER_ADDRESS
    driver_path = resolve_chromedriver_path()
    if driver_path:
        return webdriver.Chrome(service=Service(driver_path), options=options)
    return webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)


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
