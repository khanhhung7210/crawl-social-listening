from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote_plus

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

from social_listening.film_paths import platform_raw_dir
from social_listening.keyword_config import collect_config_values, load_keyword_payload
from social_listening.paths import DATA_DIR, ensure_dir
from social_listening.chromedriver_utils import build_attached_chrome, leave_chrome_open
from social_listening.maps_locale import is_galaxy_cinema_place_url, maps_url_with_hl


DEBUGGER_ADDRESS = os.getenv("GOOGLE_MAPS_DEBUGGER_ADDRESS", "127.0.0.1:9227")
MAX_PLACES_PER_QUERY = int(os.getenv("GOOGLE_MAPS_MAX_PLACES_PER_QUERY", "1"))
MAX_SCROLL_ROUNDS = int(os.getenv("GOOGLE_MAPS_MAX_SCROLL_ROUNDS", "8"))
SCROLL_PAUSE_SECONDS = float(os.getenv("GOOGLE_MAPS_SCROLL_PAUSE_SECONDS", "1.5"))
OUTPUT_FILE = platform_raw_dir("google_maps") / "google_maps_search_results.json"
CINEMA_FILE = DATA_DIR / "shared" / "galaxy_cinemas.json"


def load_galaxy_cinema_queries() -> list[str]:
    from social_listening.keyword_config import uses_db_keyword_config

    if uses_db_keyword_config():
        try:
            from social_listening.config.db_source import load_galaxy_cinema_queries_from_db

            queries = load_galaxy_cinema_queries_from_db()
            if queries:
                return queries
        except Exception as exc:
            print(f"[google-maps-search] DB cinema load failed: {exc}")

    if not CINEMA_FILE.exists():
        return []
    payload = json.loads(CINEMA_FILE.read_text(encoding="utf-8"))
    cinemas = payload.get("cinemas") if isinstance(payload, dict) else payload
    if not isinstance(cinemas, list):
        return []
    return [str(x).strip() for x in cinemas if str(x).strip()]


def is_galaxy_place_url(url: str) -> bool:
    return is_galaxy_cinema_place_url(url)


def main() -> int:
    cinema_queries = load_galaxy_cinema_queries()
    payload = load_keyword_payload()
    search_queries = cinema_queries or collect_config_values(payload, "google_maps_queries")
    direct_urls = collect_config_values(payload, "google_maps_urls")
    print(f"[google-maps-search] queries={len(search_queries)} (Galaxy cinemas only)")

    driver = build_attached_chrome(DEBUGGER_ADDRESS)
    try:
        results: list[dict] = []
        seen: set[str] = set()
        ensure_dir(OUTPUT_FILE.parent)

        def persist() -> None:
            OUTPUT_FILE.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

        if OUTPUT_FILE.exists() and os.getenv("GOOGLE_MAPS_RESUME", "1") == "1":
            try:
                prev = json.loads(OUTPUT_FILE.read_text(encoding="utf-8"))
            except Exception:
                prev = []
            if isinstance(prev, list):
                for row in prev:
                    if not isinstance(row, dict):
                        continue
                    results.append(row)
                    url = str(row.get("url") or "").strip()
                    if url:
                        seen.add(url)
                done_kw = {str(r.get("keyword") or "") for r in results if r.get("url")}
                search_queries = [q for q in search_queries if q not in done_kw]
                print(f"[google-maps-search] resume kept={len(results)} remaining={len(search_queries)}")

        for position, url in enumerate(direct_urls, start=1):
            normalized = normalize_google_maps_place_url(url)
            if not normalized or not is_galaxy_place_url(normalized) or normalized in seen:
                continue
            seen.add(normalized)
            results.append(
                {
                    "keyword": "direct_url",
                    "search_keyword": "direct_url",
                    "url": normalized,
                    "search_rank": position,
                    "status": "ok",
                    "reason": "config_url",
                }
            )

        for index, keyword in enumerate(search_queries, start=1):
            print(f"[google-maps-search] {index}/{len(search_queries)} keyword={keyword}")
            try:
                search_result = search_places_for_keyword(driver, keyword)
            except Exception as exc:
                print(f"[google-maps-search] skip keyword={keyword} error={exc}")
                results.append({"keyword": keyword, "search_keyword": keyword, "url": "", "status": "error", "error": str(exc)})
                continue

            for rank, url in enumerate(search_result["urls"], start=1):
                if url in seen:
                    continue
                # Place URL often uses /maps/place/data=!4m… without the word "galaxy"
                seen.add(url)
                results.append(
                    {
                        "keyword": keyword,
                        "search_keyword": keyword,
                        "url": url,
                        "search_rank": rank,
                        "status": search_result["status"],
                        "reason": search_result.get("reason", ""),
                    }
                )
            kept = sum(1 for r in results if r.get("keyword") == keyword and r.get("url"))
            print(f"[google-maps-search] {keyword} -> {kept} galaxy place(s)", flush=True)
            persist()

        ensure_dir(OUTPUT_FILE.parent)
        OUTPUT_FILE.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"saved {len(results)} google maps urls to {OUTPUT_FILE.resolve()}")
        return 0
    finally:
        leave_chrome_open(driver)


def dismiss_maps_consent(driver: webdriver.Chrome) -> None:
    driver.execute_script(
        """
        const labels = ['Accept all', 'I agree', 'Chấp nhận tất cả', 'Tôi đồng ý', 'Reject all'];
        const buttons = Array.from(document.querySelectorAll('button, [role="button"]'));
        for (const el of buttons) {
          const text = (el.innerText || el.textContent || '').trim();
          if (labels.some((label) => text === label || text.includes(label))) {
            el.click();
            return true;
          }
        }
        return false;
        """
    )
    time.sleep(1.2)


def collect_place_urls(driver: webdriver.Chrome) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()

    def add(raw: str) -> None:
        normalized = normalize_google_maps_place_url(raw)
        if not normalized or not is_galaxy_place_url(normalized) or normalized in seen:
            return
        seen.add(normalized)
        found.append(normalized)

    add(str(driver.current_url or ""))
    for href in get_anchor_hrefs(driver):
        add(href)
    html = str(driver.page_source or "")
    for match in re.finditer(r"https://www\.google\.[^\s\"'<>]+/maps/place/[^\s\"'<>]+", html):
        add(match.group(0))
    for match in re.finditer(r"/maps/place/[^\"'\s<>]+", html):
        add("https://www.google.com" + match.group(0))
    return found


def search_places_for_keyword(driver: webdriver.Chrome, keyword: str) -> dict:
    driver.get(maps_url_with_hl(f"https://www.google.com/maps/search/{quote_plus(keyword)}"))
    time.sleep(5)
    dismiss_maps_consent(driver)
    if not normalize_google_maps_place_url(str(driver.current_url or "")):
        driver.execute_script(
            """
            const link = document.querySelector('a[href*="/maps/place/"]');
            if (link) { link.click(); return true; }
            const article = document.querySelector('div[role="article"], a.hfpxzc');
            if (article) { article.click(); return true; }
            return false;
            """
        )
        time.sleep(3)

    urls: list[str] = []
    idle_rounds = 0

    for _ in range(MAX_SCROLL_ROUNDS):
        before_count = len(urls)
        for url in collect_place_urls(driver):
            if url in urls:
                continue
            urls.append(url)
            if len(urls) >= MAX_PLACES_PER_QUERY:
                return {"urls": urls, "status": "ok", "reason": "max_places_reached"}

        idle_rounds = idle_rounds + 1 if len(urls) == before_count else 0
        if idle_rounds >= 4:
            break
        scroll_search_results(driver)
        time.sleep(SCROLL_PAUSE_SECONDS)

    # Unique cinema search often lands on the place itself
    current = normalize_google_maps_place_url(str(driver.current_url or ""))
    if current and current not in urls and is_galaxy_place_url(current):
        urls.insert(0, current)

    return {"urls": urls[:MAX_PLACES_PER_QUERY], "status": "ok" if urls else "no_results", "reason": "scroll_exhausted"}


def scroll_search_results(driver: webdriver.Chrome) -> None:
    driver.execute_script(
        """
        const panel = Array.from(document.querySelectorAll('div[role="feed"], div[aria-label]'))
          .find((node) => node.scrollHeight > node.clientHeight + 100);
        if (panel) {
          panel.scrollTop = panel.scrollHeight;
          return;
        }
        window.scrollTo(0, document.body.scrollHeight);
        """
    )
    try:
        driver.find_element(By.TAG_NAME, "body").send_keys(Keys.END)
    except Exception:
        pass


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


def normalize_google_maps_place_url(url: str) -> str:
    text = str(url or "").strip()
    if not text:
        return ""
    match = re.search(r"https://www\.google\.[^/]+/maps/place/[^?#]+", text)
    if match:
        return match.group(0)
    if "/maps?cid=" in text or "/maps/place/" in text:
        return text.split("&", 1)[0]
    return ""


if __name__ == "__main__":
    raise SystemExit(main())
