#!/usr/bin/env python3
"""
Test Location Configuration - Verify config loading and display settings
"""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_FILE = PROJECT_ROOT / "data" / "grabfood" / "config" / "location_config.json"


def main() -> int:
    print("=" * 60)
    print("GrabFood Location Configuration Test")
    print("=" * 60)

    # Check if config file exists
    if not CONFIG_FILE.exists():
        print(f"\n❌ Config file not found: {CONFIG_FILE}")
        print("\nPlease create the configuration file first.")
        return 1

    # Load configuration
    try:
        config = json.loads(CONFIG_FILE.read_text(encoding='utf-8'))
        print(f"\n✅ Config file loaded: {CONFIG_FILE}")
    except Exception as e:
        print(f"\n❌ Error loading config: {e}")
        return 1

    # Display default location
    print("\n" + "=" * 60)
    print("DEFAULT LOCATION")
    print("=" * 60)
    default_loc = config.get('default_location', {})
    print(f"Address:    {default_loc.get('address', 'N/A')}")
    print(f"Latitude:   {default_loc.get('latitude', 'N/A')}")
    print(f"Longitude:  {default_loc.get('longitude', 'N/A')}")

    # Display all locations
    print("\n" + "=" * 60)
    print("CONFIGURED LOCATIONS")
    print("=" * 60)
    locations = config.get('locations', [])

    if not locations:
        print("⚠️  No locations configured")
    else:
        enabled_count = sum(1 for loc in locations if loc.get('enabled', False))
        print(f"Total: {len(locations)} | Enabled: {enabled_count}\n")

        for idx, loc in enumerate(locations, 1):
            status = "✅ ENABLED" if loc.get('enabled', False) else "❌ DISABLED"
            print(f"{idx}. {loc.get('name', 'N/A')} - {status}")
            print(f"   ID:       {loc.get('id', 'N/A')}")
            print(f"   Address:  {loc.get('address', 'N/A')}")
            print(f"   Coords:   {loc.get('latitude', 'N/A')}, {loc.get('longitude', 'N/A')}")
            print()

    # Display search keywords
    print("=" * 60)
    print("SEARCH KEYWORDS")
    print("=" * 60)
    keywords = config.get('search_keywords', [])
    if keywords:
        for idx, keyword in enumerate(keywords, 1):
            print(f"{idx}. {keyword}")
    else:
        print("⚠️  No keywords configured")

    # Display crawler settings
    print("\n" + "=" * 60)
    print("CRAWLER SETTINGS")
    print("=" * 60)
    settings = config.get('crawler_settings', {})
    print(f"Max restaurants per search: {settings.get('max_restaurants_per_search', 'N/A')}")
    print(f"Scroll count:               {settings.get('scroll_count', 'N/A')}")
    print(f"Delay between requests:     {settings.get('delay_between_requests', 'N/A')}s")
    print(f"Headless mode:              {settings.get('headless', 'N/A')}")

    # Summary
    print("\n" + "=" * 60)
    print("CRAWL PLAN")
    print("=" * 60)
    enabled_locations = [loc for loc in locations if loc.get('enabled', False)]

    if not enabled_locations:
        print("⚠️  No enabled locations - will use default location")
        enabled_locations = [{
            'name': default_loc.get('address', 'Default'),
            'id': 'default'
        }]

    total_searches = len(enabled_locations) * len(keywords)
    print(f"Enabled locations: {len(enabled_locations)}")
    print(f"Search keywords:   {len(keywords)}")
    print(f"Total searches:    {total_searches}")
    print()
    print("Crawl sequence:")
    for loc in enabled_locations:
        for keyword in keywords:
            print(f"  - {loc.get('name', 'N/A')} × \"{keyword}\"")

    print("\n" + "=" * 60)
    print("✅ Configuration test passed!")
    print("=" * 60)
    print("\nReady to crawl! Run:")
    print("  python3 scripts/grabfood/grabfood_search_runner.py")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
