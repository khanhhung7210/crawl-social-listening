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
from social_listening.instagram_comment_parser import extract_instagram_comments_from_body_text
from social_listening.paths import ensure_dir
from social_listening.text_utils import parse_compact_count


INPUT_FILE = platform_raw_dir("instagram") / "instagram_all_posts.json"
OUTPUT_FILE = platform_processed_dir("instagram") / "instagram_grouped_parsed.json"
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
    if item.get("stale") or item.get("coverage") is False or item.get("freshness") == "stale":
        return {}
    html = str(item.get("raw_html") or "")
    metadata = extract_page_metadata(html)
    post_url = normalize_instagram_post_url(str(item.get("current_url") or item.get("url") or ""))
    post_id = str(metadata.get("post_id") or extract_shortcode(post_url))
    if not post_id:
        return {}

    post_created_at = resolve_post_created_at(metadata, item)
    comments = extract_crawled_comments(item, post_id, post_url, post_created_at)

    # Always strip IG og:description prefix from caption; prefer official counts over observed.
    cleaned_text, og_likes, og_comments = strip_instagram_engagement_prefix(
        str(metadata.get("post_text") or "")
    )
    like_count = metadata.get("like_count")
    comment_count = metadata.get("comment_count")
    if like_count is None:
        like_count = og_likes
    if comment_count is None:
        comment_count = og_comments
    if comment_count is None:
        comment_count = item.get("comment_count_observed")

    return {
        "platform": "instagram",
        "post_id": post_id,
        "page_id": str(metadata.get("page_id") or ""),
        "page_name": str(metadata.get("page_name") or ""),
        "post_url": post_url,
        "post_created_at": post_created_at,
        "post_text": cleaned_text,
        "post_keyword_match": False,
        "parent_keyword_match": bool(cleaned_text or comments),
        "source": SOURCE_NAME,
        "source_file": str(INPUT_FILE.relative_to(PROJECT_ROOT)),
        "stats": {
            "like_count": like_count,
            "comment_count": comment_count,
        },
        "comments": comments,
    }


_IG_OG_PREFIX = re.compile(
    r"^([\d.,]+)\s+likes?,\s*([\d.,]+)\s+comments?\s*-\s*[^:]+:\s*[\"']?(.*)$",
    re.IGNORECASE | re.DOTALL,
)


def _parse_count(raw: str) -> int | None:
    return parse_compact_count(raw)


def strip_instagram_engagement_prefix(text: str) -> tuple[str, int | None, int | None]:
    """Split '1,367 likes, 7 comments - user on Date: \"caption\"' → caption + counts."""
    raw = str(text or "").strip()
    if not raw:
        return "", None, None
    m = _IG_OG_PREFIX.match(raw)
    if not m:
        return raw, None, None
    likes = _parse_count(m.group(1))
    comments = _parse_count(m.group(2))
    caption = m.group(3).strip().strip('"').strip("'").strip()
    caption = caption.replace("&quot;", '"').replace("&amp;", "&")
    return caption or raw, likes, comments


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
    # Parse counts from og:description even when caption already set
    desc_for_counts = meta_desc or post_text or ""
    m = re.search(
        r"([\d.,]+)\s*likes?,\s*([\d.,]+)\s*comments?",
        desc_for_counts,
        re.IGNORECASE,
    )
    if m:
        if like_count is None:
            like_count = _parse_count(m.group(1))
        if comment_count is None:
            comment_count = _parse_count(m.group(2))
    # Never keep the og engagement prefix as caption body
    post_text, _, _ = strip_instagram_engagement_prefix(post_text)

    entity_match = re.search(r'"owner":{"id":"([^"]+)","username":"([^"]+)"', html)
    if entity_match:
        page_id = entity_match.group(1)
        if not page_name:
            page_name = entity_match.group(2)

    shortcode_match = re.search(r'"shortcode":"([^"]+)"', html)
    if shortcode_match:
        post_id = shortcode_match.group(1)

    if not created_at:
        created_at = extract_unix_timestamp_iso(html)

    return {
        "page_id": page_id,
        "page_name": page_name,
        "post_text": post_text,
        "like_count": like_count,
        "comment_count": comment_count,
        "post_id": post_id,
        "post_created_at": created_at,
    }


def extract_unix_timestamp_iso(html: str) -> str:
    """Prefer real Instagram publish time from embedded media JSON.

    IG HTML often has `"taken_at":1564064246` (not only `taken_at_timestamp`).
    """
    patterns = (
        r'"taken_at_timestamp"\s*:\s*(\d{9,12})',
        r'"taken_at"\s*:\s*(\d{9,12})',
        r'"caption"\s*:\s*\{[^{}]*?"created_at"\s*:\s*(\d{9,12})',
        r'"date_published"\s*:\s*(\d{9,12})',
    )
    candidates: list[int] = []
    for pattern in patterns:
        for match in re.finditer(pattern, html):
            try:
                value = int(match.group(1))
            except Exception:
                continue
            # Ignore non-second epoch noise
            if 1_000_000_000 <= value <= 4_000_000_000:
                candidates.append(value)
    if not candidates:
        return ""
    # Earliest media timestamp ≈ post publish time
    try:
        return datetime.fromtimestamp(min(candidates), tz=timezone.utc).isoformat()
    except Exception:
        return ""


def search_meta_content(html: str, property_name: str) -> str:
    match = re.search(
        rf'<meta[^>]+property="{re.escape(property_name)}"[^>]+content="([^"]*)"',
        html,
        re.IGNORECASE,
    )
    return match.group(1) if match else ""


def extract_crawled_comments(item: dict, post_id: str, post_url: str, post_created_at: str = "") -> list[dict]:
    raw_comments = item.get("crawled_comments") or []
    if not isinstance(raw_comments, list):
        raw_comments = []
    if not raw_comments:
        raw_comments = extract_instagram_comments_from_body_text(str(item.get("body_text") or ""), post_url)

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
                    post_created_at,
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
    """Publish time only — never fall back to crawled_at / now."""
    for candidate in (
        metadata.get("post_created_at"),
        extract_date_from_body_text(str(item.get("body_text") or "")),
    ):
        resolved = normalize_created_at(candidate)
        if resolved and not _is_same_instant(resolved, item.get("crawled_at")):
            return resolved

    # Relative UI crumbs like "366w" / "3d" — only if we can anchor to crawl time
    crawled_at = parse_iso_datetime(item.get("crawled_at"))
    if crawled_at is not None:
        relative = extract_relative_label_from_body(str(item.get("body_text") or ""))
        if relative:
            from social_listening.review_utils import parse_media_date_label

            parsed = parse_media_date_label(relative, reference=crawled_at)
            if parsed is None:
                parsed = parse_relative_time_label(relative, crawled_at)
            if parsed is not None:
                return parsed.astimezone(timezone.utc).isoformat()
    return ""


def extract_date_from_body_text(body: str) -> str:
    if not body:
        return ""
    match = re.search(
        r"(?i)((?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
        r"Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
        r"\s+\d{1,2},?\s+\d{4})",
        body,
    )
    return match.group(1) if match else ""


def extract_relative_label_from_body(body: str) -> str:
    """Instagram often shows `366w` under the username before caption."""
    if not body:
        return ""
    # Prefer early lines (header), not random numbers in caption
    head = "\n".join((body or "").splitlines()[:12])
    match = re.search(
        r"(?i)\b(\d+\s*[smhdwy]|just\s+now|\d+\s*(?:second|minute|hour|day|week|month|year)s?\s*ago|"
        r"\d+\s*(?:giây|phút|giờ|ngày|tuần|tháng|năm)\s*trước)\b",
        head,
    )
    return match.group(1).strip() if match else ""


def _is_same_instant(iso_a: object, iso_b: object, *, tolerance_seconds: int = 2) -> bool:
    a = parse_iso_datetime(iso_a)
    b = parse_iso_datetime(iso_b)
    if a is None or b is None:
        return False
    return abs((a - b).total_seconds()) <= tolerance_seconds


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


def resolve_comment_created_at(value: object, label: str, crawled_at: str, post_created_at: str = "") -> str:
    normalized = normalize_created_at(value)
    if normalized and _is_same_instant(normalized, crawled_at):
        normalized = ""
    if normalized:
        return normalized
    reference = parse_iso_datetime(crawled_at) or parse_iso_datetime(post_created_at)
    if reference is None:
        return ""
    if not (label or "").strip():
        return ""
    from social_listening.review_utils import parse_media_date_label

    parsed_label = parse_media_date_label(label, reference=reference)
    if parsed_label is not None:
        return parsed_label.replace(tzinfo=timezone.utc).isoformat()
    relative_dt = parse_relative_time_label(label, reference)
    if relative_dt is not None:
        return relative_dt.isoformat()
    return ""


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
