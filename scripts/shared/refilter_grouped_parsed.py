from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from social_listening.keyword_config import collect_search_terms, load_keyword_payload
from social_listening.text_utils import contains_keyword


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refilter grouped_parsed.json files by a named keyword set")
    parser.add_argument("--set-name", required=True, help="saved_keyword_sets[].name to use")
    parser.add_argument("files", nargs="+", help="grouped_parsed.json files to refilter in place")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = load_keyword_payload()
    keyword_payload = resolve_keyword_set(payload, args.set_name)
    search_terms = collect_search_terms(keyword_payload)
    film_title = str(keyword_payload.get("film_title") or "").strip()
    if film_title and film_title not in search_terms:
        search_terms = [film_title, *search_terms]
    if not search_terms:
        raise RuntimeError(f"No search terms found for keyword set: {args.set_name}")

    for raw_file in args.files:
        path = Path(raw_file).resolve()
        refilter_grouped_file(path, search_terms, args.set_name, film_title)
    return 0


def resolve_keyword_set(payload: dict, set_name: str) -> dict:
    saved_sets = payload.get("saved_keyword_sets") or []
    if not isinstance(saved_sets, list):
        raise RuntimeError("saved_keyword_sets must be a JSON array")

    for item in saved_sets:
        if not isinstance(item, dict):
            continue
        if str(item.get("name") or "").strip() == set_name:
            return item
    raise RuntimeError(f"Keyword set not found: {set_name}")


def refilter_grouped_file(path: Path, search_terms: list[str], set_name: str, film_title: str) -> None:
    if not path.exists():
        raise FileNotFoundError(f"Missing grouped_parsed file: {path}")

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise RuntimeError(f"grouped_parsed payload must be a JSON array: {path}")

    filtered_records: list[dict] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        filtered = build_filtered_record(item, search_terms, set_name, film_title)
        if filtered:
            filtered_records.append(filtered)

    backup_path = path.with_suffix(path.suffix + ".bak")
    shutil.copy2(path, backup_path)
    path.write_text(json.dumps(filtered_records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"refiltered {path} -> kept {len(filtered_records)}/{len(payload)} "
        f"records using set={set_name}; backup={backup_path}"
    )


def build_filtered_record(item: dict, search_terms: list[str], set_name: str, film_title: str) -> dict:
    post_text = str(item.get("post_text") or "")
    post_keyword_matches = find_matches(post_text, search_terms)
    post_keyword_match = bool(post_keyword_matches)

    comments: list[dict] = []
    comment_keyword_match = False
    for raw_comment in item.get("comments") or []:
        if not isinstance(raw_comment, dict):
            continue
        text = str(raw_comment.get("text") or "")
        keyword_matches = find_matches(text, search_terms)
        keyword_match = bool(keyword_matches)
        comment_keyword_match = comment_keyword_match or keyword_match
        comments.append({**raw_comment, "keyword_match": keyword_match, "keyword_matches": keyword_matches})

    parent_keyword_match = post_keyword_match or comment_keyword_match
    if not parent_keyword_match:
        return {}

    return {
        **item,
        "film_title": film_title or str(item.get("film_title") or "").strip(),
        "post_keyword_match": post_keyword_match,
        "post_keyword_matches": post_keyword_matches,
        "parent_keyword_match": parent_keyword_match,
        "keyword_set": set_name,
        "comments": comments,
    }


def find_matches(text: str, search_terms: list[str]) -> list[str]:
    return [term for term in search_terms if contains_keyword(text, term)]


if __name__ == "__main__":
    raise SystemExit(main())
