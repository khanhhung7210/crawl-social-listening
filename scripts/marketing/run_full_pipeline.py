#!/usr/bin/env python3
"""
Master pipeline runner - Chạy toàn bộ từ crawl đến import DB

Usage:
    python scripts/marketing/run_full_pipeline.py threads
    python scripts/marketing/run_full_pipeline.py facebook
    python scripts/marketing/run_full_pipeline.py instagram
    python scripts/marketing/run_full_pipeline.py tiktok
    python scripts/marketing/run_full_pipeline.py youtube
    python scripts/marketing/run_full_pipeline.py all

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
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

def _project_root() -> Path:
    current = Path(__file__).resolve().parent
    for cand in [current, *current.parents]:
        if (cand / "src" / "social_listening").is_dir():
            return cand
    raise RuntimeError(f"Cannot find project root from {__file__}")


PROJECT_ROOT = _project_root()

# Platform configurations (Galaxy cinema / social — no F&B Meili)
# Step order matches scripts/windows/run_platform_pipeline.ps1
PLATFORMS = {
    "threads": {
        "name": "Threads",
        "steps": [
            {"script": "scripts/marketing/crawl/threads/threads_crawl_runner.py", "stage": "crawl"},
            {"script": "scripts/marketing/crawl/threads/threads_search_filter_job.py", "stage": "crawl"},
            {"script": "scripts/marketing/crawl/threads/threads_replies_runner.py", "stage": "crawl"},
            {"script": "scripts/marketing/crawl/threads/threads_format_job.py", "stage": "format"},
            {"script": "scripts/marketing/crawl/threads/threads_keyword_filter_job.py", "stage": "filter"},
        ],
        "postgres_import": "scripts/shared/import_keyword_mentions.py",
        "import_args": ["--film", "galaxy_cinema"],
    },
    "facebook": {
        "name": "Facebook",
        "steps": [
            {"script": "scripts/marketing/crawl/facebook/facebook_raw_runner.py", "stage": "crawl"},
            {"script": "scripts/marketing/crawl/facebook/facebook_keyword_filter_job.py", "stage": "filter"},
            {"script": "scripts/marketing/crawl/facebook/facebook_format_job.py", "stage": "format"},
        ],
        "postgres_import": "scripts/shared/import_keyword_mentions.py",
        "import_args": ["--film", "galaxy_cinema"],
    },
    "instagram": {
        "name": "Instagram",
        "steps": [
            {"script": "scripts/marketing/crawl/instagram/instagram_search_runner.py", "stage": "crawl"},
            {"script": "scripts/marketing/crawl/instagram/instagram_post_runner.py", "stage": "crawl"},
            {"script": "scripts/marketing/crawl/instagram/instagram_format_job.py", "stage": "format"},
            {"script": "scripts/marketing/crawl/instagram/instagram_keyword_filter_job.py", "stage": "filter"},
        ],
        "postgres_import": "scripts/shared/import_keyword_mentions.py",
        "import_args": ["--film", "galaxy_cinema"],
    },
    "tiktok": {
        "name": "TikTok",
        "steps": [
            {"script": "scripts/marketing/crawl/tiktok/tiktok_search_runner.py", "stage": "crawl"},
            {"script": "scripts/marketing/crawl/tiktok/tiktok_search_filter_job.py", "stage": "crawl"},
            {"script": "scripts/marketing/crawl/tiktok/tiktok_video_runner.py", "stage": "crawl"},
            {"script": "scripts/marketing/crawl/tiktok/tiktok_format_job.py", "stage": "format"},
            {"script": "scripts/marketing/crawl/tiktok/tiktok_keyword_filter_job.py", "stage": "filter"},
        ],
        "postgres_import": "scripts/shared/import_keyword_mentions.py",
        "import_args": ["--film", "galaxy_cinema"],
    },
    "youtube": {
        "name": "YouTube",
        "steps": [
            {"script": "scripts/marketing/crawl/youtube/youtube_search_runner.py", "stage": "crawl"},
            {"script": "scripts/marketing/crawl/youtube/youtube_search_filter_job.py", "stage": "crawl"},
            {"script": "scripts/marketing/crawl/youtube/youtube_video_runner.py", "stage": "crawl"},
            {"script": "scripts/marketing/crawl/youtube/youtube_format_job.py", "stage": "format"},
            {"script": "scripts/marketing/crawl/youtube/youtube_keyword_filter_job.py", "stage": "filter"},
        ],
        "postgres_import": "scripts/shared/import_keyword_mentions.py",
        "import_args": ["--film", "galaxy_cinema"],
    },
    "google_maps": {
        "name": "Google Maps",
        "steps": [
            {
                "script": "scripts/marketing/crawl/reviews/google_maps/google_maps_search_runner.py",
                "stage": "crawl",
            },
            {
                "script": "scripts/marketing/crawl/reviews/google_maps/google_maps_review_runner.py",
                "stage": "crawl",
            },
            {
                "script": "scripts/marketing/crawl/reviews/google_maps/google_maps_format_job.py",
                "stage": "format",
            },
            {
                "script": "scripts/marketing/crawl/reviews/google_maps/google_maps_keyword_filter_job.py",
                "stage": "filter",
            },
        ],
        "postgres_import": "scripts/shared/import_keyword_mentions.py",
        "import_args": ["--film", "galaxy_cinema"],
    },
}

DEFAULT_PLATFORMS = [
    "threads",
    "facebook",
    "instagram",
    "tiktok",
    "youtube",
    "google_maps",
]


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
            "INFO": "[i]",
            "SUCCESS": "[OK]",
            "ERROR": "[ERR]",
            "SKIP": "[SKIP]",
            "RUNNING": "[..]",
        }.get(level, "*")
        print(f"[{timestamp}] {prefix} {message}")

    def run_command(
        self,
        script_path: str,
        stage_name: str,
        extra_args: list[str] | None = None,
    ) -> bool:
        """Run a Python script and return success status"""
        full_path = PROJECT_ROOT / script_path

        if not full_path.exists():
            self.log(f"{stage_name}: Script not found - {script_path}", "SKIP")
            self.stats["skipped"].append(stage_name)
            return True

        self.log(f"{stage_name}: Starting...", "RUNNING")

        python_bin = sys.executable or "python3"
        cmd = [python_bin, str(full_path)]
        if extra_args:
            cmd.extend(extra_args)

        if self.args.dry_run:
            self.log(f"{stage_name}: [DRY RUN] {' '.join(cmd)}", "INFO")
            self.stats["success"].append(stage_name)
            return True

        try:
            result = subprocess.run(
                cmd,
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
                timeout=10800,  # 3 hour timeout (detail crawl needs more than 1h)
                env={
                    **os.environ,
                    "PYTHONPATH": str(PROJECT_ROOT / "src"),
                    # Windows console defaults to cp1252; Vietnamese/emoji prints crash otherwise
                    "PYTHONUTF8": "1",
                    "PYTHONIOENCODING": "utf-8",
                },
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
            self.log(f"{stage_name}: Timed out after 3 hours", "ERROR")
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
                timeout=10800,
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

    def _should_skip_stage(self, stage: str) -> bool:
        if self.args.only_crawl and stage in ("format", "filter"):
            return True
        if stage == "crawl" and self.args.skip_crawl:
            return True
        if stage == "format" and self.args.skip_format:
            return True
        if stage == "filter" and self.args.skip_filter:
            return True
        return False

    def run_pipeline(self) -> bool:
        """Run the complete pipeline for this platform"""
        self.log(f"Starting pipeline for {self.config['name']}", "INFO")
        self.log("=" * 60, "INFO")

        for step in self.config.get("steps") or []:
            stage = str(step.get("stage") or "crawl")
            script = str(step.get("script") or "").strip()
            if not script:
                continue
            if self._should_skip_stage(stage):
                self.log(f"Skipping {script} ({stage})", "SKIP")
                self.stats["skipped"].append(script)
                continue
            label = f"{stage.title()} — {Path(script).name}"
            extra_args = list(step.get("extra_args") or [])
            if script.endswith("facebook_raw_runner.py") and (
                str(os.getenv("FACEBOOK_FORCE_RECrawl", "")).strip().lower() in {"1", "true", "yes", "on"}
            ):
                extra_args.append("--force")
            if not self.run_command(script, label, extra_args=extra_args or None):
                if not self.args.continue_on_error:
                    return False

        if self.args.only_crawl:
            self.log("Stopping after crawl stage (--only-crawl)", "INFO")
            return True

        if not self.args.skip_sync and self.config.get("postgres_import"):
            import_args = list(self.config.get("import_args") or [])
            if not self.run_command(
                self.config["postgres_import"],
                "PostgreSQL Import",
                extra_args=import_args,
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

        self.log("All stages completed successfully!", "SUCCESS")
        return True


def main():
    # Windows: force UTF-8 stdio early (Vietnamese keywords / paths)
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

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

        for platform in DEFAULT_PLATFORMS:
            print("\n")
            print("=" * 70)
            print(f"PLATFORM: {PLATFORMS[platform]['name'].upper()}")
            print("=" * 70)

            runner = PipelineRunner(platform, args)
            success = runner.run_pipeline()
            runner.print_summary()
            results[platform] = success

            if not success and not args.continue_on_error:
                print(f"\n[ERR] Stopping at {platform} due to errors")
                return 1

            # Brief pause between platforms
            if platform != DEFAULT_PLATFORMS[-1]:
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
            status = "[OK] SUCCESS" if success else "[ERR] FAILED"
            print(f"  {PLATFORMS[platform]['name']:12} {status}")

        failed = [p for p, s in results.items() if not s]
        if failed:
            print(f"\n[ERR] {len(failed)} platform(s) failed")
            return 1

        print("\n[OK] All platforms completed successfully!")
        return 0

    # Run for single platform
    runner = PipelineRunner(args.platform, args)
    success = runner.run_pipeline()
    runner.print_summary()

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
