from __future__ import annotations

import json
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

from social_listening.film_paths import platform_processed_dir
from social_listening.keyword_config import film_title
from social_listening.paths import ensure_dir


INPUT_FILE = platform_processed_dir("facebook") / "facebook_keyword_mentions.json"
OUTPUT_FILE = platform_processed_dir("facebook") / "facebook_formatted_mentions.json"
SOURCE_NAME = "facebook_format_job"
MAX_SAFE_INTEGER = 9_007_199_254_740_991


def main() -> int:
    if not INPUT_FILE.exists():
        raise RuntimeError(f"Missing input file: {INPUT_FILE}")

    payload = json.loads(INPUT_FILE.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise RuntimeError("facebook_keyword_mentions.json must be a JSON array")

    title = film_title()
    records: list[dict] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        record = build_legacy_record(item, title)
        if record:
            records.append(record)

    ensure_dir(OUTPUT_FILE.parent)
    OUTPUT_FILE.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved {len(records)} formatted posts to {OUTPUT_FILE.resolve()}")
    return 0


def build_legacy_record(item: dict, title: str) -> dict:
    platform = str(item.get("platform") or "").strip()
    raw_post_id = str(item.get("post_id") or "").strip()
    if platform != "facebook" or not raw_post_id:
        return {}

    comments = [comment for comment in item.get("comments") or [] if isinstance(comment, dict)]
    comment_texts = [str(comment.get("text") or "") for comment in comments]

    post_id = normalize_identifier(raw_post_id)
    page_id = normalize_identifier(str(item.get("page_id") or "").strip())

    return {
        "id": post_id,
        "platform": "facebook",
        "post_id": post_id,
        "page_id": page_id,
        "page_name": str(item.get("page_name") or "").strip(),
        "post_text": str(item.get("post_text") or "").strip(),
        "comments_": comment_texts,
        "created_at_comment": pick_latest_comment_timestamp(comments),
        "film_title": title,
    }


def normalize_identifier(value: str):
    text = (value or "").strip()
    if not text:
        return ""
    if text.isdigit():
        number = int(text)
        if number <= MAX_SAFE_INTEGER:
            return number
    return text


def pick_latest_comment_timestamp(comments: list[dict]) -> str:
    values: list[datetime] = []
    for comment in comments:
        created_at = str(comment.get("created_at") or "").strip()
        if not created_at:
            continue
        try:
            dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        except Exception:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        values.append(dt.astimezone(timezone.utc))
    if not values:
        return ""
    return max(values).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
