#!/usr/bin/env python3
"""Seed MKT campaigns + keywords + owned source_profiles (idempotent).

Usage:
  PYTHONPATH=src python3 scripts/marketing/classify/seed_campaigns.py
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

# Display name, status, start, end, keywords as (term, is_hashtag)
CAMPAIGNS: list[tuple[str, str, str | None, str | None, list[tuple[str, bool]]]] = [
    (
        "Cine Chào Summer",
        "running",
        "2026-06-01",
        None,
        [
            ("#CineChaoSummer", True),
            ("#cinechaosummer", True),
            ("#CineChàoSummer", True),
            ("Cine Chào Summer", False),
            ("Cine Chao Summer", False),
            ("cine chào summer", False),
            ("cine chao summer", False),
            ("đắm mình trong sắc màu mùa hè", False),
            ("dam minh trong sac mau mua he", False),
            ("chào summer galaxy", False),
            ("chao summer galaxy", False),
            ("ưu đãi cine chào summer", False),
            ("chuong trinh cine chao summer", False),
            ("chương trình cine chào summer", False),
        ],
    ),
    (
        "Rewards Program",
        "running",
        "2026-01-01",
        None,
        [
            ("#GalaxyRewards", True),
            ("GalaxyRewards", False),
            ("galaxy rewards", False),
            ("thành viên galaxy", False),
            ("thanh vien galaxy", False),
            ("galaxy member", False),
            ("điểm thưởng galaxy", False),
            ("thẻ thành viên", False),
            ("the thanh vien", False),
            ("galaxy loyalty", False),
            ("tích điểm galaxy", False),
            ("tich diem galaxy", False),
        ],
    ),
    (
        "IMAX Launch",
        "ended",
        "2025-11-01",
        "2026-03-31",
        [
            ("#GalaxyIMAX", True),
            ("GalaxyIMAX", False),
            ("galaxy imax", False),
            ("imax galaxy", False),
            ("khai trương imax galaxy", False),
            ("imax", False),
            ("phòng imax", False),
            ("phong imax", False),
        ],
    ),
]

# Old seed names → rename to current campaign names (idempotent migrate)
CAMPAIGN_RENAMES: list[tuple[str, str]] = [
    ("Galaxy Summer Deals", "Cine Chào Summer"),
]

# (platform_code, source_key, source_name, media_type)
OWNED_SOURCES: list[tuple[str, str, str, str]] = [
    ("facebook", "galaxycinema", "Galaxy Cinema", "owned"),
    ("facebook", "galaxy cinema", "Galaxy Cinema", "owned"),
    ("facebook", "galaxy_cinema", "Galaxy Cinema", "owned"),
    ("facebook", "galaxycinemavn", "Galaxy Cinema VN", "owned"),
    ("facebook", "cgvcinemasvietnam", "CGV Cinemas Vietnam", "owned"),
    ("tiktok", "galaxycinema", "Galaxy Cinema", "owned"),
    ("tiktok", "galaxy.cinema", "Galaxy Cinema", "owned"),
    ("tiktok", "galaxy_cinema", "Galaxy Cinema", "owned"),
    ("threads", "galaxycinema", "Galaxy Cinema", "owned"),
    ("instagram", "galaxycinema", "Galaxy Cinema", "owned"),
    ("instagram", "galaxy_cinema", "Galaxy Cinema", "owned"),
    ("instagram", "galaxycinemavn", "Galaxy Cinema VN", "owned"),
    ("instagram", "cgvcinemasvietnam", "CGV Cinemas Vietnam", "owned"),
    ("youtube", "galaxycinema", "Galaxy Cinema", "owned"),
    ("news", "galaxycinema.vn", "Galaxy Cinema Official", "owned"),
]


def seed_campaigns(cur) -> int:
    cur.execute("SELECT brand_id::text FROM brands WHERE brand_slug = 'glx'")
    row = cur.fetchone()
    if not row:
        raise RuntimeError("Brand glx missing — apply galaxy_mkt_schema.sql first")
    brand_id = row[0]

    for old_name, new_name in CAMPAIGN_RENAMES:
        cur.execute(
            """
            UPDATE campaigns
            SET campaign_name = %s, updated_at = NOW()
            WHERE brand_id = %s::uuid
              AND campaign_name = %s
              AND NOT EXISTS (
                SELECT 1 FROM campaigns c2
                WHERE c2.brand_id = %s::uuid AND c2.campaign_name = %s
              )
            """,
            (new_name, brand_id, old_name, brand_id, new_name),
        )

    n = 0

    for name, status, start, end, keywords in CAMPAIGNS:
        cur.execute(
            """
            SELECT campaign_id::text FROM campaigns
            WHERE brand_id = %s::uuid AND campaign_name = %s
            LIMIT 1
            """,
            (brand_id, name),
        )
        existing = cur.fetchone()
        if existing:
            campaign_id = existing[0]
            cur.execute(
                """
                UPDATE campaigns SET
                    status = %s,
                    start_date = %s::date,
                    end_date = %s::date,
                    updated_at = NOW()
                WHERE campaign_id = %s::uuid
                """,
                (status, start, end, campaign_id),
            )
        else:
            cur.execute(
                """
                INSERT INTO campaigns (
                    brand_id, campaign_name, status, start_date, end_date, metadata
                ) VALUES (
                    %s::uuid, %s, %s, %s::date, %s::date, '{"seed": true}'::jsonb
                )
                RETURNING campaign_id::text
                """,
                (brand_id, name, status, start, end),
            )
            campaign_id = cur.fetchone()[0]

        for term, is_hashtag in keywords:
            cur.execute(
                """
                INSERT INTO campaign_keywords (campaign_id, keyword, is_hashtag)
                VALUES (%s::uuid, %s, %s)
                ON CONFLICT (campaign_id, keyword) DO UPDATE
                SET is_hashtag = EXCLUDED.is_hashtag
                """,
                (campaign_id, term, is_hashtag),
            )
        # Drop stale keywords no longer in seed list
        keep = [term for term, _ in keywords]
        cur.execute(
            """
            DELETE FROM campaign_keywords
            WHERE campaign_id = %s::uuid
              AND NOT (keyword = ANY(%s))
            """,
            (campaign_id, keep),
        )
        n += 1
    return n


def seed_source_profiles(cur) -> int:
    cur.execute("SELECT brand_id::text FROM brands WHERE brand_slug = 'glx'")
    brand_id = cur.fetchone()[0]
    n = 0
    for platform, key, name, media_type in OWNED_SOURCES:
        cur.execute(
            """
            INSERT INTO source_profiles (
                brand_id, platform_code, source_key, source_name, media_type, tier
            ) VALUES (
                %s::uuid, %s, %s, %s, %s, 'brand'
            )
            ON CONFLICT (platform_code, source_key) DO UPDATE SET
                source_name = EXCLUDED.source_name,
                media_type = EXCLUDED.media_type,
                brand_id = EXCLUDED.brand_id,
                is_active = TRUE,
                updated_at = NOW()
            """,
            (brand_id, platform, key, name, media_type),
        )
        n += 1
    return n


def main() -> int:
    with get_connection() as conn:
        cur = conn.cursor()
        camps = seed_campaigns(cur)
        sources = seed_source_profiles(cur)
        print(f"Seeded campaigns={camps} source_profiles={sources}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
