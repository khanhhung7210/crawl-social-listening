#!/usr/bin/env python3
"""Seed listening_queries for gift lead gen (process: gift_leads).

  PYTHONPATH=src python3 scripts/mkt/seed_gift_leads_config.py
  PYTHONPATH=src python3 scripts/mkt/seed_gift_leads_config.py --force
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from social_listening.gift_leads import GIFT_LEAD_KEYWORDS, PROCESS_NAME, keyword_table_rows  # noqa: E402
from social_listening.pg import get_connection  # noqa: E402

DEFAULT_PLATFORMS = ["facebook", "threads"]
QUERY_NAME = "gift_leads"


def seed_gift_leads_query(cur, force: bool) -> None:
    cur.execute(
        """
        SELECT query_id
        FROM listening_queries
        WHERE query_type = 'generic' AND query_name = %s
        LIMIT 1
        """,
        (QUERY_NAME,),
    )
    exists = cur.fetchone()
    if exists and not force:
        print(f"  gift_leads query: already exists (skip) — use --force to refresh")
        return

    keywords = json.dumps(GIFT_LEAD_KEYWORDS, ensure_ascii=False)
    platforms = json.dumps(DEFAULT_PLATFORMS, ensure_ascii=False)
    metadata = json.dumps(
        {
            "process": PROCESS_NAME,
            "active_process": PROCESS_NAME,
            "purpose": "outbound_gift_sales_leads",
            "strategy": "crawl_broad_classify_demand",
            "clusters": [
                "priority_phrase",
                "gift_intent",
                "bulk_order",
                "product",
            ],
            "intent_tags": [
                "buy_gift",
                "year_end_gift",
                "corporate_gift",
                "bulk_order",
            ],
            "keyword_count": len(GIFT_LEAD_KEYWORDS),
            "docs": "scripts/mkt/GIFT_LEAD_KEYWORDS.md",
        },
        ensure_ascii=False,
    )

    if exists:
        cur.execute(
            """
            UPDATE listening_queries
            SET keywords = %s::jsonb,
                platforms = %s::jsonb,
                metadata = %s::jsonb,
                is_active = TRUE,
                updated_at = NOW()
            WHERE query_type = 'generic' AND query_name = %s
            """,
            (keywords, platforms, metadata, QUERY_NAME),
        )
        print(f"  gift_leads query: updated ({len(GIFT_LEAD_KEYWORDS)} keywords)")
    else:
        cur.execute(
            """
            INSERT INTO listening_queries (
                query_type, query_name, keywords, hashtags, platforms, metadata, is_active
            ) VALUES (
                'generic', %s, %s::jsonb, '[]'::jsonb, %s::jsonb, %s::jsonb, TRUE
            )
            """,
            (QUERY_NAME, keywords, platforms, metadata),
        )
        print(f"  gift_leads query: inserted ({len(GIFT_LEAD_KEYWORDS)} keywords)")

    # Quick cluster breakdown for operators
    from collections import Counter

    counts = Counter(str(item.get("cluster") or "?") for item in GIFT_LEAD_KEYWORDS)
    print("  clusters:", dict(counts))
    print(f"  docs rows: {len(keyword_table_rows())} — see scripts/mkt/GIFT_LEAD_KEYWORDS.md")


def ensure_gift_leads_table(cur) -> None:
    cur.execute(
        """
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = current_schema()
          AND table_name = 'gift_leads'
        """
    )
    if cur.fetchone():
        print("  gift_leads table: OK")
        return

    migration = PROJECT_ROOT / "sql" / "migrations" / "001_gift_leads.sql"
    if not migration.is_file():
        print(f"  gift_leads table: MISSING — apply {migration}")
        return
    sql = migration.read_text(encoding="utf-8")
    cur.execute(sql)
    print("  gift_leads table: created from migration")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing gift_leads listening_queries row",
    )
    args = parser.parse_args()

    with get_connection() as conn:
        cur = conn.cursor()
        print("Seed gift lead gen config")
        ensure_gift_leads_table(cur)
        seed_gift_leads_query(cur, force=args.force)
        conn.commit()
        print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
