#!/usr/bin/env python3
"""Recompute galaxy_sl.daily_film_metrics from mentions + mention_films (+ post views)."""

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
        mf.film_id,
        m.platform_code,
        m.mention_kind,
        m.sentiment,
        m.author_key,
        m.post_id,
        m.intent
    FROM mentions m
    JOIN mention_films mf ON mf.mention_id = m.mention_id
    WHERE m.is_spam = FALSE
      AND m.occurred_at IS NOT NULL
),
post_views AS (
    SELECT DISTINCT
        b.metric_date,
        b.film_id,
        b.platform_code,
        b.post_id,
        COALESCE(p.view_count, 0) AS view_count
    FROM base b
    JOIN posts p ON p.post_id = b.post_id
    WHERE b.mention_kind = 'post'
      AND b.post_id IS NOT NULL
),
views_platform AS (
    SELECT metric_date, film_id, platform_code, SUM(view_count) AS view_count
    FROM post_views
    GROUP BY metric_date, film_id, platform_code
),
views_all AS (
    SELECT metric_date, film_id, 'all'::text AS platform_code, SUM(view_count) AS view_count
    FROM post_views
    GROUP BY metric_date, film_id
),
views AS (
    SELECT * FROM views_platform
    UNION ALL
    SELECT * FROM views_all
),
agg_platform AS (
    SELECT
        metric_date,
        film_id,
        platform_code,
        COUNT(*) AS buzz_count,
        COUNT(*) FILTER (WHERE mention_kind = 'post') AS post_count,
        COUNT(*) FILTER (WHERE mention_kind = 'comment') AS comment_count,
        COUNT(*) FILTER (WHERE sentiment = 'positive') AS positive_count,
        COUNT(*) FILTER (WHERE sentiment = 'negative') AS negative_count,
        COUNT(*) FILTER (WHERE sentiment = 'neutral') AS neutral_count,
        COUNT(DISTINCT author_key) AS unique_authors,
        COUNT(*) FILTER (WHERE intent = 'want_to_see') AS intent_want_count,
        COUNT(*) FILTER (WHERE intent IS NOT NULL) AS intent_total
    FROM base
    GROUP BY metric_date, film_id, platform_code
),
agg_all AS (
    SELECT
        metric_date,
        film_id,
        'all'::text AS platform_code,
        COUNT(*) AS buzz_count,
        COUNT(*) FILTER (WHERE mention_kind = 'post') AS post_count,
        COUNT(*) FILTER (WHERE mention_kind = 'comment') AS comment_count,
        COUNT(*) FILTER (WHERE sentiment = 'positive') AS positive_count,
        COUNT(*) FILTER (WHERE sentiment = 'negative') AS negative_count,
        COUNT(*) FILTER (WHERE sentiment = 'neutral') AS neutral_count,
        COUNT(DISTINCT author_key) AS unique_authors,
        COUNT(*) FILTER (WHERE intent = 'want_to_see') AS intent_want_count,
        COUNT(*) FILTER (WHERE intent IS NOT NULL) AS intent_total
    FROM base
    GROUP BY metric_date, film_id
),
combined AS (
    SELECT * FROM agg_platform
    UNION ALL
    SELECT * FROM agg_all
),
with_views AS (
    SELECT
        c.*,
        COALESCE(v.view_count, 0)::bigint AS view_count
    FROM combined c
    LEFT JOIN views v
      ON v.metric_date = c.metric_date
     AND v.film_id = c.film_id
     AND v.platform_code = c.platform_code
),
with_sov AS (
    SELECT
        w.*,
        CASE WHEN day_total.total > 0
            THEN ROUND(100.0 * w.buzz_count / day_total.total, 3)
            ELSE NULL END AS sov_pct
    FROM with_views w
    JOIN LATERAL (
        SELECT SUM(w2.buzz_count) AS total
        FROM with_views w2
        WHERE w2.metric_date = w.metric_date
          AND w2.platform_code = w.platform_code
    ) day_total ON TRUE
)
INSERT INTO daily_film_metrics (
    metric_date, film_id, platform_code,
    buzz_count, post_count, comment_count,
    positive_count, negative_count, neutral_count,
    unique_authors, view_count, sov_pct,
    intent_want_count, intent_total, updated_at
)
SELECT
    metric_date, film_id, platform_code,
    buzz_count, post_count, comment_count,
    positive_count, negative_count, neutral_count,
    unique_authors, view_count, sov_pct,
    intent_want_count, intent_total, NOW()
FROM with_sov
ON CONFLICT (metric_date, film_id, platform_code) DO UPDATE SET
    buzz_count = EXCLUDED.buzz_count,
    post_count = EXCLUDED.post_count,
    comment_count = EXCLUDED.comment_count,
    positive_count = EXCLUDED.positive_count,
    negative_count = EXCLUDED.negative_count,
    neutral_count = EXCLUDED.neutral_count,
    unique_authors = EXCLUDED.unique_authors,
    view_count = EXCLUDED.view_count,
    sov_pct = EXCLUDED.sov_pct,
    intent_want_count = EXCLUDED.intent_want_count,
    intent_total = EXCLUDED.intent_total,
    updated_at = NOW()
"""


def main() -> int:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = current_schema() AND table_name = 'daily_film_metrics'
            """
        )
        if not cur.fetchone():
            print("daily_film_metrics missing — apply sql/galaxy_dis_schema.sql first")
            return 1
        cur.execute(SQL)
        print("Recomputed daily_film_metrics.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
