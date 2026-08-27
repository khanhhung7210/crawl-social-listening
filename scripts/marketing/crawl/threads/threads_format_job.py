from __future__ import annotations

import json
import re
import sys
from pathlib import Path

def _project_root() -> Path:
    current = Path(__file__).resolve().parent
    for cand in [current, *current.parents]:
        if (cand / "src" / "social_listening").is_dir():
            return cand
    raise RuntimeError(f"Cannot find project root from {__file__}")


PROJECT_ROOT = _project_root()
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from social_listening.film_paths import platform_processed_dir, platform_raw_dir
from social_listening.keyword_config import collect_search_terms, load_keyword_payload
from social_listening.paths import DATA_DIR, ensure_dir
from social_listening.review_utils import is_relative_only_time_label
from social_listening.text_utils import parse_compact_count


INPUT_FILE = platform_raw_dir("threads") / "threads_all_threads.json"
OUTPUT_FILE = platform_processed_dir("threads") / "threads_grouped_parsed.json"
SOURCE_NAME = "threads_format_job"
THREADS_CHROME_RE = re.compile(
    r"(?i)messages\s+activity\s+profile|insights\s+saved\s+feeds|ghost\s+posts|"
    r"edit\s+following|view\s+activity|new\s+thread|for\s+you"
)


def is_threads_chrome_text(value: str) -> bool:
    text = (value or "").strip()
    if not text:
        return True
    if THREADS_CHROME_RE.search(text):
        return True
    # Mostly nav chrome, very little unique post content
    if text.lower().startswith("messages activity profile"):
        return True
    return False

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
    if not INPUT_FILE.exists():
        print(f"[threads-format] Input file not found: {INPUT_FILE}")
        print(f"[threads-format] This is normal when no URLs were crawled - nothing to format")
        return 0

    payload = json.loads(INPUT_FILE.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise RuntimeError("threads_all_threads.json must be a JSON array")

    if not payload:
        print(f"[threads-format] Input file is empty - nothing to format")
        return 0

    keyword_payload = load_keyword_payload()
    active_film_title = str(keyword_payload.get("film_title") or "").strip()
    active_keywords = collect_search_terms(keyword_payload)

    records: list[dict] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        parsed = parse_thread_record(item, active_film_title, active_keywords)
        if parsed:
            records.append(parsed)

    ensure_dir(OUTPUT_FILE.parent)
    OUTPUT_FILE.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved {len(records)} parsed threads to {OUTPUT_FILE.resolve()}")
    return 0


def parse_thread_record(item: dict, film_title: str, keywords: list[str]) -> dict:
    body_text = str(item.get("body_text") or "")
    lines = [line.strip() for line in body_text.splitlines() if line.strip()]
    if len(lines) < 5:
        return {}

    post_url = normalize_thread_url(
        str(item.get("current_url") or "") or first_linked_thread(item.get("linked_threads"))
    )
    page_name = extract_username(post_url)
    post_id = extract_post_code(post_url)
    post_created_at = ""
    post_text = ""

    top_index = find_comments_start_index(lines, page_name)

    owner_block = extract_owner_post(lines, page_name, len(lines))
    if owner_block:
        post_created_at, post_text = owner_block
    elif len(lines) >= 4:
        if is_date_line(lines[3]):
            post_created_at = lines[3]
            post_text = collect_post_text(lines[4:top_index])
        elif len(lines) >= 5 and is_date_line(lines[4]):
            post_created_at = lines[4]
            post_text = collect_post_text(lines[5:top_index])
        else:
            post_text = collect_post_text(lines[3:top_index])

    html_date = extract_date_from_html(str(item.get("raw_html") or ""), body_text)
    if html_date:
        post_created_at = html_date

    if not post_created_at:
        post_created_at = extract_date_label(lines, body_text)
    elif is_relative_only_time_label(post_created_at):
        absolute = extract_date_from_html(str(item.get("raw_html") or ""), body_text)
        if not absolute:
            absolute = extract_absolute_date_label(lines, body_text)
        if absolute:
            post_created_at = absolute

    # Never keep relative crumbs like "1h" / "2 ngày" as publish time — import would
    # resolve them against "now" and invent crawl-ish dates (same bug class as Facebook).
    if post_created_at and is_relative_only_time_label(post_created_at):
        post_created_at = ""

    if is_threads_chrome_text(post_text):
        for idx, line in enumerate(lines):
            if is_date_line(line) and idx + 1 < len(lines):
                candidate = lines[idx + 1]
                if not is_threads_chrome_text(candidate) and len(candidate) > 10:
                    post_text = candidate
                    break

    owner_start = find_owner_line_index(lines, page_name)
    comments = parse_comments(lines, top_index, post_id, owner_start=owner_start)
    if is_threads_chrome_text(post_text) and not comments:
        return {}

    stats = extract_engagement_stats(
        html=str(item.get("raw_html") or ""),
        post_id=post_id,
        body_text=body_text,
    )

    return {
        "platform": "threads",
        "post_id": post_id,
        "page_id": "",
        "page_name": page_name,
        "post_url": post_url,
        "post_created_at": post_created_at,
        "post_text": post_text,
        "film_title": film_title,
        "keywords": keywords,
        "post_keyword_match": False,
        "parent_keyword_match": bool(post_text or comments),
        "search_keyword": str(item.get("keyword") or "").strip(),
        "search_keywords": normalize_keywords(item.get("keywords")),
        "source": SOURCE_NAME,
        "source_file": str(INPUT_FILE),
        "stats": stats,
        "comments": comments,
    }


def extract_engagement_stats(*, html: str, post_id: str, body_text: str) -> dict:
    """Pull like/reply/view counts for this post code from embedded JSON (+ body views)."""
    like_count = None
    comment_count = None
    repost_count = None
    quote_count = None
    view_count = None
    fbid = None

    if post_id and html:
        needle = f'"code":"{post_id}"'
        pos = 0
        while True:
            index = html.find(needle, pos)
            if index < 0:
                break
            window = html[index : index + 2500]
            if like_count is None:
                match = re.search(r'"like_count"\s*:\s*(\d+)', window)
                if match:
                    like_count = int(match.group(1))
            if fbid is None:
                match = re.search(r'"fbid"\s*:\s*"(\d+)"', window)
                if match:
                    fbid = match.group(1)
            if like_count is not None and fbid is not None:
                break
            pos = index + 1

        if fbid:
            info_needle = f"XDTTextPostAppMediaInfo:{fbid}"
            pos = 0
            while True:
                index = html.find(info_needle, pos)
                if index < 0:
                    break
                blob = html[max(0, index - 400) : index + 900]

                def _grab(key: str, current: int | None) -> int | None:
                    if current is not None:
                        return current
                    match = re.search(rf'"{key}"\s*:\s*(\d+)', blob)
                    return int(match.group(1)) if match else None

                comment_count = _grab("direct_reply_count", comment_count)
                repost_count = _grab("repost_count", repost_count)
                quote_count = _grab("quote_count", quote_count)
                view_count = _grab("impression_count", view_count)
                pos = index + 1

    body_views = extract_views_from_body(body_text)
    if body_views is not None:
        view_count = body_views

    return {
        "like_count": like_count,
        "comment_count": comment_count,
        "repost_count": repost_count,
        "quote_count": quote_count,
        "view_count": view_count,
    }


def extract_views_from_body(body_text: str) -> int | None:
    match = re.search(
        r"(?i)([\d.,]+(?:\.\d+)?\s*[KkMmBb]?)\s*(?:views|lượt xem)",
        body_text or "",
    )
    if not match:
        return None
    return parse_compact_count(match.group(1))


def normalize_keywords(value: object) -> list[str]:
    if not isinstance(value, list):
        return []

    terms: list[str] = []
    for item in value:
        term = str(item or "").strip()
        if term and term not in terms:
            terms.append(term)
    return terms


def parse_comments(lines: list[str], top_index: int, post_id: str, owner_start: int = -1) -> list[dict]:
    comments: list[dict] = []
    if top_index >= len(lines):
        return comments

    index = top_index
    while index < len(lines) and lines[index] in TOP_MARKERS | ACTIVITY_MARKERS:
        index += 1

    comment_counter = 0
    while index < len(lines):
        if looks_like_username(lines[index]):
            if owner_start >= 0 and index <= owner_start:
                index += 1
                continue
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


def looks_like_username(value: str) -> bool:
    if not value or " " in value:
        return False
    if value.startswith("@"):
        return True
    return bool(re.fullmatch(r"[A-Za-z0-9._]+", value))


def is_date_line(value: str) -> bool:
    compact = value.strip().casefold()
    return (
        bool(re.fullmatch(r"\d{2}/\d{2}/\d{2}", compact))
        or bool(re.fullmatch(r"\d{2}/\d{2}/\d{4}", compact))
        or bool(re.fullmatch(r"\d+[smhdw]", compact))
        or bool(re.fullmatch(r"\d+\s*(sec|secs|second|seconds|min|mins|minute|minutes|hour|hours|day|days|week|weeks)", compact))
        or bool(re.fullmatch(r"\d+\s*(giay|giây|phut|phút|gio|giờ|ngay|ngày|tuan|tuần)", compact))
    )


def extract_absolute_date_label(lines: list[str], body_text: str) -> str:
    """Absolute MM/DD/YY only — never relative crumbs like 2h."""
    for line in lines[:40]:
        compact = line.strip()
        if re.fullmatch(r"\d{1,2}/\d{1,2}/\d{2,4}", compact):
            return compact
    blob = body_text or " ".join(lines[:40])
    m = re.search(r"\b(\d{1,2}/\d{1,2}/\d{2,4})\b", blob)
    return m.group(1) if m else ""


def extract_date_label(lines: list[str], body_text: str) -> str:
    """Find absolute Threads date first (07/31/26), then relative (13h)."""
    for line in lines[:40]:
        compact = line.strip()
        if re.fullmatch(r"\d{1,2}/\d{1,2}/\d{2,4}", compact):
            return compact
    blob = body_text or " ".join(lines[:40])
    m = re.search(r"\b(\d{1,2}/\d{1,2}/\d{2,4})\b", blob)
    if m:
        return m.group(1)
    for line in lines[:40]:
        if is_date_line(line) and re.fullmatch(r"\d+[smhdw]", line.strip().casefold()):
            return line.strip()
    m = re.search(r"(?i)\b(\d+[smhdw])\b", blob)
    if m:
        return m.group(1)
    return ""


def extract_date_from_html(html: str, body_text: str = "") -> str:
    blob = f"{html}\n{body_text}"
    m = re.search(r"\b(\d{2}/\d{2}/\d{2,4})\b", blob)
    if m:
        return m.group(1)
    m = re.search(
        r'aria-label="(\d{1,2}\s+th(?:áng|g)\s+\d{1,2}(?:[^"]*)?)"',
        blob,
        re.IGNORECASE,
    )
    if m:
        return m.group(1)
    return ""


def find_owner_line_index(lines: list[str], page_name: str) -> int:
    if not page_name:
        return -1
    target = page_name.lstrip("@").casefold()
    for index, line in enumerate(lines):
        if line.lstrip("@").casefold() == target:
            return index
    return -1


def extract_owner_post(lines: list[str], page_name: str, top_index: int) -> tuple[str, str] | None:
    """On reply-thread pages, take the URL owner's block — not the quoted parent post."""
    index = find_owner_line_index(lines, page_name)
    if index < 0:
        return None
    created_at, content_start = extract_comment_header(lines, index)
    if not created_at:
        return None
    text_lines: list[str] = []
    idx = content_start
    while idx < top_index and idx < len(lines):
        line = lines[idx]
        if looks_like_username(line) and line.lstrip("@").casefold() != page_name.lstrip("@").casefold():
            break
        if line in NOISE_LINES or is_metric_line(line):
            idx += 1
            continue
        text_lines.append(line)
        idx += 1
    text = " ".join(text_lines).strip()
    if not text or is_threads_chrome_text(text):
        return None
    return created_at, text


def is_metric_line(value: str) -> bool:
    compact = value.strip()
    return bool(re.fullmatch(r"[\d./KMBkmmb]+", compact))


def find_comments_start_index(lines: list[str], page_name: str = "") -> int:
    owner_idx = find_owner_line_index(lines, page_name)
    if owner_idx >= 0:
        _, content_start = extract_comment_header(lines, owner_idx)
        idx = max(content_start, owner_idx + 1)
        while idx < len(lines):
            line = lines[idx]
            if line in NOISE_LINES or is_metric_line(line):
                idx += 1
                continue
            if looks_like_username(line) and line.lstrip("@").casefold() != page_name.lstrip("@").casefold():
                return idx
            idx += 1
        return len(lines)

    explicit_marker = next((index for index, value in enumerate(lines) if value in TOP_MARKERS), -1)
    if explicit_marker >= 0:
        return explicit_marker

    # Fallback: look for the first likely comment header after the main post body.
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

    # Handle cases like username -> date -> · -> Tác giả -> text
    if probe + 1 < len(lines) and is_date_line(lines[probe + 1]):
        return lines[probe + 1], probe + 2

    return "", index


def normalize_thread_url(url: str) -> str:
    match = re.search(r"https://www\.threads\.(?:net|com)/@[^/]+/post/[^/?#]+", url or "")
    return match.group(0) if match else ""


def extract_username(url: str) -> str:
    match = re.search(r"https://www\.threads\.(?:net|com)/@([^/]+)/post/", url or "")
    return match.group(1) if match else ""


def extract_post_code(url: str) -> str:
    match = re.search(r"/post/([^/?#]+)", url or "")
    return match.group(1) if match else ""


def first_linked_thread(value: object) -> str:
    if isinstance(value, list) and value:
        first = value[0]
        return str(first or "")
    return ""


if __name__ == "__main__":
    raise SystemExit(main())
