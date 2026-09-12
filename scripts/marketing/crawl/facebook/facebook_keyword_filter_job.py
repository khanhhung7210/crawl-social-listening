from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

def _project_root() -> Path:
    current = Path(__file__).resolve().parent
    for cand in [current, *current.parents]:
        if (cand / "src" / "social_listening").is_dir():
            return cand
    raise RuntimeError(f"Cannot find project root from {__file__}")


PROJECT_ROOT = _project_root()
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from social_listening.paths import DATA_DIR, ensure_dir
from social_listening.film_paths import film_slug, platform_processed_dir
from social_listening.film_crawl_filter import keep_distribution_record, passes_film_relevance
from social_listening.keyword_config import collect_exclude_terms, collect_search_terms, load_keyword_payload
from social_listening.review_utils import VN_TZ, parse_facebook_datetime_label
from social_listening.text_utils import contains_keyword, parse_compact_count


INPUT_ROOT = DATA_DIR / "facebook" / "raw" / film_slug()
OUTPUT_FILE = platform_processed_dir("facebook") / "facebook_keyword_mentions.json"
SOURCE_NAME = "facebook_keyword_filter_job"


def main() -> int:
    ensure_dir(OUTPUT_FILE.parent)
    keyword_payload = load_keyword_payload()
    search_terms = collect_search_terms(keyword_payload)
    exclude_terms = collect_exclude_terms(keyword_payload)
    if not search_terms:
        raise RuntimeError("No search terms found in shared keyword config")

    records: list[dict] = []
    skipped_spam = 0

    for path in sorted(INPUT_ROOT.rglob("*.jsonl")):
        page_id, page_name = parse_page_context(path)
        with path.open("r", encoding="utf-8") as file:
            for line_number, raw_line in enumerate(file, start=1):
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                try:
                    post = json.loads(raw_line)
                except json.JSONDecodeError as exc:
                    print(f"[skip] invalid json path={path} line={line_number}: {exc}")
                    continue

                grouped_post = build_grouped_post(
                    post,
                    search_terms,
                    exclude_terms,
                    keyword_payload,
                    page_id,
                    page_name,
                    path,
                )
                if grouped_post is None:
                    skipped_spam += 1
                    continue
                if grouped_post:
                    records.append(grouped_post)

    OUTPUT_FILE.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved {len(records)} posts to {OUTPUT_FILE.resolve()} (skipped_spam={skipped_spam})")
    return 0


def hits_exclude(text: str, exclude_terms: list[str]) -> list[str]:
    return [term for term in exclude_terms if contains_keyword(text, term)]


def build_grouped_post(
    post: dict,
    search_terms: list[str],
    exclude_terms: list[str],
    keyword_payload: dict,
    page_id: str,
    page_name: str,
    source_path: Path,
) -> dict | None:
    post_id = str(post.get("id") or "").strip()
    if not post_id:
        return {}

    post_text = pick_post_text(post)
    post_excludes = hits_exclude(post_text, exclude_terms)
    if post_excludes:
        return None

    comments = ((post.get("comments") or {}).get("data") or []) if isinstance(post.get("comments"), dict) else []
    post_matches = find_keyword_matches(post_text, search_terms)
    comment_items = flatten_comments(comments, search_terms, exclude_terms, post_id, post.get("permalink_url") or "")
    post_keyword_match = bool(post_matches)
    parent_keyword_match = post_keyword_match or any(item["keyword_match"] for item in comment_items)
    if not parent_keyword_match:
        return {}

    comments_payload = [
        {
            "text": str(item.get("comment_text") or item.get("text") or ""),
            "keyword_matches": list(item.get("keyword_matches") or []),
        }
        for item in comment_items
    ]
    keep, filtered_comments = keep_distribution_record(post_text, post_matches, comments_payload)
    if not keep:
        return None
    kept_texts = {str(c.get("text") or "") for c in filtered_comments}
    comment_items = [
        item
        for item in comment_items
        if str(item.get("comment_text") or item.get("text") or "") in kept_texts
    ]
    post_keyword_match = passes_film_relevance(post_text, post_matches)
    parent_keyword_match = post_keyword_match or bool(comment_items)

    candidate = {
        "platform": "facebook",
        "post_id": post_id,
        "page_id": page_id,
        "page_name": page_name,
        "post_url": post.get("permalink_url") or "",
        "post_created_at": (lambda dt: dt.isoformat() if dt else None)(resolve_raw_post_created_at(post)),
        "post_created_at_label": str(post.get("created_time_label") or "").strip() or None,
        "post_text": post_text,
        "post_keyword_match": post_keyword_match,
        "post_keyword_matches": post_matches,
        "parent_keyword_match": parent_keyword_match,
        "source": SOURCE_NAME,
        "source_file": str(source_path),
        "stats": build_post_stats(post, comment_items),
        "comments": [
            build_comment_record(
                item=item,
                page_id=page_id,
                page_name=page_name,
                post_id=post_id,
                parent_keyword_match=parent_keyword_match,
            )
            for item in comment_items
        ],
    }
    return candidate


def build_post_stats(post: dict, comment_items: list[dict]) -> dict:
    like_count = first_int(
        post.get("like_count"),
        post.get("reaction_count"),
        (post.get("stats") or {}).get("like_count") if isinstance(post.get("stats"), dict) else None,
    )
    comment_count = first_int(
        post.get("comment_count"),
        (post.get("stats") or {}).get("comment_count") if isinstance(post.get("stats"), dict) else None,
    )
    share_count = first_int(
        post.get("share_count"),
        (post.get("stats") or {}).get("share_count") if isinstance(post.get("stats"), dict) else None,
    )
    # Fallback: number of comments we actually crawled (underestimates total).
    if comment_count is None and comment_items:
        comment_count = len(comment_items)
    return {
        "like_count": like_count,
        "comment_count": comment_count,
        "share_count": share_count,
    }


def first_int(*values: object) -> int | None:
    for value in values:
        parsed = parse_compact_count(value)
        if parsed is not None:
            return parsed
    return None


def flatten_comments(
    comments: list[dict],
    search_terms: list[str],
    exclude_terms: list[str],
    post_id: str,
    post_url: str,
) -> list[dict]:
    items: list[dict] = []
    for comment in comments:
        comment_id = str(comment.get("id") or "").strip()
        if not comment_id:
            continue
        comment_text = str(comment.get("message") or "").strip()
        if hits_exclude(comment_text, exclude_terms):
            continue
        comment_matches = find_keyword_matches(comment_text, search_terms)
        items.append(
            {
                "record_type": "comment",
                "id": comment_id,
                "text": comment_text,
                "url": build_comment_url(post_url, comment_id),
                "parent_comment_id": "",
                "keyword_match": bool(comment_matches),
                "keyword_matches": comment_matches,
                "comment": comment,
            }
        )

        replies = ((comment.get("comments") or {}).get("data") or []) if isinstance(comment.get("comments"), dict) else []
        for reply in replies:
            reply_id = str(reply.get("id") or "").strip()
            if not reply_id:
                continue
            reply_text = str(reply.get("message") or "").strip()
            if hits_exclude(reply_text, exclude_terms):
                continue
            reply_matches = find_keyword_matches(reply_text, search_terms)
            items.append(
                {
                    "record_type": "reply",
                    "id": reply_id,
                    "text": reply_text,
                    "url": build_comment_url(post_url, comment_id),
                    "parent_comment_id": comment_id,
                    "keyword_match": bool(reply_matches),
                    "keyword_matches": reply_matches,
                    "comment": reply,
                }
            )
    return items


def build_comment_record(
    item: dict,
    page_id: str,
    page_name: str,
    post_id: str,
    parent_keyword_match: bool,
) -> dict:
    comment = item["comment"]
    return {
        "external_id": f"{item['record_type']}:{item['id']}",
        "record_type": item["record_type"],
        "text": item["text"],
        "author": page_name or page_id,
        "url": item["url"],
        "created_at": _comment_created_at_iso(comment),
        "page_id": page_id,
        "page_name": page_name,
        "post_id": post_id,
        "parent_comment_id": item["parent_comment_id"],
        "keyword_match": item["keyword_match"],
        "keyword_matches": item["keyword_matches"],
        "parent_keyword_match": parent_keyword_match,
    }


def find_keyword_matches(text: str, search_terms: list[str]) -> list[str]:
    return [term for term in search_terms if contains_keyword(text, term)]


def parse_page_context(path: Path) -> tuple[str, str]:
    stem = path.stem
    if "_" not in stem:
        return "", stem
    page_id, page_name = stem.split("_", 1)
    return page_id.strip(), page_name.strip()


def pick_post_text(post: dict) -> str:
    return str(post.get("message") or post.get("story") or "").strip()


def build_comment_url(post_url: str, comment_id: str) -> str:
    post_url = (post_url or "").strip()
    if not post_url or not comment_id:
        return post_url
    separator = "&" if "?" in post_url else "?"
    return f"{post_url}{separator}comment_id={comment_id}"


def parse_ts(value: str) -> datetime | None:
    if not value or not str(value).strip():
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S%z").astimezone(timezone.utc)
    except Exception:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            return None


def resolve_raw_post_created_at(post: dict) -> datetime | None:
    """Prefer UI label when it has an explicit year — crawler ISO can be wrong.

    Facebook day-first labels like ``Saturday 12 September 2026 at 10:09`` used to
    parse as Sep 2025 and mark fresh complaint posts as stale.
    """
    label = str(post.get("created_time_label") or "").strip()
    iso_raw = str(post.get("created_time") or post.get("published_at") or "").strip()
    iso_dt = parse_ts(iso_raw) if iso_raw else None

    label_has_year = bool(re.search(r"\b(19|20)\d{2}\b", label))
    if label:
        parsed = parse_facebook_datetime_label(label)
        if parsed is not None:
            local = parsed.replace(tzinfo=VN_TZ) if parsed.tzinfo is None else parsed.astimezone(VN_TZ)
            label_dt = local.astimezone(timezone.utc)
            if label_has_year:
                return label_dt
            if iso_dt is None:
                return label_dt
            # Relative / yearless label: keep ISO if present.
    return iso_dt


def _comment_created_at_iso(comment: dict) -> str | None:
    label = str(comment.get("created_time_label") or "").strip()
    if label and re.search(r"\b(19|20)\d{2}\b", label):
        parsed = parse_facebook_datetime_label(label)
        if parsed is not None:
            local = parsed.replace(tzinfo=VN_TZ) if parsed.tzinfo is None else parsed.astimezone(VN_TZ)
            return local.astimezone(timezone.utc).isoformat()
    dt = parse_ts(str(comment.get("created_time") or ""))
    return dt.isoformat() if dt is not None else None


if __name__ == "__main__":
    raise SystemExit(main())
