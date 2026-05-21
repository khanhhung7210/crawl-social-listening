#!/usr/bin/env python3
"""
Dashboard Data Pipeline - Tổng hợp payload cho web dashboard
Chạy enrichment và synthesis để tạo data cho dashboard

Usage:
    python3 scripts/dashboard/run_dashboard_pipeline.py [options]

Examples:
    python3 scripts/dashboard/run_dashboard_pipeline.py
    python3 scripts/dashboard/run_dashboard_pipeline.py --skip-enrich
    python3 scripts/dashboard/run_dashboard_pipeline.py --dry-run
    python3 scripts/dashboard/run_dashboard_pipeline.py --loop --interval 3600
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


def main():
    parser = argparse.ArgumentParser(
        description="Dashboard Data Pipeline - Enrichment & Synthesis",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--skip-enrich", action="store_true", help="Skip OpenAI enrichment stage")
    parser.add_argument("--skip-synthesis", action="store_true", help="Skip dashboard synthesis stage")
    parser.add_argument("--dry-run", action="store_true", help="Print commands without running")
    parser.add_argument("--continue-on-error", action="store_true", help="Continue even if a stage fails")
    parser.add_argument("--loop", action="store_true", help="Run continuously in a loop")
    parser.add_argument("--interval", type=int, default=3600, help="Interval in seconds for loop mode (default: 3600)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")

    args = parser.parse_args()

    # Change to project root
    project_root = Path(__file__).resolve().parents[2]
    os.chdir(project_root)

    # Set DRY_RUN env if needed
    if args.dry_run:
        os.environ["DRY_RUN"] = "1"

    # Check required environment variables
    if not args.dry_run and not args.skip_enrich:
        openai_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not openai_key:
            print_error("OPENAI_API_KEY is required for enrichment")
            print_info("Export it: export OPENAI_API_KEY=sk-...")
            return 1

    # Print configuration
    print_header("Dashboard Data Pipeline")
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
    else:
        return run_pipeline(args)


def run_pipeline(args: argparse.Namespace) -> int:
    """Run the full pipeline once"""
    overall_status = 0

    # Stage 1: Enrich mentions and reviews with OpenAI
    if not args.skip_enrich:
        print_section("Stage 1: OpenAI Enrichment")
        print_info("Enriching mentions & reviews với sentiment/topic analysis...")
        print()

        if not args.dry_run:
            status = run_node_script("scripts/dashboard/enrich_meili_postgres_openai.mjs", args.verbose)
            if status == 0:
                print_success("✓ Enrichment completed successfully")
            else:
                print_error("✗ Enrichment failed")
                overall_status = 1
                if not args.continue_on_error:
                    return 1
        else:
            print_warning("[DRY RUN] Would run: node scripts/dashboard/enrich_meili_postgres_openai.mjs")
        print()
    else:
        print_warning("Skipping enrichment stage")
        print()

    # Stage 2: Synthesize dashboard snapshot with OpenAI
    if not args.skip_synthesis:
        print_section("Stage 2: Dashboard Synthesis")
        print_info("Synthesizing dashboard snapshot với OpenAI insights...")
        print()

        if not args.dry_run:
            status = run_node_script("scripts/dashboard/synthesize_dashboard_snapshot_openai.mjs", args.verbose)
            if status == 0:
                print_success("✓ Synthesis completed successfully")
            else:
                print_error("✗ Synthesis failed")
                overall_status = 1
                if not args.continue_on_error:
                    return 1
        else:
            print_warning("[DRY RUN] Would run: node scripts/dashboard/synthesize_dashboard_snapshot_openai.mjs")
        print()
    else:
        print_warning("Skipping synthesis stage")
        print()

    # Summary
    print_section("Pipeline Summary")
    if overall_status == 0:
        print_success("Pipeline completed successfully! 🎉")
        print()
        print_info("Dashboard payload is ready!")
        print_info("Start dashboard server:")
        print_info("  python3 -m social_listening.dashboard.server")
    else:
        print_warning("Pipeline completed with errors")

    return overall_status


def run_node_script(script_path: str, verbose: bool = False) -> int:
    """Run a Node.js script and return exit code"""
    try:
        cmd = ["node", script_path]
        if verbose:
            print_info(f"Running: {' '.join(cmd)}")

        result = subprocess.run(
            cmd,
            capture_output=not verbose,
            text=True,
            check=False,
        )

        if result.returncode == 0 and result.stdout:
            try:
                output = json.loads(result.stdout)
                print_json(output)
            except json.JSONDecodeError:
                if verbose:
                    print(result.stdout)
        elif result.returncode != 0:
            if result.stderr:
                print_error(result.stderr)
            if result.stdout and verbose:
                print(result.stdout)

        return result.returncode
    except FileNotFoundError:
        print_error("Node.js not found. Please install Node.js first.")
        return 1
    except Exception as e:
        print_error(f"Error running script: {e}")
        return 1


def print_config(args: argparse.Namespace):
    """Print current configuration"""
    print_info("Configuration:")
    config = {
        "PGDATABASE": os.getenv("PGDATABASE", "meili_dashboard"),
        "PGSCHEMA": os.getenv("PGSCHEMA", "meili_dashboard"),
        "BRAND_SLUG": os.getenv("BRAND_SLUG", "meili-mi-bo-dai-loan"),
        "OPENAI_MODEL": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        "DRY_RUN": str(args.dry_run),
        "SKIP_ENRICH": str(args.skip_enrich),
        "SKIP_SYNTHESIS": str(args.skip_synthesis),
    }
    for key, value in config.items():
        print(f"  {key:20} {value}")
    print()


def print_header(text: str):
    """Print header"""
    print("\n" + "=" * 50)
    print(f"  {text}")
    print("=" * 50 + "\n")


def print_section(text: str):
    """Print section header"""
    print("=" * 50)
    print(f"  {text}")
    print("=" * 50)
    print()


def print_success(text: str):
    """Print success message in green"""
    print(f"\033[0;32m{text}\033[0m")


def print_error(text: str):
    """Print error message in red"""
    print(f"\033[0;31m{text}\033[0m", file=sys.stderr)


def print_warning(text: str):
    """Print warning message in yellow"""
    print(f"\033[1;33m{text}\033[0m")


def print_info(text: str):
    """Print info message in blue"""
    print(f"\033[0;34m{text}\033[0m")


def print_json(data: dict):
    """Print JSON data"""
    print(json.dumps(data, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print()
        print_warning("Interrupted by user")
        sys.exit(130)
    except Exception as e:
        print_error(f"Unexpected error: {e}")
        sys.exit(1)
