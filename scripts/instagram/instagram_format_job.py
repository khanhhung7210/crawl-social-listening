from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from social_listening.paths import DATA_DIR, ensure_dir


INPUT_FILE = DATA_DIR / "instagram" / "raw" / "instagram_all_posts.json"
OUTPUT_FILE = DATA_DIR / "instagram" / "processed" / "instagram_grouped_parsed.json"
SOURCE_NAME = "instagram_format_job"


def main() -> int:
    payload = json.loads(INPUT_FILE.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise RuntimeError("instagram_all_posts.json must be a JSON array")

    records: list[dict] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        parsed = parse_post_record(item)
        if parsed:
            records.append(parsed)

    ensure_dir(OUTPUT_FILE.parent)
    OUTPUT_FILE.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved {len(records)} parsed instagram posts to {OUTPUT_FILE.resolve()}")
    return 0


def parse_post_record(item: dict) -> dict:
    html = str(item.get("raw_html") or "")
    metadata = extract_page_metadata(html)
    post_url = normalize_instagram_post_url(str(item.get("current_url") or item.get("url") or ""))
    post_id = str(metadata.get("post_id") or extract_shortcode(post_url))
    if not post_id:
        return {}

    comments = extract_crawled_comments(item, post_id, post_url)
    return {
        "platform": "instagram",
        "post_id": post_id,
        "page_id": str(metadata.get("page_id") or ""),
        "page_name": str(metadata.get("page_name") or ""),
        "post_url": post_url,
        "post_created_at": resolve_post_created_at(metadata, item),
        "post_text": str(metadata.get("post_text") or ""),
        "post_keyword_match": False,
        "parent_keyword_match": bool(metadata.get("post_text") or comments),
        "source": SOURCE_NAME,
        "source_file": str(INPUT_FILE.relative_to(PROJECT_ROOT)),
        "stats": {
            "like_count": metadata.get("like_count"),
            "comment_count": metadata.get("comment_count") or item.get("comment_count_observed"),
        },
        "comments": comments,
    }


def extract_page_metadata(html: str) -> dict:
    page_name = ""
    post_text = ""
    page_id = ""
    like_count = None
    comment_count = None
    post_id = ""
    created_at = ""

    json_ld_match = re.search(r'<script type="application/ld\+json">(\{.*?\})</script>', html, re.DOTALL)
    if json_ld_match:
        try:
            payload = json.loads(json_ld_match.group(1))
            post_text = str(payload.get("caption") or payload.get("description") or "").strip()
            page_name = str((payload.get("author") or {}).get("alternateName") or "").strip()
            created_at = str(payload.get("uploadDate") or "").strip()
            interaction = payload.get("interactionStatistic") or []
            if isinstance(interaction, list):
                for item in interaction:
                    if not isinstance(item, dict):
                        continue
                    interaction_type = str((item.get("interactionType") or {}).get("@type") or "")
                    count = item.get("userInteractionCount")
                    if interaction_type.endswith("LikeAction"):
                        like_count = count
                    if interaction_type.endswith("CommentAction"):
                        comment_count = count
        except Exception:
            pass

    meta_title = search_meta_content(html, "og:title")
    if meta_title and not page_name:
        page_name = meta_title.split(" on Instagram", 1)[0].strip()
    meta_desc = search_meta_content(html, "og:description")
    if meta_desc and not post_text:
        post_text = meta_desc.strip()

    entity_match = re.search(r'"owner":{"id":"([^"]+)","username":"([^"]+)"', html)
    if entity_match:
        page_id = entity_match.group(1)
        if not page_name:
            page_name = entity_match.group(2)

    shortcode_match = re.search(r'"shortcode":"([^"]+)"', html)
    if shortcode_match:
        post_id = shortcode_match.group(1)

    timestamp_match = re.search(r'"taken_at_timestamp":(\d+)', html)
    if timestamp_match and not created_at:
        try:
            created_at = datetime.fromtimestamp(int(timestamp_match.group(1)), tz=timezone.utc).isoformat()
        except Exception:
            pass

    return {
        "page_id": page_id,
        "page_name": page_name,
        "post_text": post_text,
        "like_count": like_count,
        "comment_count": comment_count,
        "post_id": post_id,
        "post_created_at": created_at,
    }


def search_meta_content(html: str, property_name: str) -> str:
    match = re.search(
        rf'<meta[^>]+property="{re.escape(property_name)}"[^>]+content="([^"]*)"',
        html,
        re.IGNORECASE,
    )
    return match.group(1) if match else ""


def extract_crawled_comments(item: dict, post_id: str, post_url: str) -> list[dict]:
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
        comments.append(
            {
                "external_id": external_id,
                "record_type": str(raw_comment.get("record_type") or "comment"),
                "author": str(raw_comment.get("author") or "").strip(),
                "text": text,
                "created_at": resolve_comment_created_at(
                    raw_comment.get("created_at"),
                    str(raw_comment.get("created_at_label") or ""),
                    crawled_at,
                ),
                "created_at_label": str(raw_comment.get("created_at_label") or "").strip(),
                "url": str(raw_comment.get("url") or build_comment_url(post_url, external_id)),
                "post_id": post_id,
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
    return f"{post_url}#comment-{comment_id}"


def resolve_post_created_at(metadata: dict, item: dict) -> str:
    for candidate in (metadata.get("post_created_at"), item.get("crawled_at")):
        resolved = normalize_created_at(candidate)
        if resolved:
            return resolved
    return datetime.now(timezone.utc).isoformat()


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


def resolve_comment_created_at(value: object, label: str, crawled_at: str) -> str:
    normalized = normalize_created_at(value)
    if normalized:
        return normalized
    reference = parse_iso_datetime(crawled_at) or datetime.now(timezone.utc)
    relative_dt = parse_relative_time_label(label, reference)
    if relative_dt is not None:
        return relative_dt.isoformat()
    return reference.isoformat()


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
        (r"(\d+)\s*s", 1),
        (r"(\d+)\s*m", 60),
        (r"(\d+)\s*h", 3600),
        (r"(\d+)\s*d", 86400),
        (r"(\d+)\s*w", 7 * 86400),
        (r"(\d+)\s*giây trước", 1),
        (r"(\d+)\s*phút trước", 60),
        (r"(\d+)\s*giờ trước", 3600),
        (r"(\d+)\s*ngày trước", 86400),
        (r"(\d+)\s*tuần trước", 7 * 86400),
        (r"(\d+)\s*second(?:s)?\s*ago", 1),
        (r"(\d+)\s*minute(?:s)?\s*ago", 60),
        (r"(\d+)\s*hour(?:s)?\s*ago", 3600),
        (r"(\d+)\s*day(?:s)?\s*ago", 86400),
        (r"(\d+)\s*week(?:s)?\s*ago", 7 * 86400),
    ]
    for pattern, multiplier in patterns:
        match = re.search(pattern, normalized)
        if match:
            return reference - timedelta(seconds=int(match.group(1)) * multiplier)
    return None


def normalize_instagram_post_url(url: str) -> str:
    if not url:
        return ""
    match = re.search(r"https://www\.instagram\.com/(?:p|reel|reels)/([^/?#]+)/?", url)
    if not match:
        return ""
    kind = "reel" if "/reel/" in url or "/reels/" in url else "p"
    return f"https://www.instagram.com/{kind}/{match.group(1)}/"


def extract_shortcode(url: str) -> str:
    match = re.search(r"/(?:p|reel)/([^/?#]+)/?", url or "")
    return match.group(1) if match else ""


if __name__ == "__main__":
    raise SystemExit(main())
