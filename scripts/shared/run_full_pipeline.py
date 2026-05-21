#!/usr/bin/env python3
"""
Master pipeline runner - Chạy toàn bộ từ crawl đến import DB

Usage:
    python scripts/shared/run_full_pipeline.py threads
    python scripts/shared/run_full_pipeline.py facebook
    python scripts/shared/run_full_pipeline.py instagram
    python scripts/shared/run_full_pipeline.py tiktok
    python scripts/shared/run_full_pipeline.py youtube
    python scripts/shared/run_full_pipeline.py all

Options:
    --skip-crawl        Skip crawl stage (search + detail)
    --skip-format       Skip format job
    --skip-filter       Skip keyword filter
    --skip-sync         Skip PostgreSQL import
    --skip-enrich       Skip OpenAI enrichment
    --only-crawl        Only run crawl stage
    --dry-run           Print commands without running
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Platform configurations
PLATFORMS = {
    "threads": {
        "name": "Threads",
        "crawl_search": "scripts/threads/threads_crawl_runner.py",
        "crawl_detail": "scripts/threads/threads_replies_runner.py",
        "format_job": "scripts/threads/threads_format_job.py",
        "keyword_filter": "scripts/threads/threads_keyword_filter_job.py",
        "postgres_import": "scripts/dashboard/import_meili_to_postgres.py",
        "has_enrich": False,
    },
    "facebook": {
        "name": "Facebook",
        "crawl_search": "scripts/facebook/facebook_raw_runner.py",
        "crawl_detail": None,  # Combined in raw_runner
        "format_job": "scripts/facebook/facebook_format_job.py",
        "keyword_filter": "scripts/facebook/facebook_keyword_filter_job.py",
        "postgres_import": "scripts/dashboard/import_meili_to_postgres.py",
        "has_enrich": True,
    },
    "instagram": {
        "name": "Instagram",
        "crawl_search": "scripts/instagram/instagram_search_runner.py",
        "crawl_detail": "scripts/instagram/instagram_post_runner.py",
        "format_job": "scripts/instagram/instagram_format_job.py",
        "keyword_filter": "scripts/instagram/instagram_keyword_filter_job.py",
        "postgres_import": "scripts/dashboard/import_meili_to_postgres.py",
        "has_enrich": False,
    },
    "tiktok": {
        "name": "TikTok",
        "crawl_search": "scripts/tiktok/tiktok_search_runner.py",
        "crawl_detail": "scripts/tiktok/tiktok_video_runner.py",
        "format_job": None,  # Not yet implemented
        "keyword_filter": "scripts/tiktok/tiktok_keyword_filter_job.py",
        "postgres_import": "scripts/dashboard/import_meili_to_postgres.py",
        "has_enrich": False,
    },
    "youtube": {
        "name": "YouTube",
        "crawl_search": "scripts/youtube/youtube_search_runner.py",
        "crawl_detail": "scripts/youtube/youtube_video_runner.py",
        "format_job": "scripts/youtube/youtube_format_job.py",
        "keyword_filter": None,  # Not yet implemented
        "postgres_import": "scripts/dashboard/import_meili_to_postgres.py",
        "has_enrich": False,
    },
}


class PipelineRunner:
    def __init__(self, platform: str, args: argparse.Namespace):
        self.platform = platform
        self.config = PLATFORMS[platform]
        self.args = args
        self.start_time = datetime.now()
        self.stats = {
            "success": [],
            "failed": [],
            "skipped": [],
        }

    def log(self, message: str, level: str = "INFO"):
        timestamp = datetime.now().strftime("%H:%M:%S")
        prefix = {
            "INFO": "ℹ️",
            "SUCCESS": "✅",
            "ERROR": "❌",
            "SKIP": "⏭️",
            "RUNNING": "🔄",
        }.get(level, "•")
        print(f"[{timestamp}] {prefix} {message}")

    def run_command(self, script_path: str, stage_name: str) -> bool:
        """Run a Python script and return success status"""
        full_path = PROJECT_ROOT / script_path

        if not full_path.exists():
            self.log(f"{stage_name}: Script not found - {script_path}", "SKIP")
            self.stats["skipped"].append(stage_name)
            return True

        self.log(f"{stage_name}: Starting...", "RUNNING")

        if self.args.dry_run:
            self.log(f"{stage_name}: [DRY RUN] python3 {script_path}", "INFO")
            self.stats["success"].append(stage_name)
            return True

        try:
            result = subprocess.run(
                ["python3", str(full_path)],
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
                timeout=3600,  # 1 hour timeout
            )

            if result.returncode == 0:
                self.log(f"{stage_name}: Completed successfully", "SUCCESS")
                self.stats["success"].append(stage_name)
                return True
            else:
                self.log(f"{stage_name}: Failed with exit code {result.returncode}", "ERROR")
                if result.stderr:
                    print(f"    Error output: {result.stderr[:500]}")
                self.stats["failed"].append(stage_name)
                return False

        except subprocess.TimeoutExpired:
            self.log(f"{stage_name}: Timed out after 1 hour", "ERROR")
            self.stats["failed"].append(stage_name)
            return False
        except Exception as exc:
            self.log(f"{stage_name}: Exception - {exc}", "ERROR")
            self.stats["failed"].append(stage_name)
            return False

    def run_node_command(self, script_path: str, stage_name: str) -> bool:
        """Run a Node.js script"""
        full_path = PROJECT_ROOT / script_path

        if not full_path.exists():
            self.log(f"{stage_name}: Script not found - {script_path}", "SKIP")
            self.stats["skipped"].append(stage_name)
            return True

        self.log(f"{stage_name}: Starting...", "RUNNING")

        if self.args.dry_run:
            self.log(f"{stage_name}: [DRY RUN] node {script_path}", "INFO")
            self.stats["success"].append(stage_name)
            return True

        try:
            result = subprocess.run(
                ["node", str(full_path)],
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
                timeout=3600,
            )

            if result.returncode == 0:
                self.log(f"{stage_name}: Completed successfully", "SUCCESS")
                self.stats["success"].append(stage_name)
                return True
            else:
                self.log(f"{stage_name}: Failed with exit code {result.returncode}", "ERROR")
                self.stats["failed"].append(stage_name)
                return False

        except Exception as exc:
            self.log(f"{stage_name}: Exception - {exc}", "ERROR")
            self.stats["failed"].append(stage_name)
            return False

    def run_pipeline(self) -> bool:
        """Run the complete pipeline for this platform"""
        self.log(f"Starting pipeline for {self.config['name']}", "INFO")
        self.log("=" * 60, "INFO")

        # Stage 1: Crawl Search
        if not self.args.skip_crawl and self.config["crawl_search"]:
            if not self.run_command(self.config["crawl_search"], "Crawl Search"):
                if not self.args.continue_on_error:
                    return False

        # Stage 2: Crawl Detail
        if not self.args.skip_crawl and self.config["crawl_detail"]:
            if not self.run_command(self.config["crawl_detail"], "Crawl Detail"):
                if not self.args.continue_on_error:
                    return False

        # Exit if only crawl
        if self.args.only_crawl:
            self.log("Stopping after crawl stage (--only-crawl)", "INFO")
            return True

        # Stage 3: Format Job
        if not self.args.skip_format and self.config["format_job"]:
            if not self.run_command(self.config["format_job"], "Format Job"):
                if not self.args.continue_on_error:
                    return False

        # Stage 4: Keyword Filter
        if not self.args.skip_filter and self.config["keyword_filter"]:
            if not self.run_command(self.config["keyword_filter"], "Keyword Filter"):
                if not self.args.continue_on_error:
                    return False

        # Stage 5: PostgreSQL Import
        if not self.args.skip_sync and self.config["postgres_import"]:
            if not self.run_command(self.config["postgres_import"], "PostgreSQL Import"):
                if not self.args.continue_on_error:
                    return False

        # Stage 6: OpenAI Enrichment (optional)
        if not self.args.skip_enrich and self.config["has_enrich"]:
            if not self.run_node_command(
                "scripts/dashboard/enrich_meili_postgres_openai.mjs",
                "OpenAI Enrichment"
            ):
                if not self.args.continue_on_error:
                    return False

        return True

    def print_summary(self):
        """Print pipeline execution summary"""
        duration = (datetime.now() - self.start_time).total_seconds()

        self.log("=" * 60, "INFO")
        self.log(f"Pipeline Summary for {self.config['name']}", "INFO")
        self.log(f"Duration: {duration:.1f}s ({duration/60:.1f} min)", "INFO")

        if self.stats["success"]:
            self.log(f"Success ({len(self.stats['success'])}): {', '.join(self.stats['success'])}", "SUCCESS")

        if self.stats["skipped"]:
            self.log(f"Skipped ({len(self.stats['skipped'])}): {', '.join(self.stats['skipped'])}", "SKIP")

        if self.stats["failed"]:
            self.log(f"Failed ({len(self.stats['failed'])}): {', '.join(self.stats['failed'])}", "ERROR")
            return False

        self.log("All stages completed successfully! 🎉", "SUCCESS")
        return True


def main():
    parser = argparse.ArgumentParser(
        description="Run complete pipeline from crawl to database import",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument(
        "platform",
        choices=list(PLATFORMS.keys()) + ["all"],
        help="Platform to run pipeline for"
    )

    parser.add_argument("--skip-crawl", action="store_true", help="Skip crawl stage")
    parser.add_argument("--skip-format", action="store_true", help="Skip format job")
    parser.add_argument("--skip-filter", action="store_true", help="Skip keyword filter")
    parser.add_argument("--skip-sync", action="store_true", help="Skip PostgreSQL import")
    parser.add_argument("--skip-enrich", action="store_true", help="Skip OpenAI enrichment")
    parser.add_argument("--only-crawl", action="store_true", help="Only run crawl stage")
    parser.add_argument("--continue-on-error", action="store_true", help="Continue even if a stage fails")
    parser.add_argument("--dry-run", action="store_true", help="Print commands without running")

    args = parser.parse_args()

    # Run for all platforms
    if args.platform == "all":
        overall_start = datetime.now()
        results = {}

        for platform in PLATFORMS.keys():
            print("\n")
            print("=" * 70)
            print(f"PLATFORM: {PLATFORMS[platform]['name'].upper()}")
            print("=" * 70)

            runner = PipelineRunner(platform, args)
            success = runner.run_pipeline()
            runner.print_summary()
            results[platform] = success

            if not success and not args.continue_on_error:
                print(f"\n❌ Stopping at {platform} due to errors")
                return 1

            # Brief pause between platforms
            if platform != list(PLATFORMS.keys())[-1]:
                print("\nWaiting 5 seconds before next platform...")
                time.sleep(5)

        # Overall summary
        overall_duration = (datetime.now() - overall_start).total_seconds()
        print("\n")
        print("=" * 70)
        print("OVERALL SUMMARY")
        print("=" * 70)
        print(f"Total duration: {overall_duration/60:.1f} minutes")
        print(f"\nResults:")
        for platform, success in results.items():
            status = "✅ SUCCESS" if success else "❌ FAILED"
            print(f"  {PLATFORMS[platform]['name']:12} {status}")

        failed = [p for p, s in results.items() if not s]
        if failed:
            print(f"\n❌ {len(failed)} platform(s) failed")
            return 1

        print("\n✅ All platforms completed successfully! 🎉")
        return 0

    # Run for single platform
    runner = PipelineRunner(args.platform, args)
    success = runner.run_pipeline()
    runner.print_summary()

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
