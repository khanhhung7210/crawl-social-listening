from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PGDATABASE = os.getenv("PGDATABASE", "meili_dashboard")
PSQL_BIN = os.getenv("PSQL_BIN", "psql")
SCHEMA = os.getenv("PGSCHEMA", "meili_dashboard")
BRAND_SLUG = os.getenv("BRAND_SLUG", "meili-mi-bo-dai-loan")


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit whether crawled data can satisfy the Meili dashboard requirements")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    args = parser.parse_args()

    metrics = collect_metrics()
    assessment = assess(metrics)
    payload = {"metrics": metrics, "assessment": assessment}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print_report(metrics, assessment)
    return 0 if assessment["overall_ready"] else 2


def collect_metrics() -> dict:
    sql = f"""
SET search_path TO {SCHEMA}, public;
WITH brand AS (
  SELECT brand_id FROM brands WHERE brand_slug = '{BRAND_SLUG}' LIMIT 1
),
review_platforms AS (
  SELECT platform, COUNT(*) AS review_count, ROUND(AVG(rating)::numeric, 2) AS avg_rating
  FROM reviews
  WHERE brand_id = (SELECT brand_id FROM brand)
  GROUP BY platform
),
branch_reviews AS (
  SELECT b.branch_slug, b.branch_name, COUNT(r.review_id) AS review_count
  FROM branches b
  LEFT JOIN reviews r ON r.branch_id = b.branch_id
  WHERE b.brand_id = (SELECT brand_id FROM brand)
  GROUP BY b.branch_slug, b.branch_name
),
mention_mapping AS (
  SELECT platform,
         COUNT(*) AS total_mentions,
         COUNT(*) FILTER (WHERE branch_id IS NOT NULL) AS mapped_mentions
  FROM mentions
  WHERE brand_id = (SELECT brand_id FROM brand)
  GROUP BY platform
),
foundation AS (
  SELECT
    (SELECT COUNT(*) FROM hourly_signal_metrics WHERE brand_id = (SELECT brand_id FROM brand)) AS hourly_metrics,
    (SELECT COUNT(*) FROM response_tracking WHERE brand_id = (SELECT brand_id FROM brand)) AS response_rows,
    (SELECT COUNT(*) FROM action_items WHERE brand_id = (SELECT brand_id FROM brand)) AS action_rows,
    (SELECT COUNT(*) FROM proof_assets WHERE brand_id = (SELECT brand_id FROM brand)) AS proof_assets,
    (SELECT COUNT(*) FROM search_demand_signals WHERE brand_id = (SELECT brand_id FROM brand)) AS search_demand_rows,
    (SELECT COUNT(*) FROM competitor_sources WHERE brand_id = (SELECT brand_id FROM brand)) AS competitor_sources,
    (SELECT COUNT(*) FROM competitor_intel WHERE brand_id = (SELECT brand_id FROM brand)) AS competitor_intel
)
SELECT jsonb_build_object(
  'review_platforms', COALESCE((SELECT jsonb_agg(row_to_json(review_platforms) ORDER BY platform) FROM review_platforms), '[]'::jsonb),
  'branch_reviews', COALESCE((SELECT jsonb_agg(row_to_json(branch_reviews) ORDER BY branch_name) FROM branch_reviews), '[]'::jsonb),
  'mention_mapping', COALESCE((SELECT jsonb_agg(row_to_json(mention_mapping) ORDER BY platform) FROM mention_mapping), '[]'::jsonb),
  'foundation', (SELECT row_to_json(foundation) FROM foundation)
)::text;
""".strip()
    result = subprocess.run(
        [PSQL_BIN, PGDATABASE, "-Atqc", sql],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    db_metrics = json.loads(result.stdout.strip() or "{}")
    file_metrics = collect_file_metrics()
    return {**db_metrics, "files": file_metrics}


def collect_file_metrics() -> dict:
    files = {
        "shopeefood_reviews_jsonl": PROJECT_ROOT / "data/shopeefood/processed/meili_mi_bo_dai_loan/shopeefood_formatted_reviews.jsonl",
        "grabfood_reviews_jsonl": PROJECT_ROOT / "data/grabfood/processed/meili_mi_bo_dai_loan/grabfood_formatted_reviews.jsonl",
        "google_maps_places": PROJECT_ROOT / "data/google_maps/raw/meili_mi_bo_dai_loan/google_maps_all_places.json",
        "grabfood_formatted": PROJECT_ROOT / "data/grabfood/processed/meili_mi_bo_dai_loan/grabfood_formatted.json",
        "shopeefood_grouped": PROJECT_ROOT / "data/shopeefood/processed/meili_mi_bo_dai_loan/shopeefood_grouped_parsed.json",
    }
    metrics = {}
    for key, path in files.items():
        metrics[key] = {"path": str(path.relative_to(PROJECT_ROOT)), "exists": path.exists(), "records": count_records(path)}
    return metrics


def count_records(path: Path) -> int:
    if not path.exists():
        return 0
    if path.suffix == ".jsonl":
        return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return 0
    return len(payload) if isinstance(payload, list) else 1


def assess(metrics: dict) -> dict:
    review_platforms = {row["platform"]: int(row["review_count"]) for row in metrics.get("review_platforms") or []}
    branch_reviews = metrics.get("branch_reviews") or []
    mention_mapping = metrics.get("mention_mapping") or []
    foundation = metrics.get("foundation") or {}
    branch_social_total = sum(int(row.get("total_mentions") or 0) for row in mention_mapping if row.get("platform") in {"facebook", "tiktok", "instagram", "threads", "youtube"})
    branch_social_mapped = sum(int(row.get("mapped_mentions") or 0) for row in mention_mapping if row.get("platform") in {"facebook", "tiktok", "instagram", "threads", "youtube"})
    mapping_ratio = branch_social_mapped / branch_social_total if branch_social_total else 0

    checks = {
        "delivery_reviews_by_branch": all(int(row.get("review_count") or 0) >= 20 for row in branch_reviews)
        and review_platforms.get("shopeefood", 0) >= 50
        and review_platforms.get("grabfood", 0) >= 50,
        "social_branch_context": mapping_ratio >= 0.60,
        "competitor_basic": int(foundation.get("competitor_sources") or 0) >= 3,
        "incremental_aggregation": int(foundation.get("hourly_metrics") or 0) > 0
        and int(foundation.get("action_rows") or 0) > 0
        and int(foundation.get("response_rows") or 0) > 0,
    }
    gaps = []
    if not checks["delivery_reviews_by_branch"]:
        gaps.append("Need >=20 reviews per branch and >=50 each from ShopeeFood + GrabFood for stable branch/review modules.")
    if not checks["social_branch_context"]:
        gaps.append(f"Need >=60% mapped social mentions; current mapped social ratio is {mapping_ratio:.1%}.")
    if not checks["competitor_basic"]:
        gaps.append("Need competitor Google Maps/delivery source rows.")
    if not checks["incremental_aggregation"]:
        gaps.append("Need hourly/action/response aggregation rows.")
    return {
        "checks": checks,
        "overall_ready": all(checks.values()),
        "social_branch_mapping_ratio": round(mapping_ratio, 4),
        "gaps": gaps,
    }


def print_report(metrics: dict, assessment: dict) -> None:
    print("Crawl readiness for dashboard requirements")
    print("")
    print("Checks:")
    for name, ok in assessment["checks"].items():
        print(f"- {name}: {'READY' if ok else 'MISSING'}")
    print("")
    print(f"Social branch mapping ratio: {assessment['social_branch_mapping_ratio']:.1%}")
    print("")
    print("Review platforms:")
    for row in metrics.get("review_platforms") or []:
        print(f"- {row['platform']}: {row['review_count']} reviews, avg {row.get('avg_rating')}")
    print("")
    print("Branch review coverage:")
    for row in metrics.get("branch_reviews") or []:
        print(f"- {row['branch_name']}: {row['review_count']} reviews")
    print("")
    if assessment["gaps"]:
        print("Gaps:")
        for gap in assessment["gaps"]:
            print(f"- {gap}")
    else:
        print("All P0 readiness checks pass.")


if __name__ == "__main__":
    raise SystemExit(main())
