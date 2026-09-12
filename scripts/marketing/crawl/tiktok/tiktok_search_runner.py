from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from selenium import webdriver
from selenium.common.exceptions import SessionNotCreatedException, WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from webdriver_manager.chrome import ChromeDriverManager


def _ensure_utf8_stdio() -> None:
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


_ensure_utf8_stdio()


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
from social_listening.chromedriver_utils import chrome_debugger_ready, resolve_chromedriver_path
from social_listening.crawl_freshness import KeywordCrawlStats, load_freshness_policy


DEBUGGER_ADDRESS = os.getenv("TIKTOK_DEBUGGER_ADDRESS", "127.0.0.1:9223")
POLICY = load_freshness_policy("tiktok")
DISCOVERY_LIMIT = POLICY.discovery_limit
FINAL_LIMIT = POLICY.final_limit
MAX_VIDEOS = DISCOVERY_LIMIT
MAX_SCROLL_ROUNDS = POLICY.max_scroll_rounds
IDLE_ROUNDS_BEFORE_STOP = POLICY.idle_rounds_before_stop
MAX_EMPTY_ROUNDS_BEFORE_SKIP = POLICY.empty_rounds_before_skip
SCROLL_PAUSE_SECONDS = float(os.getenv("TIKTOK_SCROLL_PAUSE_SECONDS", "2.5"))
PAGE_LOAD_WAIT_SECONDS = float(os.getenv("TIKTOK_PAGE_LOAD_WAIT_SECONDS", "5.0"))
MAX_RUNTIME_SECONDS = POLICY.max_runtime_seconds
KEYWORD_RUNTIME_SECONDS = POLICY.keyword_runtime_seconds
OUTPUT_FILE = platform_raw_dir("tiktok") / "tiktok_search_results.json"

# Smoke 2026-09-11 (web TikTok, keyword "rạp galaxy"):
# - sort_type / publish_time stay in URL but barely change SERP vs default
# - /search (general) vs /search/video DO return different video sets
# - UI Filters panel often missing unless fully logged-in session
# So: crawl date-posted URL + week URL + video relevance + general Top, merge.
TIKTOK_DATE_POSTED_QS = "sort_type=3"
TIKTOK_THIS_WEEK_QS = "publish_time=7"
TIKTOK_DATE_WEEK_QS = "sort_type=3&publish_time=7"


def main() -> int:
    search_terms = collect_search_terms(load_keyword_payload())
    keyword_limit = int(os.getenv("TIKTOK_KEYWORD_LIMIT", "0") or "0")
    if keyword_limit > 0:
        search_terms = search_terms[:keyword_limit]
        print(f"[tiktok-search] TIKTOK_KEYWORD_LIMIT={keyword_limit}")
    if not search_terms:
        raise RuntimeError("No search terms found in shared keyword config")

    with IncrementalCrawlState() as state:
        is_initial = state.is_initial_run("tiktok") and state.is_initial_run("tiktok_detail")
        run_type = "initial" if is_initial else "incremental"
        existing_urls = state.get_known_urls("tiktok", "tiktok_detail")

        print(f"[tiktok-search] Run type: {run_type}")
        print(f"[tiktok-search] Keywords: {len(search_terms)}")
        print(f"[tiktok-search] Existing URLs: {len(existing_urls)}")
        print(
            f"[tiktok-search] Policy lookback={POLICY.lookback_days:.1f}d "
            f"discovery={DISCOVERY_LIMIT} final={FINAL_LIMIT} scroll={MAX_SCROLL_ROUNDS} "
            f"runtime={MAX_RUNTIME_SECONDS}s keyword_runtime={KEYWORD_RUNTIME_SECONDS}s"
        )
        print(
            "[tiktok-search] Note: crawl Date-week URL (sort_type=3&publish_time=7) + "
            "video Relevance + general Top; web date params are weak so merge SERPs; "
            "UI Filters backup; FINAL newest sort still happens at detail"
        )

        run_id = state.start_run("tiktok", run_type)

        driver = build_driver()
        try:
            new_results: list[dict] = []
            global_seen: set[str] = set()
            urls_discovered = 0
            urls_new = 0

            for index, keyword in enumerate(search_terms, start=1):
                print(f"[tiktok-search] {index}/{len(search_terms)} keyword={keyword}")
                try:
                    search_result = search_videos_for_keyword_incremental(
                        driver, keyword, existing_urls
                    )
                except Exception as exc:
                    print(f"[tiktok-search] skip keyword={keyword} error={exc}")
                    continue

                stats: KeywordCrawlStats = search_result["stats"]
                stats.log("tiktok-search")
                urls = search_result["urls"]
                urls_discovered += stats.discovered
                urls_new += len(urls)

                if not urls:
                    continue

                for url in urls:
                    if url in global_seen:
                        continue
                    global_seen.add(url)
                    modes = sorted(search_result.get("url_modes", {}).get(url) or [])
                    new_results.append(
                        {
                            "keyword": keyword,
                            "url": url,
                            "status": search_result["status"],
                            "reason": search_result.get("reason", ""),
                            "search_modes": modes,
                            "pending_detail": True,
                        }
                    )

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
                keywords_processed=len(search_terms),
            )

            print("[tiktok-search] Summary:")
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
    """Scroll until idle/empty/safety. Merge multiple TikTok SERP modes."""
    urls: list[str] = []
    url_modes: dict[str, set[str]] = {}
    seen: set[str] = set()
    all_discovered: list[str] = []
    already_seen = 0
    stop_reason = "no_results"
    keyword_started = time.monotonic()
    mode_budget = max(10, MAX_VIDEOS // 3)
    mode_counts: dict[str, int] = {}
    date_filter_ok = False

    for search_url, mode in resolve_search_urls(keyword):
        if time.monotonic() - keyword_started >= KEYWORD_RUNTIME_SECONDS:
            stop_reason = "keyword_runtime_limit"
            break
        if len(urls) >= MAX_VIDEOS:
            stop_reason = "max_videos_reached"
            break
        if mode_counts.get(mode, 0) >= mode_budget:
            continue

        driver.get(search_url)
        time.sleep(PAGE_LOAD_WAIT_SECONDS)

        if mode == "date_week":
            via = ensure_mode_url(driver, search_url, mode)
            if via == "unavailable":
                ui_ok = ensure_latest_or_date_filter_ui(driver)
                via = "ui" if ui_ok else "unavailable"
            date_filter_ok = via != "unavailable"
            print(
                f"[tiktok-search] keyword={keyword} mode={mode} date_filter="
                f"{'on' if date_filter_ok else 'unavailable(fail-soft)'} via={via}",
                flush=True,
            )
        else:
            print(
                f"[tiktok-search] keyword={keyword} mode={mode} serp=on via=url",
                flush=True,
            )

        started_at = time.monotonic()
        idle_rounds = 0
        empty_rounds = 0
        scroll_rounds = 0
        mode_full = False
        duplicate_only_rounds = 0

        for _ in range(MAX_SCROLL_ROUNDS):
            scroll_rounds += 1
            elapsed_keyword = time.monotonic() - keyword_started
            elapsed_mode = time.monotonic() - started_at
            if elapsed_keyword >= KEYWORD_RUNTIME_SECONDS:
                stop_reason = "keyword_runtime_limit"
                break
            if elapsed_mode >= MAX_RUNTIME_SECONDS:
                stop_reason = "runtime_limit"
                break

            before_count = len(urls)
            before_seen = len(seen)
            page_hits = 0
            for href in get_anchor_hrefs(driver):
                normalized = normalize_tiktok_video_url(href)
                if not normalized:
                    continue
                page_hits += 1
                if normalized in seen:
                    url_modes.setdefault(normalized, set()).add(mode)
                    continue
                seen.add(normalized)
                all_discovered.append(normalized)
                url_modes.setdefault(normalized, set()).add(mode)
                if normalized in existing_urls:
                    already_seen += 1
                    continue
                urls.append(normalized)
                mode_counts[mode] = mode_counts.get(mode, 0) + 1
                if mode_counts[mode] >= mode_budget:
                    mode_full = True
                    stop_reason = f"{mode}_budget_reached"
                    break
                if len(urls) >= MAX_VIDEOS:
                    stop_reason = "max_videos_reached"
                    break

            if stop_reason == "max_videos_reached" or mode_full:
                break

            # SERP only repeats URLs already collected from earlier modes → move on.
            if page_hits > 0 and len(seen) == before_seen:
                duplicate_only_rounds += 1
            else:
                duplicate_only_rounds = 0
            if duplicate_only_rounds >= 2:
                stop_reason = f"{mode}_duplicates_only"
                break

            idle_rounds = idle_rounds + 1 if len(urls) == before_count else 0
            empty_rounds = empty_rounds + 1 if page_hits == 0 else 0
            if scroll_rounds % 5 == 0 or idle_rounds == 0:
                print(
                    f"[tiktok-search] keyword={keyword} mode={mode} "
                    f"discovered={len(all_discovered)} queued={len(urls)} "
                    f"mode_count={mode_counts.get(mode, 0)}/{mode_budget} idle={idle_rounds}",
                    flush=True,
                )
            if idle_rounds >= IDLE_ROUNDS_BEFORE_STOP:
                stop_reason = "idle_limit"
                break
            if empty_rounds >= MAX_EMPTY_ROUNDS_BEFORE_SKIP:
                stop_reason = "empty_limit"
                break

            scroll_search_results(driver)
            time.sleep(SCROLL_PAUSE_SECONDS)

        if stop_reason in {"keyword_runtime_limit", "runtime_limit", "max_videos_reached"}:
            break
        # duplicates_only / idle / budget → continue next mode
        if stop_reason.endswith("_duplicates_only") or stop_reason.endswith("_budget_reached") or stop_reason in {
            "idle_limit",
            "empty_limit",
        }:
            stop_reason = "no_results" if not urls else stop_reason
            continue

    url_modes_out = {u: sorted(m) for u, m in url_modes.items()}
    stats = KeywordCrawlStats(
        keyword=keyword,
        discovered=len(all_discovered),
        new=len(urls),
        already_seen=already_seen,
        runtime_seconds=time.monotonic() - keyword_started,
        stop_reason=stop_reason,
        extras={
            "date_filter": date_filter_ok,
            **{f"{k}_count": v for k, v in mode_counts.items()},
            "mode_budget": mode_budget,
        },
    )
    status = "ok" if urls else ("partial" if all_discovered else "no_results")
    if stop_reason in {"runtime_limit", "keyword_runtime_limit"} and urls:
        status = "partial"

    # Leave browser on date-posted URL so a watching human doesn't only see Relevance.
    try:
        driver.get(f"https://www.tiktok.com/search/video?q={quote(keyword)}&{TIKTOK_DATE_WEEK_QS}")
        time.sleep(1.0)
    except Exception:
        pass

    return {
        "urls": urls,
        "url_modes": url_modes_out,
        "status": status,
        "reason": stop_reason,
        "stats": stats,
        "date_filter": date_filter_ok,
    }


def resolve_search_urls(keyword: str) -> list[tuple[str, str]]:
    q = quote(keyword)
    return [
        (f"https://www.tiktok.com/search/video?q={q}&{TIKTOK_DATE_WEEK_QS}", "date_week"),
        (f"https://www.tiktok.com/search/video?q={q}", "video_relevance"),
        (f"https://www.tiktok.com/search?q={q}", "general_top"),
    ]


def ensure_mode_url(driver: webdriver.Chrome, expected_url: str, mode: str) -> str:
    """Confirm expected query params survived navigation."""
    cur = driver.current_url or ""
    qs = parse_qs(urlparse(cur).query)
    exp = parse_qs(urlparse(expected_url).query)
    ok = True
    for key in ("sort_type", "publish_time"):
        if key in exp and qs.get(key) != exp.get(key):
            ok = False
    if ok and any(k in exp for k in ("sort_type", "publish_time")):
        return "url"
    # Hard re-open
    try:
        driver.get(expected_url)
        time.sleep(PAGE_LOAD_WAIT_SECONDS)
        qs2 = parse_qs(urlparse(driver.current_url).query)
        for key in ("sort_type", "publish_time"):
            if key in exp and qs2.get(key) != exp.get(key):
                return "unavailable"
        return "url"
    except Exception:
        return "unavailable"


def ensure_latest_or_date_filter_ui(driver: webdriver.Chrome) -> bool:
    """Best-effort Filters → Latest / Date posted / This week (often hidden)."""
    try:
        opened = driver.execute_script(
            """
            const sels = [
              '[data-e2e="search-filter-icon"]',
              '[data-e2e="filter-icon"]',
              '[data-e2e="search-filter"]',
            ];
            for (const s of sels) {
              const el = document.querySelector(s);
              if (el) { el.click(); return s; }
            }
            const nodes = Array.from(document.querySelectorAll('button, [role="button"], div, span'));
            for (const el of nodes) {
              const t = ((el.getAttribute('aria-label') || '') + ' ' + (el.innerText || '')).trim();
              if (!t || t.length > 40) continue;
              if (/^filters?$/i.test(t) || t === 'Bộ lọc' || /filter/i.test(t)) {
                el.click();
                return t;
              }
            }
            return null;
            """
        )
        if not opened:
            return False
        time.sleep(1.2)
        clicked = driver.execute_script(
            """
            const wants = [
              'Latest', 'Mới nhất', 'Date posted', 'Ngày đăng',
              'This week', 'Tuần này', 'Past week', 'Past 24 hours', 'Hôm nay'
            ];
            const nodes = Array.from(document.querySelectorAll('button, [role="button"], div, span, label'));
            for (const want of wants) {
              for (const el of nodes) {
                const t = (el.innerText || '').trim();
                if (t === want || t.includes(want)) { el.click(); return t; }
              }
            }
            return null;
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


def tiktok_chrome_profile_dir() -> Path:
    return PROJECT_ROOT / "runtime" / "chrome" / "tiktok"


def ensure_tiktok_debug_chrome() -> None:
    if chrome_debugger_ready(DEBUGGER_ADDRESS):
        return
    host, port_text = DEBUGGER_ADDRESS.rsplit(":", 1)
    profile_dir = tiktok_chrome_profile_dir()
    profile_dir.mkdir(parents=True, exist_ok=True)
    chrome_bin = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    if not Path(chrome_bin).is_file():
        raise RuntimeError(f"Google Chrome not found at {chrome_bin}")
    cmd = [
        chrome_bin,
        f"--remote-debugging-port={port_text}",
        f"--remote-debugging-address={host}",
        "--remote-allow-origins=*",
        f"--user-data-dir={profile_dir}",
        "--disable-blink-features=AutomationControlled",
        "--no-first-run",
        "--no-default-browser-check",
        "about:blank",
    ]
    print(f"[tiktok-search] starting debug Chrome on {DEBUGGER_ADDRESS}")
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    for _ in range(30):
        time.sleep(1)
        if chrome_debugger_ready(DEBUGGER_ADDRESS):
            print(f"[tiktok-search] debug Chrome ready on {DEBUGGER_ADDRESS}")
            return
    raise RuntimeError(
        f"Chrome debug did not start on {DEBUGGER_ADDRESS}. Try manually: {' '.join(cmd)}"
    )


def build_driver() -> webdriver.Chrome:
    ensure_tiktok_debug_chrome()
    options = Options()
    options.debugger_address = DEBUGGER_ADDRESS
    try:
        return webdriver.Chrome(options=options)
    except SessionNotCreatedException:
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
                "--remote-debugging-port=9223 --remote-allow-origins=* "
                f"--user-data-dir={tiktok_chrome_profile_dir()}"
            ) from exc


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
