#!/usr/bin/env python3
"""Import GBO Share (Gross Box Office) vào galaxy_sl.gbo_snapshots.

GBO không crawl từ MXH — lấy từ báo cáo nội bộ (CSV).

CSV columns:
  period_start, period_end, brand_slug, gbo_share_pct [, cinema_count] [, source_name]

Usage:
  PYTHONPATH=src python3 scripts/shared/import_gbo_share.py
  PYTHONPATH=src python3 scripts/shared/import_gbo_share.py --input data/shared/gbo_share_sample.csv
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import date, datetime
from pathlib import Path

def _project_root() -> Path:
    current = Path(__file__).resolve().parent
    for cand in [current, *current.parents]:
        if (cand / "src" / "social_listening").is_dir():
            return cand
    raise RuntimeError(f"Cannot find project root from {__file__}")


PROJECT_ROOT = _project_root()
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from social_listening.pg import fetch_brand_map, get_connection  # noqa: E402

DEFAULT_INPUT = PROJECT_ROOT / "data" / "shared" / "gbo_share_sample.csv"


def parse_date(value: str) -> date:
    text = (value or "").strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Invalid date: {value!r}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    args = parser.parse_args()
    if not args.input.exists():
        print(f"Input not found: {args.input}", file=sys.stderr)
        return 1

    rows: list[dict] = []
    with args.input.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        required = {"period_start", "period_end", "brand_slug", "gbo_share_pct"}
        if not reader.fieldnames or not required.issubset({c.strip() for c in reader.fieldnames}):
            print(f"CSV needs columns: {sorted(required)}", file=sys.stderr)
            return 1
        for raw in reader:
            slug = (raw.get("brand_slug") or "").strip().lower()
            if not slug:
                continue
            rows.append(
                {
                    "period_start": parse_date(raw["period_start"]),
                    "period_end": parse_date(raw["period_end"]),
                    "brand_slug": slug,
                    "gbo_share_pct": float(raw["gbo_share_pct"]),
                    "cinema_count": (
                        int(raw["cinema_count"])
                        if (raw.get("cinema_count") or "").strip()
                        else None
                    ),
                    "source_name": (raw.get("source_name") or "internal_gbo").strip(),
                }
            )

    if not rows:
        print("No rows to import.")
        return 0

    upserted = 0
    with get_connection() as conn:
        cur = conn.cursor()
        brand_map = fetch_brand_map(cur)
        for row in rows:
            brand_id = brand_map.get(row["brand_slug"])
            if not brand_id:
                print(f"  skip unknown brand_slug={row['brand_slug']}", file=sys.stderr)
                continue
            cur.execute(
                """
                DELETE FROM gbo_snapshots
                WHERE brand_id = %s::uuid
                  AND period_start = %s
                  AND period_end = %s
                """,
                (brand_id, row["period_start"], row["period_end"]),
            )
            cur.execute(
                """
                INSERT INTO gbo_snapshots (
                    brand_id, period_start, period_end, gbo_share_pct, cinema_count, source_name
                ) VALUES (%s::uuid, %s, %s, %s, %s, %s)
                """,
                (
                    brand_id,
                    row["period_start"],
                    row["period_end"],
                    row["gbo_share_pct"],
                    row["cinema_count"],
                    row["source_name"],
                ),
            )
            upserted += 1
            print(
                f"  {row['brand_slug']}: {row['gbo_share_pct']}% "
                f"({row['period_start']} → {row['period_end']})"
            )

    print(f"Imported gbo_snapshots={upserted} from {args.input}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
