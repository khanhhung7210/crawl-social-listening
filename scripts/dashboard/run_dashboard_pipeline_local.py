#!/usr/bin/env python3
"""
Dashboard local pipeline: heuristic enrichment + local snapshot synthesis + JSON export.

Designed for recurring runs without OpenAI API.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Dashboard Local Pipeline - heuristic enrichment & synthesis",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--skip-enrich", action="store_true", help="Skip local enrichment stage")
    parser.add_argument("--skip-foundation", action="store_true", help="Skip crawl foundation metrics stage")
    parser.add_argument("--skip-synthesis", action="store_true", help="Skip local dashboard snapshot stage")
    parser.add_argument("--skip-export", action="store_true", help="Skip dashboard JSON export stage")
    parser.add_argument("--dry-run", action="store_true", help="Print commands without running")
    parser.add_argument("--continue-on-error", action="store_true", help="Continue even if a stage fails")
    parser.add_argument("--loop", action="store_true", help="Run continuously in a loop")
    parser.add_argument("--interval", type=int, default=1800, help="Loop interval in seconds (default: 1800)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[2]
    os.chdir(project_root)

    if args.dry_run:
      os.environ["DRY_RUN"] = "1"

    print_header("Dashboard Local Pipeline")
    print_config(args)

    if args.loop:
        print_info(f"Running in loop mode with {args.interval}s interval")
        print_info("Press Ctrl+C to stop")
        print()
        run_count = 0
        while True:
            run_count += 1
            print_section(f"Run #{run_count} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            status = run_pipeline(args)
            if status != 0 and not args.continue_on_error:
                print_error(f"Pipeline failed on run #{run_count}")
                return status
            print_success(f"✓ Run #{run_count} completed")
            print_info(f"Next run in {args.interval} seconds...")
            print()
            try:
                time.sleep(args.interval)
            except KeyboardInterrupt:
                print()
                print_info("Stopped by user")
                return 0
    return run_pipeline(args)


def run_pipeline(args: argparse.Namespace) -> int:
    overall_status = 0

    stages = [
        (
            "Stage 1: Local Enrichment",
            "Enriching mentions & reviews with heuristic rules...",
            args.skip_enrich,
            ["node", "scripts/dashboard/enrich_meili_postgres_local.mjs"],
        ),
        (
            "Stage 2: Crawl Foundation Metrics",
            "Applying crawl schema, branch mapping, hourly aggregation, response tracking, action queue and proof assets...",
            args.skip_foundation,
            ["python3", "scripts/dashboard/build_crawl_foundation_metrics.py"],
        ),
        (
            "Stage 3: Dashboard Backend Processing",
            "Building dashboard-ready snapshot from PostgreSQL and Dashboard_req_mapping.xlsx...",
            args.skip_synthesis,
            ["python3", "scripts/dashboard/process_dashboard_backend.py"],
        ),
        (
            "Stage 4: Dashboard JSON Export",
            "Exporting dashboard payload from PostgreSQL...",
            args.skip_export,
            ["python3", "scripts/dashboard/export_dashboard_json.py"],
        ),
    ]

    for title, description, should_skip, command in stages:
        if should_skip:
            print_warning(f"Skipping {title.lower()}")
            print()
            continue

        print_section(title)
        print_info(description)
        print()
        if args.dry_run:
            print_warning(f"[DRY RUN] Would run: {' '.join(command)}")
            print()
            continue

        status = run_command(command, args.verbose)
        if status == 0:
            print_success("✓ Stage completed successfully")
        else:
            print_error("✗ Stage failed")
            overall_status = 1
            if not args.continue_on_error:
                return 1
        print()

    print_section("Pipeline Summary")
    if overall_status == 0:
        print_success("Pipeline completed successfully")
        print()
        print_info("Dashboard payload is ready")
        print_info("Run every 30 minutes with:")
        print_info("  python3 scripts/dashboard/run_dashboard_pipeline_local.py --loop --interval 1800")
    else:
        print_warning("Pipeline completed with errors")
    return overall_status


def run_command(command: list[str], verbose: bool = False) -> int:
    try:
        if verbose:
            print_info(f"Running: {' '.join(command)}")
        result = subprocess.run(
            command,
            capture_output=not verbose,
            text=True,
            check=False,
        )
        if result.returncode == 0 and result.stdout:
            try:
                payload = json.loads(result.stdout)
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            except json.JSONDecodeError:
                if verbose:
                    print(result.stdout)
        elif result.returncode != 0:
            if result.stderr:
                print_error(result.stderr)
            if result.stdout and verbose:
                print(result.stdout)
        return result.returncode
    except FileNotFoundError as exc:
        print_error(str(exc))
        return 1


def print_config(args: argparse.Namespace) -> None:
    print_info("Configuration:")
    config = {
        "PGDATABASE": os.getenv("PGDATABASE", "meili_dashboard"),
        "PGSCHEMA": os.getenv("PGSCHEMA", "meili_dashboard"),
        "BRAND_SLUG": os.getenv("BRAND_SLUG", "meili-mi-bo-dai-loan"),
        "DRY_RUN": str(args.dry_run),
        "SKIP_ENRICH": str(args.skip_enrich),
        "SKIP_FOUNDATION": str(args.skip_foundation),
        "SKIP_SYNTHESIS": str(args.skip_synthesis),
        "SKIP_EXPORT": str(args.skip_export),
        "INTERVAL": str(args.interval),
    }
    for key, value in config.items():
        print(f"  {key:20} {value}")
    print()


def print_header(text: str) -> None:
    print("\n" + "=" * 50)
    print(f"  {text}")
    print("=" * 50 + "\n")


def print_section(text: str) -> None:
    print("=" * 50)
    print(f"  {text}")
    print("=" * 50)
    print()


def print_info(text: str) -> None:
    print(text)


def print_success(text: str) -> None:
    print(text)


def print_warning(text: str) -> None:
    print(text)


def print_error(text: str) -> None:
    print(text, file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
