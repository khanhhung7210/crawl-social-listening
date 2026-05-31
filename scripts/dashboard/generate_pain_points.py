#!/usr/bin/env python3
"""
Generate Pain Priority Matrix with specific pain points
Matching mockup structure: [pain_name, impact_score, urgency_score, action]
"""

import sys
import json
from pathlib import Path
from datetime import datetime
from collections import defaultdict

PROJECT_ROOT = Path(__file__).resolve().parents[2]

try:
    import psycopg2
except ImportError:
    import subprocess
    subprocess.run([sys.executable, "-m", "pip", "install", "psycopg2-binary"], check=True)
    import psycopg2

def get_db_connection():
    """Get PostgreSQL connection"""
    return psycopg2.connect(
        host="localhost",
        database="meili_dashboard",
        user="khangnhq",
        password=""
    )

# Define pain point patterns
PAIN_PATTERNS = {
    # Negative pain points
    'delivery_negative': {
        'name': 'Delivery issue',
        'keywords': ['delivery', 'giao', 'ship', 'nguội', 'lâu', 'chậm', 'mất', 'sai'],
        'type': 'pain',
        'action_default': 'Fix'
    },
    'price_backlash': {
        'name': 'Price backlash',
        'keywords': ['mắc', 'đắt', 'expensive', 'giá cao', 'không đáng', 'overpriced'],
        'type': 'pain',
        'action_default': 'Monitor'
    },
    'service_friction': {
        'name': 'Service friction',
        'keywords': ['phục vụ', 'service', 'nhân viên', 'thái độ', 'chờ lâu', 'không nhiệt tình'],
        'type': 'pain',
        'action_default': 'Fix'
    },
    'booking_friction': {
        'name': 'Booking friction',
        'keywords': ['đặt bàn', 'booking', 'reserve', 'không đặt được', 'khó đặt'],
        'type': 'pain',
        'action_default': 'Fix'
    },
    'food_quality': {
        'name': 'Food quality issue',
        'keywords': ['không ngon', 'dở', 'tệ', 'kém', 'chất lượng giảm', 'không tươi'],
        'type': 'pain',
        'action_default': 'Fix'
    },

    # Positive opportunities (should amplify)
    'taste_proof': {
        'name': 'Taste / quality proof',
        'keywords': ['ngon', 'delicious', 'tuyệt', 'amazing', 'chất lượng tốt', 'fresh', 'tươi'],
        'type': 'opportunity',
        'action_default': 'Amplify'
    },
    'ambiance_proof': {
        'name': 'Ambiance / space proof',
        'keywords': ['không gian', 'đẹp', 'view', 'trang trí', 'cozy', 'sang', 'xịn'],
        'type': 'opportunity',
        'action_default': 'Amplify'
    },
    'value_proof': {
        'name': 'Value for money proof',
        'keywords': ['đáng tiền', 'worth it', 'hợp lý', 'ok price', 'good value'],
        'type': 'opportunity',
        'action_default': 'Amplify'
    }
}

def classify_pain_point(text):
    """Classify text into pain point categories"""
    text_lower = text.lower() if text else ''

    matches = []
    for pain_id, pain_def in PAIN_PATTERNS.items():
        keyword_count = sum(1 for kw in pain_def['keywords'] if kw in text_lower)
        if keyword_count > 0:
            matches.append((pain_id, keyword_count, pain_def))

    # Return strongest match
    if matches:
        matches.sort(key=lambda x: x[1], reverse=True)
        return matches[0][0], matches[0][2]

    return None, None

def generate_pain_priority_matrix():
    """Generate Pain Priority Matrix matching mockup structure"""
    print("\n📊 Generating Pain Priority Matrix (mockup format)...")

    conn = get_db_connection()
    cursor = conn.cursor()

    # Get all relevant mentions
    query = """
        SELECT
            m.content_text,
            e.sentiment_label,
            m.platform,
            m.content_created_at,
            m.content_type
        FROM meili_dashboard.mentions m
        LEFT JOIN meili_dashboard.mention_enrichments e ON m.mention_id = e.mention_id
        WHERE m.relevance_type IN ('brand', 'relevant')
            AND m.content_created_at >= CURRENT_DATE - INTERVAL '30 days'
            AND m.content_text IS NOT NULL
        ORDER BY m.content_created_at DESC
        LIMIT 500
    """

    cursor.execute(query)
    rows = cursor.fetchall()

    # Aggregate by pain point
    pain_aggregates = defaultdict(lambda: {
        'count': 0,
        'negative_count': 0,
        'positive_count': 0,
        'recent_count': 0,
        'high_quality_count': 0,
        'examples': []
    })

    for row in rows:
        content_text, sentiment, platform, created_at, content_type = row

        pain_id, pain_def = classify_pain_point(content_text)

        if pain_id:
            pain_aggregates[pain_id]['count'] += 1

            if sentiment == 'negative':
                pain_aggregates[pain_id]['negative_count'] += 1
            elif sentiment == 'positive':
                pain_aggregates[pain_id]['positive_count'] += 1

            # Recent mentions (last 7 days)
            if created_at and (datetime.now().date() - created_at.date()).days <= 7:
                pain_aggregates[pain_id]['recent_count'] += 1

            # High quality sources
            if platform in ['google_maps', 'facebook'] or content_type == 'post':
                pain_aggregates[pain_id]['high_quality_count'] += 1

            # Store examples
            if len(pain_aggregates[pain_id]['examples']) < 3:
                pain_aggregates[pain_id]['examples'].append({
                    'text': content_text[:100],
                    'sentiment': sentiment,
                    'platform': platform
                })

    # Calculate scores for each pain point
    pain_points = []

    for pain_id, agg in pain_aggregates.items():
        pain_def = PAIN_PATTERNS[pain_id]

        # Impact score (0-100)
        # Based on: volume, sentiment ratio, source quality
        volume_score = min(agg['count'] * 5, 50)  # Max 50 from volume

        if pain_def['type'] == 'pain':
            sentiment_score = (agg['negative_count'] / max(agg['count'], 1)) * 30
        else:  # opportunity
            sentiment_score = (agg['positive_count'] / max(agg['count'], 1)) * 30

        quality_score = (agg['high_quality_count'] / max(agg['count'], 1)) * 20

        impact = min(volume_score + sentiment_score + quality_score, 100)

        # Urgency score (0-100)
        # Based on: recency, growth rate
        recency_score = (agg['recent_count'] / max(agg['count'], 1)) * 60

        # Spike detection (simple)
        if agg['recent_count'] > agg['count'] * 0.5:  # More than 50% in last 7 days
            spike_score = 40
        else:
            spike_score = 20

        urgency = min(recency_score + spike_score, 100)

        # Determine action
        if pain_def['type'] == 'pain':
            if impact >= 70 and urgency >= 70:
                action = 'Fix'
            elif impact >= 50 or urgency >= 50:
                action = 'Monitor'
            else:
                action = 'Watch'
        else:  # opportunity
            if impact >= 60:
                action = 'Amplify'
            else:
                action = 'Watch'

        pain_points.append({
            'pain_id': pain_id,
            'name': pain_def['name'],
            'type': pain_def['type'],
            'impact_score': round(impact, 1),
            'urgency_score': round(urgency, 1),
            'action': action,
            'count': agg['count'],
            'negative_count': agg['negative_count'],
            'positive_count': agg['positive_count'],
            'recent_count': agg['recent_count'],
            'examples': agg['examples']
        })

    # Sort by priority (impact * urgency)
    pain_points.sort(key=lambda x: x['impact_score'] * x['urgency_score'], reverse=True)

    # Format for mockup (matrix data)
    matrix_data = []
    for p in pain_points:
        matrix_data.append([
            p['name'],
            p['impact_score'],
            p['urgency_score'],
            p['action']
        ])

    # Analysis
    analysis = []

    # Top pain
    top_pains = [p for p in pain_points if p['type'] == 'pain'][:2]
    if top_pains:
        pain_names = ' và '.join([p['name'] for p in top_pains])
        analysis.append(f"{pain_names} đang nằm ở vùng ưu tiên cao nhất.")

    # Opportunities
    top_opps = [p for p in pain_points if p['type'] == 'opportunity'][:2]
    if top_opps:
        opp_names = ' và '.join([p['name'] for p in top_opps])
        analysis.append(f"{opp_names} là tài sản mạnh - nên amplify thay vì chỉ nhìn vào pain.")

    # Guardrail
    fix_count = len([p for p in pain_points if p['action'] == 'Fix'])
    if fix_count > 0:
        analysis.append(f"Có {fix_count} pain points cần Fix ngay - ưu tiên high impact + high urgency trước.")

    result = {
        'dashboard_name': 'Pain Priority Matrix',
        'generated_at': datetime.now().isoformat(),
        'chart_type': 'matrix',
        'matrix_data': matrix_data,
        'pain_points': pain_points,
        'analysis': analysis,
        'action': {
            'guardrail': 'High impact + high urgency first',
            'owner': 'CEO + Function owners',
            'cta': 'Create Today Action List'
        }
    }

    cursor.close()
    conn.close()

    print(f"   ✅ Generated {len(pain_points)} pain points")
    print(f"   🔴 Pains: {len([p for p in pain_points if p['type'] == 'pain'])}")
    print(f"   🟢 Opportunities: {len([p for p in pain_points if p['type'] == 'opportunity'])}")
    print(f"   ⚠️  Fix required: {fix_count}")

    # Print top 5
    print(f"\n   📊 Top 5 pain points:")
    for i, p in enumerate(pain_points[:5], 1):
        emoji = '🔴' if p['type'] == 'pain' else '🟢'
        print(f"      {i}. {emoji} {p['name']}: Impact {p['impact_score']}, Urgency {p['urgency_score']} → {p['action']}")

    return result

def main():
    """Generate pain priority matrix"""
    print("="*80)
    print("GENERATING PAIN PRIORITY MATRIX (MOCKUP FORMAT)")
    print("="*80)

    output_dir = PROJECT_ROOT / "data" / "dashboard" / "overview"
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        data = generate_pain_priority_matrix()

        # Save file
        output_file = output_dir / "pain_priority_matrix_v2.json"
        output_file.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        print(f"\n💾 Saved to {output_file}")

        print("\n" + "="*80)
        print("✅ DONE!")
        print("="*80)

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
