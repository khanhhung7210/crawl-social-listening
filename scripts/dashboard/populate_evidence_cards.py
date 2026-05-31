#!/usr/bin/env python3
"""
Populate evidence_cards từ mentions và reviews
Evidence cards = proof points để support insights trong dashboard
"""

import subprocess
import json
from datetime import datetime

def psql_exec(query: str, database: str = "meili_dashboard"):
    """Execute psql command"""
    cmd = f'PGDATABASE={database} psql -c "{query}"'
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error: {result.stderr}")
    return result.returncode == 0

def get_brand_id():
    """Get the brand_id for Meili"""
    cmd = """PGDATABASE=meili_dashboard psql -t -A -c "SELECT brand_id FROM meili_dashboard.brands WHERE brand_slug = 'meili-mi-bo-dai-loan' LIMIT 1" """
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    return None

def populate_evidence_from_mentions(brand_id: str):
    """Populate evidence cards from mentions with enrichments"""
    print("📊 Populating evidence cards from mentions...")

    query = f"""
    INSERT INTO meili_dashboard.evidence_cards
    (brand_id, branch_id, source_record_type, source_record_id, platform, evidence_date,
     sentiment_label, confidence_score, metric_label, evidence_quote, source_url, tags)
    SELECT
        m.brand_id,
        m.branch_id,
        'mention' as source_record_type,
        m.mention_id as source_record_id,
        m.platform,
        m.content_created_at as evidence_date,
        COALESCE(e.sentiment_label, 'neutral') as sentiment_label,
        COALESCE(e.sentiment_score, 50) as confidence_score,
        CASE
            WHEN e.topic_label IS NOT NULL THEN e.topic_label || ' signal'
            ELSE 'social mention'
        END as metric_label,
        SUBSTRING(m.content_text, 1, 500) as evidence_quote,
        m.post_url as source_url,
        jsonb_build_object(
            'topic', COALESCE(e.topic_label, 'general'),
            'subtopic', COALESCE(e.subtopic_label, ''),
            'issue_type', COALESCE(e.issue_type, ''),
            'needs_response', COALESCE(e.needs_response, false)
        ) as tags
    FROM meili_dashboard.mentions m
    LEFT JOIN meili_dashboard.mention_enrichments e ON m.mention_id = e.mention_id
    WHERE m.brand_id = '{brand_id}'
      AND m.content_text IS NOT NULL
      AND LENGTH(m.content_text) > 20
    LIMIT 200
    ON CONFLICT DO NOTHING
    """

    if psql_exec(query):
        # Count inserted
        count_query = f"SELECT COUNT(*) FROM meili_dashboard.evidence_cards WHERE brand_id = '{brand_id}' AND source_record_type = 'mention'"
        result = subprocess.run(
            f'PGDATABASE=meili_dashboard psql -t -A -c "{count_query}"',
            shell=True, capture_output=True, text=True
        )
        count = result.stdout.strip() if result.returncode == 0 else "?"
        print(f"  ✅ Inserted evidence from mentions: {count} cards")
    else:
        print(f"  ❌ Failed to insert evidence from mentions")

def populate_evidence_from_reviews(brand_id: str):
    """Populate evidence cards from reviews with enrichments"""
    print("📊 Populating evidence cards from reviews...")

    query = f"""
    INSERT INTO meili_dashboard.evidence_cards
    (brand_id, branch_id, source_record_type, source_record_id, platform, evidence_date,
     sentiment_label, confidence_score, metric_label, evidence_quote, source_url, tags)
    SELECT
        r.brand_id,
        r.branch_id,
        'review' as source_record_type,
        r.review_id as source_record_id,
        r.platform,
        r.review_created_at as evidence_date,
        COALESCE(e.sentiment_label, 'neutral') as sentiment_label,
        COALESCE(e.sentiment_score, 50) as confidence_score,
        CASE
            WHEN r.rating IS NOT NULL THEN r.rating::text || ' stars'
            ELSE 'review'
        END as metric_label,
        SUBSTRING(r.review_text, 1, 500) as evidence_quote,
        r.review_url as source_url,
        jsonb_build_object(
            'rating', COALESCE(r.rating, 0),
            'owner_replied', r.owner_replied,
            'topic', COALESCE(e.topic_label, 'general'),
            'issue_type', COALESCE(e.issue_type, '')
        ) as tags
    FROM meili_dashboard.reviews r
    LEFT JOIN meili_dashboard.review_enrichments e ON r.review_id = e.review_id
    WHERE r.brand_id = '{brand_id}'
      AND r.review_text IS NOT NULL
      AND LENGTH(r.review_text) > 20
    LIMIT 100
    ON CONFLICT DO NOTHING
    """

    if psql_exec(query):
        # Count inserted
        count_query = f"SELECT COUNT(*) FROM meili_dashboard.evidence_cards WHERE brand_id = '{brand_id}' AND source_record_type = 'review'"
        result = subprocess.run(
            f'PGDATABASE=meili_dashboard psql -t -A -c "{count_query}"',
            shell=True, capture_output=True, text=True
        )
        count = result.stdout.strip() if result.returncode == 0 else "?"
        print(f"  ✅ Inserted evidence from reviews: {count} cards")
    else:
        print(f"  ❌ Failed to insert evidence from reviews")

def main():
    print("🚀 Starting evidence cards population...")
    print()

    brand_id = get_brand_id()
    if not brand_id:
        print("❌ Could not find brand ID for Meili")
        return 1

    print(f"✅ Brand ID: {brand_id}")
    print()

    print("=" * 60)
    print("POPULATING EVIDENCE CARDS")
    print("=" * 60)

    populate_evidence_from_mentions(brand_id)
    populate_evidence_from_reviews(brand_id)

    print()
    print("=" * 60)
    print("✅ EVIDENCE CARDS POPULATED!")
    print("=" * 60)

    # Show summary
    summary_query = f"""
    SELECT
        source_record_type,
        COUNT(*) as count,
        COUNT(CASE WHEN sentiment_label = 'positive' THEN 1 END) as positive,
        COUNT(CASE WHEN sentiment_label = 'negative' THEN 1 END) as negative,
        COUNT(CASE WHEN sentiment_label = 'neutral' THEN 1 END) as neutral
    FROM meili_dashboard.evidence_cards
    WHERE brand_id = '{brand_id}'
    GROUP BY source_record_type
    """
    print("\nSummary:")
    subprocess.run(f'PGDATABASE=meili_dashboard psql -c "{summary_query}"', shell=True)

    return 0

if __name__ == "__main__":
    exit(main())
