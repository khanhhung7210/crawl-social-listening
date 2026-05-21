#!/usr/bin/env python3
"""
GrabFood MongoDB Sync - Sync filtered data to MongoDB
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from pymongo import MongoClient, ASCENDING
except ImportError:
    print("❌ pymongo not installed")
    print("Install: pip3 install pymongo")
    sys.exit(1)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from social_listening.film_paths import platform_processed_dir
from social_listening.mongodb_sync import build_mongo_client

FILTERED_FILE = platform_processed_dir("grabfood") / "grabfood_filtered.json"


def main() -> int:
    print("[grabfood] 💾 Syncing GrabFood data to MongoDB...")

    if not FILTERED_FILE.exists():
        print(f"[grabfood] ❌ Filtered file not found: {FILTERED_FILE}")
        return 1

    # Load filtered data
    filtered_data = json.loads(FILTERED_FILE.read_text(encoding='utf-8'))
    print(f"[grabfood] 📂 Loaded {len(filtered_data)} filtered entries")

    # Connect to MongoDB
    client = build_mongo_client()
    db = client['CRM']

    # Collections
    restaurants_col = db['grabfood_restaurants']
    dishes_col = db['grabfood_dishes']
    ratings_col = db['grabfood_ratings']

    # Ensure indexes
    ensure_indexes(restaurants_col, dishes_col, ratings_col)

    # Sync data
    restaurants_synced = 0
    dishes_synced = 0
    ratings_synced = 0

    for entry in filtered_data:
        try:
            # Sync restaurant
            restaurant_doc = {
                "restaurant_id": entry['id'],
                "platform": "grabfood",
                "restaurant_name": entry['restaurant_name'],
                "restaurant_name_normalized": entry['restaurant_name_normalized'],
                "branch": entry.get('branch', ''),
                "rating": entry['rating'],
                "review_count": entry['review_count'],
                "review_count_raw": entry.get('review_count_raw', ''),
                "url": entry.get("url", ""),
                "delivery_time": entry.get("delivery_time", ""),
                "distance": entry.get("distance", ""),
                "promo": entry.get("promo", ""),
                "crawled_at": entry['crawled_at'],
                "formatted_at": entry.get('formatted_at'),
                "updated_at": datetime.now(timezone.utc)
            }

            restaurants_col.update_one(
                {"restaurant_id": entry['id']},
                {"$set": restaurant_doc},
                upsert=True
            )
            restaurants_synced += 1

            # Sync rating snapshot (time series)
            rating_doc = {
                "restaurant_id": entry['id'],
                "platform": "grabfood",
                "rating": entry['rating'],
                "review_count": entry['review_count'],
                "recorded_at": datetime.now(timezone.utc)
            }
            ratings_col.insert_one(rating_doc)
            ratings_synced += 1

            # Sync dishes
            for dish in entry.get('dishes', []):
                dish_doc = {
                    "restaurant_id": entry['id'],
                    "dish_id": dish['dish_id'],
                    "dish_name": dish['name'],
                    "dish_name_full": dish.get('name_full', dish['name']),
                    "dish_name_secondary": dish.get('name_secondary'),
                    "price_raw": dish.get("price_raw", ""),
                    "description": dish.get("description", ""),
                    "image_url": dish.get("image_url", ""),
                    "order_count_raw": dish.get('order_count_raw', '0'),
                    "order_count_min": dish.get('order_count_min', 0),
                    "order_count_display": dish.get('order_count_display', '0'),
                    "keyword_match": dish.get('keyword_match', False),
                    "crawled_at": entry['crawled_at'],
                    "updated_at": datetime.now(timezone.utc)
                }

                dishes_col.update_one(
                    {
                        "restaurant_id": entry['id'],
                        "dish_id": dish['dish_id']
                    },
                    {"$set": dish_doc},
                    upsert=True
                )
                dishes_synced += 1

        except Exception as e:
            print(f"[grabfood] ⚠️  Error syncing entry {entry.get('id')}: {e}")
            continue

    print(f"[grabfood] ✅ Synced:")
    print(f"   • Restaurants: {restaurants_synced}")
    print(f"   • Dishes: {dishes_synced}")
    print(f"   • Rating snapshots: {ratings_synced}")

    client.close()
    return 0


def ensure_indexes(restaurants_col, dishes_col, ratings_col):
    """Create indexes for efficient queries"""

    # Restaurants indexes
    restaurants_col.create_index([("restaurant_id", ASCENDING)], unique=True)
    restaurants_col.create_index([("restaurant_name", ASCENDING)])
    restaurants_col.create_index([("branch", ASCENDING)])
    restaurants_col.create_index([("rating", ASCENDING)])

    # Dishes indexes
    dishes_col.create_index([("restaurant_id", ASCENDING), ("dish_id", ASCENDING)], unique=True)
    dishes_col.create_index([("dish_name", ASCENDING)])
    dishes_col.create_index([("order_count_min", ASCENDING)])

    # Ratings indexes (time series)
    ratings_col.create_index([("restaurant_id", ASCENDING), ("recorded_at", ASCENDING)])
    ratings_col.create_index([("recorded_at", ASCENDING)])

    print("[grabfood] ✓ Indexes ensured")


if __name__ == "__main__":
    sys.exit(main())
