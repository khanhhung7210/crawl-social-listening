from __future__ import annotations

import json
import os
import subprocess
import sys


PGDATABASE = os.getenv("PGDATABASE", "meili_dashboard")
PSQL_BIN = os.getenv("PSQL_BIN", "psql")
SCHEMA = os.getenv("PGSCHEMA", "meili_dashboard")


def main() -> int:
    rows = query_json(
        f"""
        SELECT COALESCE(json_agg(row_to_json(t) ORDER BY platform), '[]'::json)
        FROM (
          SELECT
            platform,
            COUNT(*)::int AS total_menu_items,
            COUNT(*) FILTER (WHERE sold_count IS NOT NULL)::int AS sold_metric_items,
            COUNT(*) FILTER (WHERE COALESCE(sold_count, 0) > 0)::int AS nonzero_sold_items,
            COUNT(*) FILTER (WHERE item_review_count > 0)::int AS item_review_metric_items,
            COUNT(*) FILTER (WHERE jsonb_array_length(review_comments) > 0)::int AS item_comment_items
          FROM {SCHEMA}.menu_items
          WHERE platform IN ('shopeefood', 'grabfood')
          GROUP BY platform
        ) t;
        """
    )
    details = query_json(
        f"""
        SELECT COALESCE(json_agg(row_to_json(t) ORDER BY platform, item_review_count DESC, sold_count DESC NULLS LAST), '[]'::json)
        FROM (
          SELECT
            platform,
            item_name,
            COALESCE(sold_count, 0)::int AS sold_count,
            item_review_count::int,
            jsonb_array_length(review_comments)::int AS review_comment_count
          FROM {SCHEMA}.menu_items
          WHERE platform IN ('shopeefood', 'grabfood')
            AND (sold_count IS NOT NULL OR item_review_count > 0 OR jsonb_array_length(review_comments) > 0)
          LIMIT 20
        ) t;
        """
    )
    payload = {
        "coverage": rows,
        "sample_items": details,
        "gaps": detect_gaps(rows),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 1 if payload["gaps"] else 0


def detect_gaps(rows: list[dict]) -> list[str]:
    by_platform = {row["platform"]: row for row in rows}
    gaps: list[str] = []
    for platform in ("shopeefood", "grabfood"):
        row = by_platform.get(platform)
        if not row or int(row.get("total_menu_items") or 0) == 0:
            gaps.append(f"{platform}: no menu items")
            continue
        if int(row.get("sold_metric_items") or 0) == 0:
            gaps.append(f"{platform}: no item sold_count captured")
        if int(row.get("nonzero_sold_items") or 0) == 0:
            gaps.append(f"{platform}: sold_count captured but all values are zero")
        if int(row.get("item_comment_items") or 0) == 0:
            gaps.append(f"{platform}: no item-level review comments")
    return gaps


def query_json(sql: str):
    completed = subprocess.run([PSQL_BIN, PGDATABASE, "-Atqc", sql], capture_output=True, text=True, check=True)
    output = completed.stdout.strip()
    return json.loads(output) if output else []


if __name__ == "__main__":
    raise SystemExit(main())
