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


INPUT_FILE = platform_raw_dir("tiktok") / "tiktok_all_videos.json"
OUTPUT_FILE = platform_processed_dir("tiktok") / "tiktok_grouped_parsed.json"
SOURCE_NAME = "tiktok_format_job"


def main() -> int:
    payload = json.loads(INPUT_FILE.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise RuntimeError("tiktok_all_videos.json must be a JSON array")

    records: list[dict] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        parsed = parse_video_record(item)
        if parsed:
            records.append(parsed)

    ensure_dir(OUTPUT_FILE.parent)
    OUTPUT_FILE.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved {len(records)} parsed videos to {OUTPUT_FILE.resolve()}")
    return 0


def parse_video_record(item: dict) -> dict:
    html = str(item.get("raw_html") or "")
    page_data = extract_page_data(html)
    if not page_data:
        return {}

    scope = pick_scope(page_data)
    item_module = ((scope.get("__DEFAULT_SCOPE__") or {}).get("webapp.video-detail") or {}).get("itemInfo") or {}
    item_struct = (item_module.get("itemStruct") or {}) if isinstance(item_module, dict) else {}
    if not item_struct:
        item_struct = extract_first_item_struct(scope)
    if not item_struct:
        return {}

    author = item_struct.get("author") or {}
    stats = item_struct.get("stats") or {}
    video_id = str(item_struct.get("id") or extract_video_id(str(item.get("current_url") or item.get("url") or "")))
    current_url = normalize_tiktok_video_url(str(item.get("current_url") or item.get("url") or ""))
    description = str(item_struct.get("desc") or "").strip()
    comments = merge_comments(
        extract_crawled_comments(item, video_id, current_url),
        extract_comments(scope, video_id, current_url),
    )

    return {
        "platform": "tiktok",
        "post_id": video_id,
        "page_id": str(author.get("id") or ""),
        "page_name": str(author.get("uniqueId") or author.get("nickname") or ""),
        "post_url": current_url,
        "post_created_at": created_at_iso(item_struct.get("createTime")),
        "post_text": description,
        "post_keyword_match": False,
        "parent_keyword_match": bool(description or comments),
        "source": SOURCE_NAME,
        "source_file": str(INPUT_FILE.relative_to(PROJECT_ROOT)),
        "stats": {
            "digg_count": stats.get("diggCount"),
            "like_count": stats.get("diggCount"),
            "comment_count": stats.get("commentCount"),
            "play_count": stats.get("playCount"),
            "view_count": stats.get("playCount"),
            "share_count": stats.get("shareCount"),
        },
        "comments": comments,
    }


def extract_page_data(html: str) -> dict:
    candidates = [
        r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>',
        r'<script id="SIGI_STATE"[^>]*>(.*?)</script>',
    ]
    for pattern in candidates:
        match = re.search(pattern, html, re.DOTALL)
        if not match:
            continue
        raw_json = match.group(1).strip()
        try:
            return json.loads(raw_json)
        except json.JSONDecodeError:
            continue
    return {}


def pick_scope(page_data: dict) -> dict:
    if "webapp.video-detail" in page_data:
        return page_data
    default_scope = page_data.get("__DEFAULT_SCOPE__")
    if isinstance(default_scope, dict):
        return page_data
    return page_data


def extract_first_item_struct(scope: dict) -> dict:
    item_module = scope.get("ItemModule")
    if isinstance(item_module, dict) and item_module:
        first_key = next(iter(item_module))
        first_item = item_module.get(first_key)
        if isinstance(first_item, dict):
            return first_item
    return {}


def extract_comments(scope: dict, video_id: str, post_url: str) -> list[dict]:
    comments: list[dict] = []
    seen: set[str] = set()

    comment_module = scope.get("CommentModule")
    if isinstance(comment_module, dict):
        for _, value in comment_module.items():
            if not isinstance(value, dict):
                continue
            parsed = build_comment_record(value, video_id, post_url)
            if not parsed:
                continue
            external_id = parsed["external_id"]
            if external_id in seen:
                continue
            seen.add(external_id)
            comments.append(parsed)

    comments_page = ((scope.get("__DEFAULT_SCOPE__") or {}).get("webapp.video-detail") or {}).get("comments") or {}
    if isinstance(comments_page, list):
        for value in comments_page:
            if not isinstance(value, dict):
                continue
            parsed = build_comment_record(value, video_id, post_url)
            if not parsed:
                continue
            external_id = parsed["external_id"]
            if external_id in seen:
                continue
            seen.add(external_id)
            comments.append(parsed)

    return comments


def extract_crawled_comments(item: dict, video_id: str, post_url: str) -> list[dict]:
    raw_comments = item.get("crawled_comments") or []
    if not isinstance(raw_comments, list):
        return []

    crawled_at = normalize_created_at(item.get("crawled_at"))
    comments: list[dict] = []
    for raw_comment in raw_comments:
        if not isinstance(raw_comment, dict):
            continue
        external_id = str(raw_comment.get("external_id") or "").strip()
        text = str(raw_comment.get("text") or "").strip()
        if not external_id or not text:
            continue
        comment_id = external_id.removeprefix("comment:")
        created_at_label = str(raw_comment.get("created_at_label") or "").strip()
        comments.append(
            {
                "external_id": external_id,
                "record_type": str(raw_comment.get("record_type") or "comment"),
                "author": str(raw_comment.get("author") or ""),
                "text": text,
                "created_at": resolve_comment_created_at(
                    raw_comment.get("created_at"),
                    created_at_label,
                    crawled_at,
                ),
                "created_at_label": created_at_label,
                "url": build_comment_url(post_url, comment_id),
                "post_id": video_id,
                "parent_comment_id": str(raw_comment.get("parent_comment_id") or ""),
                "keyword_match": bool(raw_comment.get("keyword_match")),
                "crawl_source": str(raw_comment.get("source") or "dom"),
            }
        )
    return comments


def build_comment_record(comment: dict, video_id: str, post_url: str) -> dict:
    comment_id = str(comment.get("cid") or comment.get("id") or "").strip()
    if not comment_id:
        return {}

    user = comment.get("user") or {}
    text = str(comment.get("text") or "").strip()
    return {
        "external_id": f"comment:{comment_id}",
        "record_type": "comment",
        "author": str(user.get("unique_id") or user.get("nickname") or user.get("uid") or ""),
        "text": text,
        "created_at": parse_created_at(comment.get("createTime")).isoformat(),
        "created_at_label": "",
        "url": build_comment_url(post_url, comment_id),
        "post_id": video_id,
        "parent_comment_id": str(
            comment.get("reply_id")
            or comment.get("reply_comment_id")
            or comment.get("parentCommentId")
            or ""
        ),
        "keyword_match": False,
    }


def merge_comments(primary: list[dict], secondary: list[dict]) -> list[dict]:
    merged: list[dict] = []
    seen: set[str] = set()
    for collection in (primary, secondary):
        for comment in collection:
            external_id = str(comment.get("external_id") or "").strip()
            if not external_id or external_id in seen:
                continue
            seen.add(external_id)
            merged.append(comment)
    return merged


def build_comment_url(post_url: str, comment_id: str) -> str:
    if not post_url or not comment_id:
        return post_url
    return f"{post_url}?comment_id={comment_id}"


def normalize_tiktok_video_url(url: str) -> str:
    match = re.search(r"https://www\.tiktok\.com/@[^/]+/video/\d+", url or "")
    return match.group(0) if match else ""


def extract_video_id(url: str) -> str:
    match = re.search(r"/video/(\d+)", url or "")
    return match.group(1) if match else ""


def parse_created_at(value: object) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    except Exception:
        return None


def created_at_iso(value: object) -> str:
    dt = parse_created_at(value)
    return dt.isoformat() if dt is not None else ""


def normalize_created_at(value: object) -> str:
    if isinstance(value, str) and value.strip():
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).isoformat()
        except Exception:
            pass
    dt = parse_created_at(value)
    return dt.isoformat() if dt is not None else ""


def resolve_comment_created_at(value: object, label: str, crawled_at: str, post_created_at: str = "") -> str:
    normalized = normalize_created_at(value) if value not in (None, "") else ""
    # Reject raw timestamps that are just the crawl clock (common DOM scrape bug).
    if normalized and _same_instant(normalized, crawled_at):
        normalized = ""
    if normalized:
        return normalized

    crawl_dt = parse_iso_datetime(crawled_at) or parse_iso_datetime(post_created_at)
    if crawl_dt is None:
        return ""
    if not (label or "").strip():
        return ""

    relative_dt = parse_relative_time_label(label, crawl_dt)
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
    normalized = (label or "").strip().casefold().replace(" ", "")
    if normalized.endswith("ago"):
        normalized = normalized.removesuffix("ago")

    match = re.fullmatch(r"(\d+)(s|m|h|d|w|mo|y)", normalized)
    if not match:
        return None

    amount = int(match.group(1))
    unit = match.group(2)
    seconds_by_unit = {
        "s": 1,
        "m": 60,
        "h": 3600,
        "d": 86400,
        "w": 7 * 86400,
        "mo": 30 * 86400,
        "y": 365 * 86400,
    }
    return reference - timedelta(seconds=amount * seconds_by_unit[unit])


if __name__ == "__main__":
    raise SystemExit(main())
