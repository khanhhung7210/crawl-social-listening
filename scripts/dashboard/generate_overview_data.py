#!/usr/bin/env python3
"""
Generate data for Overview screen dashboards
Based on DASHBOARD_IMPLEMENTATION_MAPPING.md
"""

import sys
import json
from pathlib import Path
from datetime import datetime, timedelta

PROJECT_ROOT = Path(__file__).resolve().parents[2]

try:
    import psycopg2
    from psycopg2 import sql
except ImportError:
    import subprocess
    subprocess.run([sys.executable, "-m", "pip", "install", "psycopg2-binary"], check=True)
    import psycopg2
    from psycopg2 import sql

def get_db_connection():
    """Get PostgreSQL connection"""
    return psycopg2.connect(
        host="localhost",
        database="meili_dashboard",
        user="khangnhq",
        password=""
    )

def generate_pain_priority_matrix():
    """Dashboard 1: Pain Priority Matrix"""
    print("\n📊 Generating Pain Priority Matrix...")

    conn = get_db_connection()
    cursor = conn.cursor()

    # Get negative signals with priority scoring
    query = """
        SELECT
            m.content_text,
            m.platform,
            b.branch_name,
            m.content_created_at,
            -- Severity based on keywords
            CASE
                WHEN m.content_text ILIKE '%food poisoning%' OR m.content_text ILIKE '%ngộ độc%' THEN 100
                WHEN m.content_text ILIKE '%rất dở%' OR m.content_text ILIKE '%terrible%' OR m.content_text ILIKE '%tệ%' THEN 80
                WHEN m.content_text ILIKE '%kém%' OR m.content_text ILIKE '%không ngon%' THEN 60
                ELSE 30
            END as severity,
            -- Urgency from recency
            CASE
                WHEN m.content_created_at >= CURRENT_DATE - INTERVAL '3 days' THEN 100
                WHEN m.content_created_at >= CURRENT_DATE - INTERVAL '7 days' THEN 70
                WHEN m.content_created_at >= CURRENT_DATE - INTERVAL '14 days' THEN 40
                ELSE 20
            END as urgency_score,
            -- Business impact (placeholder)
            60 as business_impact,
            -- Confidence based on source quality
            CASE
                WHEN m.platform IN ('google_maps', 'facebook') THEN 90
                WHEN m.platform = 'tiktok' AND m.content_type = 'post' THEN 70
                ELSE 50
            END as confidence,
            -- Issue category extraction
            CASE
                WHEN m.content_text ILIKE '%mì%' OR m.content_text ILIKE '%noodle%' OR m.content_text ILIKE '%bò%' THEN 'Food Quality'
                WHEN m.content_text ILIKE '%phục vụ%' OR m.content_text ILIKE '%service%' OR m.content_text ILIKE '%nhân viên%' THEN 'Service'
                WHEN m.content_text ILIKE '%delivery%' OR m.content_text ILIKE '%giao%' OR m.content_text ILIKE '%ship%' THEN 'Delivery'
                WHEN m.content_text ILIKE '%giá%' OR m.content_text ILIKE '%mắc%' OR m.content_text ILIKE '%tiền%' THEN 'Pricing'
                WHEN m.content_text ILIKE '%sạch%' OR m.content_text ILIKE '%bẩn%' OR m.content_text ILIKE '%clean%' THEN 'Cleanliness'
                ELSE 'General'
            END as category
        FROM meili_dashboard.mentions m
        LEFT JOIN meili_dashboard.mention_enrichments e ON m.mention_id = e.mention_id
        LEFT JOIN meili_dashboard.branches b ON m.branch_id = b.branch_id
        WHERE e.sentiment_label = 'negative'
            AND m.relevance_type IN ('brand', 'relevant')
            AND m.content_created_at >= CURRENT_DATE - INTERVAL '30 days'
        ORDER BY m.content_created_at DESC
        LIMIT 200
    """

    cursor.execute(query)
    rows = cursor.fetchall()

    pains = []
    for row in rows:
        content_text, platform, branch, content_created_at, severity, urgency, business_impact, confidence, category = row

        # Calculate priority score
        priority_score = round(
            severity * 0.35 +
            business_impact * 0.25 +
            urgency * 0.20 +
            confidence * 0.20,
            2
        )

        # Priority class
        if priority_score >= 75:
            priority_class = 'High'
        elif priority_score >= 50:
            priority_class = 'Medium'
        else:
            priority_class = 'Low'

        # Guardrail
        can_recommend = confidence >= 70

        pains.append({
            'issue': content_text[:150] + '...' if len(content_text) > 150 else content_text,
            'priority_score': priority_score,
            'priority_class': priority_class,
            'severity': severity,
            'urgency': urgency,
            'confidence': confidence,
            'branch': branch or 'Unknown',
            'category': category,
            'platform': platform,
            'date': content_created_at.strftime('%Y-%m-%d') if content_created_at else None,
            'can_recommend_action': can_recommend
        })

    # Sort by priority score
    pains.sort(key=lambda x: x['priority_score'], reverse=True)

    # Group by category for summary
    category_summary = {}
    for pain in pains:
        cat = pain['category']
        if cat not in category_summary:
            category_summary[cat] = {'count': 0, 'avg_priority': 0, 'issues': []}
        category_summary[cat]['count'] += 1
        category_summary[cat]['issues'].append(pain)

    for cat in category_summary:
        avg_priority = sum(p['priority_score'] for p in category_summary[cat]['issues']) / category_summary[cat]['count']
        category_summary[cat]['avg_priority'] = round(avg_priority, 2)

    # Matrix visualization (severity x frequency)
    matrix = {
        'high_severity_high_frequency': [],
        'high_severity_low_frequency': [],
        'low_severity_high_frequency': [],
        'low_severity_low_frequency': []
    }

    # Count frequency by category
    category_freq = {}
    for pain in pains:
        cat = pain['category']
        category_freq[cat] = category_freq.get(cat, 0) + 1

    for pain in pains:
        freq = category_freq[pain['category']]
        sev = pain['severity']

        if sev >= 60 and freq >= 5:
            matrix['high_severity_high_frequency'].append(pain)
        elif sev >= 60 and freq < 5:
            matrix['high_severity_low_frequency'].append(pain)
        elif sev < 60 and freq >= 5:
            matrix['low_severity_high_frequency'].append(pain)
        else:
            matrix['low_severity_low_frequency'].append(pain)

    result = {
        'dashboard_name': 'Pain Priority Matrix',
        'generated_at': datetime.now().isoformat(),
        'total_pains': len(pains),
        'top_10_critical': pains[:10],
        'category_summary': category_summary,
        'matrix_visualization': matrix,
        'all_pains': pains
    }

    cursor.close()
    conn.close()

    print(f"   ✅ Generated {len(pains)} pain points")
    print(f"   📋 Categories: {list(category_summary.keys())}")
    print(f"   ⚠️  High priority: {len([p for p in pains if p['priority_class'] == 'High'])}")

    return result

def generate_category_pulse():
    """Dashboard 5: Category Pulse"""
    print("\n📊 Generating Category Pulse...")

    conn = get_db_connection()
    cursor = conn.cursor()

    query = """
        WITH categorized_signals AS (
            SELECT
                m.mention_id,
                m.content_text,
                e.sentiment_label,
                m.platform,
                m.content_created_at,
                CASE
                    WHEN m.content_text ILIKE '%mì%' OR m.content_text ILIKE '%noodle%' OR m.content_text ILIKE '%bò%' THEN 'Noodles'
                    WHEN m.content_text ILIKE '%phục vụ%' OR m.content_text ILIKE '%service%' OR m.content_text ILIKE '%nhân viên%' THEN 'Service'
                    WHEN m.content_text ILIKE '%delivery%' OR m.content_text ILIKE '%giao%' OR m.content_text ILIKE '%ship%' THEN 'Delivery'
                    WHEN m.content_text ILIKE '%giá%' OR m.content_text ILIKE '%price%' OR m.content_text ILIKE '%tiền%' THEN 'Pricing'
                    WHEN m.content_text ILIKE '%không gian%' OR m.content_text ILIKE '%ambiance%' OR m.content_text ILIKE '%view%' THEN 'Ambiance'
                    ELSE 'General'
                END as category
            FROM meili_dashboard.mentions m
            LEFT JOIN meili_dashboard.mention_enrichments e ON m.mention_id = e.mention_id
            WHERE m.relevance_type IN ('brand', 'relevant')
                AND m.content_created_at >= CURRENT_DATE - INTERVAL '30 days'
        )
        SELECT
            category,
            COUNT(*) as total_signals,
            COUNT(CASE WHEN sentiment_label = 'positive' THEN 1 END) as positive_count,
            COUNT(CASE WHEN sentiment_label = 'negative' THEN 1 END) as negative_count,
            ROUND(
                ((COUNT(CASE WHEN sentiment_label = 'positive' THEN 1 END)::numeric -
                  COUNT(CASE WHEN sentiment_label = 'negative' THEN 1 END)::numeric) /
                 NULLIF(COUNT(*)::numeric, 0)) * 100,
                2
            ) as sentiment_health
        FROM categorized_signals
        GROUP BY category
        HAVING COUNT(*) >= 5  -- Filter out categories with too few signals
        ORDER BY total_signals DESC
    """

    cursor.execute(query)
    rows = cursor.fetchall()

    categories = []
    for row in rows:
        category, total, positive, negative, health = row

        # Quality adjusted health (placeholder for signal quality)
        health_val = float(health) if health is not None else 0
        quality_adjusted = round(health_val * 0.60 + 70 * 0.40, 2)

        # Status
        if quality_adjusted >= 75:
            status = 'Healthy'
        elif quality_adjusted >= 50:
            status = 'Watch'
        else:
            status = 'Critical'

        # Trend (placeholder - would need time series data)
        trend = '→'  # Neutral for now

        categories.append({
            'name': category,
            'health_score': quality_adjusted,
            'sentiment_health': health_val,
            'status': status,
            'trend': trend,
            'total_signals': total,
            'positive_count': positive,
            'negative_count': negative
        })

    result = {
        'dashboard_name': 'Category Pulse',
        'generated_at': datetime.now().isoformat(),
        'categories': categories
    }

    cursor.close()
    conn.close()

    print(f"   ✅ Generated {len(categories)} categories")
    for cat in categories:
        print(f"   📊 {cat['name']}: {cat['health_score']}/100 ({cat['status']})")

    return result

def generate_branch_risk_snapshot():
    """Dashboard 10: Branch Risk Snapshot"""
    print("\n📊 Generating Branch Risk Snapshot...")

    conn = get_db_connection()
    cursor = conn.cursor()

    # Query branch signals and reviews
    query = """
        WITH branch_signals AS (
            SELECT
                b.branch_name,
                COUNT(*) as total_signals,
                COUNT(CASE WHEN e.sentiment_label = 'negative' THEN 1 END) as negative_count,
                COUNT(CASE WHEN e.sentiment_label = 'positive' THEN 1 END) as positive_count
            FROM meili_dashboard.mentions m
            LEFT JOIN meili_dashboard.mention_enrichments e ON m.mention_id = e.mention_id
            LEFT JOIN meili_dashboard.branches b ON m.branch_id = b.branch_id
            WHERE b.branch_name IS NOT NULL
                AND m.relevance_type IN ('brand', 'relevant')
                AND m.content_created_at >= CURRENT_DATE - INTERVAL '30 days'
            GROUP BY b.branch_name
        )
        SELECT
            branch_name as branch,
            total_signals,
            negative_count as complaints,
            positive_count,
            ROUND(
                (negative_count::numeric / NULLIF(total_signals, 0) * 100 * 0.50) +
                (50 * 0.30) +  -- Placeholder for rating score
                (90 * 0.20),   -- Placeholder for source confidence
                2
            ) as risk_score
        FROM branch_signals
        WHERE total_signals >= 3  -- Min sample size
        ORDER BY risk_score DESC
    """

    cursor.execute(query)
    rows = cursor.fetchall()

    branches = []
    for row in rows:
        branch, total, complaints, positive, risk = row

        # Risk class
        if risk >= 75:
            risk_class = 'High'
        elif risk >= 50:
            risk_class = 'Medium'
        else:
            risk_class = 'Low'

        branches.append({
            'branch': branch,
            'risk_score': float(risk),
            'risk_class': risk_class,
            'total_signals': total,
            'complaints': complaints,
            'positive': positive,
            'sample_size_adequate': total >= 10
        })

    result = {
        'dashboard_name': 'Branch Risk Snapshot',
        'generated_at': datetime.now().isoformat(),
        'total_branches': len(branches),
        'top_10_problematic': branches[:10],
        'all_branches': branches
    }

    cursor.close()
    conn.close()

    print(f"   ✅ Generated risk scores for {len(branches)} branches")
    print(f"   ⚠️  High risk branches: {len([b for b in branches if b['risk_class'] == 'High'])}")

    return result

def generate_qualified_signal_summary():
    """Dashboard 7: Qualified Signal Summary"""
    print("\n📊 Generating Qualified Signal Summary...")

    conn = get_db_connection()
    cursor = conn.cursor()

    query = """
        SELECT
            COUNT(*) as total_collected,
            COUNT(CASE WHEN relevance_type IN ('brand', 'relevant') THEN 1 END) as qualified_signals,
            COUNT(CASE WHEN relevance_type = 'brand' THEN 1 END) as brand_signals,
            COUNT(CASE WHEN relevance_type = 'relevant' THEN 1 END) as relevant_signals,
            COUNT(CASE WHEN relevance_type = 'noise' THEN 1 END) as noise_signals,
            -- By platform
            COUNT(CASE WHEN platform = 'google_maps' THEN 1 END) as google_maps_total,
            COUNT(CASE WHEN platform = 'google_maps' AND relevance_type IN ('brand', 'relevant') THEN 1 END) as google_maps_qualified,
            COUNT(CASE WHEN platform = 'facebook' THEN 1 END) as facebook_total,
            COUNT(CASE WHEN platform = 'facebook' AND relevance_type IN ('brand', 'relevant') THEN 1 END) as facebook_qualified,
            COUNT(CASE WHEN platform = 'tiktok' THEN 1 END) as tiktok_total,
            COUNT(CASE WHEN platform = 'tiktok' AND relevance_type IN ('brand', 'relevant') THEN 1 END) as tiktok_qualified,
            COUNT(CASE WHEN platform = 'instagram' THEN 1 END) as instagram_total,
            COUNT(CASE WHEN platform = 'instagram' AND relevance_type IN ('brand', 'relevant') THEN 1 END) as instagram_qualified
        FROM meili_dashboard.mentions
        WHERE content_created_at >= CURRENT_DATE - INTERVAL '30 days'
    """

    cursor.execute(query)
    row = cursor.fetchone()

    total, qualified, brand, relevant, noise, gm_total, gm_qual, fb_total, fb_qual, tt_total, tt_qual, ig_total, ig_qual = row

    qualified_pct = round(qualified / total * 100, 2) if total > 0 else 0

    # Data readiness status
    if qualified_pct >= 40:
        readiness = 'Ready'
    elif qualified_pct >= 20:
        readiness = 'Moderate'
    else:
        readiness = 'Need more data'

    result = {
        'dashboard_name': 'Qualified Signal Summary',
        'generated_at': datetime.now().isoformat(),
        'overview': {
            'total_collected': total,
            'qualified_signals': qualified,
            'qualified_percentage': qualified_pct,
            'noise_filtered': noise,
            'data_readiness': readiness
        },
        'by_type': {
            'brand': brand,
            'relevant': relevant,
            'noise': noise
        },
        'by_platform': [
            {
                'platform': 'Google Maps',
                'total': gm_total,
                'qualified': gm_qual,
                'quality_ratio': round(gm_qual / gm_total * 100, 1) if gm_total > 0 else 0
            },
            {
                'platform': 'Facebook',
                'total': fb_total,
                'qualified': fb_qual,
                'quality_ratio': round(fb_qual / fb_total * 100, 1) if fb_total > 0 else 0
            },
            {
                'platform': 'TikTok',
                'total': tt_total,
                'qualified': tt_qual,
                'quality_ratio': round(tt_qual / tt_total * 100, 1) if tt_total > 0 else 0
            },
            {
                'platform': 'Instagram',
                'total': ig_total,
                'qualified': ig_qual,
                'quality_ratio': round(ig_qual / ig_total * 100, 1) if ig_total > 0 else 0
            }
        ]
    }

    cursor.close()
    conn.close()

    print(f"   ✅ Qualified: {qualified}/{total} ({qualified_pct}%)")
    print(f"   📊 Readiness: {readiness}")

    return result

def main():
    """Generate all Overview dashboard data"""
    print("="*80)
    print("GENERATING OVERVIEW SCREEN DATA")
    print("="*80)

    output_dir = PROJECT_ROOT / "data" / "dashboard" / "overview"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Generate each dashboard
    dashboards = {
        'pain_priority_matrix': generate_pain_priority_matrix,
        'category_pulse': generate_category_pulse,
        'branch_risk_snapshot': generate_branch_risk_snapshot,
        'qualified_signal_summary': generate_qualified_signal_summary
    }

    results = {}
    for name, generator_func in dashboards.items():
        try:
            data = generator_func()
            results[name] = data

            # Save individual file
            output_file = output_dir / f"{name}.json"
            output_file.write_text(json.dumps(data, ensure_ascii=False, indent=2))
            print(f"   💾 Saved to {output_file}")

        except Exception as e:
            print(f"   ❌ Error generating {name}: {e}")
            import traceback
            traceback.print_exc()

    # Save combined file
    combined_file = output_dir / "overview_all.json"
    combined_file.write_text(json.dumps(results, ensure_ascii=False, indent=2))

    print("\n" + "="*80)
    print(f"✅ DONE! Generated {len(results)} dashboards")
    print(f"📁 Output directory: {output_dir}")
    print("="*80)

if __name__ == "__main__":
    main()
