#!/usr/bin/env python3
"""
View crawl state statistics and recent run history.

Usage:
    python scripts/shared/crawl_state_stats.py [platform]

Examples:
    python scripts/shared/crawl_state_stats.py threads
    python scripts/shared/crawl_state_stats.py          # Show all platforms
"""

from __future__ import annotations

import sys
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from social_listening.crawl_state import IncrementalCrawlState


def format_duration(seconds: int | None) -> str:
    """Format duration in seconds to human readable"""
    if seconds is None:
        return "N/A"

    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    else:
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        return f"{hours}h {minutes}m"


def format_datetime(dt_str: str | None) -> str:
    """Format datetime string to human readable"""
    if not dt_str:
        return "N/A"

    try:
        dt = datetime.fromisoformat(dt_str)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return dt_str


def show_platform_stats(state: IncrementalCrawlState, platform: str) -> None:
    """Show statistics for a specific platform"""
    print(f"\n{'=' * 80}")
    print(f"Platform: {platform.upper()}")
    print(f"{'=' * 80}")

    # Summary stats
    summary = state.get_stats_summary(platform)
    if not summary or summary.get("total_urls", 0) == 0:
        print("No data found for this platform.")
        return

    print(f"\n📊 Summary:")
    print(f"  Total URLs crawled: {summary.get('total_urls', 0):,}")
    print(f"  Unique keywords: {summary.get('unique_keywords', 0)}")
    print(f"  URLs with timestamp: {summary.get('urls_with_timestamp', 0):,}")
    print(f"  First crawl: {format_datetime(summary.get('first_crawl'))}")
    print(f"  Last crawl: {format_datetime(summary.get('last_crawl'))}")

    # Recent runs
    runs = state.get_run_stats(platform, limit=10)
    if runs:
        print(f"\n📅 Recent Runs (last {len(runs)}):")
        print(f"  {'Type':<12} {'Started':<20} {'Duration':<12} {'Discovered':<12} {'Crawled':<10} {'Skipped':<10}")
        print(f"  {'-' * 78}")

        for run in runs:
            run_type = run.get("run_type", "N/A")
            started = format_datetime(run.get("started_at"))
            duration = format_duration(run.get("duration_seconds"))
            discovered = run.get("urls_discovered", 0)
            crawled = run.get("urls_crawled", 0)
            skipped = run.get("urls_skipped", 0)
            completed = run.get("completed_at")

            status = "✓" if completed else "⏳"
            print(f"  {status} {run_type:<10} {started:<20} {duration:<12} {discovered:<12} {crawled:<10} {skipped:<10}")


def show_all_platforms(state: IncrementalCrawlState) -> None:
    """Show statistics for all platforms"""
    cursor = state.conn.execute("""
        SELECT
            platform,
            COUNT(*) as url_count,
            COUNT(DISTINCT keyword) as keyword_count,
            MAX(last_seen_at) as last_seen
        FROM crawled_urls
        GROUP BY platform
        ORDER BY url_count DESC
    """)

    platforms = list(cursor.fetchall())

    if not platforms:
        print("\n⚠️  No crawl data found. Run some crawlers first!")
        return

    print(f"\n{'=' * 80}")
    print(f"All Platforms Overview")
    print(f"{'=' * 80}\n")

    print(f"{'Platform':<20} {'URLs':<12} {'Keywords':<12} {'Last Seen':<20}")
    print(f"{'-' * 78}")

    for row in platforms:
        platform = row[0]
        url_count = row[1]
        keyword_count = row[2]
        last_seen = format_datetime(row[3])

        print(f"{platform:<20} {url_count:<12,} {keyword_count:<12} {last_seen:<20}")

    print(f"\nTotal platforms: {len(platforms)}")


def main() -> int:
    platform_arg = sys.argv[1] if len(sys.argv) > 1 else None

    with IncrementalCrawlState() as state:
        if platform_arg:
            show_platform_stats(state, platform_arg)
        else:
            show_all_platforms(state)

            # Prompt to view specific platform
            print("\n💡 Tip: Run with platform name for detailed stats:")
            print("   python scripts/shared/crawl_state_stats.py threads")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted by user")
        sys.exit(1)
    except Exception as exc:
        print(f"\n❌ Error: {exc}")
        sys.exit(1)
