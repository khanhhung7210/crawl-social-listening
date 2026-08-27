#!/usr/bin/env python3
"""Gán region Distribution cho mentions → metadata.dis_region (phục vụ heatmap Buzz/Intent).

Dùng chung rule với crawl + dashboard (social_listening.dis_regions).

Ví dụ:
  PYTHONPATH=src python3 scripts/distribution/classify/classify_mention_region.py
  PYTHONPATH=src python3 scripts/distribution/classify/classify_mention_region.py --film-slug the_odyssey
"""

from __future__ import annotations

import argparse
import json
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

from social_listening.dis_regions import DIS_REGIONS, classify_region  # noqa: E402
from social_listening.pg import get_connection  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--film-slug", default="", help="Chỉ mentions gắn film slug này")
    parser.add_argument(
        "--only-missing",
        action="store_true",
        help="Chỉ cập nhật mention chưa có metadata.dis_region",
    )
    args = parser.parse_args()

    sql = """
        SELECT m.mention_id::text,
               m.content_text,
               COALESCE(p.author_name, m.author_key, '') AS author,
               COALESCE(m.metadata, '{}'::jsonb) AS metadata
        FROM mentions m
        JOIN mention_films mf ON mf.mention_id = m.mention_id
        JOIN films f ON f.film_id = mf.film_id
        LEFT JOIN posts p ON p.post_id = m.post_id
        WHERE m.is_spam = FALSE
    """
    params: list = []
    if args.film_slug:
        sql += " AND f.film_slug = %s"
        params.append(args.film_slug)
    if args.only_missing:
        sql += " AND COALESCE(m.metadata->>'dis_region', '') = ''"

    updated = 0
    counts = {r: 0 for r in DIS_REGIONS}
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall()
        for mention_id, text, author, metadata in rows:
            region = classify_region(str(text or ""), str(author or ""))
            counts[region] = counts.get(region, 0) + 1
            meta = metadata if isinstance(metadata, dict) else json.loads(metadata or "{}")
            if meta.get("dis_region") == region:
                continue
            meta["dis_region"] = region
            cur.execute(
                """
                UPDATE mentions
                SET metadata = %s::jsonb, updated_at = NOW()
                WHERE mention_id = %s::uuid
                """,
                (json.dumps(meta, ensure_ascii=False), mention_id),
            )
            updated += 1
        print(f"Classified region on {updated}/{len(rows)} mentions")
        print("Distribution:", counts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
