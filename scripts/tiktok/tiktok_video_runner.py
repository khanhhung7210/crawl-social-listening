from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from selenium import webdriver
from selenium.common.exceptions import SessionNotCreatedException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from social_listening.keyword_config import collect_search_terms, load_keyword_payload
from social_listening.film_paths import platform_raw_dir
from social_listening.paths import DATA_DIR, ensure_dir
from social_listening.text_utils import contains_keyword, normalize_text


DEBUGGER_ADDRESS = os.getenv("TIKTOK_DEBUGGER_ADDRESS", "127.0.0.1:9223")
VIDEO_URL = ""
FILTERED_INPUT_FILE = platform_raw_dir("tiktok") / "tiktok_search_results_filtered.json"
INPUT_FILE = platform_raw_dir("tiktok") / "tiktok_search_results.json"
LEGACY_FILTERED_INPUT_FILE = DATA_DIR / "tiktok" / "raw" / "tiktok_search_results_filtered.json"
LEGACY_INPUT_FILE = DATA_DIR / "tiktok" / "raw" / "tiktok_search_results.json"
SCROLL_SECONDS_PER_VIDEO = 8
OUTPUT_FILE = platform_raw_dir("tiktok") / "tiktok_all_videos.json"
COMMENT_IDLE_ROUNDS_BEFORE_STOP = 6
MAX_COMMENT_SCROLL_ROUNDS = 80
INITIAL_VIDEO_WAIT_SECONDS = float(os.getenv("TIKTOK_INITIAL_VIDEO_WAIT_SECONDS", "6"))
CAPTCHA_WAIT_SECONDS = float(os.getenv("TIKTOK_CAPTCHA_WAIT_SECONDS", "20"))
COMMENT_PANEL_WAIT_SECONDS = float(os.getenv("TIKTOK_COMMENT_PANEL_WAIT_SECONDS", "2.5"))
COMMENT_SCROLL_PAUSE_SECONDS = float(os.getenv("TIKTOK_COMMENT_SCROLL_PAUSE_SECONDS", "2.8"))


def main() -> int:
    search_terms = collect_search_terms(load_keyword_payload())
    input_file = resolve_input_file()
    video_urls = load_video_urls(input_file)
    if not video_urls and VIDEO_URL.strip():
        video_urls = [{"keyword": "", "url": normalize_tiktok_video_url(VIDEO_URL.strip())}]

    video_urls = [item for item in video_urls if item.get("url")]
    if not video_urls:
        raise RuntimeError("No TikTok video URLs found.")

    print(f"using tiktok input file: {input_file}")

    output_path = OUTPUT_FILE
    records = load_existing_records(output_path)
    existing_urls = collect_existing_video_urls(records)
    pending_urls = [item for item in video_urls if item["url"] not in existing_urls]

    if not pending_urls:
        print(f"no pending videos; {len(records)} records already saved in {output_path.resolve()}")
        return 0

    driver = build_driver()
    try:
        total = len(pending_urls)
        for index, item in enumerate(pending_urls, start=1):
            url = item["url"]
            keyword = item["keyword"]
            try:
                record = crawl_video(driver, url, keyword, search_terms)
            except Exception as exc:
                record = {
                    "keyword": keyword,
                    "url": url,
                    "matched": False,
                    "error": str(exc),
                }
            records.append(record)
            save_records(output_path, records)
            print(f"[{index}/{total}] saved {url}")

        print(f"saved {len(records)} total video payloads to {output_path.resolve()}")
        return 0
    finally:
        driver.quit()


def resolve_input_file() -> Path:
    for path in (FILTERED_INPUT_FILE, INPUT_FILE, LEGACY_FILTERED_INPUT_FILE, LEGACY_INPUT_FILE):
        if path.exists():
            return path
    return FILTERED_INPUT_FILE


def load_video_urls(path: Path) -> list[dict]:
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
        url = normalize_tiktok_video_url(str(item.get("url") or "").strip())
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


def collect_existing_video_urls(records: list[dict]) -> set[str]:
    urls: set[str] = set()
    for item in records:
        if not isinstance(item, dict):
            continue
        for raw_url in (item.get("current_url"), item.get("url")):
            url = normalize_tiktok_video_url(str(raw_url or "").strip())
            if url:
                urls.add(url)
    return urls


def save_records(path: Path, records: list[dict]) -> None:
    deduped_records = dedupe_records(records)
    ensure_dir(path.parent)
    path.write_text(
        json.dumps(deduped_records, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def dedupe_records(records: list[dict]) -> list[dict]:
    deduped: list[dict] = []
    seen_urls: set[str] = set()
    for item in records:
        if not isinstance(item, dict):
            continue
        normalized_url = ""
        for raw_url in (item.get("current_url"), item.get("url")):
            normalized_url = normalize_tiktok_video_url(str(raw_url or "").strip())
            if normalized_url:
                break

        if normalized_url:
            if normalized_url in seen_urls:
                continue
            seen_urls.add(normalized_url)

        deduped.append(item)
    return deduped


def crawl_video(driver: webdriver.Chrome, url: str, keyword: str, search_terms: list[str]) -> dict:
    driver.get(url)
    wait_for_tiktok_side_panel(driver, timeout=max(INITIAL_VIDEO_WAIT_SECONDS, 6))
    time.sleep(INITIAL_VIDEO_WAIT_SECONDS)

    if has_captcha_or_challenge(driver):
        print(f"[tiktok] captcha/challenge detected, waiting on {url}")
        time.sleep(CAPTCHA_WAIT_SECONDS)
        wait_for_tiktok_side_panel(driver, timeout=max(CAPTCHA_WAIT_SECONDS, 10))

    # focus video để TikTok render panel ổn định hơn
    driver.execute_script("""
    const videoArea =
        document.querySelector('video') ||
        document.querySelector('[data-e2e*="browse-video"]') ||
        document.querySelector('[class*="DivPlayerContainer"]');
    if (videoArea) videoArea.click();
    """)
    time.sleep(COMMENT_PANEL_WAIT_SECONDS)

    page_source = driver.page_source
    body_text = driver.execute_script("return document.body ? document.body.innerText : '';") or ""
    page_title = driver.title or ""
    current_url = driver.current_url or url
    crawled_at = datetime.now(timezone.utc).isoformat()
    matched_terms = [term for term in search_terms if contains_keyword(normalize_text(body_text), term)]
    matched = bool(matched_terms)

    comments = crawl_comments(driver)

    return {
        "keyword": keyword,
        "url": url,
        "current_url": current_url,
        "title": page_title,
        "crawled_at": crawled_at,
        "matched": matched,
        "matched_terms": matched_terms,
        "comment_count_observed": len(comments),
        "crawled_comments": comments,
        "body_text": body_text,
        "raw_html": page_source,
        "linked_videos": sorted(set(re.findall(r"https://www\.tiktok\.com/@[^/]+/video/\d+", page_source))),
    }


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


def normalize_tiktok_video_url(url: str) -> str:
    match = re.search(r"https://www\.tiktok\.com/@[^/]+/video/\d+", url or "")
    return match.group(0) if match else ""


def crawl_comments(driver: webdriver.Chrome) -> list[dict]:
    ensure_comments_panel_open(driver)
    time.sleep(COMMENT_PANEL_WAIT_SECONDS)

    comments: dict[str, dict] = {}
    idle_rounds = 0

    for _ in range(MAX_COMMENT_SCROLL_ROUNDS):
        # nếu TikTok reset về You may like thì ép lại Comments
        if not is_comments_tab_active(driver):
            ensure_comments_panel_open(driver)
            time.sleep(COMMENT_PANEL_WAIT_SECONDS)
            if not is_comments_tab_active(driver):
                break

        before_count = len(comments)

        extracted = extract_comments_from_dom(driver)
        for comment in extracted:
            external_id = str(comment.get("external_id") or "").strip()
            if external_id:
                comments.setdefault(external_id, comment)

        container = find_comment_container(driver)
        moved = scroll_comment_container(driver, container)
        if moved:
            time.sleep(COMMENT_SCROLL_PAUSE_SECONDS)
        else:
            time.sleep(COMMENT_PANEL_WAIT_SECONDS)

        # sau khi scroll, tab có thể bị reset tiếp
        if not is_comments_tab_active(driver):
            ensure_comments_panel_open(driver)
            time.sleep(COMMENT_PANEL_WAIT_SECONDS)

        refreshed = extract_comments_from_dom(driver)
        for comment in refreshed:
            external_id = str(comment.get("external_id") or "").strip()
            if external_id:
                comments.setdefault(external_id, comment)

        if len(comments) > before_count:
            idle_rounds = 0
        else:
            idle_rounds += 1

        if not moved and idle_rounds >= 2:
            break

        if idle_rounds >= COMMENT_IDLE_ROUNDS_BEFORE_STOP:
            break

    return list(comments.values())

from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait

def ensure_comments_panel_open(driver: webdriver.Chrome) -> None:
    for i in range(6):
        if is_comments_tab_active(driver):
            return

        items = driver.find_elements(By.CSS_SELECTOR, ".TUXTabBar-item")
        target = None

        for el in items:
            text = (el.text or "").strip().lower()
            if "comments" in text or "bình luận" in text:
                target = el
                break

        if not target:
            return

        try:
            driver.execute_script("arguments[0].scrollIntoView({block:'center', inline:'center'});", target)
            time.sleep(COMMENT_PANEL_WAIT_SECONDS / 2)

            # click thật bằng selenium
            ActionChains(driver).move_to_element(target).pause(0.2).click(target).perform()

            # thử click thêm vào title con nếu cần
            try:
                title = target.find_element(By.CSS_SELECTOR, ".TUXTabBar-itemTitle")
                ActionChains(driver).move_to_element(title).pause(0.2).click(title).perform()
            except Exception:
                pass

            try:
                WebDriverWait(driver, 2).until(lambda d: is_comments_tab_active(d))
                return
            except Exception:
                active = driver.execute_script("""
                    const el = document.querySelector('.TUXTabBar-itemTitle--active, .TUXTabBar-item--active');
                    return el ? (el.innerText || el.textContent || '').trim().toLowerCase() : '';
                """)

        except Exception as exc:
            print("selenium click failed:", exc)


def has_captcha_or_challenge(driver: webdriver.Chrome) -> bool:
    try:
        body_text = (driver.execute_script("return document.body ? document.body.innerText : '';") or "").lower()
    except Exception:
        return False

    patterns = (
        "captcha",
        "verify to continue",
        "security check",
        "complete the puzzle",
        "slide to verify",
        "too many attempts",
        "something went wrong",
    )
    return any(pattern in body_text for pattern in patterns)

def is_comments_tab_active(driver: webdriver.Chrome) -> bool:
    return bool(driver.execute_script("""
        function norm(s) {
            return (s || '').replace(/\\s+/g, ' ').trim().toLowerCase();
        }

        const active = document.querySelector('.TUXTabBar-itemTitle--active, .TUXTabBar-item--active');
        if (!active) return false;

        const text = norm(active.innerText || active.textContent || active.getAttribute('aria-label'));
        return text.includes('comments') || text.includes('bình luận');
    """))

def find_comment_container(driver: webdriver.Chrome):
    return driver.execute_script(
        """
        const commentSelectors = [
            '[data-e2e="comment-level-1"]',
            '[data-e2e="comment-item"]',
            '[class*="DivCommentItemContainer"]',
            '[class*="CommentItem"]',
        ];
        const elements = [...document.querySelectorAll('*')];
        let best = null;
        let bestScore = 0;
        for (const el of elements) {
            if (!el) continue;
            const style = window.getComputedStyle(el);
            const canScroll = /(auto|scroll)/.test(style.overflowY || '') && el.scrollHeight > el.clientHeight;
            if (!canScroll) continue;
            const text = (el.innerText || '').trim();
            const rect = el.getBoundingClientRect();
            const visible = rect.width > 200 && rect.height > 120;
            if (!visible) continue;
            const commentItemCount = commentSelectors.reduce(
                (count, selector) => count + el.querySelectorAll(selector).length,
                0
            );
            if (commentItemCount === 0) continue;
            const score =
                commentItemCount * 25 +
                ((/comment|comments|bình luận|reply|trả lời/i.test(text) ? 25 : 0)) +
                Math.min(el.scrollHeight - el.clientHeight, 5000) / 100 +
                Math.min(text.length, 5000) / 200;
            if (score > bestScore) {
                best = el;
                bestScore = score;
            }
        }
        return best;
        """
    )


def scroll_comment_container(driver: webdriver.Chrome, container) -> bool:
    if container is None:
        return False

    return bool(
        driver.execute_script(
            """
            const el = arguments[0];
            if (!el) return false;

            const before = el.scrollTop;
            const maxScrollTop = el.scrollHeight - el.clientHeight;

            el.scrollTop = Math.min(
                el.scrollTop + Math.max(el.clientHeight * 0.85, 400),
                maxScrollTop
            );

            return el.scrollTop !== before;
            """,
            container,
        )
    )

def wait_for_tiktok_side_panel(driver: webdriver.Chrome, timeout: int = 15) -> None:
    wait = WebDriverWait(driver, timeout)

    def ready(d):
        return d.execute_script(
            """
            const text = (document.body?.innerText || '').toLowerCase();
            const hasTab =
                Array.from(document.querySelectorAll('.TUXTabBar-item, .TUXTabBar-itemTitle, div, span, button, a'))
                    .some(n => {
                        const t = (n.innerText || n.textContent || n.getAttribute('aria-label') || '')
                            .replace(/\\s+/g, ' ')
                            .trim()
                            .toLowerCase();
                        return t.includes('comments') || t.includes('comment') || t.includes('bình luận') || t.includes('you may like');
                    });

            const hasCommentItem =
                document.querySelector('[data-e2e="comment-level-1"]') ||
                document.querySelector('[data-e2e="comment-item"]') ||
                document.querySelector('[class*="CommentItem"]');

            const hasBody = text.length > 100;

            return hasTab || hasCommentItem || hasBody;
            """
        )

    wait.until(ready)


def extract_comments_from_dom(driver: webdriver.Chrome) -> list[dict]:
    raw_comments = driver.execute_script(
        """
        const selectors = [
            '[data-e2e="comment-level-1"]',
            '[data-e2e="comment-item"]',
            '[class*="DivCommentItemContainer"]',
            '[class*="CommentItem"]',
        ];

        const nodes = [];
        const seen = new Set();
        for (const selector of selectors) {
            for (const node of document.querySelectorAll(selector)) {
                if (seen.has(node)) continue;
                seen.add(node);
                nodes.push(node);
            }
        }

        const actionWords = new Set([
            'like', 'reply', 'replies', 'bình luận', 'trả lời', 'thích', 'xem thêm', 'see more',
            'view replies', 'view more replies'
        ]);
        const timePattern = /^((\\d+)(s|m|h|d|w|mo|y))\\s+ago$/i;
        const compactTimePattern = /^(\\d+)(s|m|h|d|w|mo|y)$/i;
        const metricPattern = /^[\\d,.]+$/;

        const results = [];
        for (const node of nodes) {
            const rect = node.getBoundingClientRect();
            if (rect.width === 0 || rect.height === 0) continue;

            const rawText = (node.innerText || '').trim();
            if (!rawText) continue;

            const authorNode = node.querySelector('a[href*="/@"], h3, [data-e2e*="comment-username"]');
            const author = (authorNode ? authorNode.innerText : '').trim();

            const lines = rawText
                .split('\\n')
                .map((line) => line.trim())
                .filter(Boolean)
                .filter((line) => !actionWords.has(line.toLowerCase()));

            let createdAtLabel = '';
            let text = '';
            for (const line of lines) {
                if (!text && author && line === author) continue;
                const compact = line.toLowerCase().replace(/\\s+/g, '');
                if (timePattern.test(line.toLowerCase()) || compactTimePattern.test(compact)) {
                    if (!createdAtLabel) {
                        createdAtLabel = compactTimePattern.test(compact) ? compact : line.toLowerCase();
                    }
                    continue;
                }
                if (metricPattern.test(line)) continue;
                text = text ? `${text} ${line}` : line;
            }
            text = text.trim();
            if (!text || text === author) continue;

            const rawId =
                node.getAttribute('data-id') ||
                node.getAttribute('data-e2e') ||
                node.id ||
                `${author}|${text.slice(0, 80)}`;

            results.push({
                external_id: `comment:${rawId}`,
                record_type: 'comment',
                author: author,
                text: text,
                created_at: '',
                created_at_label: createdAtLabel,
                parent_comment_id: '',
                keyword_match: false,
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
        comments.append(
            {
                "external_id": str(item.get("external_id") or ""),
                "record_type": str(item.get("record_type") or "comment"),
                "author": str(item.get("author") or ""),
                "text": str(item.get("text") or "").strip(),
                "created_at": normalize_iso_datetime(str(item.get("created_at") or "")),
                "created_at_label": str(item.get("created_at_label") or "").strip(),
                "parent_comment_id": str(item.get("parent_comment_id") or "").strip(),
                "keyword_match": bool(item.get("keyword_match")),
                "source": str(item.get("source") or "dom"),
            }
        )
    return comments


def normalize_iso_datetime(value: str) -> str:
    if not value:
        return ""
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
    except Exception:
        return ""


if __name__ == "__main__":
    raise SystemExit(main())
