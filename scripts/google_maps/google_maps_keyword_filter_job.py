from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from social_listening.film_paths import platform_processed_dir
from social_listening.fnb_relevance import evaluate_fnb_relevance
from social_listening.keyword_config import collect_search_terms, load_keyword_payload
from social_listening.paths import ensure_dir
from social_listening.text_utils import contains_keyword


INPUT_FILE = platform_processed_dir("google_maps") / "google_maps_grouped_parsed.json"
OUTPUT_FILE = platform_processed_dir("google_maps") / "google_maps_keyword_mentions.json"
SOURCE_NAME = "google_maps_keyword_filter_job"


def main() -> int:
    if not INPUT_FILE.exists():
        raise RuntimeError(f"Missing input file: {INPUT_FILE}")
    payload = json.loads(INPUT_FILE.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise RuntimeError("google_maps_grouped_parsed.json must be a JSON array")

    keyword_payload = load_keyword_payload()
    search_terms = collect_search_terms(keyword_payload, include_hashtags=False)
    records: list[dict] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        filtered = build_filtered_record(item, search_terms, keyword_payload)
        if filtered:
            records.append(filtered)

    ensure_dir(OUTPUT_FILE.parent)
    OUTPUT_FILE.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved {len(records)} google maps records to {OUTPUT_FILE.resolve()}")
    return 0


def build_filtered_record(item: dict, search_terms: list[str], keyword_payload: dict) -> dict:
    post_text = str(item.get("post_text") or "")
    post_keyword_matches = find_keyword_matches(post_text, search_terms)
    post_keyword_match = bool(post_keyword_matches)

    comments: list[dict] = []
    comment_keyword_match = False
    for raw_comment in item.get("comments") or []:
        if not isinstance(raw_comment, dict):
            continue
        text = str(raw_comment.get("text") or "")
        keyword_matches = find_keyword_matches(text, search_terms)
        keyword_match = bool(keyword_matches)
        comment_keyword_match = comment_keyword_match or keyword_match
        comments.append({**raw_comment, "keyword_match": keyword_match, "keyword_matches": keyword_matches})

    parent_keyword_match = post_keyword_match or comment_keyword_match
    if not parent_keyword_match:
        return {}

    candidate = {
        **item,
        "post_keyword_match": post_keyword_match,
        "post_keyword_matches": post_keyword_matches,
        "parent_keyword_match": parent_keyword_match,
        "source": SOURCE_NAME,
        "comments": comments,
    }
    fnb_relevance = evaluate_fnb_relevance(candidate, keyword_payload)
    if not fnb_relevance["is_relevant_fnb"]:
        return {}

    return {
        **candidate,
        "fnb_relevance": fnb_relevance,
    }


def find_keyword_matches(text: str, search_terms: list[str]) -> list[str]:
    return [term for term in search_terms if contains_keyword(text, term)]


if __name__ == "__main__":
    raise SystemExit(main())
