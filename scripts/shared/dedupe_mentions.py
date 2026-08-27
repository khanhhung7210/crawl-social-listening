#!/usr/bin/env python3
"""Remove duplicate mentions/comments then add unique indexes + recompute metrics.

Usage:
  PYTHONPATH=src .venv/bin/python scripts/shared/dedupe_mentions.py
"""

from __future__ import annotations

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


def main() -> int:
    with get_connection() as conn:
        cur = conn.cursor()

        cur.execute("SELECT count(*) FROM mentions")
        before_mentions = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM comments")
        before_comments = cur.fetchone()[0]

        # 1) Duplicate post-mentions → keep earliest
        cur.execute(
            """
            WITH ranked AS (
                SELECT mention_id,
                       ROW_NUMBER() OVER (
                           PARTITION BY post_id
                           ORDER BY created_at ASC, mention_id ASC
                       ) AS rn
                FROM mentions
                WHERE mention_kind = 'post' AND post_id IS NOT NULL
            )
            DELETE FROM mentions
            WHERE mention_id IN (SELECT mention_id FROM ranked WHERE rn > 1)
            """
        )
        deleted_post_mentions = cur.rowcount

        # 2) Duplicate comments (same post + external id) → keep earliest
        #    Mentions for deleted comments cascade via FK ON DELETE CASCADE
        cur.execute(
            """
            WITH ranked AS (
                SELECT comment_id,
                       ROW_NUMBER() OVER (
                           PARTITION BY post_id, COALESCE(NULLIF(external_comment_id, ''), comment_id::text)
                           ORDER BY created_at ASC, comment_id ASC
                       ) AS rn
                FROM comments
            )
            DELETE FROM comments
            WHERE comment_id IN (SELECT comment_id FROM ranked WHERE rn > 1)
            """
        )
        deleted_comments = cur.rowcount

        # 3) Any leftover duplicate comment-mentions
        cur.execute(
            """
            WITH ranked AS (
                SELECT mention_id,
                       ROW_NUMBER() OVER (
                           PARTITION BY comment_id
                           ORDER BY created_at ASC, mention_id ASC
                       ) AS rn
                FROM mentions
                WHERE mention_kind = 'comment' AND comment_id IS NOT NULL
            )
            DELETE FROM mentions
            WHERE mention_id IN (SELECT mention_id FROM ranked WHERE rn > 1)
            """
        )
        deleted_comment_mentions = cur.rowcount

        # Unique indexes (idempotent)
        cur.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_comments_post_external
                ON comments (post_id, external_comment_id)
                WHERE external_comment_id IS NOT NULL AND external_comment_id <> ''
            """
        )
        cur.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_mentions_post_kind
                ON mentions (post_id)
                WHERE mention_kind = 'post' AND post_id IS NOT NULL
            """
        )
        cur.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_mentions_comment_kind
                ON mentions (comment_id)
                WHERE mention_kind = 'comment' AND comment_id IS NOT NULL
            """
        )

        cur.execute("SELECT count(*) FROM mentions")
        after_mentions = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM comments")
        after_comments = cur.fetchone()[0]

        print(
            f"dedupe: post_mentions_deleted={deleted_post_mentions} "
            f"comments_deleted={deleted_comments} "
            f"comment_mentions_deleted={deleted_comment_mentions}"
        )
        print(f"mentions {before_mentions} → {after_mentions}")
        print(f"comments {before_comments} → {after_comments}")

    # Recompute metrics after cleanup
    try:
        import importlib.util

        for name in ("recompute_daily_brand_metrics", "build_campaign_tracking"):
            path = Path(__file__).with_name(f"{name}.py")
            spec = importlib.util.spec_from_file_location(name, path)
            if not spec or not spec.loader:
                continue
            mod = importlib.util.module_from_spec(spec)
            old_argv = sys.argv[:]
            try:
                if name == "build_campaign_tracking":
                    sys.argv = [str(path), "--brand", "glx"]
                spec.loader.exec_module(mod)
                if hasattr(mod, "main"):
                    mod.main()
            finally:
                sys.argv = old_argv
    except Exception as exc:
        print(f"Warning: metrics rebuild failed: {exc}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
