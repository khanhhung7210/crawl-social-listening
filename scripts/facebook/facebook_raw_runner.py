from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from selenium import webdriver
from selenium.common.exceptions import InvalidSessionIdException, SessionNotCreatedException, WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from webdriver_manager.chrome import ChromeDriverManager

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from social_listening.film_paths import film_slug
from social_listening.keyword_config import collect_search_terms, load_keyword_payload
from social_listening.paths import DATA_DIR, ensure_dir
from social_listening.crawl_state import IncrementalCrawlState


FACEBOOK_SEARCH_URLS = [
    "https://www.facebook.com/search/posts?q={query}",
    "https://www.facebook.com/search/posts/?q={query}",
    "https://www.facebook.com/search/top/?q={query}",
]
DEBUGGER_ADDRESS = os.getenv("FACEBOOK_DEBUGGER_ADDRESS", "127.0.0.1:9226")
OUTPUT_ROOT = DATA_DIR / "facebook" / "raw" / film_slug()
MAX_POSTS = int(os.getenv("FACEBOOK_MAX_POSTS", "100"))
MAX_POSTS_PER_KEYWORD = int(os.getenv("FACEBOOK_MAX_POSTS_PER_KEYWORD", str(MAX_POSTS)))
MAX_SCROLL_ROUNDS = int(os.getenv("FACEBOOK_MAX_SCROLL_ROUNDS", "80"))
IDLE_ROUNDS_BEFORE_STOP = int(os.getenv("FACEBOOK_IDLE_ROUNDS_BEFORE_STOP", "8"))
MAX_EMPTY_ROUNDS_BEFORE_SKIP = int(os.getenv("FACEBOOK_MAX_EMPTY_ROUNDS_BEFORE_SKIP", "5"))
SCROLL_PAUSE_SECONDS = float(os.getenv("FACEBOOK_SCROLL_PAUSE_SECONDS", "2.0"))
PAGE_LOAD_WAIT_SECONDS = float(os.getenv("FACEBOOK_PAGE_LOAD_WAIT_SECONDS", "5.0"))
POST_LOAD_WAIT_SECONDS = float(os.getenv("FACEBOOK_POST_LOAD_WAIT_SECONDS", "3.0"))
MAX_COMMENTS = int(os.getenv("FACEBOOK_MAX_COMMENTS", "200"))
COMMENT_LOAD_ROUNDS = int(os.getenv("FACEBOOK_COMMENT_LOAD_ROUNDS", "24"))
COMMENT_IDLE_ROUNDS_BEFORE_STOP = int(os.getenv("FACEBOOK_COMMENT_IDLE_ROUNDS_BEFORE_STOP", "5"))
COMMENT_LOAD_PAUSE_SECONDS = float(os.getenv("FACEBOOK_COMMENT_LOAD_PAUSE_SECONDS", "1.75"))
DEBUG_COMMENT_LOADING = str(os.getenv("FACEBOOK_DEBUG_COMMENTS", "")).strip().lower() in {"1", "true", "yes", "on"}

META_DATE_SELECTORS = [
    "meta[property='article:published_time']",
    "meta[name='article:published_time']",
    "meta[property='og:updated_time']",
]
META_DESCRIPTION_SELECTORS = [
    "meta[property='og:description']",
    "meta[name='description']",
]


def main() -> int:
    search_terms = collect_search_terms(load_keyword_payload())
    if not search_terms:
        raise RuntimeError("No search terms found in shared keyword config")

    with IncrementalCrawlState() as state:
        # Load existing URLs from state (global deduplication across runs)
        existing_urls = state.get_existing_urls("facebook")
        is_initial = state.is_initial_run("facebook")
        run_type = "initial" if is_initial else "incremental"

        print(f"[facebook-search] Run type: {run_type}")
        print(f"[facebook-search] Keywords: {len(search_terms)}")
        print(f"[facebook-search] Existing URLs in state: {len(existing_urls)}")
        print(f"[facebook-search] ⚠️  Note: Facebook search is non-chronological, cannot early-stop")

        run_id = state.start_run("facebook", run_type)

        driver = build_driver()
        try:
            today_str = datetime.now().strftime("%Y%m%d")
            output_dir = ensure_dir(OUTPUT_ROOT / today_str)

            processed_keywords = 0
            session_crawled_urls: set[str] = set()  # Dedupe within this session
            session_crawled_post_keys: set[str] = set()
            total_urls_discovered = 0
            total_urls_crawled = 0
            total_urls_skipped = 0

            for index, keyword in enumerate(search_terms, start=1):
                safe_keyword = sanitize_filename(keyword) or f"keyword_{index}"
                file_path = output_dir / f"search_{safe_keyword}.jsonl"

                # Check if keyword file already exists from today
                if file_path.exists() and file_path.stat().st_size > 0:
                    print(f"[facebook-search] skip keyword={keyword} existing_file={file_path.name}")
                    processed_keywords += 1
                    continue

                print(f"[facebook-search] {index}/{len(search_terms)} keyword={keyword}")
                try:
                    search_result = search_posts_for_keyword(driver, keyword)
                except Exception as exc:
                    print(f"[facebook-search] skip keyword={keyword} error={exc}")
                    processed_keywords += 1
                    continue

                # Dedupe URLs: session + global state
                keyword_urls = []
                for url in search_result["urls"]:
                    if url in session_crawled_urls or url in existing_urls:
                        total_urls_skipped += 1
                        continue
                    session_crawled_urls.add(url)
                    keyword_urls.append(url)

                total_urls_discovered += len(search_result["urls"])

                print(
                    f"[facebook-search] keyword={keyword} discovered={len(search_result['urls'])} "
                    f"new={len(keyword_urls)} skipped={len(search_result['urls']) - len(keyword_urls)}"
                )

                # Crawl details for new URLs only
                posts: list[dict] = []
                for url_index, url in enumerate(keyword_urls[:MAX_POSTS_PER_KEYWORD], start=1):
                    if url_index % 10 == 0:
                        print(
                            f"[facebook-search] keyword={keyword} crawling detail "
                            f"{url_index}/{min(len(keyword_urls), MAX_POSTS_PER_KEYWORD)}"
                        )

                    driver, post = crawl_post_with_retries(driver, url)
                    if not post:
                        continue

                    post_key = canonical_post_key(post)
                    if post_key and post_key in session_crawled_post_keys:
                        continue
                    if post_key:
                        session_crawled_post_keys.add(post_key)

                    posts.append(post)
                    total_urls_crawled += 1

                    # Mark URL as crawled in state
                    content_timestamp = post.get("created_time")
                    state.mark_crawled(url, "facebook", keyword, content_timestamp)

                # Save keyword results to JSONL
                with file_path.open("w", encoding="utf-8") as file:
                    if posts:
                        file.write("\n".join(json.dumps(post, ensure_ascii=False) for post in posts) + "\n")

                print(
                    f"[facebook-search] finished keyword={keyword} status={search_result['status']} "
                    f"reason={search_result.get('reason', '')} new_urls={len(keyword_urls)} "
                    f"posts_crawled={len(posts)} file={file_path.name}"
                )
                processed_keywords += 1

            # Complete run tracking
            state.complete_run(
                run_id,
                urls_discovered=total_urls_discovered,
                urls_crawled=total_urls_crawled,
                urls_skipped=total_urls_skipped,
                keywords_processed=processed_keywords
            )

            print(f"\n[facebook-search] Summary:")
            print(f"  - Output directory: {output_dir.resolve()}")
            print(f"  - Keywords processed: {processed_keywords}/{len(search_terms)}")
            print(f"  - URLs discovered: {total_urls_discovered}")
            print(f"  - URLs crawled (detail): {total_urls_crawled}")
            print(f"  - URLs skipped (already had): {total_urls_skipped}")
            print(f"  - Total URLs in state: {len(existing_urls) + total_urls_crawled}")
            return 0
        finally:
            driver.quit()


def search_posts_for_keyword(driver: webdriver.Chrome, keyword: str) -> dict:
    load_search_results(driver, keyword)

    urls: list[str] = []
    seen: set[str] = set()
    idle_rounds = 0
    empty_rounds = 0

    for _ in range(MAX_SCROLL_ROUNDS):
        before_count = len(urls)
        for raw_href in get_anchor_hrefs(driver):
            href = normalize_post_url(raw_href)
            if not href or href in seen:
                continue
            seen.add(href)
            urls.append(href)
            if len(urls) >= MAX_POSTS:
                return {"urls": urls, "status": "ok", "reason": "max_posts_reached"}

        idle_rounds = idle_rounds + 1 if len(urls) == before_count else 0
        empty_rounds = empty_rounds + 1 if not urls else 0
        print(
            f"[facebook-search] keyword={keyword} discovered_urls={len(urls)} "
            f"idle_rounds={idle_rounds} empty_rounds={empty_rounds}",
            flush=True,
        )
        if idle_rounds >= IDLE_ROUNDS_BEFORE_STOP:
            return {"urls": urls, "status": "partial" if urls else "no_results", "reason": "idle_limit"}
        if empty_rounds >= MAX_EMPTY_ROUNDS_BEFORE_SKIP:
            return {"urls": urls, "status": "partial" if urls else "no_results", "reason": "empty_limit"}

        scroll_search_results(driver)
        time.sleep(SCROLL_PAUSE_SECONDS)

    return {"urls": urls, "status": "ok" if urls else "no_results", "reason": "scroll_exhausted"}


def load_search_results(driver: webdriver.Chrome, keyword: str) -> None:
    encoded_query = quote(keyword)
    last_error = ""

    for template in FACEBOOK_SEARCH_URLS:
        driver.get(template.format(query=encoded_query))
        time.sleep(PAGE_LOAD_WAIT_SECONDS)
        dismiss_dialogs(driver)
        time.sleep(1)

        if page_looks_like_not_found(driver):
            last_error = f"not_found:{template}"
            continue

        if ensure_posts_context(driver, keyword):
            return

        last_error = f"posts_tab_unavailable:{template}"

    raise RuntimeError(f"Unable to open Facebook post search for keyword={keyword} ({last_error})")


def ensure_posts_context(driver: webdriver.Chrome, keyword: str) -> bool:
    if has_post_links(driver):
        return True

    for xpath in (
        "//a[contains(@href, '/search/posts') or contains(@href, '/posts/?q=')]",
        "//span[normalize-space()='Posts']/ancestor::a[1]",
        "//span[normalize-space()='Bài viết']/ancestor::a[1]",
        "//div[@role='tab']//span[normalize-space()='Posts']/ancestor::*[@role='tab'][1]",
        "//div[@role='tab']//span[normalize-space()='Bài viết']/ancestor::*[@role='tab'][1]",
    ):
        try:
            elements = driver.find_elements(By.XPATH, xpath)
            for element in elements[:2]:
                if not element.is_displayed():
                    continue
                driver.execute_script("arguments[0].click();", element)
                time.sleep(PAGE_LOAD_WAIT_SECONDS)
                dismiss_dialogs(driver)
                if has_post_links(driver):
                    return True
        except Exception:
            continue

    return submit_search_from_input(driver, keyword)


def submit_search_from_input(driver: webdriver.Chrome, keyword: str) -> bool:
    for xpath in (
        "//input[@type='search']",
        "//input[contains(@aria-label, 'Search Facebook')]",
        "//input[contains(@aria-label, 'Tìm kiếm trên Facebook')]",
    ):
        try:
            inputs = driver.find_elements(By.XPATH, xpath)
            for element in inputs[:2]:
                if not element.is_displayed() or not element.is_enabled():
                    continue
                element.click()
                element.send_keys(Keys.COMMAND, "a")
                element.send_keys(keyword)
                element.send_keys(Keys.ENTER)
                time.sleep(PAGE_LOAD_WAIT_SECONDS)
                dismiss_dialogs(driver)
                if has_post_links(driver):
                    return True
                for tab_xpath in (
                    "//span[normalize-space()='Posts']/ancestor::a[1]",
                    "//span[normalize-space()='Bài viết']/ancestor::a[1]",
                ):
                    tabs = driver.find_elements(By.XPATH, tab_xpath)
                    for tab in tabs[:1]:
                        driver.execute_script("arguments[0].click();", tab)
                        time.sleep(PAGE_LOAD_WAIT_SECONDS)
                        dismiss_dialogs(driver)
                        if has_post_links(driver):
                            return True
        except Exception:
            continue

    return has_post_links(driver)


def has_post_links(driver: webdriver.Chrome) -> bool:
    for href in get_anchor_hrefs(driver):
        if normalize_post_url(href):
            return True
    return False


def page_looks_like_not_found(driver: webdriver.Chrome) -> bool:
    title = (driver.title or "").strip().lower()
    source = (driver.page_source or "")[:4000].lower()
    return "not found" in title or ">not found<" in source


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
            "--remote-debugging-port=9226 "
            "--user-data-dir=/tmp/chrome-codex-facebook"
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


def normalize_post_url(url: str) -> str:
    if not url:
        return ""

    url = url.replace("m.facebook.com", "www.facebook.com").replace("mbasic.facebook.com", "www.facebook.com")
    parsed = urlparse(url)
    if "facebook.com" not in parsed.netloc:
        return ""

    clean_query = parse_qs(parsed.query)
    story_fbid = clean_query.get("story_fbid", [""])[0]
    owner_id = clean_query.get("id", [""])[0]
    fbid = clean_query.get("fbid", [""])[0]
    post_id = clean_query.get("post_id", [""])[0]
    video_id = clean_query.get("v", [""])[0]

    if story_fbid:
        if owner_id:
            return f"https://www.facebook.com/story.php?story_fbid={story_fbid}&id={owner_id}"
        return ""
    if parsed.path.endswith("/posts") and post_id:
        return f"https://www.facebook.com{parsed.path}?post_id={post_id}"
    if fbid and "permalink.php" in parsed.path:
        return f"https://www.facebook.com/permalink.php?fbid={fbid}"
    if video_id and "watch" in parsed.path:
        return f"https://www.facebook.com/watch/?v={video_id}"

    patterns = [
        r"^/.+/posts/[^/?#]+$",
        r"^/.+/videos/[^/?#]+$",
        r"^/.+/reels/[^/?#]+$",
        r"^/reel/[^/?#]+$",
        r"^/share/p/[A-Za-z0-9_-]+$",
    ]
    normalized_path = parsed.path.rstrip("/")
    if any(re.match(pattern, normalized_path) for pattern in patterns):
        return f"https://www.facebook.com{normalized_path}"

    photo_set = clean_query.get("set", [""])[0]
    if fbid and "photo" in parsed.path:
        if photo_set:
            return f"https://www.facebook.com/photo/?fbid={fbid}&set={photo_set}"
        return f"https://www.facebook.com/photo/?fbid={fbid}"
    return ""


def crawl_post(driver: webdriver.Chrome, post_url: str) -> dict:
    if DEBUG_COMMENT_LOADING:
        print(f"[facebook-post] start requested_url={post_url}")
    driver.get(post_url)
    time.sleep(POST_LOAD_WAIT_SECONDS)
    dismiss_dialogs(driver)
    ensure_post_detail_context(driver)

    if DEBUG_COMMENT_LOADING:
        print(
            "[facebook-post] "
            f"after_context current_url={driver.current_url} "
            f"is_detail={is_post_detail_context(driver)} title={(driver.title or '').strip()[:120]}"
        )

    text = extract_post_text(driver)
    created_at = extract_meta_content(driver, META_DATE_SELECTORS)
    canonical_url = extract_meta_content(driver, ["meta[property='og:url']"]) or normalize_post_url(driver.current_url) or post_url
    post_id = extract_post_id(canonical_url)

    if not post_id:
        return {}

    post = {
        "id": post_id,
        "created_time": normalize_datetime(created_at),
        "permalink_url": canonical_url,
        "message": text,
        "story": "",
        "comments": {"data": []},
    }

    if MAX_COMMENTS != 0:
        post["comments"]["data"] = extract_comments(driver, canonical_url)[:comment_limit()]

    return post


def crawl_post_with_retries(driver: webdriver.Chrome, post_url: str, attempts: int = 2) -> tuple[webdriver.Chrome, dict]:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return driver, crawl_post(driver, post_url)
        except InvalidSessionIdException as exc:
            last_error = exc
            print(f"[facebook-post] session_lost attempt={attempt} url={post_url}")
            try:
                driver.quit()
            except Exception:
                pass
            driver = build_driver()
        except WebDriverException as exc:
            message = str(exc).lower()
            if "invalid session id" not in message:
                raise
            last_error = exc
            print(f"[facebook-post] session_lost attempt={attempt} url={post_url}")
            try:
                driver.quit()
            except Exception:
                pass
            driver = build_driver()

    if last_error is not None:
        raise last_error
    return driver, {}


def dismiss_dialogs(driver: webdriver.Chrome) -> None:
    for text in ("Not Now", "Close", "Đóng", "Lúc khác"):
        try:
            buttons = driver.find_elements(By.XPATH, f"//span[normalize-space()='{text}'] | //div[normalize-space()='{text}']")
            for button in buttons[:2]:
                button.click()
                time.sleep(0.5)
        except Exception:
            continue


def ensure_post_detail_context(driver: webdriver.Chrome) -> None:
    if is_post_detail_context(driver):
        return

    if DEBUG_COMMENT_LOADING:
        print(f"[facebook-post] detail_context initial_miss current_url={driver.current_url}")

    click_view_post_entrypoint(driver)
    time.sleep(POST_LOAD_WAIT_SECONDS)
    dismiss_dialogs(driver)

    if is_post_detail_context(driver):
        if DEBUG_COMMENT_LOADING:
            print(f"[facebook-post] detail_context recovered_via=view_post current_url={driver.current_url}")
        return

    click_open_comments_entrypoint(driver)
    time.sleep(POST_LOAD_WAIT_SECONDS)
    dismiss_dialogs(driver)
    if DEBUG_COMMENT_LOADING:
        print(f"[facebook-post] detail_context recovered_via=comments current_url={driver.current_url} is_detail={is_post_detail_context(driver)}")


def is_post_detail_context(driver: webdriver.Chrome) -> bool:
    current = driver.current_url or ""
    normalized = normalize_post_url(current)
    if normalized and "photo/?fbid=" not in normalized:
        return True

    title = (driver.title or "").strip().lower()
    if "bài viết của" in title or "post by" in title:
        return True

    for xpath in (
        "//div[@role='dialog']//div[contains(normalize-space(), 'Bài viết của ')]",
        "//div[@role='dialog']//div[contains(normalize-space(), 'Post by ')]",
        "//div[contains(@aria-label, 'Bài viết')]",
        "//div[contains(@aria-label, 'Post')]",
    ):
        try:
            if driver.find_elements(By.XPATH, xpath):
                return True
        except Exception:
            continue
    return False


def click_view_post_entrypoint(driver: webdriver.Chrome) -> None:
    for xpath in (
        "//span[normalize-space()='Xem bài viết']/ancestor::a[1]",
        "//span[normalize-space()='Xem bài viết']/ancestor::*[@role='link'][1]",
        "//span[normalize-space()='Xem bài viết']/ancestor::*[@role='button'][1]",
        "//a[.//span[normalize-space()='View post']]",
        "//span[normalize-space()='View post']/ancestor::*[@role='link'][1]",
        "//span[normalize-space()='View post']/ancestor::*[@role='button'][1]",
        "//a[contains(@href, '/posts/') or contains(@href, 'permalink.php') or contains(@href, 'story.php')]",
    ):
        try:
            elements = driver.find_elements(By.XPATH, xpath)
            for element in elements[:3]:
                if not element.is_displayed():
                    continue
                href = (element.get_attribute("href") or "").strip()
                driver.execute_script("arguments[0].click();", element)
                time.sleep(POST_LOAD_WAIT_SECONDS)
                dismiss_dialogs(driver)
                if href and is_post_permalink(href):
                    return
                if is_post_detail_context(driver):
                    return
        except Exception:
            continue


def click_open_comments_entrypoint(driver: webdriver.Chrome) -> None:
    for xpath in (
        "//span[contains(normalize-space(), 'bình luận')]/ancestor::*[@role='button'][1]",
        "//span[contains(normalize-space(), 'comments')]/ancestor::*[@role='button'][1]",
        "//div[contains(normalize-space(), 'bình luận')]/ancestor::*[@role='button'][1]",
        "//div[contains(normalize-space(), 'comments')]/ancestor::*[@role='button'][1]",
    ):
        try:
            elements = driver.find_elements(By.XPATH, xpath)
            for element in elements[:2]:
                if not element.is_displayed():
                    continue
                driver.execute_script("arguments[0].click();", element)
                time.sleep(POST_LOAD_WAIT_SECONDS)
                dismiss_dialogs(driver)
                if is_post_detail_context(driver):
                    return
        except Exception:
            continue


def is_post_permalink(url: str) -> bool:
    normalized = normalize_post_url(url)
    return bool(normalized and "photo/?fbid=" not in normalized)


def extract_post_text(driver: webdriver.Chrome) -> str:
    meta_text = extract_meta_content(driver, META_DESCRIPTION_SELECTORS)
    if meta_text:
        return meta_text.strip()

    scripts = driver.find_elements(By.TAG_NAME, "script")
    for script in scripts:
        content = script.get_attribute("innerHTML") or ""
        match = re.search(r'"message"\s*:\s*\{"text"\s*:\s*"(.+?)"\}', content)
        if match:
            return decode_js_string(match.group(1)).strip()

    candidates = driver.find_elements(By.XPATH, "//div[@data-ad-preview='message']//span | //div[@dir='auto']//span")
    texts: list[str] = []
    for node in candidates:
        value = (node.text or "").strip()
        if len(value) < 20:
            continue
        if value not in texts:
            texts.append(value)
        if len(" ".join(texts)) >= 400:
            break
    return "\n".join(texts).strip()


def extract_comments(driver: webdriver.Chrome, canonical_url: str) -> list[dict]:
    expand_comments(driver)

    comments: list[dict] = []
    seen: set[str] = set()
    texts = extract_comment_texts(driver)
    for index, text in enumerate(texts, start=1):
        if not looks_like_comment_text(text) or text in seen:
            continue
        seen.add(text)
        comments.append(
            {
                "id": f"{extract_post_id(canonical_url)}_{index}",
                "created_time": "",
                "message": text,
                "comments": {"data": []},
            }
        )
        if len(comments) >= comment_limit():
            break
    return comments


def expand_comments(driver: webdriver.Chrome) -> None:
    last_count = 0
    idle_rounds = 0

    thread_opened = open_comment_thread(driver)
    focus_comment_section(driver)
    filter_changed = set_all_comments_filter(driver)
    if DEBUG_COMMENT_LOADING:
        print(
            f"[facebook-comments] init thread_opened={thread_opened} "
            f"filter_changed={filter_changed} nodes={count_comment_like_nodes(driver)}"
        )

    for round_index in range(1, COMMENT_LOAD_ROUNDS + 1):
        thread_opened = open_comment_thread(driver)
        focus_comment_section(driver)
        expanded_before = click_expand_comment_controls(driver)
        scroll_state = scroll_comments(driver)
        expanded_after = click_expand_comment_controls(driver)
        time.sleep(COMMENT_LOAD_PAUSE_SECONDS)

        count = count_comment_like_nodes(driver)
        if count <= last_count:
            idle_rounds += 1
        else:
            idle_rounds = 0
            last_count = count
        if DEBUG_COMMENT_LOADING:
            print(
                "[facebook-comments] "
                f"round={round_index} nodes={count} idle_rounds={idle_rounds} "
                f"thread_opened={thread_opened} expanded_before={expanded_before} "
                f"expanded_after={expanded_after} touched={format_scroll_debug(scroll_state)}"
            )
        if idle_rounds >= COMMENT_IDLE_ROUNDS_BEFORE_STOP:
            break


def set_all_comments_filter(driver: webdriver.Chrome) -> bool:
    for xpath in (
        ".//span[normalize-space()='All comments']/ancestor::*[@role='button'][1]",
        ".//span[normalize-space()='Tất cả bình luận']/ancestor::*[@role='button'][1]",
    ):
        try:
            buttons = find_in_active_dialog(driver, xpath)
            for button in buttons[:1]:
                if not button.is_displayed():
                    continue
                driver.execute_script("arguments[0].click();", button)
                time.sleep(1)
                for option_xpath in (
                    ".//span[normalize-space()='All comments']/ancestor::*[@role='menuitem'][1]",
                    ".//span[normalize-space()='Tất cả bình luận']/ancestor::*[@role='menuitem'][1]",
                ):
                    options = find_in_active_dialog(driver, option_xpath)
                    for option in options[:1]:
                        driver.execute_script("arguments[0].click();", option)
                        time.sleep(1)
                        return True
        except Exception:
            continue
    return False


def focus_comment_section(driver: webdriver.Chrome) -> None:
    for xpath in (
        ".//*[contains(@placeholder, 'Viết bình luận')]",
        ".//*[contains(@placeholder, 'Write a comment')]",
        ".//*[contains(@placeholder, 'Trả lời')]",
        ".//*[contains(@placeholder, 'Reply')]",
        ".//*[@role='textbox' and (contains(@aria-label, 'bình luận') or contains(@aria-label, 'comment') or contains(@aria-label, 'Trả lời') or contains(@aria-label, 'Reply'))]",
        ".//span[contains(normalize-space(), 'bình luận')]/ancestor::*[@role='button'][1]",
        ".//span[contains(normalize-space(), 'comments')]/ancestor::*[@role='button'][1]",
        ".//div[contains(normalize-space(), 'bình luận')]/ancestor::*[@role='button'][1]",
        ".//div[contains(normalize-space(), 'comments')]/ancestor::*[@role='button'][1]",
        ".",
    ):
        try:
            elements = find_in_active_dialog(driver, xpath)
            for element in elements[:1]:
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", element)
                time.sleep(0.3)
                if element.get_attribute("role") in {"button", "link"} and element.is_displayed():
                    driver.execute_script("arguments[0].click();", element)
                    time.sleep(0.5)
                return
        except Exception:
            continue


def open_comment_thread(driver: webdriver.Chrome) -> bool:
    for xpath in (
        ".//span[contains(normalize-space(), 'bình luận')]/ancestor::*[@role='button'][1]",
        ".//span[contains(normalize-space(), 'comments')]/ancestor::*[@role='button'][1]",
        ".//span[contains(normalize-space(), 'bình luận')]/ancestor::a[1]",
        ".//span[contains(normalize-space(), 'comments')]/ancestor::a[1]",
        ".//*[contains(@placeholder, 'Viết bình luận')]",
        ".//*[contains(@placeholder, 'Write a comment')]",
        ".//*[@role='textbox' and (contains(@aria-label, 'bình luận') or contains(@aria-label, 'comment'))]",
    ):
        try:
            elements = find_in_active_dialog(driver, xpath)
            for element in elements[:2]:
                if not element.is_displayed():
                    continue
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", element)
                time.sleep(0.25)
                role = (element.get_attribute("role") or "").strip()
                tag = (element.tag_name or "").lower()
                if role in {"button", "link"} or tag in {"a", "button"}:
                    driver.execute_script("arguments[0].click();", element)
                    time.sleep(0.5)
                    return True
                return False
        except Exception:
            continue
    return False


def click_expand_comment_controls(driver: webdriver.Chrome) -> int:
    labels = (
        "View more comments",
        "View previous comments",
        "View more replies",
        "See more comments",
        "See more replies",
        "See previous comments",
        "Most relevant",
        "Xem thêm bình luận",
        "Xem bình luận trước đó",
        "Xem thêm câu trả lời",
        "Xem thêm phản hồi",
        "Xem thêm câu trả lời trước",
    )
    clicked = 0
    for label in labels:
        xpath = (
            f".//span[normalize-space()='{label}']/ancestor::*[@role='button'][1] | "
            f".//div[normalize-space()='{label}']/ancestor::*[@role='button'][1] | "
            f".//span[contains(normalize-space(), '{label}')]/ancestor::*[@role='button'][1]"
        )
        try:
            buttons = find_in_active_dialog(driver, xpath)
            for button in buttons[:3]:
                if not button.is_displayed():
                    continue
                driver.execute_script("arguments[0].click();", button)
                time.sleep(0.5)
                clicked += 1
        except Exception:
            continue
    return clicked


def scroll_comments(driver: webdriver.Chrome) -> dict:
    scroll_state = driver.execute_script(
        """
        const isScrollable = (el) => {
          if (!el) return false;
          return el.scrollHeight > el.clientHeight + 40;
        };

        const dialogs = Array.from(document.querySelectorAll('[role="dialog"]'))
          .filter((el) => {
            const rect = el.getBoundingClientRect();
            return rect.width > 200 && rect.height > 200;
          })
          .sort((a, b) => {
            const ar = a.getBoundingClientRect();
            const br = b.getBoundingClientRect();
            return (br.width * br.height) - (ar.width * ar.height);
          });
        const dialog = dialogs[0] || null;
        const root = dialog || document.body;
        const anchors = Array.from(root.querySelectorAll('[placeholder*="Trả lời" i], [placeholder*="Reply" i], [placeholder*="Viết bình luận" i], [placeholder*="Write a comment" i], [aria-label*="bình luận" i], [aria-label*="comment" i]'));
        if (anchors.length) {
          anchors[0].scrollIntoView({block:'center'});
        }

        const scrollables = [root, ...root.querySelectorAll('div')]
          .filter(isScrollable)
          .sort((a, b) => (b.scrollHeight - b.clientHeight) - (a.scrollHeight - a.clientHeight));

        const touched = [];
        for (const el of scrollables.slice(0, 8)) {
          const step = Math.max((el.clientHeight || window.innerHeight) * 0.9, 700);
          const before = el.scrollTop;
          el.scrollTop = Math.min(el.scrollTop + step, el.scrollHeight);
          if (el.scrollTop !== before) {
            touched.push({
              tag: el.tagName,
              role: el.getAttribute('role') || '',
              aria: el.getAttribute('aria-label') || '',
              top: el.scrollTop,
              height: el.scrollHeight,
              clientHeight: el.clientHeight
            });
          }
        }

        if (!touched.length) {
          window.scrollBy(0, Math.max(window.innerHeight * 0.9, 700));
        }

        return {
          touched
        };
        """
    )
    try:
        active = driver.switch_to.active_element
        active.send_keys(Keys.PAGE_DOWN)
    except Exception:
        try:
            body = driver.find_element(By.TAG_NAME, "body")
            body.send_keys(Keys.PAGE_DOWN)
        except Exception:
            return scroll_state or {"touched": []}
    return scroll_state or {"touched": []}


def count_comment_like_nodes(driver: webdriver.Chrome) -> int:
    try:
        return len(extract_comment_texts(driver))
    except Exception:
        return 0


def format_scroll_debug(scroll_state: dict | None) -> str:
    touched = (scroll_state or {}).get("touched") or []
    if not touched:
        return "none"
    parts: list[str] = []
    for item in touched[:3]:
        role = str(item.get("role") or "").strip() or "-"
        aria = str(item.get("aria") or "").strip() or "-"
        top = item.get("top", 0)
        height = item.get("height", 0)
        client_height = item.get("clientHeight", 0)
        parts.append(f"{role}|{aria}|top={top}|h={height}|ch={client_height}")
    return "; ".join(parts)


def extract_comment_texts(driver: webdriver.Chrome) -> list[str]:
    try:
        raw_texts = driver.execute_script(
            """
            const selectors = [
              '[role="dialog"] [aria-label*="comment" i] ul li',
              '[role="dialog"] [aria-label*="bình luận" i] ul li',
              '[role="main"] [aria-label*="comment" i] ul li',
              '[role="main"] [aria-label*="bình luận" i] ul li',
              '[role="dialog"] ul li',
              '[role="main"] ul li',
              '[role="dialog"] [role="article"]',
              '[role="main"] [role="article"]',
            ];

            const blocked = new Set([
              'like', 'reply', 'share', 'send', 'edited', 'most relevant', 'all comments',
              'thích', 'trả lời', 'chia sẻ', 'gửi', 'đã chỉnh sửa', 'phù hợp nhất', 'tất cả bình luận',
              'view more comments', 'view previous comments', 'view more replies',
              'see more comments', 'see previous comments', 'see more replies',
              'xem thêm bình luận', 'xem bình luận trước đó', 'xem thêm câu trả lời', 'xem thêm phản hồi'
            ]);
            const timePattern = /^(?:\\d+[smhdwy]|\\d+\\s*(?:phút|giờ|ngày|tuần|tháng|năm)|\\d+\\s*(?:minute|minutes|hour|hours|day|days|week|weeks|month|months|year|years))$/i;
            const metricPattern = /^[\\d.,]+(?:\\s*[KMBkmb])?$/;
            const nameLike = /^[\\p{L}][\\p{L}\\p{M}\\p{N}_.\\- ]{0,79}$/u;

            const seenNodes = new Set();
            const results = [];
            const seenTexts = new Set();

            for (const selector of selectors) {
              for (const node of document.querySelectorAll(selector)) {
                if (seenNodes.has(node)) continue;
                seenNodes.add(node);

                const rect = node.getBoundingClientRect();
                if (rect.width === 0 || rect.height === 0) continue;

                const lines = (node.innerText || '')
                  .split('\\n')
                  .map((line) => line.replace(/\\s+/g, ' ').trim())
                  .filter(Boolean);
                if (!lines.length) continue;

                const filtered = [];
                for (const line of lines) {
                  const lowered = line.toLowerCase();
                  if (blocked.has(lowered)) continue;
                  if (timePattern.test(lowered)) continue;
                  if (metricPattern.test(line)) continue;
                  filtered.push(line);
                }
                if (!filtered.length) continue;

                const textLines = filtered.slice();
                if (
                  textLines.length >= 2 &&
                  nameLike.test(textLines[0]) &&
                  !/[.!?]/.test(textLines[0]) &&
                  !timePattern.test(textLines[1].toLowerCase())
                ) {
                  textLines.shift();
                }
                if (!textLines.length) continue;

                const text = textLines.join(' ').replace(/\\s+/g, ' ').trim();
                if (!text || seenTexts.has(text)) continue;
                if (text.length < 2 || text.length > 2000) continue;

                seenTexts.add(text);
                results.push(text);
              }
            }
            return results;
            """
        )
    except WebDriverException:
        return []

    return [str(text).strip() for text in raw_texts if str(text).strip()] if isinstance(raw_texts, list) else []


def find_comment_text_nodes(driver: webdriver.Chrome):
    # Compatibility wrapper for older tests/callers that still reference the previous helper name.
    return extract_comment_texts(driver)


def looks_like_comment_text(text: str) -> bool:
    normalized = " ".join((text or "").split()).strip()
    if len(normalized) < 2:
        return False
    lowered = normalized.lower()
    blocked = {
        "like",
        "reply",
        "share",
        "send",
        "edited",
        "thích",
        "trả lời",
        "chia sẻ",
        "đã chỉnh sửa",
    }
    if lowered in blocked:
        return False
    if re.fullmatch(r"\d+[hmdwy]|\d+\s+(minute|minutes|hour|hours|day|days|week|weeks)", lowered):
        return False
    return True


def comment_limit() -> int:
    return MAX_COMMENTS if MAX_COMMENTS > 0 else 10**9


def extract_meta_content(driver: webdriver.Chrome, selectors: list[str]) -> str:
    for selector in selectors:
        try:
            elements = driver.find_elements(By.CSS_SELECTOR, selector)
            for element in elements:
                content = (element.get_attribute("content") or "").strip()
                if content:
                    return content
        except Exception:
            continue
    return ""


def extract_post_id(url: str) -> str:
    if not url:
        return ""

    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    for key in ("story_fbid", "fbid", "v", "post_id"):
        value = query.get(key, [""])[0].strip()
        if value:
            return value

    match = re.search(r"/(?:posts|videos|reels?|reel)/([^/?#]+)", parsed.path)
    if match:
        return match.group(1)

    match = re.search(r"/share/p/([A-Za-z0-9_-]+)", parsed.path)
    if match:
        return match.group(1)

    return ""


def normalize_datetime(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return datetime.now(timezone.utc).isoformat()
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except Exception:
        return datetime.now(timezone.utc).isoformat()


def decode_js_string(value: str) -> str:
    try:
        return json.loads(f'"{value}"')
    except Exception:
        return value


def sanitize_filename(value: str) -> str:
    return re.sub(r"[^\w\s.-]", "_", value, flags=re.UNICODE).strip().replace("/", "_")


def canonical_post_key(post: dict) -> str:
    permalink = normalize_post_url(str(post.get("permalink_url") or "").strip())
    if permalink and "photo/?fbid=" not in permalink:
        return permalink

    post_id = str(post.get("id") or "").strip()
    if post_id:
        return f"id:{post_id}"
    return ""


def active_dialog_candidates(driver: webdriver.Chrome) -> list:
    candidates: list = []
    try:
        dialogs = driver.find_elements(By.XPATH, "//div[@role='dialog']")
        visible_dialogs = [dialog for dialog in dialogs if dialog.is_displayed()]
        if visible_dialogs:
            candidates.extend(visible_dialogs)
    except Exception:
        pass
    try:
        mains = driver.find_elements(By.XPATH, "//div[@role='main']")
        visible_mains = [main for main in mains if main.is_displayed()]
        if visible_mains:
            candidates.extend(visible_mains)
    except Exception:
        pass
    try:
        body = driver.find_element(By.TAG_NAME, "body")
        if body.is_displayed():
            candidates.append(body)
    except Exception:
        pass

    deduped: list = []
    seen_ids: set[str] = set()
    for candidate in candidates:
        candidate_id = candidate.id
        if candidate_id in seen_ids:
            continue
        seen_ids.add(candidate_id)
        deduped.append(candidate)
    return deduped


def find_in_active_dialog(driver: webdriver.Chrome, xpath: str) -> list:
    for container in active_dialog_candidates(driver):
        try:
            if xpath == ".":
                return [container]
            elements = container.find_elements(By.XPATH, xpath)
            if elements:
                return elements
        except Exception:
            continue
    return []


if __name__ == "__main__":
    raise SystemExit(main())
