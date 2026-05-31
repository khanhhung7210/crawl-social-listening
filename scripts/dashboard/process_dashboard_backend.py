#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
load_dotenv(PROJECT_ROOT / ".env")

from social_listening.dashboard.backend_processor import DashboardBackendProcessor
from social_listening.dashboard.repository import PostgresDashboardRepository


def main() -> int:
    parser = argparse.ArgumentParser(description="Build dashboard-ready snapshot from DB + Dashboard_req_mapping.xlsx")
    parser.add_argument("--mapping-file", default=str(PROJECT_ROOT / "Dashboard_req_mapping.xlsx"))
    parser.add_argument("--dry-run", action="store_true", help="Build and validate snapshot without writing DB")
    args = parser.parse_args()

    repo = PostgresDashboardRepository(
        database=os.getenv("PGDATABASE", "meili_dashboard"),
        schema=os.getenv("PGSCHEMA", "meili_dashboard"),
        brand_slug=os.getenv("DASHBOARD_BRAND_SLUG", os.getenv("BRAND_SLUG", "meili-mi-bo-dai-loan")),
        psql_bin=os.getenv("PSQL_BIN", "psql"),
    )
    processor = DashboardBackendProcessor(repo, Path(args.mapping_file))
    snapshot = processor.build_snapshot()
    if not args.dry_run:
        processor.save_snapshot(snapshot)

    validation = snapshot.get("backend", {}).get("validation", {})
    summary = {
        "backend": snapshot.get("backend", {}).get("name"),
        "snapshot_written": not args.dry_run,
        "mapping_file": str(args.mapping_file),
        "overview_cards": len(snapshot.get("overview", {}).get("top_cards") or []),
        "screen_modules": {
            key: len((screen.get("modules") or []))
            for key, screen in (snapshot.get("screens") or {}).items()
        },
        "missing": validation.get("missing") or [],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
