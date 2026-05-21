from __future__ import annotations

import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from social_listening.dashboard.repository import PostgresDashboardRepository


def main() -> int:
    output_path = Path(
        os.getenv("DASHBOARD_JSON_OUT")
        or PROJECT_ROOT / "data" / "dashboard" / "meili_dashboard.json"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)

    repo = PostgresDashboardRepository(
        database=os.getenv("PGDATABASE", "meili_dashboard"),
        schema=os.getenv("PGSCHEMA", "meili_dashboard"),
        brand_slug=os.getenv("DASHBOARD_BRAND_SLUG", "meili-mi-bo-dai-loan"),
        psql_bin=os.getenv("PSQL_BIN", "psql"),
    )
    payload = repo.get_dashboard_payload()
    if not isinstance(payload, dict) or not payload:
        raise RuntimeError("No dashboard payload returned from PostgreSQL repository")

    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
