#!/usr/bin/env python3
"""Recompute galaxy_sl.daily_brand_metrics from mentions + mention_brands."""

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


SQL = """
WITH base AS (
    SELECT
        (m.occurred_at AT TIME ZONE 'Asia/Ho_Chi_Minh')::date AS metric_date,
        mb.brand_id,
        m.platform_code,
        m.mention_kind,
        m.sentiment,
        m.media_type,
        m.author_key
    FROM mentions m
    JOIN mention_brands mb ON mb.mention_id = m.mention_id
    WHERE m.is_spam = FALSE
      AND m.occurred_at IS NOT NULL
),
agg_platform AS (
    SELECT
        metric_date,
        brand_id,
        platform_code,
        COUNT(*) AS buzz_count,
        COUNT(*) FILTER (WHERE mention_kind = 'post') AS post_count,
        COUNT(*) FILTER (WHERE mention_kind = 'comment') AS comment_count,
        COUNT(*) FILTER (WHERE sentiment = 'positive') AS positive_count,
        COUNT(*) FILTER (WHERE sentiment = 'negative') AS negative_count,
        COUNT(*) FILTER (WHERE sentiment = 'neutral') AS neutral_count,
        COUNT(*) FILTER (WHERE media_type = 'owned') AS owned_count,
        COUNT(*) FILTER (WHERE media_type = 'paid') AS paid_count,
        COUNT(*) FILTER (WHERE media_type = 'earned') AS earned_count,
        COUNT(DISTINCT author_key) AS unique_authors
    FROM base
    GROUP BY metric_date, brand_id, platform_code
),
agg_all AS (
    SELECT
        metric_date,
        brand_id,
        'all'::text AS platform_code,
        COUNT(*) AS buzz_count,
        COUNT(*) FILTER (WHERE mention_kind = 'post') AS post_count,
        COUNT(*) FILTER (WHERE mention_kind = 'comment') AS comment_count,
        COUNT(*) FILTER (WHERE sentiment = 'positive') AS positive_count,
        COUNT(*) FILTER (WHERE sentiment = 'negative') AS negative_count,
        COUNT(*) FILTER (WHERE sentiment = 'neutral') AS neutral_count,
        COUNT(*) FILTER (WHERE media_type = 'owned') AS owned_count,
        COUNT(*) FILTER (WHERE media_type = 'paid') AS paid_count,
        COUNT(*) FILTER (WHERE media_type = 'earned') AS earned_count,
        COUNT(DISTINCT author_key) AS unique_authors
    FROM base
    GROUP BY metric_date, brand_id
),
combined AS (
    SELECT * FROM agg_platform
    UNION ALL
    SELECT * FROM agg_all
),
with_sov AS (
    SELECT
        c.*,
        CASE WHEN day_total.total > 0
            THEN ROUND(100.0 * c.buzz_count / day_total.total, 3)
            ELSE NULL END AS sov_pct
    FROM combined c
    JOIN LATERAL (
        SELECT SUM(c2.buzz_count) AS total
        FROM combined c2
        WHERE c2.metric_date = c.metric_date
          AND c2.platform_code = c.platform_code
    ) day_total ON TRUE
)
INSERT INTO daily_brand_metrics (
    metric_date, brand_id, platform_code,
    buzz_count, post_count, comment_count, source_count,
    positive_count, negative_count, neutral_count,
    owned_count, paid_count, earned_count, sov_pct, unique_authors, updated_at
)
SELECT
    metric_date, brand_id, platform_code,
    buzz_count, post_count, comment_count, 0,
    positive_count, negative_count, neutral_count,
    owned_count, paid_count, earned_count, sov_pct, unique_authors, NOW()
FROM with_sov
ON CONFLICT (metric_date, brand_id, platform_code) DO UPDATE SET
    buzz_count = EXCLUDED.buzz_count,
    post_count = EXCLUDED.post_count,
    comment_count = EXCLUDED.comment_count,
    positive_count = EXCLUDED.positive_count,
    negative_count = EXCLUDED.negative_count,
    neutral_count = EXCLUDED.neutral_count,
    owned_count = EXCLUDED.owned_count,
    paid_count = EXCLUDED.paid_count,
    earned_count = EXCLUDED.earned_count,
    sov_pct = EXCLUDED.sov_pct,
    unique_authors = EXCLUDED.unique_authors,
    updated_at = NOW();
"""


def main() -> int:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(SQL)
        print(f"Recomputed daily_brand_metrics (rows upserted via ON CONFLICT).")
        cur.execute("SELECT COUNT(*) FROM daily_brand_metrics")
        print(f"Total daily_brand_metrics rows: {cur.fetchone()[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
