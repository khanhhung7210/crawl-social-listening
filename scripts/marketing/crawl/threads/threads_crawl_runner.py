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
    """Avoid Windows cp1252 crashes on Vietnamese keyword prints."""
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
from social_listening.crawl_freshness import (
    KeywordCrawlStats,
    load_freshness_policy,
    should_stop_for_validated_stale_content,
)


DEBUGGER_ADDRESS = os.getenv("THREADS_DEBUGGER_ADDRESS", "127.0.0.1:9222")
POLICY = load_freshness_policy("threads")
DISCOVERY_LIMIT = POLICY.discovery_limit
FINAL_LIMIT = POLICY.final_limit
MAX_THREADS = DISCOVERY_LIMIT  # search candidate pool; detail/final applied downstream
MAX_SCROLL_ROUNDS = POLICY.max_scroll_rounds
IDLE_ROUNDS_BEFORE_STOP = POLICY.idle_rounds_before_stop
MAX_EMPTY_ROUNDS_BEFORE_SKIP = POLICY.empty_rounds_before_skip
SCROLL_PAUSE_SECONDS = float(os.getenv("THREADS_SCROLL_PAUSE_SECONDS", "2.5"))
PAGE_LOAD_WAIT_SECONDS = float(os.getenv("THREADS_PAGE_LOAD_WAIT_SECONDS", "5.0"))
MAX_RUNTIME_SECONDS = POLICY.max_runtime_seconds
KEYWORD_RUNTIME_SECONDS = POLICY.keyword_runtime_seconds
OUTPUT_FILE = platform_raw_dir("threads") / "threads_search_results.json"
# Native Threads Recent filter — URL param is reliable; Top-tab UI click is NOT
# (smoke 2026-09-11: clicking "Recent" left SERP on Top and did not add filter=recent).
SPECIAL_SEARCH_URLS = {
    "bts live viewing": [
        "https://www.threads.com/search?q=BTS%20LIVE%20VIEWING&filter=recent",
        "https://www.threads.com/search?q=bts%20live%20viewing&serp_type=tags&filter=recent",
    ],
    "cgv bts": [
        "https://www.threads.com/search?q=cgv%20bts&serp_type=default&filter=recent",
    ],
    "lotte bts": [
        "https://www.threads.com/search?q=lotte%20bts&serp_type=default&filter=recent",
    ],
    "galaxy bts": [
        "https://www.threads.com/search?q=galaxy%20bts&serp_type=default&filter=recent",
    ],
}


def main() -> int:
    keyword_payload = load_keyword_payload()
    search_terms = collect_search_terms(keyword_payload)
    keyword_limit = int(os.getenv("THREADS_KEYWORD_LIMIT", "0") or "0")
    if keyword_limit > 0:
        search_terms = search_terms[:keyword_limit]
        print(f"[threads-search] THREADS_KEYWORD_LIMIT={keyword_limit}")
    if not search_terms:
        raise RuntimeError("No search terms found in shared keyword config")

    with IncrementalCrawlState() as state:
        is_initial = state.is_initial_run("threads") and state.is_initial_run("threads_detail")
        run_type = "initial" if is_initial else "incremental"
        existing_urls = state.get_known_urls("threads", "threads_detail")

        print(f"[threads-search] Run type: {run_type}")
        print(f"[threads-search] Keywords: {len(search_terms)}")
        print(f"[threads-search] Existing URLs in state: {len(existing_urls)}")
        print(
            f"[threads-search] Policy lookback={POLICY.lookback_days:.1f}d "
            f"discovery={DISCOVERY_LIMIT} final={FINAL_LIMIT} scroll={MAX_SCROLL_ROUNDS} "
            f"runtime={MAX_RUNTIME_SECONDS}s keyword_runtime={KEYWORD_RUNTIME_SECONDS}s "
            f"content_stale_stop={POLICY.consecutive_stale_content_stop}"
        )
        print(
            "[threads-search] Note: crawl BOTH Recent (filter=recent URL) AND Top; "
            "Recent alone is often phone/Galaxy spam for cinema keywords; "
            "merge+dedupe; UI Recent click is backup only"
        )

        run_id = state.start_run("threads", run_type)

        driver = build_driver()
        try:
            new_results: list[dict] = []
            urls_discovered = 0
            urls_new = 0

            for index, keyword in enumerate(search_terms, start=1):
                print(f"[threads-search] {index}/{len(search_terms)} keyword={keyword}")
                try:
                    search_result = search_threads_for_keyword_incremental(
                        driver,
                        keyword,
                        existing_urls,
                    )
                except Exception as exc:
                    print(f"[threads-search] skip keyword={keyword} error={exc}")
                    new_results.append(
                        {
                            "keyword": keyword,
                            "url": "",
                            "status": "error",
                            "error": str(exc),
                        }
                    )
                    continue

                stats: KeywordCrawlStats = search_result["stats"]
                stats.log("threads-search")
                urls = search_result["urls"]
                status = search_result["status"]
                reason = search_result.get("reason", "")
                urls_discovered += stats.discovered
                urls_new += len(urls)

                if not urls:
                    continue

                for position, url in enumerate(urls, start=1):
                    modes = sorted(search_result.get("url_modes", {}).get(url) or [])
                    new_results.append(
                        {
                            "keyword": keyword,
                            "search_keyword": keyword,
                            "url": url,
                            "search_rank": position,
                            "search_modes": modes,
                            "status": status,
                            "reason": reason,
                            "pending_detail": True,
                        }
                    )

            ensure_dir(OUTPUT_FILE.parent)
            existing_results = load_existing_results()
            merged_results = merge_results(existing_results, new_results)

            OUTPUT_FILE.write_text(
                json.dumps(merged_results, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            state.complete_run(
                run_id,
                urls_discovered=urls_discovered,
                urls_crawled=0,
                urls_skipped=len(existing_urls),
                keywords_processed=len(search_terms),
            )

            print(f"[threads-search] Summary:")
            print(f"  - Discovered (all keywords): {urls_discovered}")
            print(f"  - New URLs queued for detail: {urls_new}")
            print(f"  - Saved to: {OUTPUT_FILE.resolve()}")
            return 0
        finally:
            driver.quit()


def search_threads_for_keyword_incremental(
    driver: webdriver.Chrome,
    keyword: str,
    existing_urls: set[str],
) -> dict:
    """
    Incremental search without URL-history early-stop.

    Runs BOTH Recent (filter=recent) and Top SERPs, then merges. Recent alone
    often returns unrelated "Galaxy" phone spam for cinema keywords like
    "rạp galaxy"; Top carries the relevant VN cinema posts.
    """
    urls: list[str] = []
    url_modes: dict[str, set[str]] = {}
    seen: set[str] = set()
    all_discovered: list[str] = []
    already_seen = 0
    consecutive_stale_content = 0
    last_reason = "no_results"
    keyword_started = time.monotonic()
    mode_budget = max(10, MAX_THREADS // 2)
    mode_counts = {"recent": 0, "top": 0}

    for search_url in resolve_search_urls(keyword):
        if time.monotonic() - keyword_started >= KEYWORD_RUNTIME_SECONDS:
            last_reason = "keyword_runtime_limit"
            break
        if len(urls) >= MAX_THREADS:
            last_reason = "max_threads_reached"
            break

        mode = "recent" if recent_filter_in_url(search_url) else "top"
        if mode_counts[mode] >= mode_budget:
            continue

        driver.get(search_url)
        time.sleep(PAGE_LOAD_WAIT_SECONDS)
        if mode == "recent":
            via = ensure_recent_search(driver, keyword)
            print(
                f"[threads-search] keyword={keyword} mode=recent recent_filter="
                f"{'on' if via != 'unavailable' else 'unavailable(fail-soft)'} via={via}",
                flush=True,
            )
        else:
            via = ensure_top_search(driver, keyword)
            print(
                f"[threads-search] keyword={keyword} mode=top top_serp="
                f"{'on' if via == 'top' else 'unavailable(fail-soft)'} via={via}",
                flush=True,
            )

        started_at = time.monotonic()
        idle_rounds = 0
        empty_rounds = 0
        scroll_rounds = 0
        mode_full = False

        for _ in range(MAX_SCROLL_ROUNDS):
            if mode == "recent" and not recent_filter_in_url(driver.current_url):
                via = ensure_recent_search(driver, keyword)
                if via == "unavailable":
                    print(
                        f"[threads-search] keyword={keyword} recent_filter lost; continuing fail-soft",
                        flush=True,
                    )
            elif mode == "top" and recent_filter_in_url(driver.current_url):
                ensure_top_search(driver, keyword)

            scroll_rounds += 1
            elapsed_keyword = time.monotonic() - keyword_started
            elapsed_url = time.monotonic() - started_at
            if elapsed_keyword >= KEYWORD_RUNTIME_SECONDS:
                last_reason = "keyword_runtime_limit"
                break
            if elapsed_url >= MAX_RUNTIME_SECONDS:
                last_reason = "runtime_limit"
                break

            before_count = len(urls)
            card_rows = extract_search_cards(driver)
            stop = None

            def _accept(normalized: str, content_ts=None):
                nonlocal already_seen, consecutive_stale_content, last_reason, mode_full
                if not normalized or normalized in seen:
                    return None
                seen.add(normalized)
                all_discovered.append(normalized)
                url_modes.setdefault(normalized, set()).add(mode)

                if normalized in existing_urls:
                    already_seen += 1
                    return None

                if mode == "recent" and content_ts is not None:
                    from social_listening.crawl_freshness import is_stale

                    stale = is_stale(content_ts, POLICY)
                    if stale is True:
                        consecutive_stale_content += 1
                        if should_stop_for_validated_stale_content(consecutive_stale_content, POLICY):
                            urls.append(normalized)
                            mode_counts[mode] += 1
                            last_reason = "freshness_boundary"
                            return "freshness_boundary"
                    elif stale is False:
                        consecutive_stale_content = 0

                urls.append(normalized)
                mode_counts[mode] += 1
                if mode_counts[mode] >= mode_budget:
                    mode_full = True
                    last_reason = f"{mode}_budget_reached"
                    return "mode_budget"
                if len(urls) >= MAX_THREADS:
                    last_reason = "max_threads_reached"
                    return "max_threads"
                return None

            for row in card_rows:
                stop = _accept(row["url"], row.get("content_timestamp"))
                if stop:
                    break

            if not card_rows and stop is None:
                for href in get_anchor_hrefs(driver):
                    stop = _accept(normalize_thread_url(href))
                    if stop:
                        break

            if stop in {"freshness_boundary", "max_threads"}:
                break
            if mode_full or stop == "mode_budget":
                break

            idle_rounds = idle_rounds + 1 if len(urls) == before_count else 0
            empty_rounds = empty_rounds + 1 if mode_counts[mode] == 0 and not already_seen else 0
            if scroll_rounds % 5 == 0 or idle_rounds == 0:
                print(
                    f"[threads-search] keyword={keyword} mode={mode} "
                    f"discovered={len(all_discovered)} queued={len(urls)} "
                    f"mode_count={mode_counts[mode]}/{mode_budget} idle={idle_rounds}",
                    flush=True,
                )

            if idle_rounds >= IDLE_ROUNDS_BEFORE_STOP:
                last_reason = "idle_limit"
                break
            if empty_rounds >= MAX_EMPTY_ROUNDS_BEFORE_SKIP:
                last_reason = "empty_limit"
                break

            scroll_search_results(driver)
            time.sleep(SCROLL_PAUSE_SECONDS)

        if last_reason == "freshness_boundary":
            # Recent hit stale boundary; still crawl Top for relevance.
            last_reason = "recent_freshness_boundary"
            continue
        if last_reason in {"keyword_runtime_limit", "runtime_limit", "max_threads_reached"}:
            break

    url_modes_out = {u: sorted(modes) for u, modes in url_modes.items()}
    stats = KeywordCrawlStats(
        keyword=keyword,
        discovered=len(all_discovered),
        new=len(urls),
        stale=consecutive_stale_content,
        already_seen=already_seen,
        runtime_seconds=time.monotonic() - keyword_started,
        stop_reason=last_reason,
        extras={
            "recent_count": mode_counts["recent"],
            "top_count": mode_counts["top"],
            "mode_budget": mode_budget,
        },
    )
    status = "ok" if urls else ("partial" if all_discovered else "no_results")
    if last_reason in {"runtime_limit", "keyword_runtime_limit"} and urls:
        status = "partial"
    return {
        "urls": urls,
        "url_modes": url_modes_out,
        "status": status,
        "reason": last_reason,
        "stats": stats,
    }



def extract_search_cards(driver: webdriver.Chrome) -> list[dict]:
    """Best-effort URL + relative/absolute time labels from Threads search cards."""
    try:
        rows = driver.execute_script(
            """
            const out = [];
            const seen = new Set();
            const anchors = Array.from(document.querySelectorAll('a[href*="/post/"]'));
            for (const a of anchors) {
              const href = a.href || '';
              const m = href.match(/https:\\/\\/www\\.threads\\.(?:net|com)\\/@[^/]+\\/post\\/[^/?#]+/);
              if (!m || seen.has(m[0])) continue;
              seen.add(m[0]);
              let timeLabel = '';
              const root = a.closest('div') || a.parentElement;
              if (root) {
                const timeNode = root.querySelector('time[datetime], time');
                if (timeNode) {
                  timeLabel = timeNode.getAttribute('datetime') || timeNode.getAttribute('title') || timeNode.innerText || '';
                }
                if (!timeLabel) {
                  const aria = root.querySelector('[aria-label]');
                  if (aria) timeLabel = aria.getAttribute('aria-label') || '';
                }
              }
              out.push({ url: m[0], time_label: (timeLabel || '').trim() });
            }
            return out;
            """
        )
    except WebDriverException:
        return []

    if not isinstance(rows, list):
        return []

    from social_listening.review_utils import parse_facebook_datetime_label

    results: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        url = normalize_thread_url(str(row.get("url") or ""))
        if not url:
            continue
        label = str(row.get("time_label") or "").strip()
        content_ts = None
        if label:
            # ISO first
            from social_listening.crawl_freshness import parse_content_timestamp

            content_ts = parse_content_timestamp(label)
            if content_ts is None:
                parsed = parse_facebook_datetime_label(label)
                if parsed is not None:
                    content_ts = parsed
        results.append({"url": url, "content_timestamp": content_ts, "time_label": label})
    return results


def load_existing_results() -> list[dict]:
    if not OUTPUT_FILE.exists():
        return []

    try:
        content = OUTPUT_FILE.read_text(encoding="utf-8")
        results = json.loads(content)
        if not isinstance(results, list):
            return []
        return results
    except Exception as exc:
        print(f"[threads-search] Warning: Could not load existing results: {exc}")
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


def resolve_search_urls(keyword: str) -> list[str]:
    """
    Crawl Recent AND Top.

    Recent: &filter=recent (freshness).
    Top: no filter (relevance — needed for cinema keywords like "rạp galaxy").
    """
    normalized = " ".join(str(keyword or "").strip().lower().split())
    q = quote(keyword)
    recent_urls = [
        f"https://www.threads.com/search?q={q}&filter=recent",
        f"https://www.threads.com/search?q={q}&serp_type=default&filter=recent",
    ]
    if normalized in SPECIAL_SEARCH_URLS:
        recent_urls = list(SPECIAL_SEARCH_URLS[normalized])
    top_urls = [
        f"https://www.threads.com/search?q={q}",
        f"https://www.threads.com/search?q={q}&serp_type=default",
    ]
    out: list[str] = []
    for url in recent_urls + top_urls:
        if url not in out:
            out.append(url)
    return out


def recent_filter_in_url(url: str) -> bool:
    try:
        vals = [v.lower() for v in parse_qs(urlparse(url).query).get("filter", [])]
        return "recent" in vals
    except Exception:
        return False


def recent_search_url(keyword: str) -> str:
    return f"https://www.threads.com/search?q={quote(keyword)}&filter=recent"


def top_search_url(keyword: str) -> str:
    return f"https://www.threads.com/search?q={quote(keyword)}"


def ensure_top_search(driver: webdriver.Chrome, keyword: str) -> str:
    """Stay on Top SERP (no filter=recent)."""
    if not recent_filter_in_url(driver.current_url):
        return "top"
    try:
        driver.get(top_search_url(keyword))
        time.sleep(PAGE_LOAD_WAIT_SECONDS)
        if not recent_filter_in_url(driver.current_url):
            return "top"
    except Exception:
        pass
    return "unavailable"


def ensure_recent_search(driver: webdriver.Chrome, keyword: str) -> str:
    """
    Guarantee Threads Recent SERP.

    Smoke showed: opening with &filter=recent works; clicking the Recent tab from
    Top often leaves results unchanged and does not add filter=recent to the URL.
    """
    if recent_filter_in_url(driver.current_url):
        return "url"

    # Prefer an explicit Recent href if present.
    try:
        for el in driver.find_elements(By.CSS_SELECTOR, "a[href*='filter=recent']")[:4]:
            if not el.is_displayed():
                continue
            driver.execute_script("arguments[0].click();", el)
            time.sleep(PAGE_LOAD_WAIT_SECONDS)
            if recent_filter_in_url(driver.current_url):
                return "ui"
    except Exception:
        pass

    # Label click (EN/VI) — only accept if URL actually gains filter=recent.
    for xpath in (
        "//a[normalize-space()='Recent' or normalize-space()='Mới nhất' or normalize-space()='Latest']",
        "//div[@role='tab' and (normalize-space()='Recent' or normalize-space()='Mới nhất')]",
        "//span[normalize-space()='Recent' or normalize-space()='Mới nhất']/ancestor::a[1]",
    ):
        try:
            for el in driver.find_elements(By.XPATH, xpath)[:3]:
                if not el.is_displayed():
                    continue
                driver.execute_script("arguments[0].click();", el)
                time.sleep(PAGE_LOAD_WAIT_SECONDS)
                if recent_filter_in_url(driver.current_url):
                    return "ui"
        except Exception:
            continue

    # Hard re-open with filter=recent (canonical path).
    try:
        driver.get(recent_search_url(keyword))
        time.sleep(PAGE_LOAD_WAIT_SECONDS)
        if recent_filter_in_url(driver.current_url):
            return "url"
    except Exception:
        pass
    return "unavailable"


def threads_chrome_profile_dir() -> Path:
    return PROJECT_ROOT / "runtime" / "chrome" / "threads"


def ensure_threads_debug_chrome() -> None:
    if chrome_debugger_ready(DEBUGGER_ADDRESS):
        return

    host, port_text = DEBUGGER_ADDRESS.rsplit(":", 1)
    profile_dir = threads_chrome_profile_dir()
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
    print(f"[threads-search] starting debug Chrome on {DEBUGGER_ADDRESS}")
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    for _ in range(30):
        time.sleep(1)
        if chrome_debugger_ready(DEBUGGER_ADDRESS):
            print(f"[threads-search] debug Chrome ready on {DEBUGGER_ADDRESS}")
            return
    raise RuntimeError(
        f"Chrome debug did not start on {DEBUGGER_ADDRESS}. Try manually: {' '.join(cmd)}"
    )


def build_driver() -> webdriver.Chrome:
    ensure_threads_debug_chrome()
    options = Options()
    options.debugger_address = DEBUGGER_ADDRESS
    try:
        # Prefer Selenium Manager (matches installed Chrome).
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
                "--remote-debugging-port=9222 --remote-allow-origins=* "
                f"--user-data-dir={threads_chrome_profile_dir()}"
            ) from exc


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


def normalize_thread_url(url: str) -> str:
    if not url:
        return ""
    match = re.search(r"https://www\.threads\.(?:net|com)/@[^/]+/post/[^/?#]+", url)
    if match:
        return match.group(0)
    return ""


if __name__ == "__main__":
    raise SystemExit(main())
