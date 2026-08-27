#!/bin/bash
# Crawl Google Maps reviews for ~30 Galaxy Cinema VN locations, then import DB.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../../../.." && pwd)"
cd "$ROOT"
export PYTHONPATH=src PYTHONUTF8=1 PYTHONIOENCODING=utf-8 PYTHONUNBUFFERED=1
export GOOGLE_MAPS_DEBUGGER_ADDRESS="${GOOGLE_MAPS_DEBUGGER_ADDRESS:-127.0.0.1:9227}"
export GOOGLE_MAPS_MAX_PLACE_COUNT="${GOOGLE_MAPS_MAX_PLACE_COUNT:-30}"
export GOOGLE_MAPS_MAX_PLACES_PER_QUERY=1
export GOOGLE_MAPS_REVIEW_SCROLL_ROUNDS="${GOOGLE_MAPS_REVIEW_SCROLL_ROUNDS:-6}"

echo "== search 30 rạp Galaxy =="
python3 scripts/marketing/crawl/reviews/google_maps/google_maps_search_runner.py

echo "== crawl reviews =="
python3 scripts/marketing/crawl/reviews/google_maps/google_maps_review_runner.py

echo "== format + filter + import =="
python3 scripts/marketing/crawl/reviews/google_maps/google_maps_format_job.py
python3 scripts/marketing/crawl/reviews/google_maps/google_maps_keyword_filter_job.py
python3 scripts/shared/import_keyword_mentions.py --file data/google_maps/processed/galaxy_cinema/google_maps_keyword_mentions.json

echo "== done =="
