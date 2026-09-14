from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone
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
from social_listening.paths import DATA_DIR, ensure_dir
from social_listening.text_utils import parse_compact_count


INPUT_FILE = platform_raw_dir("youtube") / "youtube_all_videos.json"
LEGACY_INPUT_FILE = DATA_DIR / "youtube" / "raw" / "youtube_all_videos.json"
OUTPUT_FILE = platform_processed_dir("youtube") / "youtube_grouped_parsed.json"
SOURCE_NAME = "youtube_format_job"


def main() -> int:
    input_file = INPUT_FILE if INPUT_FILE.exists() else LEGACY_INPUT_FILE
    if not input_file.exists():
        raise RuntimeError(f"Missing input file: {INPUT_FILE}")

    payload = json.loads(input_file.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise RuntimeError("youtube_all_videos.json must be a JSON array")

    records: list[dict] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        parsed = parse_video_record(item, input_file)
        if parsed:
            records.append(parsed)

    ensure_dir(OUTPUT_FILE.parent)
    OUTPUT_FILE.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved {len(records)} parsed youtube videos to {OUTPUT_FILE.resolve()}")
    return 0


def parse_video_record(item: dict, source_file: Path) -> dict:
    html = str(item.get("raw_html") or "")
    player_response = extract_embedded_json(html, "ytInitialPlayerResponse")
    initial_data = extract_embedded_json(html, "ytInitialData")
    microformat = ((player_response.get("microformat") or {}).get("playerMicroformatRenderer") or {})
    video_details = player_response.get("videoDetails") or {}

    video_id = str(video_details.get("videoId") or extract_video_id(str(item.get("current_url") or item.get("url") or "")))
    if not video_id:
        return {}

    channel_id = str(video_details.get("channelId") or "")
    channel_name = str(video_details.get("author") or "")
    post_url = normalize_youtube_video_url(str(item.get("current_url") or item.get("url") or ""))
    post_text = pick_description(video_details, microformat)
    post_created_at = resolve_video_created_at(microformat, initial_data, item)
    comments = extract_crawled_comments(item, video_id, post_url, post_created_at)

    return {
        "platform": "youtube",
        "post_id": video_id,
        "page_id": channel_id,
        "page_name": channel_name,
        "post_url": post_url,
        "post_created_at": post_created_at,
        "post_text": post_text,
        "post_keyword_match": False,
        "parent_keyword_match": bool(post_text or comments),
        "source": SOURCE_NAME,
        "source_file": str(source_file.relative_to(PROJECT_ROOT)),
        "stats": {
            "view_count": parse_compact_count(video_details.get("viewCount")),
            "comment_count": parse_compact_count(extract_comment_count(initial_data, item)),
            "like_count": parse_compact_count(extract_like_count(initial_data, item)),
        },
        "comments": comments,
    }


def extract_embedded_json(html: str, variable_name: str) -> dict:
    anchors = [
        f"{variable_name} = ",
        f"var {variable_name} = ",
    ]
    for anchor in anchors:
        start = html.find(anchor)
        if start < 0:
            continue
        json_start = html.find("{", start + len(anchor))
        if json_start < 0:
            continue
        raw_json = extract_balanced_json(html, json_start)
        if not raw_json:
            continue
        try:
            return json.loads(raw_json)
        except json.JSONDecodeError:
            continue
    return {}


def extract_balanced_json(text: str, start_index: int) -> str:
    depth = 0
    in_string = False
    escaped = False

    for index in range(start_index, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start_index : index + 1]
    return ""


def pick_description(video_details: dict, microformat: dict) -> str:
    short_description = str(video_details.get("shortDescription") or "").strip()
    if short_description:
        return short_description
    description = ((microformat.get("description") or {}).get("simpleText") or "").strip()
    return str(description)


def extract_crawled_comments(item: dict, video_id: str, post_url: str, post_created_at: str = "") -> list[dict]:
    raw_comments = item.get("crawled_comments") or []
    if not isinstance(raw_comments, list):
        return []

    crawled_at = normalize_created_at(item.get("crawled_at"))
    comments: list[dict] = []
    body_text = str(item.get("body_text") or "")
    for raw_comment in raw_comments:
        if not isinstance(raw_comment, dict):
            continue
        external_id = str(raw_comment.get("external_id") or "").strip()
        text = str(raw_comment.get("text") or "").strip()
        if not external_id or not text:
            continue
        author = str(raw_comment.get("author") or "").strip()
        label = str(raw_comment.get("created_at_label") or "").strip()
        if not label or label.lstrip("@") == author.lstrip("@"):
            label = extract_comment_time_label(body_text, author) or label
        created_at = resolve_comment_created_at(
            raw_comment.get("created_at"),
            label,
            crawled_at,
            post_created_at,
        )
        comments.append(
            {
                "external_id": external_id,
                "record_type": str(raw_comment.get("record_type") or "comment"),
                "author": author,
                "text": text,
                "created_at": created_at,
                "created_at_label": label,
                "url": str(raw_comment.get("url") or build_comment_url(post_url, external_id)),
                "post_id": video_id,
                "parent_comment_id": str(raw_comment.get("parent_comment_id") or "").strip(),
                "keyword_match": bool(raw_comment.get("keyword_match")),
                "crawl_source": str(raw_comment.get("source") or "dom"),
            }
        )
    return comments


def build_comment_url(post_url: str, external_id: str) -> str:
    comment_id = external_id.removeprefix("comment:")
    if not comment_id:
        return post_url
    separator = "&" if "?" in post_url else "?"
    return f"{post_url}{separator}lc={comment_id}"


def resolve_video_created_at(microformat: dict, initial_data: dict, item: dict) -> str:
    for candidate in (
        microformat.get("publishDate"),
        microformat.get("uploadDate"),
        extract_date_text(initial_data),
        extract_date_from_body_text(str(item.get("body_text") or "")),
    ):
        resolved = normalize_created_at(candidate)
        if resolved:
            return resolved
    return ""


def extract_date_from_body_text(body: str) -> str:
    if not body:
        return ""
    match = re.search(
        r"(?i)(?:\d[\d,.\s]*\s+views?\s+)?"
        r"((?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
        r"Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
        r"\s+\d{1,2},?\s+\d{4})",
        body,
    )
    return match.group(1) if match else ""


def extract_comment_time_label(body: str, author: str) -> str:
    if not body or not author:
        return ""
    author_key = author.lstrip("@")
    pattern = rf"(?im){re.escape(author_key)}\s*\n\s*([^\n]{{3,40}})"
    match = re.search(pattern, body)
    if not match:
        pattern = rf"(?im)@{re.escape(author_key)}\s*\n\s*([^\n]{{3,40}})"
        match = re.search(pattern, body)
    if not match:
        return ""
    label = match.group(1).strip()
    if re.search(r"(?i)(ago|trước|year|month|week|day|hour|minute|giờ|ngày|tuần|tháng|năm)", label):
        return label
    return ""


def extract_date_text(initial_data: dict) -> str:
    contents = json.dumps(initial_data, ensure_ascii=False)
    match = re.search(r'"dateText":\{"simpleText":"([^"]+)"\}', contents)
    return match.group(1) if match else ""


def extract_comment_count(initial_data: dict, item: dict) -> object:
    contents = json.dumps(initial_data, ensure_ascii=False)
    match = re.search(r'"countText":\{"runs":\[\{"text":"([\d.,]+)"\}', contents)
    if match:
        return match.group(1)
    return item.get("comment_count_observed")


def extract_like_count(initial_data: dict, item: dict | None = None) -> object:
    contents = json.dumps(initial_data, ensure_ascii=False)
    patterns = [
        r'"label"\s*:\s*"([\d.,]+[KkMmBb]?)\s+likes?"',
        r'"accessibilityText"\s*:\s*"([\d.,]+[KkMmBb]?)\s+likes?"',
        r'"simpleText"\s*:\s*"([\d.,]+[KkMmBb]?)"[^}]{0,80}"label"\s*:\s*"[^"]*likes?"',
        r'"likeCount(?:Text)?"\s*:\s*"?([\d.,]+[KkMmBb]?)"?',
    ]
    for pattern in patterns:
        match = re.search(pattern, contents, re.IGNORECASE)
        if match:
            return match.group(1)
    if isinstance(item, dict):
        return item.get("like_count") or item.get("like_count_observed")
    return None


def normalize_youtube_video_url(url: str) -> str:
    match = re.search(r"(?:https?://)?(?:www\.)?youtube\.com/watch\?[^#]*\bv=([A-Za-z0-9_-]{6,})", url or "")
    if match:
        return f"https://www.youtube.com/watch?v={match.group(1)}"
    short_match = re.search(r"(?:https?://)?youtu\.be/([A-Za-z0-9_-]{6,})", url or "")
    if short_match:
        return f"https://www.youtube.com/watch?v={short_match.group(1)}"
    return ""


def extract_video_id(url: str) -> str:
    match = re.search(r"[?&]v=([A-Za-z0-9_-]{6,})", url or "")
    return match.group(1) if match else ""


def normalize_created_at(value: object) -> str:
    if isinstance(value, str) and value.strip():
        raw = value.strip()
        iso_candidate = raw.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(iso_candidate)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).isoformat()
        except Exception:
            pass
        for fmt in ("%Y-%m-%d", "%b %d, %Y", "%d %b %Y"):
            try:
                return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc).isoformat()
            except Exception:
                continue
    return ""


def resolve_comment_created_at(
    value: object, label: str, crawled_at: str, post_created_at: str = ""
) -> str:
    normalized = normalize_created_at(value)
    if normalized and _same_instant(normalized, crawled_at):
        normalized = ""
    if normalized:
        return normalized

    if not (label or "").strip():
        return ""

    reference = parse_iso_datetime(crawled_at) or parse_iso_datetime(post_created_at)
    if reference is None:
        return ""
    from social_listening.review_utils import parse_media_date_label

    parsed_label = parse_media_date_label(label, reference=reference)
    if parsed_label is not None:
        return parsed_label.replace(tzinfo=timezone.utc).isoformat()

    relative_dt = parse_relative_time_label(label, reference)
    if relative_dt is not None:
        return relative_dt.isoformat()
    return ""


def _same_instant(iso_a: object, iso_b: object, *, tolerance_seconds: int = 2) -> bool:
    a = parse_iso_datetime(iso_a)
    b = parse_iso_datetime(iso_b)
    if a is None or b is None:
        return False
    return abs((a - b).total_seconds()) <= tolerance_seconds


def parse_iso_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_relative_time_label(label: str, reference: datetime) -> datetime | None:
    normalized = (label or "").strip().casefold()
    normalized = re.sub(r"\s+", " ", normalized)
    patterns = [
        (r"(\d+)\s*second(?:s)?\s*ago", 1),
        (r"(\d+)\s*minute(?:s)?\s*ago", 60),
        (r"(\d+)\s*hour(?:s)?\s*ago", 3600),
        (r"(\d+)\s*day(?:s)?\s*ago", 86400),
        (r"(\d+)\s*week(?:s)?\s*ago", 7 * 86400),
        (r"(\d+)\s*month(?:s)?\s*ago", 30 * 86400),
        (r"(\d+)\s*year(?:s)?\s*ago", 365 * 86400),
        (r"(\d+)\s*giây trước", 1),
        (r"(\d+)\s*phút trước", 60),
        (r"(\d+)\s*giờ trước", 3600),
        (r"(\d+)\s*ngày trước", 86400),
        (r"(\d+)\s*tuần trước", 7 * 86400),
        (r"(\d+)\s*tháng trước", 30 * 86400),
        (r"(\d+)\s*năm trước", 365 * 86400),
    ]
    for pattern, multiplier in patterns:
        match = re.search(pattern, normalized)
        if match:
            return reference - timedelta(seconds=int(match.group(1)) * multiplier)
    return None


if __name__ == "__main__":
    raise SystemExit(main())
