#!/usr/bin/env python3
"""Resolve mentions/posts media_type from source_profiles (+ light owned heuristics).

Usage:
  PYTHONPATH=src python3 scripts/marketing/classify/resolve_mention_media_types.py
"""

from __future__ import annotations

import re
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

OWNED_NAME_HINTS = (
    "galaxy cinema",
    "galaxycinema",
    "rạp galaxy official",
    "rap galaxy official",
    "galaxy cineplex",
)


def normalize_key(value: str) -> str:
    return re.sub(r"[\s._-]+", "", (value or "").lower())


def resolve(cur) -> tuple[int, int]:
    cur.execute(
        """
        SELECT platform_code, source_key, source_profile_id::text, media_type
        FROM source_profiles
        WHERE is_active = TRUE
        """
    )
    profiles = cur.fetchall()
    # platform -> list of (norm_key, profile_id, media_type)
    by_platform: dict[str, list[tuple[str, str, str]]] = {}
    for platform, key, profile_id, media_type in profiles:
        by_platform.setdefault(platform, []).append(
            (normalize_key(str(key)), str(profile_id), str(media_type))
        )

    cur.execute(
        """
        SELECT mention_id::text, platform_code,
               COALESCE(author_key, ''), COALESCE(
                   (SELECT p.author_name FROM posts p WHERE p.post_id = mentions.post_id),
                   ''
               )
        FROM mentions
        WHERE is_spam = FALSE
        """
    )
    mentions = cur.fetchall()
    updated = 0
    owned_heuristic = 0

    for mention_id, platform, author_key, author_name in mentions:
        media_type = "earned"
        profile_id = None
        key_norm = normalize_key(author_key)
        name_norm = normalize_key(author_name)
        blob = f"{author_key} {author_name}".lower()

        for cand_key, cand_id, cand_type in by_platform.get(platform, []):
            if not cand_key:
                continue
            if cand_key in key_norm or cand_key in name_norm or key_norm in cand_key:
                media_type = cand_type
                profile_id = cand_id
                break

        if media_type == "earned" and any(h.replace(" ", "") in normalize_key(blob) for h in OWNED_NAME_HINTS):
            media_type = "owned"
            owned_heuristic += 1

        cur.execute(
            """
            UPDATE mentions SET
                media_type = %s,
                source_profile_id = COALESCE(%s::uuid, source_profile_id),
                updated_at = NOW()
            WHERE mention_id = %s::uuid
              AND (
                    media_type IS DISTINCT FROM %s
                 OR ( %s::uuid IS NOT NULL AND source_profile_id IS DISTINCT FROM %s::uuid )
              )
            """,
            (media_type, profile_id, mention_id, media_type, profile_id, profile_id),
        )
        if cur.rowcount:
            updated += 1

    # Mirror onto posts when author matches
    cur.execute(
        """
        UPDATE posts p SET
            media_type = m.media_type,
            source_profile_id = m.source_profile_id,
            updated_at = NOW()
        FROM mentions m
        WHERE m.post_id = p.post_id
          AND m.mention_kind = 'post'
          AND (
                p.media_type IS DISTINCT FROM m.media_type
             OR p.source_profile_id IS DISTINCT FROM m.source_profile_id
          )
        """
    )
    return updated, owned_heuristic


def main() -> int:
    with get_connection() as conn:
        cur = conn.cursor()
        updated, heuristic = resolve(cur)
        print(f"mentions_updated={updated} owned_heuristic={heuristic}")

        # Refresh brand aggregates so owned/paid/earned columns fill
        try:
            import importlib.util

            spec = importlib.util.spec_from_file_location(
                "recompute_daily_brand_metrics",
                Path(__file__).resolve().parents[1] / "metrics" / "recompute_daily_brand_metrics.py",
            )
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                mod.main()
        except Exception as exc:
            print(f"Warning: could not recompute daily_brand_metrics: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
