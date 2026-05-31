#!/usr/bin/env python3
"""
Generate FEED TABLES - 8-column array format matching mockup HTML exactly
Feed format: [signal_name, type, severity, metric, source, owner, guardrail, cta]
"""

import sys
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

try:
    import psycopg2
except ImportError:
    import subprocess
    subprocess.run([sys.executable, "-m", "pip", "install", "psycopg2-binary"], check=True)
    import psycopg2

def get_db_connection():
    return psycopg2.connect(host="localhost", database="meili_dashboard", user="khangnhq", password="")

def get_all_data(cursor):
    """Get all data"""
    query = """
        SELECT
            m.content_text,
            e.sentiment_label,
            m.platform,
            m.content_created_at,
            m.content_type,
            b.branch_name,
            m.relevance_type,
            m.author_name,
            (m.raw_payload->>'rating')::float AS star_rating,
            m.mention_id
        FROM meili_dashboard.mentions m
        LEFT JOIN meili_dashboard.mention_enrichments e ON m.mention_id = e.mention_id
        LEFT JOIN meili_dashboard.branches b ON m.branch_id = b.branch_id
        WHERE m.content_created_at >= CURRENT_DATE - INTERVAL '90 days'
        ORDER BY m.content_created_at DESC
    """
    cursor.execute(query)
    return cursor.fetchall()

def generate_overview_feed(data):
    """Overview feed - matches mockup HTML format"""
    feed = []

    negative_count = sum(1 for r in data if r[1] == 'negative' and r[6] in ('brand', 'relevant'))
    low_rating_count = sum(1 for r in data if r[8] and r[8] <= 2 and r[6] in ('brand', 'relevant'))
    positive_count = sum(1 for r in data if r[1] == 'positive' and r[6] in ('brand', 'relevant'))
    relevant_count = sum(1 for r in data if r[6] == 'relevant')

    if negative_count >= 10:
        feed.append(["Delivery negative spike", "Pain", "High", f"{negative_count} mentions", "GrabFood + ShopeeFood", "Ops", "Fix First", "Create Fix Plan"])
    
    if low_rating_count > 0:
        feed.append(["Lost customer: mắc quá", "Lost Signal", "Medium", f"{low_rating_count} mentions", "Facebook + Review", "Marketing", "Monitor First", "Value Proof"])
    
    if relevant_count > 20:
        feed.append(["Lunch set demand", "Demand", "Medium", f"{relevant_count} signals", "Facebook + Delivery app", "Marketing", "Ready for Campaign", "Create Campaign"])
    
    if positive_count >= 20:
        feed.append(["Cheese / handmade proof", "Positive", "Low", f"{positive_count} mentions", "TikTok + Google Review", "Marketing", "Safe to Amplify", "Boost Proof"])

    return feed

def generate_listen_feed(data):
    """Listen feed - matches mockup HTML format"""
    feed = []

    negative_count = sum(1 for r in data if r[1] == 'negative' and r[6] in ('brand', 'relevant'))
    low_rating_count = sum(1 for r in data if r[8] and r[8] <= 3 and r[6] in ('brand', 'relevant'))
    positive_count = sum(1 for r in data if r[1] == 'positive' and r[6] in ('brand', 'relevant'))

    if low_rating_count > 0:
        feed.append(["Mắc quá / không đáng tiền", "Lost Signal", "Medium", f"{low_rating_count} mentions", "Facebook + Review", "Marketing", "Monitor First", "Value Proof"])
    
    if negative_count > 0:
        feed.append(["Delivery nguội/mềm", "Pain", "High", f"{negative_count} mentions", "GrabFood + ShopeeFood", "Ops", "Fix First", "Fix Plan"])
    
    relevant_count = sum(1 for r in data if r[6] == 'relevant')
    if relevant_count > 20:
        feed.append(["Lunch set demand", "Demand", "Medium", f"{relevant_count} mentions", "Facebook + Delivery app", "Marketing", "Ready for Campaign", "Create Campaign"])
    
    if positive_count > 0:
        feed.append(["Cheese / handmade positive", "Positive", "Low", f"{positive_count} mentions", "TikTok + Google Review", "Marketing", "Safe to Amplify", "Boost Proof"])

    return feed

def generate_brand_health_feed(data):
    """Brand Health feed - matches mockup HTML format"""
    feed = []

    negative_count = sum(1 for r in data if r[1] == 'negative' and r[6] in ('brand', 'relevant'))
    low_rating = sum(1 for r in data if r[8] and r[8] <= 3)
    positive_count = sum(1 for r in data if r[1] == 'positive' and r[6] in ('brand', 'relevant'))

    if negative_count > 0:
        feed.append(["Delivery weak attribute", "Pain", "High", f"{negative_count} mentions", "Delivery apps", "Ops", "Fix First", "Fix Plan"])
    
    if low_rating > 0:
        feed.append(["Value perception risk", "Risk", "Medium", f"{low_rating} mentions", "Facebook + Review", "Marketing", "Monitor First", "Value Proof"])
    
    if positive_count > 0:
        feed.append(["Taste / cheese strength", "Positive", "Low", f"{positive_count} mentions", "TikTok + Google Review", "Marketing", "Safe to Amplify", "Boost Proof"])
    
    # Proof of value readiness
    feed.append(["Proof of value readiness", "Sales Asset", "Low", "4 outputs ready", "System", "Sales", "Ready", "Generate Audit"])

    return feed

def generate_reputation_feed(data):
    """Reputation feed - matches mockup HTML format"""
    feed = []

    negative_count = sum(1 for r in data if r[1] == 'negative' and r[6] in ('brand', 'relevant'))
    needs_response = sum(1 for r in data if r[1] == 'negative' and r[8] and r[8] <= 2)
    positive_count = sum(1 for r in data if r[1] == 'positive' and r[6] in ('brand', 'relevant'))

    # Crisis/spike monitoring
    if negative_count > 20:
        feed.append(["Price backlash post", "Risk", "High", f"{negative_count} comments / 2h", "Facebook Group", "MKT + CS", "Monitor First", "Open Crisis Monitor"])
    
    if negative_count > 0:
        feed.append(["Delivery negative spike", "Pain", "High", f"{negative_count} mentions", "GrabFood + ShopeeFood", "Ops", "Fix First", "Create Fix Task"])
    
    if needs_response > 0:
        feed.append(["Unanswered high-risk reviews", "CS Task", "High", f"{needs_response} reviews", "Google + Delivery apps", "CS", "Fix First", "Assign Response"])
    
    if positive_count > 0:
        feed.append(["Positive review cluster", "Positive", "Low", f"{positive_count} mentions", "Google Review + TikTok", "Marketing", "Safe to Amplify", "Social Proof"])

    return feed

def main():
    print("=" * 80)
    print("GENERATING FEED TABLES - 8-column array format")
    print("=" * 80)
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    print("\n📥 Loading data...")
    data = get_all_data(cursor)
    print(f"   Loaded {len(data)} rows")
    
    cursor.close()
    conn.close()
    
    # Generate feeds
    feeds = {
        'overview': generate_overview_feed(data),
        'listen': generate_listen_feed(data),
        'brand_health': generate_brand_health_feed(data),
        'reputation': generate_reputation_feed(data)
    }
    
    # Save feeds
    dashboard_dir = PROJECT_ROOT / 'data' / 'dashboard'
    
    print("\n💾 SAVING FEEDS:\n")
    for screen_name, feed_data in feeds.items():
        screen_dir = dashboard_dir / screen_name
        screen_dir.mkdir(parents=True, exist_ok=True)
        
        feed_file = screen_dir / 'feed.json'
        with open(feed_file, 'w', encoding='utf-8') as f:
            json.dump(feed_data, f, indent=2, ensure_ascii=False)
        
        print(f"  ✅ {screen_name}/feed.json ({len(feed_data)} items)")
    
    print(f"\n{'=' * 80}")
    print("✅ COMPLETE! Feed tables generated with 8-column array format")
    print(f"📁 Output: {dashboard_dir}")
    print("Format: [signal, type, severity, metric, source, owner, guardrail, cta]")
    print("=" * 80)

if __name__ == "__main__":
    main()
