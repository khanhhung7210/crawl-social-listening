#!/usr/bin/env python3
"""Delete mentions that are not Vietnam-market relevant; rebuild metrics.

Usage:
  PYTHONPATH=src .venv/bin/python scripts/shared/purge_non_vietnam_mentions.py
  PYTHONPATH=src .venv/bin/python scripts/shared/purge_non_vietnam_mentions.py --dry-run
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

from social_listening.pg import get_connection  # noqa: E402
from social_listening.vietnam_filter import is_vietnam_relevant  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT m.mention_id::text, m.platform_code, m.content_text, m.permalink, m.author_key
            FROM mentions m
            WHERE m.is_spam = FALSE
            """
        )
        rows = cur.fetchall()
        drop_ids: list[str] = []
        for mention_id, platform, text, permalink, author in rows:
            if not is_vietnam_relevant(text, permalink=permalink, author=author, platform=platform):
                drop_ids.append(mention_id)

        print(f"mentions={len(rows)} non_vietnam={len(drop_ids)} dry_run={args.dry_run}")
        if args.dry_run:
            # show a few
            shown = 0
            for mention_id, platform, text, permalink, author in rows:
                if is_vietnam_relevant(text, permalink=permalink, author=author, platform=platform):
                    continue
                print(f"  DROP [{platform}] {(text or '')[:120]!r}")
                shown += 1
                if shown >= 15:
                    break
            return 0

        if drop_ids:
            # chunk deletes
            for i in range(0, len(drop_ids), 500):
                chunk = drop_ids[i : i + 500]
                cur.execute(
                    "DELETE FROM mentions WHERE mention_id::text = ANY(%s)",
                    (chunk,),
                )

        cur.execute(
            """
            DELETE FROM comments c
            WHERE NOT EXISTS (SELECT 1 FROM mentions m WHERE m.comment_id = c.comment_id)
            """
        )
        orphan_c = cur.rowcount
        cur.execute(
            """
            DELETE FROM posts p
            WHERE NOT EXISTS (SELECT 1 FROM mentions m WHERE m.post_id = p.post_id)
              AND NOT EXISTS (SELECT 1 FROM comments c WHERE c.post_id = p.post_id)
            """
        )
        orphan_p = cur.rowcount
        cur.execute("SELECT count(*) FROM mentions")
        print(f"kept_mentions={cur.fetchone()[0]} orphan_comments={orphan_c} orphan_posts={orphan_p}")

    try:
        import importlib.util

        for name, extra in (
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
                sys.argv = [str(path), *extra]
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
