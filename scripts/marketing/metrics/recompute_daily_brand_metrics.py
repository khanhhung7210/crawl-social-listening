#!/usr/bin/env python3
"""Recompute galaxy_sl.daily_brand_metrics from mentions + mention_brands.

Population source of truth:
  mentions (is_spam=FALSE, occurred_at NOT NULL) JOIN mention_brands

Strategy (lowest risk vs TRUNCATE):
  1) Build fresh aggregation for the recompute scope into a TEMP table.
  2) DELETE orphan daily_brand_metrics rows inside that scope whose
     PRIMARY KEY (metric_date, brand_id, platform_code) is absent from fresh.
  3) UPSERT fresh rows.

Default scope = all dates present in live aggregation (full recompute).
Optional --from / --to limit both prune and upsert to metric_date range so
rows outside the window are never deleted.

Does not modify mentions or mention_brands.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Optional


def _project_root() -> Path:
    current = Path(__file__).resolve().parent
    for cand in [current, *current.parents]:
        if (cand / "src" / "social_listening").is_dir():
            return cand
    raise RuntimeError(f"Cannot find project root from {__file__}")


PROJECT_ROOT = _project_root()
sys.path.insert(0, str(PROJECT_ROOT / "src"))


# --- Pure helpers (unit-tested; mirror SQL prune+upsert semantics) ---

MetricKey = tuple[date, str, str]  # metric_date, brand_id, platform_code


def parse_iso_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def keys_in_scope(
    keys: Iterable[MetricKey],
    from_date: Optional[date],
    to_date: Optional[date],
) -> set[MetricKey]:
    """Return keys whose metric_date falls in [from_date, to_date] (inclusive).

    None bounds mean unbounded on that side. Both None => all keys.
    """
    out: set[MetricKey] = set()
    for key in keys:
        d = key[0]
        if from_date is not None and d < from_date:
            continue
        if to_date is not None and d > to_date:
            continue
        out.add(key)
    return out


def orphan_keys_to_delete(
    existing: Iterable[MetricKey],
    fresh: Iterable[MetricKey],
    *,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
) -> set[MetricKey]:
    """Keys present in existing, inside recompute scope, but missing from fresh."""
    fresh_set = set(fresh)
    scoped_existing = keys_in_scope(existing, from_date, to_date)
    return scoped_existing - fresh_set


def apply_prune_and_upsert(
    existing: dict[MetricKey, dict],
    fresh: dict[MetricKey, dict],
    *,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
) -> dict[MetricKey, dict]:
    """Return metrics map after scoped prune + upsert (idempotent if fresh stable)."""
    to_delete = orphan_keys_to_delete(
        existing.keys(),
        fresh.keys(),
        from_date=from_date,
        to_date=to_date,
    )
    out = {k: dict(v) for k, v in existing.items() if k not in to_delete}
    for k, v in fresh.items():
        d = k[0]
        if from_date is not None and d < from_date:
            continue
        if to_date is not None and d > to_date:
            continue
        out[k] = dict(v)
    return out


def build_fresh_select_sql(
    *,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
) -> tuple[str, list]:
    """Return SQL + params for the fresh aggregation SELECT (no side effects)."""
    params: list = []
    date_filter = ""
    if from_date is not None:
        params.append(from_date)
        date_filter += (
            " AND (m.occurred_at AT TIME ZONE 'Asia/Ho_Chi_Minh')::date "
            ">= %s::date"
        )
    if to_date is not None:
        params.append(to_date)
        date_filter += (
            " AND (m.occurred_at AT TIME ZONE 'Asia/Ho_Chi_Minh')::date "
            "<= %s::date"
        )

    sql = f"""
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
      {date_filter}
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
)
SELECT
    c.metric_date,
    c.brand_id,
    c.platform_code,
    c.buzz_count,
    c.post_count,
    c.comment_count,
    c.positive_count,
    c.negative_count,
    c.neutral_count,
    c.owned_count,
    c.paid_count,
    c.earned_count,
    CASE WHEN day_total.total > 0
        THEN ROUND(100.0 * c.buzz_count / day_total.total, 3)
        ELSE NULL END AS sov_pct,
    c.unique_authors
FROM combined c
JOIN LATERAL (
    SELECT SUM(c2.buzz_count) AS total
    FROM combined c2
    WHERE c2.metric_date = c.metric_date
      AND c2.platform_code = c.platform_code
) day_total ON TRUE
"""
    return sql, params


def build_prune_sql(
    *,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
) -> tuple[str, list]:
    """DELETE orphan rows in scope not present in TEMP _fresh_daily_brand_metrics."""
    params: list = []
    scope = ""
    if from_date is not None:
        params.append(from_date)
        scope += " AND d.metric_date >= %s::date"
    if to_date is not None:
        params.append(to_date)
        scope += " AND d.metric_date <= %s::date"

    sql = f"""
DELETE FROM daily_brand_metrics d
WHERE TRUE
  {scope}
  AND NOT EXISTS (
    SELECT 1
    FROM _fresh_daily_brand_metrics f
    WHERE f.metric_date = d.metric_date
      AND f.brand_id = d.brand_id
      AND f.platform_code = d.platform_code
  )
"""
    return sql, params


UPSERT_SQL = """
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
FROM _fresh_daily_brand_metrics
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
    updated_at = NOW()
"""


def recompute_daily_brand_metrics(
    cur,
    *,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
) -> dict[str, int]:
    """Prune orphans in scope, then upsert fresh rows. Returns counts."""
    if from_date is not None and to_date is not None and from_date > to_date:
        raise ValueError(f"from_date {from_date} > to_date {to_date}")

    fresh_sql, fresh_params = build_fresh_select_sql(
        from_date=from_date, to_date=to_date
    )
    cur.execute("DROP TABLE IF EXISTS _fresh_daily_brand_metrics")
    cur.execute(
        f"""
        CREATE TEMP TABLE _fresh_daily_brand_metrics ON COMMIT DROP AS
        {fresh_sql}
        """,
        fresh_params,
    )
    cur.execute("SELECT COUNT(*) FROM _fresh_daily_brand_metrics")
    fresh_rows = int(cur.fetchone()[0])

    prune_sql, prune_params = build_prune_sql(from_date=from_date, to_date=to_date)
    cur.execute(prune_sql, prune_params)
    deleted = int(cur.rowcount or 0)

    cur.execute(UPSERT_SQL)
    upserted = int(cur.rowcount or 0)

    cur.execute("SELECT COUNT(*) FROM daily_brand_metrics")
    total = int(cur.fetchone()[0])

    return {
        "fresh_rows": fresh_rows,
        "deleted_orphans": deleted,
        "upserted": upserted,
        "total_rows": total,
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Recompute daily_brand_metrics from mentions JOIN mention_brands "
        "(prune orphans in scope, then upsert)."
    )
    parser.add_argument(
        "--from",
        dest="from_date",
        metavar="YYYY-MM-DD",
        help="Inclusive metric_date lower bound (optional; default=all dates)",
    )
    parser.add_argument(
        "--to",
        dest="to_date",
        metavar="YYYY-MM-DD",
        help="Inclusive metric_date upper bound (optional; default=all dates)",
    )
    args = parser.parse_args(argv)

    from_date = parse_iso_date(args.from_date) if args.from_date else None
    to_date = parse_iso_date(args.to_date) if args.to_date else None

    from social_listening.pg import get_connection  # noqa: E402

    with get_connection() as conn:
        with conn.cursor() as cur:
            stats = recompute_daily_brand_metrics(
                cur, from_date=from_date, to_date=to_date
            )

    scope = "ALL dates"
    if from_date or to_date:
        scope = f"{from_date or '…'} → {to_date or '…'}"
    print(f"Recomputed daily_brand_metrics (prune orphans + upsert). scope={scope}")
    print(
        f"fresh_rows={stats['fresh_rows']} deleted_orphans={stats['deleted_orphans']} "
        f"upserted={stats['upserted']} total_rows={stats['total_rows']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
