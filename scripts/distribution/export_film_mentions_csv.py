#!/usr/bin/env python3
"""Export film mentions from Postgres to CSV (Distribution films)."""

from __future__ import annotations

import argparse
import csv
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

from social_listening.pg import get_connection  # noqa: E402

QUERY = """
SELECT
    f.film_slug::text AS film_slug,
    f.film_title,
    m.platform_code,
    m.mention_kind,
    m.occurred_at,
    m.sentiment,
    COALESCE(p.external_post_id, c.external_comment_id) AS external_id,
    COALESCE(p.post_url, m.permalink) AS url,
    COALESCE(p.author_name, c.author_name) AS author_name,
    COALESCE(p.post_text, c.comment_text, m.content_text) AS text_content,
    COALESCE(p.like_count, c.like_count) AS like_count,
    COALESCE(p.comment_count, 0) AS reply_count,
    COALESCE(p.share_count, 0) AS share_count,
    COALESCE(p.view_count, 0) AS view_count,
    m.mention_id::text
FROM films f
JOIN mention_films mf ON mf.film_id = f.film_id
JOIN mentions m ON m.mention_id = mf.mention_id AND COALESCE(m.is_spam, FALSE) = FALSE
LEFT JOIN posts p ON m.post_id = p.post_id
LEFT JOIN comments c ON m.comment_id = c.comment_id
WHERE f.film_slug = ANY(%s)
ORDER BY f.film_slug, m.platform_code, m.occurred_at DESC NULLS LAST
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--film", action="append", required=True, help="Film slug (repeatable)")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "distribution" / "exports",
        help="Output directory",
    )
    args = parser.parse_args()
    films = [str(x).strip() for x in args.film if str(x).strip()]
    if not films:
        raise SystemExit("Need at least one --film")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    combined = args.output_dir / f"films_{'_'.join(films)}_{stamp}.csv"

    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(QUERY, (films,))
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()

    with combined.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        w.writerows(rows)

    by_film: dict[str, list] = {}
    for row in rows:
        by_film.setdefault(row[0], []).append(row)

    for slug, film_rows in by_film.items():
        fp = args.output_dir / f"{slug}_{stamp}.csv"
        with fp.open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(cols)
            w.writerows(film_rows)
        print(f"  {slug}: {len(film_rows)} rows -> {fp}")

    print(f"Combined: {len(rows)} rows -> {combined}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
