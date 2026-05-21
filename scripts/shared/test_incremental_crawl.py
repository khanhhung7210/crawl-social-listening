#!/usr/bin/env python3
"""
Test incremental crawl system across all platforms.

Usage:
    # Test single platform
    python scripts/shared/test_incremental_crawl.py threads

    # Test all platforms
    python scripts/shared/test_incremental_crawl.py all

    # Dry run (show what would be tested)
    python scripts/shared/test_incremental_crawl.py threads --dry-run
"""

from __future__ import annotations

import sys
import subprocess
import time
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from social_listening.crawl_state import IncrementalCrawlState


# Platform configurations
PLATFORMS = {
    "threads": {
        "search_runner": "scripts/threads/threads_crawl_runner.py",
        "detail_runner": "scripts/threads/threads_replies_runner.py",
        "expected_speedup": 5.0,  # Expected speedup for incremental run
        "supports_early_stop": True,
    },
    "instagram": {
        "search_runner": "scripts/instagram/instagram_search_runner.py",
        "detail_runner": "scripts/instagram/instagram_post_runner.py",
        "expected_speedup": 4.0,
        "supports_early_stop": True,
    },
    "facebook": {
        "search_runner": "scripts/facebook/facebook_raw_runner.py",
        "detail_runner": None,  # Combined in one runner
        "expected_speedup": 2.0,  # Lower because search can't early-stop
        "supports_early_stop": False,
    },
    # Future platforms
    "tiktok": {
        "search_runner": "scripts/tiktok/tiktok_search_runner.py",
        "detail_runner": "scripts/tiktok/tiktok_video_runner.py",
        "expected_speedup": 5.0,
        "supports_early_stop": True,
        "implemented": False,
    },
    "youtube": {
        "search_runner": "scripts/youtube/youtube_search_runner.py",
        "detail_runner": "scripts/youtube/youtube_video_runner.py",
        "expected_speedup": 4.5,
        "supports_early_stop": True,
        "implemented": False,
    },
}


def run_command(cmd: list[str], desc: str) -> tuple[int, float]:
    """Run a command and return (exit_code, duration_seconds)"""
    print(f"\n{'=' * 80}")
    print(f"▶ {desc}")
    print(f"{'=' * 80}")
    print(f"Command: {' '.join(cmd)}\n")

    start_time = time.time()
    try:
        result = subprocess.run(
            cmd,
            cwd=PROJECT_ROOT,
            capture_output=False,  # Show output in real-time
            text=True,
        )
        duration = time.time() - start_time
        return result.returncode, duration
    except Exception as exc:
        print(f"❌ Error running command: {exc}")
        duration = time.time() - start_time
        return 1, duration


def test_platform(platform_name: str, dry_run: bool = False) -> dict:
    """Test a single platform"""
    config = PLATFORMS.get(platform_name)
    if not config:
        print(f"❌ Unknown platform: {platform_name}")
        return {"success": False, "error": "unknown_platform"}

    if config.get("implemented") is False:
        print(f"⚠️  Platform {platform_name} not yet implemented")
        return {"success": False, "error": "not_implemented"}

    print(f"\n{'#' * 80}")
    print(f"# Testing Platform: {platform_name.upper()}")
    print(f"{'#' * 80}\n")

    with IncrementalCrawlState() as state:
        is_initial = state.is_initial_run(platform_name)
        existing_count = len(state.get_existing_urls(platform_name))

        print(f"Current state:")
        print(f"  - Is initial run: {is_initial}")
        print(f"  - Existing URLs: {existing_count}")
        print(f"  - Supports early stop: {config['supports_early_stop']}")
        print(f"  - Expected speedup: {config['expected_speedup']}x\n")

        if dry_run:
            print("🔍 DRY RUN - Would execute:")
            print(f"   1. python {config['search_runner']}")
            if config['detail_runner']:
                print(f"   2. python {config['detail_runner']}")
            return {"success": True, "dry_run": True}

        # Run search crawler
        search_cmd = ["python", config["search_runner"]]
        search_code, search_duration = run_command(
            search_cmd,
            f"{platform_name.upper()} - Search Crawler"
        )

        if search_code != 0:
            print(f"❌ Search crawler failed with exit code {search_code}")
            return {
                "success": False,
                "search_duration": search_duration,
                "search_failed": True,
            }

        # Run detail crawler if separate
        detail_duration = 0
        if config["detail_runner"]:
            detail_cmd = ["python", config["detail_runner"]]
            detail_code, detail_duration = run_command(
                detail_cmd,
                f"{platform_name.upper()} - Detail Crawler"
            )

            if detail_code != 0:
                print(f"❌ Detail crawler failed with exit code {detail_code}")
                return {
                    "success": False,
                    "search_duration": search_duration,
                    "detail_duration": detail_duration,
                    "detail_failed": True,
                }

        # Get final stats
        stats = state.get_stats_summary(platform_name)
        recent_runs = state.get_run_stats(platform_name, limit=2)

        total_duration = search_duration + detail_duration

        result = {
            "success": True,
            "is_initial": is_initial,
            "search_duration": search_duration,
            "detail_duration": detail_duration,
            "total_duration": total_duration,
            "urls_before": existing_count,
            "urls_after": stats.get("total_urls", 0),
            "urls_added": stats.get("total_urls", 0) - existing_count,
            "recent_runs": recent_runs,
        }

        # Print summary
        print(f"\n{'=' * 80}")
        print(f"✅ {platform_name.upper()} Test Complete")
        print(f"{'=' * 80}")
        print(f"Duration:")
        print(f"  - Search: {format_duration(search_duration)}")
        if detail_duration > 0:
            print(f"  - Detail: {format_duration(detail_duration)}")
        print(f"  - Total: {format_duration(total_duration)}")
        print(f"\nURLs:")
        print(f"  - Before: {existing_count}")
        print(f"  - After: {stats.get('total_urls', 0)}")
        print(f"  - Added: {result['urls_added']}")

        # Performance check
        if not is_initial and len(recent_runs) >= 2:
            prev_duration = recent_runs[1].get("duration_seconds", 0)
            curr_duration = recent_runs[0].get("duration_seconds", 0)

            if prev_duration > 0:
                actual_speedup = prev_duration / curr_duration if curr_duration > 0 else 0
                expected_speedup = config["expected_speedup"]

                print(f"\nPerformance:")
                print(f"  - Previous run: {format_duration(prev_duration)}")
                print(f"  - Current run: {format_duration(curr_duration)}")
                print(f"  - Actual speedup: {actual_speedup:.1f}x")
                print(f"  - Expected speedup: {expected_speedup:.1f}x")

                if actual_speedup >= expected_speedup * 0.7:  # 70% of expected
                    print(f"  ✅ Performance meets expectations!")
                else:
                    print(f"  ⚠️  Performance below expectations (70% threshold)")

        return result


def format_duration(seconds: float) -> str:
    """Format duration in seconds to human readable"""
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}m {secs}s"
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{hours}h {minutes}m"


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python scripts/shared/test_incremental_crawl.py <platform>")
        print("  python scripts/shared/test_incremental_crawl.py all")
        print("\nAvailable platforms:")
        for name, config in PLATFORMS.items():
            status = "✅" if config.get("implemented", True) else "🚧"
            print(f"  {status} {name}")
        return 1

    platform_arg = sys.argv[1].lower()
    dry_run = "--dry-run" in sys.argv

    if platform_arg == "all":
        # Test all implemented platforms
        results = {}
        for platform_name, config in PLATFORMS.items():
            if config.get("implemented", True):
                result = test_platform(platform_name, dry_run)
                results[platform_name] = result
                time.sleep(2)  # Brief pause between platforms

        # Summary
        print(f"\n{'#' * 80}")
        print(f"# Overall Summary")
        print(f"{'#' * 80}\n")

        for platform_name, result in results.items():
            if result.get("dry_run"):
                print(f"🔍 {platform_name}: DRY RUN")
            elif result["success"]:
                duration = result.get("total_duration", 0)
                urls_added = result.get("urls_added", 0)
                print(f"✅ {platform_name}: {format_duration(duration)}, +{urls_added} URLs")
            else:
                error = result.get("error", "unknown")
                print(f"❌ {platform_name}: {error}")

        return 0

    else:
        # Test single platform
        result = test_platform(platform_arg, dry_run)
        return 0 if result["success"] else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\n⚠️  Test interrupted by user")
        sys.exit(1)
    except Exception as exc:
        print(f"\n\n❌ Test failed with error: {exc}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
