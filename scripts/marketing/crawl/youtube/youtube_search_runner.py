from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, quote_plus, urlparse

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
from social_listening.paths import DATA_DIR, ensure_dir
from social_listening.crawl_state import IncrementalCrawlState
from social_listening.chromedriver_utils import chrome_debugger_ready, resolve_chromedriver_path
from social_listening.crawl_freshness import KeywordCrawlStats, load_freshness_policy

# Sort / freshness URL params (smoke 2026-09-11, keyword "rạp galaxy"):
# - sp=CAI%3D  Upload date: works but STILL mixes multi-year-old videos at top
# - sp=EgQIAxAB This week: actually surfaces hours/days-old uploads
# - no sp      Relevance: popular/old official cinema intros (what the screenshot showed)
# Prefer This-week + Relevance; keep Upload-date as extra freshness pass.
YOUTUBE_UPLOAD_DATE_SP = "CAI%3D"
YOUTUBE_THIS_WEEK_SP = "EgQIAxAB"
DEBUGGER_ADDRESS = os.getenv("YOUTUBE_DEBUGGER_ADDRESS", "127.0.0.1:9225")
POLICY = load_freshness_policy("youtube")
DISCOVERY_LIMIT = POLICY.discovery_limit
FINAL_LIMIT = POLICY.final_limit
MAX_VIDEOS = DISCOVERY_LIMIT
MAX_SCROLL_ROUNDS = POLICY.max_scroll_rounds
IDLE_ROUNDS_BEFORE_STOP = POLICY.idle_rounds_before_stop
MAX_EMPTY_ROUNDS_BEFORE_SKIP = POLICY.empty_rounds_before_skip
SCROLL_PAUSE_SECONDS = float(os.getenv("YOUTUBE_SCROLL_PAUSE_SECONDS", "2.0"))
PAGE_LOAD_WAIT_SECONDS = float(os.getenv("YOUTUBE_PAGE_LOAD_WAIT_SECONDS", "4.0"))
MAX_RUNTIME_SECONDS = POLICY.max_runtime_seconds
KEYWORD_RUNTIME_SECONDS = POLICY.keyword_runtime_seconds
OUTPUT_FILE = platform_raw_dir("youtube") / "youtube_search_results.json"


def main() -> int:
    search_terms = collect_search_terms(load_keyword_payload())
    keyword_limit = int(os.getenv("YOUTUBE_KEYWORD_LIMIT", "0") or "0")
    if keyword_limit > 0:
        search_terms = search_terms[:keyword_limit]
        print(f"[youtube-search] YOUTUBE_KEYWORD_LIMIT={keyword_limit}")
    if not search_terms:
        raise RuntimeError("No search terms found in shared keyword config")

    with IncrementalCrawlState() as state:
        is_initial = state.is_initial_run("youtube") and state.is_initial_run("youtube_detail")
        run_type = "initial" if is_initial else "incremental"
        existing_urls = state.get_known_urls("youtube", "youtube_detail")

        print(f"[youtube-search] Run type: {run_type}")
        print(f"[youtube-search] Keywords: {len(search_terms)}")
        print(f"[youtube-search] Existing URLs: {len(existing_urls)}")
        print(
            f"[youtube-search] Policy discovery={DISCOVERY_LIMIT} final={FINAL_LIMIT} "
            f"scroll={MAX_SCROLL_ROUNDS} runtime={MAX_RUNTIME_SECONDS}s"
        )
        print(
            "[youtube-search] Note: crawl This-week + Upload-date + Relevance "
            "(Relevance alone looks 'all old'; Upload-date still mixes old; "
            "This-week is the real fresh window); UI filter click is backup only"
        )

        run_id = state.start_run("youtube", run_type)

        driver = build_driver()
        try:
            new_results: list[dict] = []
            global_seen: set[str] = set()
            urls_discovered = 0
            urls_new = 0

            for index, keyword in enumerate(search_terms, start=1):
                print(f"[youtube-search] {index}/{len(search_terms)} keyword={keyword}")
                try:
                    search_result = search_videos_for_keyword_incremental(
                        driver, keyword, existing_urls
                    )
                except Exception as exc:
                    print(f"[youtube-search] skip keyword={keyword} error={exc}")
                    continue

                stats: KeywordCrawlStats = search_result["stats"]
                stats.log("youtube-search")
                urls = search_result["urls"]
                urls_discovered += stats.discovered
                urls_new += len(urls)

                if not urls:
                    print(f"[youtube-search] No new URLs for keyword={keyword}")
                    continue

                for url in urls:
                    if url in global_seen:
                        continue
                    global_seen.add(url)
                    modes = sorted(search_result.get("url_modes", {}).get(url) or [])
                    new_results.append({
                        "keyword": keyword,
                        "url": url,
                        "status": search_result["status"],
                        "reason": search_result.get("reason", ""),
                        "pending_detail": True,
                        "search_modes": modes,
                        "upload_date_filter": search_result.get("upload_date_filter"),
                    })
                    # Do not mark at search time — detail owns coverage + published_at.

            # Merge with existing
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
                keywords_processed=len(search_terms)
            )

            print(f"[youtube-search] Summary:")
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
    """Scroll until idle/empty/safety. Crawl Upload-date AND Relevance SERPs."""
    urls: list[str] = []
    url_modes: dict[str, set[str]] = {}
    seen: set[str] = set()
    all_discovered: list[str] = []
    already_seen = 0
    stop_reason = "no_results"
    keyword_started = time.monotonic()
    mode_budget = max(8, MAX_VIDEOS // 3)
    mode_counts = {"this_week": 0, "upload_date": 0, "relevance": 0}
    upload_filter_ok = False

    for search_url, mode in resolve_search_urls(keyword):
        if time.monotonic() - keyword_started >= KEYWORD_RUNTIME_SECONDS:
            stop_reason = "keyword_runtime_limit"
            break
        if len(urls) >= MAX_VIDEOS:
            stop_reason = "max_videos_reached"
            break
        if mode_counts[mode] >= mode_budget:
            continue

        driver.get(search_url)
        time.sleep(PAGE_LOAD_WAIT_SECONDS)
        dismiss_consent(driver)

        if mode == "this_week":
            via = ensure_sp_sort(driver, keyword, YOUTUBE_THIS_WEEK_SP, mode="this_week")
            print(
                f"[youtube-search] keyword={keyword} mode=this_week this_week_filter="
                f"{'on' if via != 'unavailable' else 'unavailable(fail-soft)'} via={via}",
                flush=True,
            )
        elif mode == "upload_date":
            via = ensure_upload_date_sort(driver, keyword)
            upload_filter_ok = via != "unavailable"
            print(
                f"[youtube-search] keyword={keyword} mode=upload_date upload_date_filter="
                f"{'on' if upload_filter_ok else 'unavailable(fail-soft)'} via={via}",
                flush=True,
            )
        else:
            via = ensure_relevance_sort(driver, keyword)
            print(
                f"[youtube-search] keyword={keyword} mode=relevance relevance_serp="
                f"{'on' if via == 'relevance' else 'unavailable(fail-soft)'} via={via}",
                flush=True,
            )

        started_at = time.monotonic()
        idle_rounds = 0
        empty_rounds = 0
        scroll_rounds = 0
        mode_full = False

        for _ in range(MAX_SCROLL_ROUNDS):
            if mode == "this_week" and not sp_token_in_url(driver.current_url, YOUTUBE_THIS_WEEK_SP):
                ensure_sp_sort(driver, keyword, YOUTUBE_THIS_WEEK_SP, mode="this_week")
            elif mode == "upload_date" and not upload_date_sp_in_url(driver.current_url):
                via = ensure_upload_date_sort(driver, keyword)
                upload_filter_ok = via != "unavailable" or upload_filter_ok
            elif mode == "relevance" and (
                upload_date_sp_in_url(driver.current_url)
                or sp_token_in_url(driver.current_url, YOUTUBE_THIS_WEEK_SP)
            ):
                ensure_relevance_sort(driver, keyword)

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
            for href in get_anchor_hrefs(driver):
                normalized = normalize_youtube_video_url(href)
                if not normalized or normalized in seen:
                    continue
                seen.add(normalized)
                all_discovered.append(normalized)
                url_modes.setdefault(normalized, set()).add(mode)
                if normalized in existing_urls:
                    already_seen += 1
                    continue
                urls.append(normalized)
                mode_counts[mode] += 1
                if mode_counts[mode] >= mode_budget:
                    mode_full = True
                    stop_reason = f"{mode}_budget_reached"
                    break
                if len(urls) >= MAX_VIDEOS:
                    stop_reason = "max_videos_reached"
                    break

            if stop_reason == "max_videos_reached" or mode_full:
                break

            idle_rounds = idle_rounds + 1 if len(urls) == before_count else 0
            empty_rounds = empty_rounds + 1 if mode_counts[mode] == 0 and not already_seen else 0
            if scroll_rounds % 5 == 0 or idle_rounds == 0:
                print(
                    f"[youtube-search] keyword={keyword} mode={mode} "
                    f"discovered={len(all_discovered)} queued={len(urls)} "
                    f"mode_count={mode_counts[mode]}/{mode_budget} idle={idle_rounds}",
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

    url_modes_out = {u: sorted(m) for u, m in url_modes.items()}
    stats = KeywordCrawlStats(
        keyword=keyword,
        discovered=len(all_discovered),
        new=len(urls),
        already_seen=already_seen,
        runtime_seconds=time.monotonic() - keyword_started,
        stop_reason=stop_reason,
        extras={
            "upload_date_filter": upload_filter_ok,
            "this_week_count": mode_counts["this_week"],
            "upload_date_count": mode_counts["upload_date"],
            "relevance_count": mode_counts["relevance"],
            "mode_budget": mode_budget,
        },
    )
    status = "ok" if urls else ("partial" if all_discovered else "no_results")
    if stop_reason in {"runtime_limit", "keyword_runtime_limit"} and urls:
        status = "partial"
    # Leave browser on This-week so a watching human sees fresh results, not Relevance old hits.
    try:
        driver.get(this_week_search_url(keyword))
        time.sleep(1.0)
    except Exception:
        pass
    return {
        "urls": urls,
        "url_modes": url_modes_out,
        "status": status,
        "reason": stop_reason,
        "stats": stats,
        "upload_date_filter": upload_filter_ok,
    }



def resolve_search_urls(keyword: str) -> list[tuple[str, str]]:
    """Return (url, mode): This-week first (fresh), then Upload-date, then Relevance."""
    q = quote_plus(keyword)
    return [
        (f"https://www.youtube.com/results?search_query={q}&sp={YOUTUBE_THIS_WEEK_SP}", "this_week"),
        (f"https://www.youtube.com/results?search_query={q}&sp={YOUTUBE_UPLOAD_DATE_SP}", "upload_date"),
        (f"https://www.youtube.com/results?search_query={q}", "relevance"),
    ]


def sp_token_in_url(url: str, token: str) -> bool:
    """True if URL sp param contains the given token (handles % encoding variants)."""
    try:
        from urllib.parse import unquote

        needle = unquote(unquote(token)).replace("=", "")
        for raw in parse_qs(urlparse(url).query).get("sp", []):
            decoded = unquote(unquote(raw)).replace("=", "")
            if needle and needle in decoded:
                return True
            if token in raw or unquote(token) in raw:
                return True
    except Exception:
        pass
    return False


def upload_date_sp_in_url(url: str) -> bool:
    return sp_token_in_url(url, YOUTUBE_UPLOAD_DATE_SP) or sp_token_in_url(url, "CAI=")


def upload_date_search_url(keyword: str) -> str:
    return f"https://www.youtube.com/results?search_query={quote_plus(keyword)}&sp={YOUTUBE_UPLOAD_DATE_SP}"


def this_week_search_url(keyword: str) -> str:
    return f"https://www.youtube.com/results?search_query={quote_plus(keyword)}&sp={YOUTUBE_THIS_WEEK_SP}"


def relevance_search_url(keyword: str) -> str:
    return f"https://www.youtube.com/results?search_query={quote_plus(keyword)}"


def dismiss_consent(driver: webdriver.Chrome) -> None:
    try:
        driver.execute_script(
            """
            for (const b of document.querySelectorAll('button, tp-yt-paper-button')) {
              const t = (b.innerText || '').toLowerCase();
              if (t.includes('accept') || t.includes('agree') || t.includes('đồng ý') || t.includes('reject all')) {
                b.click();
                return true;
              }
            }
            return false;
            """
        )
    except Exception:
        pass


def ensure_sp_sort(driver: webdriver.Chrome, keyword: str, sp: str, *, mode: str) -> str:
    """Navigate to search URL with the given sp filter; return via=url|unavailable."""
    if sp_token_in_url(driver.current_url, sp):
        return "url"
    try:
        driver.get(f"https://www.youtube.com/results?search_query={quote_plus(keyword)}&sp={sp}")
        time.sleep(PAGE_LOAD_WAIT_SECONDS)
        dismiss_consent(driver)
        if sp_token_in_url(driver.current_url, sp):
            return "url"
    except Exception:
        pass
    return "unavailable"


def ensure_relevance_sort(driver: webdriver.Chrome, keyword: str) -> str:
    if not upload_date_sp_in_url(driver.current_url) and not sp_token_in_url(
        driver.current_url, YOUTUBE_THIS_WEEK_SP
    ):
        return "relevance"
    try:
        driver.get(relevance_search_url(keyword))
        time.sleep(PAGE_LOAD_WAIT_SECONDS)
        dismiss_consent(driver)
        if not upload_date_sp_in_url(driver.current_url) and not sp_token_in_url(
            driver.current_url, YOUTUBE_THIS_WEEK_SP
        ):
            return "relevance"
    except Exception:
        pass
    return "unavailable"


def ensure_upload_date_sort(driver: webdriver.Chrome, keyword: str) -> str:
    """Force Upload-date sort via URL first; UI chip/menu is backup only."""
    if upload_date_sp_in_url(driver.current_url):
        return "url"

    # UI backup: Filters → Upload date / Recently uploaded / Tải lên gần đây
    if ensure_upload_date_filter(driver) and upload_date_sp_in_url(driver.current_url):
        return "ui"
    # Even if UI clicked without updating sp, accept UI success if function returned True
    # but prefer hard URL:
    try:
        driver.get(upload_date_search_url(keyword))
        time.sleep(PAGE_LOAD_WAIT_SECONDS)
        dismiss_consent(driver)
        if upload_date_sp_in_url(driver.current_url):
            return "url"
    except Exception:
        pass
    return "unavailable"


def ensure_upload_date_filter(driver: webdriver.Chrome) -> bool:
    """Bộ lọc → Recently uploaded / Upload date / Tải lên gần đây. Fail-soft."""
    try:
        opened = driver.execute_script(
            """
            const labels = ['Search filters', 'Filters', 'Bộ lọc', 'Filter'];
            const nodes = Array.from(document.querySelectorAll(
              'button, yt-chip-cloud-chip-renderer, [aria-label]'
            ));
            for (const el of nodes) {
              const text = ((el.getAttribute('aria-label') || '') + ' ' + (el.innerText || '')).trim();
              if (!text) continue;
              if (labels.some((l) => text.toLowerCase().includes(l.toLowerCase()))) {
                el.click();
                return true;
              }
            }
            return false;
            """
        )
        if opened:
            time.sleep(1.0)
        clicked = driver.execute_script(
            """
            const preferred = [
              'Recently uploaded', 'Upload date', 'Tải lên gần đây', 'Ngày tải lên'
            ];
            const fallback = ['This week', 'Tuần này', 'Today', 'Hôm nay'];
            const nodes = Array.from(document.querySelectorAll(
              'yt-formatted-string, tp-yt-paper-item, a, yt-chip-cloud-chip-renderer, span'
            ));
            const clickMatch = (wanted) => {
              for (const el of nodes) {
                const text = (el.innerText || el.textContent || '').trim();
                if (!text) continue;
                if (wanted.some((w) => text === w || text.includes(w))) {
                  el.click();
                  return true;
                }
              }
              return false;
            };
            if (clickMatch(preferred)) return true;
            return clickMatch(fallback);
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


def youtube_chrome_profile_dir() -> Path:
    return PROJECT_ROOT / "runtime" / "chrome" / "youtube"


def ensure_youtube_debug_chrome() -> None:
    if chrome_debugger_ready(DEBUGGER_ADDRESS):
        return
    host, port_text = DEBUGGER_ADDRESS.rsplit(":", 1)
    profile_dir = youtube_chrome_profile_dir()
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
    print(f"[youtube-search] starting debug Chrome on {DEBUGGER_ADDRESS}")
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    for _ in range(30):
        time.sleep(1)
        if chrome_debugger_ready(DEBUGGER_ADDRESS):
            print(f"[youtube-search] debug Chrome ready on {DEBUGGER_ADDRESS}")
            return
    raise RuntimeError(
        f"Chrome debug did not start on {DEBUGGER_ADDRESS}. Try manually: {' '.join(cmd)}"
    )


def build_driver() -> webdriver.Chrome:
    ensure_youtube_debug_chrome()
    options = Options()
    options.debugger_address = DEBUGGER_ADDRESS
    options.add_argument("--lang=vi-VN")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--window-size=1440,2200")
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
                "--remote-debugging-port=9225 --remote-allow-origins=* "
                f"--user-data-dir={youtube_chrome_profile_dir()}"
            ) from exc



def scroll_search_results(driver: webdriver.Chrome) -> None:
    driver.execute_script("window.scrollBy(0, window.innerHeight * 1.5);")
    body = driver.find_element(By.TAG_NAME, "body")
    body.send_keys(Keys.END)


def get_anchor_hrefs(driver: webdriver.Chrome) -> list[str]:
    try:
        hrefs = driver.execute_script(
            """
            return Array.from(document.querySelectorAll('a#video-title, a[href*="/watch?v="]'))
              .map((anchor) => anchor.href || '')
              .filter(Boolean);
            """
        )
    except WebDriverException:
        return []
    return [str(href).strip() for href in hrefs if str(href).strip()]


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
