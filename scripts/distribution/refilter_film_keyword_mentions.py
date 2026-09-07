#!/usr/bin/env python3
"""Re-apply Distribution film_rules on existing *_keyword_mentions.json (no re-crawl).

Examples:
  PYTHONPATH=src python3 scripts/distribution/refilter_film_keyword_mentions.py \\
    --film nghi_he_so_nghi_huu quy_tu_vuot_giau

  PYTHONPATH=src python3 scripts/distribution/refilter_film_keyword_mentions.py --all-active
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _project_root() -> Path:
    current = Path(__file__).resolve().parent
    for cand in [current, *current.parents]:
        if (cand / "src" / "social_listening").is_dir():
            return cand
    raise RuntimeError(f"Cannot find project root from {__file__}")


PROJECT_ROOT = _project_root()
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from social_listening.film_crawl_filter import (  # noqa: E402
    filter_distribution_comments,
    is_distribution_crawl,
    passes_film_relevance,
)
from social_listening.paths import DATA_DIR  # noqa: E402

PLATFORMS = ("facebook", "instagram", "threads", "tiktok", "youtube", "news")


def load_catalog_slugs(all_active: bool) -> list[str]:
    catalog = json.loads((DATA_DIR / "distribution" / "film_catalog.json").read_text(encoding="utf-8"))
    films = catalog.get("films") or []
    if all_active:
        return [str(f["slug"]) for f in films if f.get("active")]
    return [str(f["slug"]) for f in films if f.get("slug")]


def _record_text(item: dict) -> str:
    parts = [
        str(item.get("title") or ""),
        str(item.get("post_text") or ""),
        str(item.get("text") or ""),
    ]
    return "\n".join(p for p in parts if p.strip())


def refilter_record(item: dict) -> dict | None:
    if not isinstance(item, dict):
        return None
    text = _record_text(item)
    matches = item.get("post_keyword_matches") or item.get("matched_search_keywords") or []
    match_list = matches if isinstance(matches, list) else []
    comments = item.get("comments") if isinstance(item.get("comments"), list) else []
    filtered_comments = filter_distribution_comments(comments)

    post_ok = passes_film_relevance(text, match_list)
    if not post_ok and not filtered_comments:
        return None

    out = dict(item)
    out["comments"] = filtered_comments
    out["parent_keyword_match"] = post_ok or bool(filtered_comments)
    out["post_keyword_match"] = post_ok
    if post_ok:
        out["post_keyword_matches"] = match_list
    else:
        out["post_keyword_matches"] = []
    out["source"] = str(out.get("source") or "refilter_film_keyword_mentions")
    return out


def refilter_file(path: Path, film_slug: str) -> tuple[int, int]:
    os.environ["SOCIAL_LISTENING_PROFILE"] = "dis"
    os.environ["SOCIAL_FILM_SLUG"] = film_slug
    if not path.exists():
        return 0, 0
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        return 0, 0
    before = len(raw)
    kept: list[dict] = []
    for item in raw:
        row = refilter_record(item)
        if row:
            kept.append(row)
    path.write_text(json.dumps(kept, ensure_ascii=False, indent=2), encoding="utf-8")
    return before, len(kept)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--film", action="append", default=[], help="Film slug (repeatable)")
    parser.add_argument("--all-active", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    slugs = args.film or (load_catalog_slugs(True) if args.all_active else [])
    if not slugs:
        raise SystemExit("Specify --film <slug> or --all-active")

    os.environ.setdefault("SOCIAL_CONFIG_SOURCE", "db")
    total_before = total_after = 0

    for slug in slugs:
        print(f"\n=== {slug} ===")
        for platform in PLATFORMS:
            path = DATA_DIR / platform / "processed" / slug / f"{platform}_keyword_mentions.json"
            if not path.exists():
                continue
            if args.dry_run:
                os.environ["SOCIAL_LISTENING_PROFILE"] = "dis"
                os.environ["SOCIAL_FILM_SLUG"] = slug
                raw = json.loads(path.read_text(encoding="utf-8"))
                before = len(raw) if isinstance(raw, list) else 0
                after = sum(1 for item in raw if refilter_record(item))
                print(f"  {platform}: {before} -> {after} (dry-run)")
                total_before += before
                total_after += after
                continue
            before, after = refilter_file(path, slug)
            if before:
                print(f"  {platform}: {before} -> {after}")
                total_before += before
                total_after += after

    print(f"\nTotal: {total_before} -> {total_after} ({total_before - total_after} removed)")
    if not is_distribution_crawl():
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
