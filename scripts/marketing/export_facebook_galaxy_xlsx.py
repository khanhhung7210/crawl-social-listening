#!/usr/bin/env python3
"""Export Galaxy-only Facebook keywords + matched posts/comments to CSV."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path


def _project_root() -> Path:
    current = Path(__file__).resolve().parent
    for cand in [current, *current.parents]:
        if (cand / "src" / "social_listening").is_dir():
            return cand
    raise RuntimeError(f"Cannot find project root from {__file__}")


PROJECT_ROOT = _project_root()
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from social_listening.film_paths import film_slug, platform_processed_dir
from social_listening.keyword_config import load_keyword_payload
from social_listening.text_utils import contains_keyword


INPUT_FILE = platform_processed_dir("facebook") / "facebook_keyword_mentions.json"
DEFAULT_OUT_DIR = PROJECT_ROOT.parent / "exports" / "marketing"
DATE_STAMP = datetime.now().strftime("%Y%m%d")

GALAXY_LISTENING_HINTS = (
    "cine chao",
    "cine chào",
    "cinechaosummer",
    "chào summer",
    "đắm mình",
    "ưu đãi cine",
)


def is_galaxy_term(term: str) -> bool:
    normalized = term.lower().lstrip("#")
    if "galaxy" in normalized or "galaxycinema" in normalized or "galaxymovie" in normalized:
        return True
    return any(hint in normalized for hint in GALAXY_LISTENING_HINTS)


def collect_galaxy_terms(payload: dict) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    seen: set[str] = set()
    for category in ("keywords", "sub_keywords", "branch_keywords", "listening_keywords", "hashtags"):
        for term in payload.get(category) or []:
            value = str(term if not isinstance(term, dict) else term.get("keyword") or term.get("value") or "").strip()
            if not value or value in seen or not is_galaxy_term(value):
                continue
            seen.add(value)
            rows.append((category, value))
    return rows


def find_matches(text: str, terms: list[str]) -> list[str]:
    return [term for term in terms if contains_keyword(text, term)]


def load_processed_posts(path: Path) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(f"Processed Facebook file not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise RuntimeError(f"Expected JSON array in {path}")
    return payload


def load_raw_posts(raw_dir: Path) -> list[dict]:
    posts: list[dict] = []
    for path in sorted(raw_dir.rglob("*.jsonl")):
        with path.open("r", encoding="utf-8") as file:
            for line in file:
                line = line.strip()
                if not line:
                    continue
                post = json.loads(line)
                post["_source_file"] = str(path)
                posts.append(post)
    return posts


def raw_post_to_rows(post: dict, galaxy_terms: list[str]) -> list[dict]:
    rows: list[dict] = []
    post_text = str(post.get("message") or post.get("story") or "").strip()
    post_matches = find_matches(post_text, galaxy_terms)
    post_id = str(post.get("id") or "").strip()
    post_url = str(post.get("permalink_url") or "").strip()
    page_name = str(post.get("page_name") or post.get("author") or "").strip()
    created_at = str(post.get("created_time") or "").strip()
    created_label = str(post.get("created_time_label") or "").strip()

    if post_matches:
        rows.append(
            {
                "record_type": "post",
                "external_id": f"post:{post_id}",
                "post_id": post_id,
                "page_name": page_name,
                "author": page_name,
                "text": post_text,
                "keyword_matches": ", ".join(post_matches),
                "url": post_url,
                "created_at": created_at,
                "created_time_label": created_label,
                "source_file": post.get("_source_file") or "",
            }
        )

    for index, comment in enumerate((post.get("comments") or {}).get("data") or [], start=1):
        comment_text = str(comment.get("message") or "").strip()
        comment_matches = find_matches(comment_text, galaxy_terms)
        if not comment_matches:
            continue
        comment_id = str(comment.get("id") or f"{post_id}_{index}").strip()
        rows.append(
            {
                "record_type": "comment",
                "external_id": f"comment:{comment_id}",
                "post_id": post_id,
                "page_name": page_name,
                "author": page_name,
                "text": comment_text,
                "keyword_matches": ", ".join(comment_matches),
                "url": post_url,
                "created_at": str(comment.get("created_time") or "").strip(),
                "created_time_label": str(comment.get("created_time_label") or "").strip(),
                "source_file": post.get("_source_file") or "",
            }
        )
    return rows


def collect_comment_rows(posts: list[dict], galaxy_terms: list[str]) -> list[dict]:
    rows: list[dict] = []

    for post in posts:
        if "message" in post or "story" in post:
            rows.extend(raw_post_to_rows(post, galaxy_terms))
            continue

        post_text = str(post.get("post_text") or "").strip()
        post_matches = find_matches(post_text, galaxy_terms)

        if post_matches:
            rows.append(
                {
                    "record_type": "post",
                    "external_id": f"post:{post.get('post_id') or ''}",
                    "post_id": post.get("post_id") or "",
                    "page_name": post.get("page_name") or "",
                    "author": post.get("page_name") or post.get("page_id") or "",
                    "text": post_text,
                    "keyword_matches": ", ".join(post_matches),
                    "url": post.get("post_url") or "",
                    "created_at": post.get("post_created_at") or "",
                    "created_time_label": post.get("post_created_at_label") or "",
                    "source_file": post.get("source_file") or "",
                }
            )

        for comment in post.get("comments") or []:
            comment_text = str(comment.get("text") or "").strip()
            comment_matches = find_matches(comment_text, galaxy_terms)
            if not comment_matches:
                continue
            rows.append(
                {
                    "record_type": comment.get("record_type") or "comment",
                    "external_id": comment.get("external_id") or "",
                    "post_id": comment.get("post_id") or post.get("post_id") or "",
                    "page_name": comment.get("page_name") or post.get("page_name") or "",
                    "author": comment.get("author") or "",
                    "text": comment_text,
                    "keyword_matches": ", ".join(comment_matches),
                    "url": comment.get("url") or post.get("post_url") or "",
                    "created_at": comment.get("created_at") or "",
                    "created_time_label": comment.get("created_at_label") or "",
                    "source_file": post.get("source_file") or "",
                }
            )

    return rows


def write_csv(path: Path, headers: list[str], rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(headers)
        writer.writerows(rows)


def write_exports(
    keyword_rows: list[tuple[str, str]],
    comment_rows: list[dict],
    output_dir: Path,
    date_stamp: str,
) -> tuple[Path, Path]:
    keywords_path = output_dir / f"facebook_galaxy_keywords_{date_stamp}.csv"
    comments_path = output_dir / f"facebook_galaxy_comments_{date_stamp}.csv"

    write_csv(
        keywords_path,
        ["category", "keyword"],
        [[category, keyword] for category, keyword in keyword_rows],
    )

    comment_headers = [
        "record_type",
        "external_id",
        "post_id",
        "page_name",
        "author",
        "text",
        "keyword_matches",
        "url",
        "created_at",
        "created_time_label",
        "source_file",
    ]
    write_csv(
        comments_path,
        comment_headers,
        [[str(row.get(header, "") or "") for header in comment_headers] for row in comment_rows],
    )
    return keywords_path, comments_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Export Galaxy Facebook keywords + comments to CSV")
    parser.add_argument("--input", type=Path, default=INPUT_FILE, help="facebook_keyword_mentions.json path")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUT_DIR, help="Output directory for CSV files")
    parser.add_argument("--date-stamp", default=DATE_STAMP, help="Date suffix for output filenames")
    parser.add_argument(
        "--raw-date",
        default="",
        help="Export from raw JSONL folder data/facebook/raw/<film>/<YYYYMMDD> instead of processed JSON",
    )
    args = parser.parse_args()

    payload = load_keyword_payload()
    keyword_rows = collect_galaxy_terms(payload)
    galaxy_terms = [keyword for _, keyword in keyword_rows]
    if args.raw_date:
        raw_dir = PROJECT_ROOT / "data" / "facebook" / "raw" / film_slug() / str(args.raw_date).strip()
        posts = load_raw_posts(raw_dir)
    else:
        posts = load_processed_posts(args.input)
    comment_rows = collect_comment_rows(posts, galaxy_terms)

    keywords_path, comments_path = write_exports(keyword_rows, comment_rows, args.output_dir, args.date_stamp)

    print(f"film={film_slug()}")
    print(f"keywords={len(keyword_rows)}")
    print(f"rows={len(comment_rows)} (posts={sum(1 for r in comment_rows if r['record_type']=='post')}, "
          f"comments={sum(1 for r in comment_rows if r['record_type']=='comment')}, "
          f"replies={sum(1 for r in comment_rows if r['record_type']=='reply')})")
    print(f"saved {keywords_path.resolve()}")
    print(f"saved {comments_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
