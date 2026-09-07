#!/usr/bin/env python3
"""Export raw crawl + filtered keyword_mentions to CSV for Distribution films."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


def _project_root() -> Path:
    current = Path(__file__).resolve().parent
    for cand in [current, *current.parents]:
        if (cand / "src" / "social_listening").is_dir():
            return cand
    raise RuntimeError(f"Cannot find project root from {__file__}")


PROJECT_ROOT = _project_root()
DATA = PROJECT_ROOT / "data"
DEFAULT_OUT = PROJECT_ROOT / "data" / "distribution" / "exports"

PLATFORMS = ("facebook", "threads", "tiktok", "instagram", "youtube")


def _text(*parts: Any) -> str:
    for p in parts:
        if p is None:
            continue
        s = str(p).strip()
        if s:
            return s
    return ""


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow(row)
    return len(rows)


def load_json(path: Path) -> Any:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def as_list(data: Any, *keys: str) -> list:
    if data is None:
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in keys:
            v = data.get(k)
            if isinstance(v, list):
                return v
    return []


def export_threads_raw(film: str) -> list[dict]:
    rows: list[dict] = []
    data = load_json(DATA / "threads" / "raw" / film / "threads_all_threads.json")
    for i, item in enumerate(as_list(data), 1):
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "film_slug": film,
                "platform": "threads",
                "row_no": i,
                "kind": "thread_search_hit",
                "search_keyword": _text(item.get("keyword"), (item.get("keywords") or [""])[0] if item.get("keywords") else ""),
                "url": _text(item.get("url"), item.get("current_url")),
                "title": _text(item.get("title")),
                "text_content": _text(item.get("body_text"), item.get("title")),
                "matched": item.get("matched"),
                "matched_terms": "; ".join(item.get("matched_terms") or []),
                "linked_count": len(item.get("linked_threads") or []),
            }
        )
    parsed = load_json(DATA / "threads" / "processed" / film / "threads_grouped_parsed.json")
    for i, item in enumerate(as_list(parsed, "threads"), 1):
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "film_slug": film,
                "platform": "threads",
                "row_no": i,
                "kind": "thread_parsed",
                "search_keyword": _text(item.get("search_keyword"), item.get("keyword")),
                "url": _text(item.get("post_url"), item.get("url"), item.get("thread_url")),
                "title": "",
                "text_content": _text(item.get("post_text"), item.get("text"), item.get("caption")),
                "author_name": _text(item.get("author"), item.get("username"), item.get("page_name")),
                "comment_count": len(item.get("comments") or []),
                "like_count": item.get("like_count"),
            }
        )
    return rows


def export_threads_filtered(film: str) -> tuple[list[dict], list[dict]]:
    posts: list[dict] = []
    comments: list[dict] = []
    data = load_json(DATA / "threads" / "processed" / film / "threads_keyword_mentions.json")
    for i, item in enumerate(as_list(data), 1):
        if not isinstance(item, dict):
            continue
        post_id = _text(item.get("post_id"), item.get("url"))
        posts.append(
            {
                "film_slug": film,
                "platform": "threads",
                "row_no": i,
                "mention_kind": "post",
                "post_id": post_id,
                "url": _text(item.get("post_url"), item.get("url")),
                "author_name": _text(item.get("page_name"), item.get("author")),
                "created_at": _text(item.get("post_created_at"), item.get("created_at")),
                "text_content": _text(item.get("post_text"), item.get("text")),
                "post_keyword_match": item.get("post_keyword_match"),
                "post_keyword_matches": "; ".join(item.get("post_keyword_matches") or []),
                "parent_keyword_match": item.get("parent_keyword_match"),
                "search_keyword": _text(item.get("search_keyword"), item.get("matched_search_keyword")),
            }
        )
        for j, c in enumerate(item.get("comments") or [], 1):
            if not isinstance(c, dict):
                continue
            comments.append(
                {
                    "film_slug": film,
                    "platform": "threads",
                    "row_no": j,
                    "mention_kind": "comment",
                    "post_id": post_id,
                    "comment_id": _text(c.get("comment_id"), c.get("id")),
                    "url": _text(c.get("url"), c.get("comment_url")),
                    "author_name": _text(c.get("author"), c.get("username")),
                    "created_at": _text(c.get("created_at"), c.get("commented_at")),
                    "text_content": _text(c.get("text"), c.get("comment_text")),
                    "keyword_match": c.get("keyword_match"),
                    "keyword_matches": "; ".join(c.get("keyword_matches") or []),
                }
            )
    return posts, comments


def export_tiktok_raw(film: str) -> list[dict]:
    rows: list[dict] = []
    data = load_json(DATA / "tiktok" / "raw" / film / "tiktok_all_videos.json")
    for i, item in enumerate(as_list(data, "videos"), 1):
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "film_slug": film,
                "platform": "tiktok",
                "row_no": i,
                "search_keyword": _text(item.get("keyword")),
                "url": _text(item.get("url"), item.get("current_url")),
                "title": _text(item.get("title")),
                "text_content": _text(item.get("body_text"), item.get("title"), item.get("description")),
                "matched": item.get("matched"),
                "matched_terms": "; ".join(item.get("matched_terms") or []),
                "comment_count": item.get("comment_count_observed") or len(item.get("crawled_comments") or []),
            }
        )
    return rows


def export_facebook_raw(film: str) -> list[dict]:
    rows: list[dict] = []
    raw_dir = DATA / "facebook" / "raw" / film
    if not raw_dir.exists():
        return rows
    n = 0
    for fp in sorted(raw_dir.rglob("*.jsonl")):
        keyword = fp.stem.replace("search_", "")
        for line in fp.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(item, dict):
                continue
            n += 1
            rows.append(
                {
                    "film_slug": film,
                    "platform": "facebook",
                    "row_no": n,
                    "search_keyword": keyword,
                    "post_id": _text(item.get("id")),
                    "url": _text(item.get("permalink_url")),
                    "created_at": _text(item.get("created_time"), item.get("created_time_label")),
                    "text_content": _text(item.get("message"), item.get("story")),
                    "like_count": item.get("like_count") or item.get("reaction_count"),
                    "comment_count": item.get("comment_count"),
                    "share_count": item.get("share_count"),
                    "raw_comments": len(item.get("comments") or []),
                }
            )
    return rows


def export_instagram_raw(film: str) -> list[dict]:
    rows: list[dict] = []
    for fname in ("instagram_all_posts.json", "instagram_search_results.json"):
        data = load_json(DATA / "instagram" / "raw" / film / fname)
        for i, item in enumerate(as_list(data, "posts", "items"), 1):
            if not isinstance(item, dict):
                continue
            rows.append(
                {
                    "film_slug": film,
                    "platform": "instagram",
                    "source_file": fname,
                    "row_no": i,
                    "url": _text(item.get("url"), item.get("post_url"), item.get("permalink")),
                    "author_name": _text(item.get("username"), item.get("owner_username")),
                    "text_content": _text(item.get("caption"), item.get("text"), item.get("title")),
                    "like_count": item.get("like_count") or item.get("likes"),
                    "comment_count": item.get("comment_count") or item.get("comments_count"),
                }
            )
    return rows


def export_youtube_raw(film: str) -> list[dict]:
    rows: list[dict] = []
    data = load_json(DATA / "youtube" / "raw" / film / "youtube_all_videos.json")
    for i, item in enumerate(as_list(data, "videos"), 1):
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "film_slug": film,
                "platform": "youtube",
                "row_no": i,
                "search_keyword": _text(item.get("keyword")),
                "url": _text(item.get("url"), item.get("video_url")),
                "title": _text(item.get("title")),
                "text_content": _text(item.get("description"), item.get("title")),
                "view_count": item.get("view_count"),
                "like_count": item.get("like_count"),
                "comment_count": item.get("comment_count"),
            }
        )
    return rows


def export_generic_filtered(film: str, platform: str) -> tuple[list[dict], list[dict]]:
    posts: list[dict] = []
    comments: list[dict] = []
    fp = DATA / platform / "processed" / film / f"{platform}_keyword_mentions.json"
    data = load_json(fp)
    for i, item in enumerate(as_list(data), 1):
        if not isinstance(item, dict):
            continue
        post_id = _text(item.get("post_id"), item.get("url"))
        posts.append(
            {
                "film_slug": film,
                "platform": platform,
                "row_no": i,
                "mention_kind": "post",
                "post_id": post_id,
                "url": _text(item.get("post_url"), item.get("url")),
                "author_name": _text(item.get("page_name"), item.get("author"), item.get("channel_name")),
                "created_at": _text(item.get("post_created_at"), item.get("created_at"), item.get("published_at")),
                "text_content": _text(item.get("post_text"), item.get("text"), item.get("title")),
                "post_keyword_match": item.get("post_keyword_match"),
                "post_keyword_matches": "; ".join(item.get("post_keyword_matches") or []),
                "parent_keyword_match": item.get("parent_keyword_match"),
                "like_count": item.get("like_count"),
                "comment_count": item.get("comment_count"),
                "view_count": item.get("view_count"),
            }
        )
        for j, c in enumerate(item.get("comments") or [], 1):
            if not isinstance(c, dict):
                continue
            comments.append(
                {
                    "film_slug": film,
                    "platform": platform,
                    "row_no": j,
                    "mention_kind": "comment",
                    "post_id": post_id,
                    "comment_id": _text(c.get("comment_id"), c.get("id")),
                    "url": _text(c.get("url"), c.get("comment_url")),
                    "author_name": _text(c.get("author"), c.get("username")),
                    "created_at": _text(c.get("created_at"), c.get("commented_at")),
                    "text_content": _text(c.get("text"), c.get("comment_text")),
                    "keyword_match": c.get("keyword_match"),
                    "keyword_matches": "; ".join(c.get("keyword_matches") or []),
                    "like_count": c.get("like_count"),
                }
            )
    return posts, comments


RAW_EXPORTERS = {
    "threads": export_threads_raw,
    "tiktok": export_tiktok_raw,
    "facebook": export_facebook_raw,
    "instagram": export_instagram_raw,
    "youtube": export_youtube_raw,
}


POST_FIELDS = [
    "film_slug", "platform", "row_no", "mention_kind", "post_id", "url", "author_name",
    "created_at", "text_content", "search_keyword", "post_keyword_match",
    "post_keyword_matches", "parent_keyword_match", "like_count", "comment_count", "view_count",
]

COMMENT_FIELDS = [
    "film_slug", "platform", "row_no", "mention_kind", "post_id", "comment_id", "url",
    "author_name", "created_at", "text_content", "keyword_match", "keyword_matches", "like_count",
]

RAW_FIELDS = [
    "film_slug", "platform", "row_no", "kind", "source_file", "search_keyword", "post_id",
    "url", "title", "author_name", "created_at", "text_content", "matched", "matched_terms",
    "linked_count", "like_count", "comment_count", "share_count", "view_count", "raw_comments",
]


def export_film(film: str, out_dir: Path) -> dict[str, int]:
    stats: dict[str, int] = {}
    all_raw: list[dict] = []
    all_filtered_posts: list[dict] = []
    all_filtered_comments: list[dict] = []

    for plat in PLATFORMS:
        raw_fn = RAW_EXPORTERS.get(plat)
        raw_rows = raw_fn(film) if raw_fn else []
        stats[f"{plat}_raw"] = len(raw_rows)
        all_raw.extend(raw_rows)
        if raw_rows:
            n = write_csv(out_dir / f"{film}__{plat}__raw.csv", raw_rows, RAW_FIELDS)
            print(f"  {film}/{plat} raw: {n} -> {out_dir.name}/{film}__{plat}__raw.csv")

        if plat == "threads":
            posts, comments = export_threads_filtered(film)
        else:
            posts, comments = export_generic_filtered(film, plat)
        stats[f"{plat}_filtered_posts"] = len(posts)
        stats[f"{plat}_filtered_comments"] = len(comments)
        all_filtered_posts.extend(posts)
        all_filtered_comments.extend(comments)

        if posts:
            n = write_csv(out_dir / f"{film}__{plat}__filtered_posts.csv", posts, POST_FIELDS)
            print(f"  {film}/{plat} filtered posts: {n} -> {film}__{plat}__filtered_posts.csv")
        if comments:
            n = write_csv(out_dir / f"{film}__{plat}__filtered_comments.csv", comments, COMMENT_FIELDS)
            print(f"  {film}/{plat} filtered comments: {n} -> {film}__{plat}__filtered_comments.csv")

    if all_raw:
        write_csv(out_dir / f"{film}__ALL__raw.csv", all_raw, RAW_FIELDS)
    if all_filtered_posts:
        write_csv(out_dir / f"{film}__ALL__filtered_posts.csv", all_filtered_posts, POST_FIELDS)
    if all_filtered_comments:
        write_csv(out_dir / f"{film}__ALL__filtered_comments.csv", all_filtered_comments, COMMENT_FIELDS)

    stats["raw_total"] = len(all_raw)
    stats["filtered_posts_total"] = len(all_filtered_posts)
    stats["filtered_comments_total"] = len(all_filtered_comments)
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--film", action="append", required=True)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()
    films = [f.strip() for f in args.film if f.strip()]
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    out_dir = args.output_dir or (DEFAULT_OUT / f"raw_and_filtered_{stamp}")
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Export -> {out_dir}")
    summary: dict[str, dict] = {}
    for film in films:
        print(f"\n[{film}]")
        summary[film] = export_film(film, out_dir)

    summary_path = out_dir / "SUMMARY.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSummary -> {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
