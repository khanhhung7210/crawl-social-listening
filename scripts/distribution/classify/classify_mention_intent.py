#!/usr/bin/env python3
"""Keyword-based intent labels for Distribution WOM (v1.1).

Uses social_listening.film_classify — positive intent + negation window,
watched + sentiment → praise/criticize.

Default: ALL mention kinds (post + comment) across ALL platforms linked to films.
"""

from __future__ import annotations

import argparse
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

from social_listening.film_classify import classify_intent  # noqa: E402
from social_listening.pg import get_connection  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--film-slug", default="", help="Only mentions linked to this film slug")
    parser.add_argument(
        "--platform",
        default="",
        help="Only this platform_code (default: all platforms)",
    )
    parser.add_argument(
        "--comments-only",
        action="store_true",
        help="Legacy: only mention_kind=comment (default is post+comment)",
    )
    parser.add_argument(
        "--reclassify",
        action="store_true",
        help="Overwrite existing intent labels (default: only fill NULL)",
    )
    args = parser.parse_args()

    sql = """
        SELECT m.mention_id::text, m.content_text, m.intent,
               m.platform_code, m.mention_kind
        FROM mentions m
        JOIN mention_films mf ON mf.mention_id = m.mention_id
        JOIN films f ON f.film_id = mf.film_id
        WHERE m.is_spam = FALSE
          AND m.platform_code <> 'news'
    """
    params: list = []
    if args.comments_only:
        sql += " AND m.mention_kind = 'comment'"
    if args.film_slug:
        sql += " AND f.film_slug = %s"
        params.append(args.film_slug)
    if args.platform:
        sql += " AND m.platform_code = %s"
        params.append(args.platform.strip().lower())

    updated = 0
    cleared = 0
    by_platform: dict[str, int] = {}
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall()
        for mention_id, text, existing, platform, _kind in rows:
            intent = classify_intent(str(text or ""))
            if not args.reclassify and existing:
                continue
            if intent == existing:
                continue
            if not intent:
                if args.reclassify and existing:
                    cur.execute(
                        "UPDATE mentions SET intent = NULL, updated_at = NOW() WHERE mention_id = %s::uuid",
                        (mention_id,),
                    )
                    cleared += 1
                continue
            cur.execute(
                "UPDATE mentions SET intent = %s, updated_at = NOW() WHERE mention_id = %s::uuid",
                (intent, mention_id),
            )
            updated += 1
            key = str(platform or "?")
            by_platform[key] = by_platform.get(key, 0) + 1
        print(f"Classified intent on {updated}/{len(rows)} mentions (cleared={cleared})")
        if by_platform:
            print("by_platform:", dict(sorted(by_platform.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
