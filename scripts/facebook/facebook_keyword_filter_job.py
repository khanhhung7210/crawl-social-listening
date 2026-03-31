from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from social_listening.paths import DATA_DIR, ensure_dir
from social_listening.film_paths import film_slug, platform_processed_dir
from social_listening.keyword_config import collect_search_terms, load_keyword_payload
from social_listening.text_utils import contains_keyword


INPUT_ROOT = DATA_DIR / "facebook" / "raw" / film_slug()
OUTPUT_FILE = platform_processed_dir("facebook") / "facebook_keyword_mentions.json"
SOURCE_NAME = "facebook_keyword_filter_job"


def main() -> int:
    ensure_dir(OUTPUT_FILE.parent)
    keyword_payload = load_keyword_payload()
    search_terms = collect_search_terms(keyword_payload)
    if not search_terms:
        raise RuntimeError("No search terms found in shared keyword config")

    records: list[dict] = []

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

                grouped_post = build_grouped_post(post, search_terms, page_id, page_name, path)
                if grouped_post:
                    records.append(grouped_post)

    OUTPUT_FILE.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved {len(records)} posts to {OUTPUT_FILE.resolve()}")
    return 0
def build_grouped_post(
    post: dict,
    search_terms: list[str],
    page_id: str,
    page_name: str,
    source_path: Path,
) -> dict:
    post_id = str(post.get("id") or "").strip()
    if not post_id:
        return {}

    post_text = pick_post_text(post)
    comments = ((post.get("comments") or {}).get("data") or []) if isinstance(post.get("comments"), dict) else []
    post_matches = find_keyword_matches(post_text, search_terms)
    comment_items = flatten_comments(comments, search_terms, post_id, post.get("permalink_url") or "")
    post_keyword_match = bool(post_matches)
    parent_keyword_match = post_keyword_match or any(item["keyword_match"] for item in comment_items)
    if not parent_keyword_match:
        return {}

    return {
        "platform": "facebook",
        "post_id": post_id,
        "page_id": page_id,
        "page_name": page_name,
        "post_url": post.get("permalink_url") or "",
        "post_created_at": parse_ts(post.get("created_time", "")).isoformat(),
        "post_text": post_text,
        "post_keyword_match": post_keyword_match,
        "post_keyword_matches": post_matches,
        "parent_keyword_match": parent_keyword_match,
        "source": SOURCE_NAME,
        "source_file": str(source_path),
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


def flatten_comments(
    comments: list[dict],
    search_terms: list[str],
    post_id: str,
    post_url: str,
) -> list[dict]:
    items: list[dict] = []
    for comment in comments:
        comment_id = str(comment.get("id") or "").strip()
        if not comment_id:
            continue
        comment_text = str(comment.get("message") or "").strip()
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
        "created_at": parse_ts(comment.get("created_time", "")).isoformat(),
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


def parse_ts(value: str) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S%z").astimezone(timezone.utc)
    except Exception:
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            return datetime.now(timezone.utc)


if __name__ == "__main__":
    raise SystemExit(main())
