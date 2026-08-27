#!/usr/bin/env python3
"""Match mentions → campaigns via campaign_keywords, then daily_campaign_metrics.

Usage:
  PYTHONPATH=src python3 scripts/marketing/classify/classify_mention_campaigns.py
  PYTHONPATH=src python3 scripts/marketing/classify/classify_mention_campaigns.py --brand glx
"""

from __future__ import annotations

import argparse
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


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def load_campaign_rules(cur, brand_slug: str | None) -> list[tuple[str, list[str]]]:
    if brand_slug:
        cur.execute(
            """
            SELECT c.campaign_id::text, ck.keyword
            FROM campaigns c
            JOIN campaign_keywords ck ON ck.campaign_id = c.campaign_id
            LEFT JOIN brands b ON b.brand_id = c.brand_id
            WHERE c.status IN ('running', 'ended')
              AND (b.brand_slug = %s OR c.brand_id IS NULL)
            """,
            (brand_slug,),
        )
    else:
        cur.execute(
            """
            SELECT c.campaign_id::text, ck.keyword
            FROM campaigns c
            JOIN campaign_keywords ck ON ck.campaign_id = c.campaign_id
            WHERE c.status IN ('running', 'ended')
            """
        )
    by_id: dict[str, list[str]] = {}
    for campaign_id, keyword in cur.fetchall():
        needle = normalize(str(keyword).lstrip("#"))
        if not needle:
            continue
        by_id.setdefault(campaign_id, [])
        if needle not in by_id[campaign_id]:
            by_id[campaign_id].append(needle)
        # also keep hashed form for hashtag text
        hashed = f"#{needle}"
        if hashed not in by_id[campaign_id]:
            by_id[campaign_id].append(hashed)
    return list(by_id.items())


def match_campaigns(text: str, rules: list[tuple[str, list[str]]]) -> list[str]:
    blob = normalize(text)
    if not blob:
        return []
    hits: list[str] = []
    for campaign_id, needles in rules:
        if any(n in blob for n in needles):
            hits.append(campaign_id)
    return hits


def classify(cur, brand_slug: str | None) -> tuple[int, int]:
    rules = load_campaign_rules(cur, brand_slug)
    if not rules:
        raise RuntimeError("No campaigns/keywords — run seed_campaigns.py first")

    if brand_slug:
        cur.execute(
            """
            SELECT m.mention_id::text, m.content_text
            FROM mentions m
            JOIN mention_brands mb ON mb.mention_id = m.mention_id
            JOIN brands b ON b.brand_id = mb.brand_id
            WHERE m.is_spam = FALSE
              AND b.brand_slug = %s
            """,
            (brand_slug,),
        )
    else:
        cur.execute(
            """
            SELECT m.mention_id::text, m.content_text
            FROM mentions m
            WHERE m.is_spam = FALSE
              AND EXISTS (SELECT 1 FROM mention_brands mb WHERE mb.mention_id = m.mention_id)
            """
        )
    rows = cur.fetchall()

    if brand_slug:
        cur.execute(
            """
            DELETE FROM mention_campaigns mc
            USING mention_brands mb, brands b
            WHERE mc.mention_id = mb.mention_id
              AND mb.brand_id = b.brand_id
              AND b.brand_slug = %s
              AND mc.match_method = 'keyword'
            """,
            (brand_slug,),
        )
    else:
        cur.execute("DELETE FROM mention_campaigns WHERE match_method = 'keyword'")

    assigned = 0
    mentions_hit = 0
    for mention_id, content in rows:
        hits = match_campaigns(content or "", rules)
        if not hits:
            continue
        mentions_hit += 1
        for campaign_id in hits:
            cur.execute(
                """
                INSERT INTO mention_campaigns (mention_id, campaign_id, match_method, confidence)
                VALUES (%s::uuid, %s::uuid, 'keyword', 1.0)
                ON CONFLICT (mention_id, campaign_id) DO UPDATE
                SET match_method = EXCLUDED.match_method,
                    confidence = EXCLUDED.confidence
                """,
                (mention_id, campaign_id),
            )
            assigned += 1
    return assigned, mentions_hit


def update_primary_platforms(cur) -> int:
    cur.execute(
        """
        WITH ranked AS (
            SELECT
                mc.campaign_id,
                m.platform_code,
                COUNT(*) AS cnt,
                ROW_NUMBER() OVER (
                    PARTITION BY mc.campaign_id ORDER BY COUNT(*) DESC
                ) AS rn
            FROM mention_campaigns mc
            JOIN mentions m ON m.mention_id = mc.mention_id
            WHERE m.is_spam = FALSE
            GROUP BY mc.campaign_id, m.platform_code
        ),
        top2 AS (
            SELECT campaign_id, jsonb_agg(platform_code ORDER BY rn) AS platforms
            FROM ranked
            WHERE rn <= 2
            GROUP BY campaign_id
        )
        UPDATE campaigns c
        SET primary_platforms = t.platforms,
            updated_at = NOW()
        FROM top2 t
        WHERE c.campaign_id = t.campaign_id
        """
    )
    return cur.rowcount


def recompute_daily_campaign_metrics(cur) -> int:
    cur.execute("DELETE FROM daily_campaign_metrics")
    cur.execute(
        """
        WITH base AS (
            SELECT
                (m.occurred_at AT TIME ZONE 'Asia/Ho_Chi_Minh')::date AS metric_date,
                mc.campaign_id,
                m.platform_code,
                m.sentiment
            FROM mentions m
            JOIN mention_campaigns mc ON mc.mention_id = m.mention_id
            WHERE m.is_spam = FALSE
              AND m.occurred_at IS NOT NULL
        ),
        agg_platform AS (
            SELECT
                metric_date,
                campaign_id,
                platform_code,
                COUNT(*) AS buzz_count,
                COUNT(*) FILTER (WHERE sentiment = 'positive') AS positive_count,
                COUNT(*) FILTER (WHERE sentiment = 'negative') AS negative_count,
                COUNT(*) FILTER (WHERE sentiment = 'neutral') AS neutral_count
            FROM base
            GROUP BY metric_date, campaign_id, platform_code
        ),
        agg_all AS (
            SELECT
                metric_date,
                campaign_id,
                'all'::text AS platform_code,
                COUNT(*) AS buzz_count,
                COUNT(*) FILTER (WHERE sentiment = 'positive') AS positive_count,
                COUNT(*) FILTER (WHERE sentiment = 'negative') AS negative_count,
                COUNT(*) FILTER (WHERE sentiment = 'neutral') AS neutral_count
            FROM base
            GROUP BY metric_date, campaign_id
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
        INSERT INTO daily_campaign_metrics (
            metric_date, campaign_id, platform_code,
            buzz_count, positive_count, negative_count, neutral_count,
            sov_pct, updated_at
        )
        SELECT
            metric_date, campaign_id, platform_code,
            buzz_count, positive_count, negative_count, neutral_count,
            sov_pct, NOW()
        FROM with_sov
        """
    )
    cur.execute("SELECT COUNT(*) FROM daily_campaign_metrics")
    return int(cur.fetchone()[0])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--brand", default="glx", help="Brand slug (default glx; empty = all)")
    args = parser.parse_args()
    brand = (args.brand or "").strip() or None

    with get_connection() as conn:
        cur = conn.cursor()
        assigned, hits = classify(cur, brand)
        metrics = recompute_daily_campaign_metrics(cur)
        platforms = update_primary_platforms(cur)
        print(
            f"campaign_links={assigned} mentions_hit={hits} "
            f"daily_campaign_metrics={metrics} primary_platforms_updated={platforms}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
