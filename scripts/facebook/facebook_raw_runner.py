from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import WebDriverException
from webdriver_manager.chrome import ChromeDriverManager

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from social_listening.paths import DATA_DIR, ensure_dir
from social_listening.film_paths import film_slug, platform_processed_dir


FACEBOOK_PAGE_URLS_FILE = DATA_DIR / "facebook" / "facebook_pages_unique_site_urls.json"
DEBUGGER_ADDRESS = os.getenv("FACEBOOK_DEBUGGER_ADDRESS", "127.0.0.1:9226")
OUTPUT_ROOT = DATA_DIR / "facebook" / "raw" / film_slug()
MAX_POSTS = int(os.getenv("FACEBOOK_MAX_POSTS", "100"))
MAX_SCROLL_ROUNDS = int(os.getenv("FACEBOOK_MAX_SCROLL_ROUNDS", "80"))
IDLE_ROUNDS_BEFORE_STOP = int(os.getenv("FACEBOOK_IDLE_ROUNDS_BEFORE_STOP", "8"))
SCROLL_PAUSE_SECONDS = float(os.getenv("FACEBOOK_SCROLL_PAUSE_SECONDS", "2.0"))
PAGE_LOAD_WAIT_SECONDS = float(os.getenv("FACEBOOK_PAGE_LOAD_WAIT_SECONDS", "5.0"))
POST_LOAD_WAIT_SECONDS = float(os.getenv("FACEBOOK_POST_LOAD_WAIT_SECONDS", "3.0"))
MAX_COMMENTS = int(os.getenv("FACEBOOK_MAX_COMMENTS", "0"))

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
    entries = load_page_entries(FACEBOOK_PAGE_URLS_FILE)
    if not entries:
        raise RuntimeError(f"No Facebook page entries found in {FACEBOOK_PAGE_URLS_FILE}")

    driver = build_driver()
    try:
        today_str = datetime.now().strftime("%Y%m%d")
        output_dir = ensure_dir(OUTPUT_ROOT / today_str)

        processed_records = 0
        for entry in entries:
            page_url = normalize_page_url(str(entry.get("UrlBase") or "").strip())
            site_name = sanitize_filename(str(entry.get("SiteName") or "").strip())
            if not page_url:
                continue

            file_name = f"{page_url.rstrip('/').split('/')[-1]}_{site_name}".strip("_")
            file_path = output_dir / f"{file_name}.jsonl"

            if file_path.exists() and file_path.stat().st_size > 0:
                print(f"=> File already exists for {file_name}, skipping...")
                processed_records += 1
                continue

            print(f"Fetching up to {MAX_POSTS} posts from {page_url} ...")
            post_urls = collect_post_urls(driver, page_url)
            posts = [crawl_post(driver, url) for url in post_urls[:MAX_POSTS]]
            posts = [post for post in posts if post]

            with file_path.open("w", encoding="utf-8") as file:
                if posts:
                    file.write("\n".join(json.dumps(post, ensure_ascii=False) for post in posts) + "\n")

            print(
                f"=> Finished {processed_records + 1}/{len(entries)} -- "
                f"scanned {len(posts)} posts into {file_path}"
            )
            processed_records += 1

        print(f"saved raw Facebook JSONL under {output_dir.resolve()}")
        return 0
    finally:
        driver.quit()


def load_page_entries(path: Path) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(
            "Facebook page list file not found. "
            f"Create {path} with items like "
            '[{"SiteName": "Example Page", "UrlBase": "https://www.facebook.com/example"}]'
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, list) else []


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


def normalize_page_url(url: str) -> str:
    if not url:
        return ""
    url = url.strip()
    if url.startswith("http://"):
        url = "https://" + url.removeprefix("http://")
    if not url.startswith("http://") and not url.startswith("https://"):
        url = f"https://www.facebook.com/{url.lstrip('/')}"
    return url.rstrip("/")


def collect_post_urls(driver: webdriver.Chrome, page_url: str) -> list[str]:
    driver.get(page_url)
    time.sleep(PAGE_LOAD_WAIT_SECONDS)
    dismiss_dialogs(driver)
    time.sleep(1)

    urls: list[str] = []
    seen: set[str] = set()
    idle_rounds = 0

    for _ in range(MAX_SCROLL_ROUNDS):
        before_count = len(urls)
        for raw_href in get_anchor_hrefs(driver):
            href = normalize_post_url(raw_href)
            if not href or href in seen:
                continue
            seen.add(href)
            urls.append(href)
            if len(urls) >= MAX_POSTS:
                return urls

        idle_rounds = idle_rounds + 1 if len(urls) == before_count else 0
        print(f"[facebook] page={page_url} discovered_urls={len(urls)} idle_rounds={idle_rounds}", flush=True)
        if idle_rounds >= IDLE_ROUNDS_BEFORE_STOP:
            break

        scroll_page(driver)
        time.sleep(SCROLL_PAUSE_SECONDS)

    return urls


def scroll_page(driver: webdriver.Chrome) -> None:
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
    path = parsed.path.rstrip("/")

    story_fbid = clean_query.get("story_fbid", [""])[0]
    fbid = clean_query.get("fbid", [""])[0]
    post_id = clean_query.get("post_id", [""])[0]
    video_id = clean_query.get("v", [""])[0]

    if story_fbid:
        return f"https://www.facebook.com/story.php?story_fbid={story_fbid}"
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
    normalized_path = parsed.path
    if any(re.match(pattern, normalized_path) for pattern in patterns):
        return f"https://www.facebook.com{normalized_path}"

    if story_fbid:
        return f"https://www.facebook.com/story.php?story_fbid={story_fbid}"
    if fbid and "photo" in parsed.path:
        return f"https://www.facebook.com/photo/?fbid={fbid}"
    return ""


def crawl_post(driver: webdriver.Chrome, post_url: str) -> dict:
    driver.get(post_url)
    time.sleep(POST_LOAD_WAIT_SECONDS)
    dismiss_dialogs(driver)

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

    if MAX_COMMENTS > 0:
        post["comments"]["data"] = extract_comments(driver, canonical_url)[:MAX_COMMENTS]

    return post


def dismiss_dialogs(driver: webdriver.Chrome) -> None:
    for text in ("Not Now", "Close", "Đóng", "Lúc khác"):
        try:
            buttons = driver.find_elements(By.XPATH, f"//span[normalize-space()='{text}'] | //div[normalize-space()='{text}']")
            for button in buttons[:2]:
                button.click()
                time.sleep(0.5)
        except Exception:
            continue


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
    comments: list[dict] = []
    seen: set[str] = set()
    nodes = driver.find_elements(By.XPATH, "//ul//div[@dir='auto']/span | //div[@aria-label='Comment']//span")
    for index, node in enumerate(nodes, start=1):
        text = (node.text or "").strip()
        if len(text) < 2 or text in seen:
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
        if len(comments) >= MAX_COMMENTS:
            break
    return comments


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

    match = re.search(r"/(?:posts|videos|reel)/(\d+)", parsed.path)
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
        return bytes(value, "utf-8").decode("unicode_escape")
    except Exception:
        return value


def sanitize_filename(value: str) -> str:
    return re.sub(r"[^\w\s.-]", "_", value, flags=re.UNICODE).strip().replace("/", "_")


if __name__ == "__main__":
    raise SystemExit(main())
