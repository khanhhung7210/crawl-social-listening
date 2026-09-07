#!/usr/bin/env python3
"""Read crawl data for Distribution films, filter noise, normalize, export one combined CSV."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# Reuse platform loaders from raw/filter export
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from export_film_raw_and_filtered_csv import (  # noqa: E402
    DATA,
    PLATFORMS,
    export_generic_filtered,
    export_threads_filtered,
)

PROJECT_ROOT = SCRIPT_DIR.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from social_listening.film_rules import film_relevant_for_slug, normalize  # noqa: E402

DEFAULT_OUT = PROJECT_ROOT / "data" / "distribution" / "exports"
CATALOG_PATH = DATA / "distribution" / "film_catalog.json"

OUTPUT_FIELDS = [
    "film_slug",
    "film_title",
    "platform",
    "mention_kind",
    "url",
    "author_name",
    "created_at",
    "text_content",
    "keyword_matches",
    "like_count",
    "comment_count",
    "view_count",
]

# Facebook page bio / UI noise from crawl
NOISE_PATTERNS = [
    re.compile(r"^\s*pages you follow\s*$", re.I),
    re.compile(r"^\s*\d[\d,\.]*\s+likes\s*[·•]\s*[\d,\.]+\s+talking about this", re.I),
    re.compile(r"^\s*\d[\d,\.]*\s+followers?\s*$", re.I),
    re.compile(r"^\s*see more\s*$", re.I),
    re.compile(r"^\s*view replies\s*$", re.I),
]


def _project_root() -> Path:
    return PROJECT_ROOT


def load_film_titles() -> dict[str, str]:
    if not CATALOG_PATH.exists():
        return {}
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    films = data.get("films") or []
    return {str(f["slug"]): str(f.get("title") or f["slug"]) for f in films if f.get("slug")}


def clean_text(text: str) -> str:
    """Normalize whitespace, strip JSON artifacts, collapse noise."""
    if not text:
        return ""
    s = str(text).strip()
    # Facebook sometimes stores JSON fragments in post_text
    if s.startswith('{"') or s.startswith("{\""):
        m = re.search(r'"text"\s*:\s*"((?:[^"\\]|\\.)*)"', s)
        if m:
            s = m.group(1).encode("utf-8").decode("unicode_escape", errors="replace")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def is_noise(text: str, author: str = "") -> bool:
    blob = f"{text} {author}".strip()
    if not blob or len(blob) < 4:
        return True
    norm = normalize(blob)
    if len(norm) < 4:
        return True
    for pat in NOISE_PATTERNS:
        if pat.search(text) or pat.search(author):
            return True
    # Page bio: "Name. 123,456 likes · 789 talking about this."
    if re.search(r"\d[\d,\.]+\s+likes\s*[·•]", text) and len(text) < 200:
        if not any(k in norm for k in ("phim", "review", "trailer", "rap", "xem", "ve")):
            return True
    return False


def row_key(row: dict) -> str:
    parts = [
        row.get("film_slug", ""),
        row.get("platform", ""),
        row.get("mention_kind", ""),
        row.get("url", ""),
        normalize(row.get("text_content", ""))[:120],
    ]
    return hashlib.md5("|".join(parts).encode()).hexdigest()


def load_filtered_rows(film: str) -> list[dict]:
    posts: list[dict] = []
    comments: list[dict] = []
    for plat in PLATFORMS:
        if plat == "threads":
            p, c = export_threads_filtered(film)
        else:
            p, c = export_generic_filtered(film, plat)
        posts.extend(p)
        comments.extend(c)

    rows: list[dict] = []
    for item in posts + comments:
        text = clean_text(item.get("text_content", ""))
        author = clean_text(item.get("author_name", ""))
        if is_noise(text, author):
            continue
        if not film_relevant_for_slug(text, film, strict=False):
            continue

        kw = item.get("post_keyword_matches") or item.get("keyword_matches") or []
        if isinstance(kw, str):
            kw = [k.strip() for k in kw.split(";") if k.strip()]

        rows.append(
            {
                "film_slug": film,
                "platform": item.get("platform", ""),
                "mention_kind": item.get("mention_kind", ""),
                "url": (item.get("url") or "").strip(),
                "author_name": author,
                "created_at": (item.get("created_at") or "").strip(),
                "text_content": text,
                "keyword_matches": "; ".join(kw) if kw else "",
                "like_count": item.get("like_count") or "",
                "comment_count": item.get("comment_count") or "",
                "view_count": item.get("view_count") or "",
            }
        )
    return rows


def dedupe_rows(rows: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for row in rows:
        key = row_key(row)
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def export_combined(films: list[str], out_path: Path) -> dict[str, Any]:
    titles = load_film_titles()
    all_rows: list[dict] = []
    stats: dict[str, Any] = {}

    for film in films:
        raw_rows = load_filtered_rows(film)
        clean_rows = dedupe_rows(raw_rows)
        title = titles.get(film, film)
        for row in clean_rows:
            row["film_title"] = title
        stats[film] = {"before_dedupe": len(raw_rows), "after_dedupe": len(clean_rows)}
        all_rows.extend(clean_rows)
        print(f"  {film}: {len(raw_rows)} -> {len(clean_rows)} (after noise filter + dedupe)")

    all_rows.sort(key=lambda r: (r["film_slug"], r["platform"], r.get("created_at") or ""), reverse=True)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=OUTPUT_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(all_rows)

    stats["total_rows"] = len(all_rows)
    stats["output_file"] = str(out_path)
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--film", action="append", required=True)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    films = [f.strip() for f in args.film if f.strip()]
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    slug_part = "_".join(films)
    out_path = args.output or (DEFAULT_OUT / f"films_clean_{slug_part}_{stamp}.csv")

    print(f"Export clean combined -> {out_path}")
    stats = export_combined(films, out_path)

    summary_path = out_path.with_suffix(".summary.json")
    summary_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Total: {stats['total_rows']} rows")
    print(f"Summary -> {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
