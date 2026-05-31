from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


DELIVERY_STAGES = [
    ("ShopeeFood shop/review crawl", ["python3", "scripts/shopeefood/shopeefood_review_runner.py"], True),
    ("ShopeeFood format", ["python3", "scripts/shopeefood/shopeefood_format_job.py"], False),
    ("ShopeeFood review format", ["python3", "scripts/shopeefood/shopeefood_review_format_job.py"], False),
    ("GrabFood search", ["python3", "scripts/grabfood/grabfood_search_runner.py"], True),
    ("GrabFood search filter", ["python3", "scripts/grabfood/grabfood_search_filter.py"], False),
    ("GrabFood menu/rating detail", ["python3", "scripts/grabfood/grabfood_detail_runner.py"], True),
    ("GrabFood menu format", ["python3", "scripts/grabfood/grabfood_format_job.py"], False),
    ("GrabFood review crawl", ["python3", "scripts/grabfood/grabfood_review_crawler.py"], True),
    ("GrabFood review format", ["python3", "scripts/grabfood/grabfood_review_format_job.py"], False),
]

COMPETITOR_STAGES = [
    ("Google Maps competitor/search crawl", ["python3", "scripts/google_maps/google_maps_search_runner.py"], True),
    ("Google Maps competitor/review crawl", ["python3", "scripts/google_maps/google_maps_review_runner.py"], True),
    ("Google Maps format", ["python3", "scripts/google_maps/google_maps_format_job.py"], False),
    ("Google Maps keyword filter", ["python3", "scripts/google_maps/google_maps_keyword_filter_job.py"], False),
    ("Seed competitor sources", ["python3", "scripts/dashboard/seed_competitor_sources.py"], False),
    ("Competitor mention detection", ["node", "scripts/dashboard/detect_competitor_mentions_openai.mjs"], True),
    ("Competitor pressure analysis", ["node", "scripts/dashboard/analyze_competitor_pressure_openai.mjs"], True),
    ("Competitor response recommendations", ["node", "scripts/dashboard/recommend_competitor_responses_openai.mjs"], True),
]

SOCIAL_CONTEXT_STAGES = [
    ("Facebook incremental crawl", ["python3", "scripts/facebook/facebook_raw_runner.py"], True),
    ("Facebook format", ["python3", "scripts/facebook/facebook_format_job.py"], False),
    ("Facebook keyword filter", ["python3", "scripts/facebook/facebook_keyword_filter_job.py"], False),
    ("TikTok incremental search", ["python3", "scripts/tiktok/tiktok_search_runner_incremental.py"], True),
    ("TikTok detail", ["python3", "scripts/tiktok/tiktok_video_runner.py"], True),
    ("TikTok format", ["python3", "scripts/tiktok/tiktok_format_job.py"], False),
    ("TikTok keyword filter", ["python3", "scripts/tiktok/tiktok_keyword_filter_job.py"], False),
    ("Instagram incremental search", ["python3", "scripts/instagram/instagram_search_runner.py"], True),
    ("Instagram detail", ["python3", "scripts/instagram/instagram_post_runner.py"], True),
    ("Instagram format", ["python3", "scripts/instagram/instagram_format_job.py"], False),
    ("Instagram keyword filter", ["python3", "scripts/instagram/instagram_keyword_filter_job.py"], False),
]

FINAL_STAGES = [
    ("PostgreSQL import", ["python3", "scripts/dashboard/import_meili_to_postgres.py"], False),
    ("Dashboard aggregation", ["python3", "scripts/dashboard/run_dashboard_pipeline_local.py", "--continue-on-error"], False),
    ("Readiness audit", ["python3", "scripts/dashboard/check_crawl_readiness.py"], False),
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Meili crawl pipeline for dashboard readiness")
    parser.add_argument("--delivery", action="store_true", help="Run delivery review/menu stages")
    parser.add_argument("--social", action="store_true", help="Run social branch-context stages")
    parser.add_argument("--competitor", action="store_true", help="Run competitor stages")
    parser.add_argument("--all", action="store_true", help="Run all groups")
    parser.add_argument("--skip-live", action="store_true", help="Skip stages that need browser/app/login/OpenAI")
    parser.add_argument("--dry-run", action="store_true", help="Print commands only")
    parser.add_argument("--continue-on-error", action="store_true", help="Continue after failed stages")
    args = parser.parse_args()

    groups: list[tuple[str, list[tuple[str, list[str], bool]]]] = []
    if args.all or args.delivery:
        groups.append(("delivery", DELIVERY_STAGES))
    if args.all or args.social:
        groups.append(("social", SOCIAL_CONTEXT_STAGES))
    if args.all or args.competitor:
        groups.append(("competitor", COMPETITOR_STAGES))
    if not groups:
        groups.append(("final", FINAL_STAGES))
    else:
        groups.append(("final", FINAL_STAGES))

    failed = []
    for group_name, stages in groups:
        print(f"\n== {group_name.upper()} ==")
        for stage_name, command, needs_live in stages:
            if needs_live and args.skip_live:
                print(f"SKIP live stage: {stage_name}")
                continue
            ok = run_stage(stage_name, command, args.dry_run)
            if not ok:
                failed.append(stage_name)
                if not args.continue_on_error:
                    return 1
    if failed:
        print(f"\nFailed stages: {', '.join(failed)}")
        return 1
    return 0


def run_stage(stage_name: str, command: list[str], dry_run: bool) -> bool:
    print(f"\n[{stage_name}] {' '.join(command)}")
    if dry_run:
        return True
    result = subprocess.run(command, cwd=PROJECT_ROOT, text=True, capture_output=True)
    if result.stdout:
        print(result.stdout[-3000:])
    if result.returncode != 0:
        if result.stderr:
            print(result.stderr[-3000:], file=sys.stderr)
        return False
    return True


if __name__ == "__main__":
    raise SystemExit(main())
