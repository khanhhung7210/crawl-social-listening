from __future__ import annotations

import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from social_listening.film_paths import platform_processed_dir, platform_raw_dir
from social_listening.keyword_config import collect_search_terms, load_keyword_payload
from social_listening.paths import DATA_DIR, ensure_dir


INPUT_FILE = platform_raw_dir("threads") / "threads_all_threads.json"
OUTPUT_FILE = platform_processed_dir("threads") / "threads_grouped_parsed.json"
SOURCE_NAME = "threads_format_job"
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

    top_index = find_comments_start_index(lines)

    if len(lines) >= 4:
        if is_date_line(lines[3]):
            post_created_at = lines[3]
            post_text = collect_post_text(lines[4:top_index])
        elif len(lines) >= 5 and is_date_line(lines[4]):
            post_created_at = lines[4]
            post_text = collect_post_text(lines[5:top_index])
        else:
            post_text = collect_post_text(lines[3:top_index])

    comments = parse_comments(lines, top_index, post_id)
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
        "comments": comments,
    }


def normalize_keywords(value: object) -> list[str]:
    if not isinstance(value, list):
        return []

    terms: list[str] = []
    for item in value:
        term = str(item or "").strip()
        if term and term not in terms:
            terms.append(term)
    return terms


def parse_comments(lines: list[str], top_index: int, post_id: str) -> list[dict]:
    comments: list[dict] = []
    if top_index >= len(lines):
        return comments

    index = top_index
    while index < len(lines) and lines[index] in TOP_MARKERS | ACTIVITY_MARKERS:
        index += 1

    comment_counter = 0
    while index < len(lines):
        if looks_like_username(lines[index]):
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


def is_metric_line(value: str) -> bool:
    compact = value.strip()
    return bool(re.fullmatch(r"[\d./KMBkmmb]+", compact))


def find_comments_start_index(lines: list[str]) -> int:
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
