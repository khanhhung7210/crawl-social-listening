from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = os.getenv("PGSCHEMA", "meili_dashboard")
PGDATABASE = os.getenv("PGDATABASE", "meili_dashboard")
PSQL_BIN = os.getenv("PSQL_BIN", "psql")
BRAND_SLUG = os.getenv("BRAND_SLUG", "meili-mi-bo-dai-loan")


def main() -> int:
    rows = []
    rows.extend(grabfood_sources())
    rows.extend(google_maps_sources())
    rows = dedupe(rows)
    sql = build_sql(rows)
    run_sql(sql)
    print(json.dumps({"competitor_sources_seeded": len(rows)}, ensure_ascii=False, indent=2))
    return 0


def grabfood_sources() -> list[dict]:
    formatted = PROJECT_ROOT / "data/grabfood/processed/meili_mi_bo_dai_loan/grabfood_formatted.json"
    if not formatted.exists():
        return []
    payload = json.loads(formatted.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        return []
    rows = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        name = str(item.get("restaurant_name") or "").strip()
        url = str(item.get("url") or "").strip()
        if not name or not url or is_our_brand(name):
            continue
        if not is_relevant_competitor(name):
            continue
        rows.append(
            {
                "competitor_name": clean_competitor_name(name),
                "platform": "grabfood",
                "source_url": url,
                "metadata": {
                    "source": "grabfood_formatted",
                    "rating": item.get("rating"),
                    "review_count": item.get("review_count"),
                    "branch": item.get("branch"),
                    "dishes": item.get("dishes") or [],
                },
            }
        )
    return rows


def google_maps_sources() -> list[dict]:
    search = PROJECT_ROOT / "data/google_maps/raw/meili_mi_bo_dai_loan/google_maps_search_results.json"
    if not search.exists():
        return []
    payload = json.loads(search.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        return []
    rows = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        keyword = str(item.get("search_keyword") or item.get("keyword") or "").strip()
        name = extract_google_maps_name(url)
        if not url or not name or is_our_brand(name):
            continue
        if not is_relevant_competitor(name + " " + keyword):
            continue
        rows.append(
            {
                "competitor_name": clean_competitor_name(name),
                "platform": "google_maps",
                "source_url": url,
                "metadata": {
                    "source": "google_maps_search_results",
                    "search_keyword": keyword,
                    "search_rank": item.get("search_rank"),
                },
            }
        )
    return rows


def extract_google_maps_name(url: str) -> str:
    text = str(url or "")
    marker = "/place/"
    if marker not in text:
        return ""
    part = text.split(marker, 1)[1].split("/", 1)[0]
    return part.replace("+", " ").replace("%E2%80%93", "-")


def is_our_brand(name: str) -> bool:
    text = name.casefold()
    return "meili" in text or "mei li" in text or "美丽" in text


def is_relevant_competitor(name: str) -> bool:
    text = name.casefold()
    return any(term in text for term in ("mì bò", "mi bo", "taiwan", "đài loan", "dai loan", "sủi cảo", "sui cao"))


def clean_competitor_name(name: str) -> str:
    text = " ".join(str(name or "").split())
    for prefix in ("[Quận 1]", "[Quận 3]", "[Quận 4]", "[Quận 7]"):
        text = text.replace(prefix, "").strip()
    return text[:160]


def dedupe(rows: list[dict]) -> list[dict]:
    seen = set()
    result = []
    for row in rows:
        key = (row["competitor_name"].casefold(), row["platform"], row["source_url"])
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
    return result


def build_sql(rows: list[dict]) -> str:
    statements = [f"SET search_path TO {SCHEMA}, public;"]
    for row in rows:
        statements.append(
            f"""
INSERT INTO competitor_sources (
  brand_id, competitor_name, platform, source_url, source_type, crawl_enabled, metadata
)
SELECT
  brand_id,
  {sql_str(row['competitor_name'])},
  {sql_str(row['platform'])},
  {sql_str(row['source_url'])},
  'competitor',
  TRUE,
  {sql_json(row['metadata'])}::jsonb
FROM brands
WHERE brand_slug = {sql_str(BRAND_SLUG)}
ON CONFLICT (brand_id, competitor_name, platform, source_url)
DO UPDATE SET metadata = EXCLUDED.metadata, updated_at = NOW();
""".strip()
        )
    return "\n".join(statements) + "\n"


def run_sql(sql: str) -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".sql", delete=False) as handle:
        handle.write(sql)
        path = Path(handle.name)
    try:
        subprocess.run([PSQL_BIN, PGDATABASE, "-v", "ON_ERROR_STOP=1", "-f", str(path)], cwd=PROJECT_ROOT, check=True)
    finally:
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def sql_str(value: object) -> str:
    if value is None:
        return "NULL"
    return "'" + str(value).replace("'", "''") + "'"


def sql_json(value: object) -> str:
    return sql_str(json.dumps(value, ensure_ascii=False))


if __name__ == "__main__":
    raise SystemExit(main())
