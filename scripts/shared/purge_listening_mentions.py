#!/usr/bin/env python3
"""Purge non-competitive (listening-skewed) mentions; keep brand-parity keywords only.

Keeps a mention only if it is linked to a brand AND its content matches that
brand's competitive keyword set (same rules as dashboard Competitive SoV).

Usage:
  PYTHONPATH=src .venv/bin/python scripts/shared/purge_listening_mentions.py
  PYTHONPATH=src .venv/bin/python scripts/shared/purge_listening_mentions.py --dry-run
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

from social_listening.brand_rules import COMPETITIVE_KEYWORD_SQL  # noqa: E402
from social_listening.pg import get_connection  # noqa: E402

# Mirror brand_rules / dashboard competitive SoV filter
COMPETITIVE_KEEP_SQL = f"""
EXISTS (
  SELECT 1
  FROM mention_brands mb
  JOIN brands b ON b.brand_id = mb.brand_id
  WHERE mb.mention_id = m.mention_id
    AND ({COMPETITIVE_KEYWORD_SQL})
)
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    with get_connection() as conn:
        cur = conn.cursor()

        cur.execute("SELECT count(*) FROM mentions")
        before = cur.fetchone()[0]
        cur.execute(
            f"""
            SELECT count(*) FROM mentions m
            WHERE NOT ({COMPETITIVE_KEEP_SQL})
            """
        )
        to_delete = cur.fetchone()[0]
        print(f"mentions total={before} listening_to_purge={to_delete} dry_run={args.dry_run}")

        if args.dry_run:
            cur.execute(
                f"""
                SELECT m.platform_code, count(*)
                FROM mentions m
                WHERE NOT ({COMPETITIVE_KEEP_SQL})
                GROUP BY 1 ORDER BY 2 DESC
                """
            )
            for row in cur.fetchall():
                print(" ", row)
            return 0

        cur.execute(
            f"""
            DELETE FROM mentions m
            WHERE NOT ({COMPETITIVE_KEEP_SQL})
            """
        )
        deleted = cur.rowcount

        # Orphan comments (no mention) — optional cleanup
        cur.execute(
            """
            DELETE FROM comments c
            WHERE NOT EXISTS (
              SELECT 1 FROM mentions m WHERE m.comment_id = c.comment_id
            )
            """
        )
        orphan_comments = cur.rowcount

        # Orphan posts with no mentions and no comments
        cur.execute(
            """
            DELETE FROM posts p
            WHERE NOT EXISTS (SELECT 1 FROM mentions m WHERE m.post_id = p.post_id)
              AND NOT EXISTS (SELECT 1 FROM comments c WHERE c.post_id = p.post_id)
            """
        )
        orphan_posts = cur.rowcount

        cur.execute("SELECT count(*) FROM mentions")
        after = cur.fetchone()[0]
        print(
            f"purged mentions={deleted} orphan_comments={orphan_comments} "
            f"orphan_posts={orphan_posts} mentions_now={after}"
        )

    # Rebuild metrics
    try:
        import importlib.util

        for name, argv_extra in (
            ("recompute_daily_brand_metrics", []),
            ("build_campaign_tracking", ["--brand", "glx"]),
        ):
            path = Path(__file__).with_name(f"{name}.py")
            spec = importlib.util.spec_from_file_location(name, path)
            if not spec or not spec.loader:
                continue
            mod = importlib.util.module_from_spec(spec)
            old = sys.argv[:]
            try:
                sys.argv = [str(path), *argv_extra]
                spec.loader.exec_module(mod)
                if hasattr(mod, "main"):
                    mod.main()
            finally:
                sys.argv = old
    except Exception as exc:
        print(f"Warning: metrics rebuild failed: {exc}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
