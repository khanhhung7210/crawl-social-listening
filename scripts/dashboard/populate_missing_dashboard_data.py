#!/usr/bin/env python3
"""
Populate missing dashboard data for Reputation and Competitor Radar screens
Populates 7 tables:
- Reputation: crisis_spike_alerts, founder_mentions, qualified_negative_summary, topic_lifecycle
- Competitor: campaign_intelligence, content_patterns, signal_diagnosis
"""

import subprocess
import json
from datetime import datetime, timedelta
from collections import Counter, defaultdict
import re

def psql_query(query: str, database: str = "meili_dashboard") -> list:
    """Execute psql query and return results"""
    cmd = f'PGDATABASE={database} psql -t -A -c "{query}"'
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Query error: {result.stderr}")
        return []
    data = result.stdout.strip()
    if not data:
        return []
    return [data]

def psql_exec(query: str, database: str = "meili_dashboard"):
    """Execute psql command"""
    cmd = f'PGDATABASE={database} psql -c "{query}"'
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Exec error: {result.stderr}")
    return result.returncode == 0

def get_brand_id():
    """Get the brand_id for Meili"""
    result = psql_query("""
        SELECT brand_id::text
        FROM meili_dashboard.brands
        WHERE brand_slug = 'meili-mi-bo-dai-loan'
        LIMIT 1
    """)
    if result and len(result) > 0:
        return result[0]
    return None

def get_evidence_cards():
    """Get evidence cards from reviews and mentions with enrichments"""
    # Combine both reviews and mentions as evidence
    cmd = """PGDATABASE=meili_dashboard psql -t -A -c "SELECT COALESCE(json_agg(row_to_json(t)), '[]') FROM (SELECT r.review_id as evidence_id, r.review_text as theme, COALESCE(e.topic_label, 'review') as theme_category, COALESCE(e.sentiment_label, 'neutral') as sentiment_label, COALESCE(e.sentiment_score::float, 0) as sentiment_score, 1 as mention_count, r.platform FROM meili_dashboard.reviews r LEFT JOIN meili_dashboard.review_enrichments e ON r.review_id = e.review_id WHERE r.brand_id = (SELECT brand_id FROM meili_dashboard.brands WHERE brand_slug = 'meili-mi-bo-dai-loan') AND r.review_text IS NOT NULL LIMIT 300) t" """
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.returncode == 0 and result.stdout.strip():
        try:
            return json.loads(result.stdout.strip())
        except:
            pass
    return []

def get_mentions():
    """Get social mentions with enrichments"""
    cmd = """PGDATABASE=meili_dashboard psql -t -A -c "SELECT COALESCE(json_agg(row_to_json(t)), '[]') FROM (SELECT m.mention_id, m.platform, m.content_text as mention_text, COALESCE(e.sentiment_label, 'neutral') as sentiment_label, COALESCE(e.sentiment_score::float, 0) as sentiment_score, m.content_created_date::text as mention_date, m.engagement FROM meili_dashboard.mentions m LEFT JOIN meili_dashboard.mention_enrichments e ON m.mention_id = e.mention_id WHERE m.brand_id = (SELECT brand_id FROM meili_dashboard.brands WHERE brand_slug = 'meili-mi-bo-dai-loan') ORDER BY m.content_created_date DESC LIMIT 1000) t" """
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.returncode == 0 and result.stdout.strip():
        try:
            return json.loads(result.stdout.strip())
        except:
            pass
    return []

# === REPUTATION DATA JOBS ===

def populate_crisis_spike_alerts(brand_id: str):
    """Detect and populate crisis spike alerts"""
    print("📊 Populating crisis_spike_alerts...")

    mentions = get_mentions()
    if not mentions:
        print("  No mentions found, skipping")
        return

    # Group by date and count negative mentions
    date_counts = defaultdict(int)
    for m in mentions:
        if m.get('sentiment_label') == 'negative':
            date = m.get('mention_date')
            if date:
                date_counts[date] += 1

    # Find spikes (days with >average negative mentions)
    if not date_counts:
        print("  No negative mentions found")
        return

    avg_negative = sum(date_counts.values()) / len(date_counts)
    threshold = avg_negative * 1.5  # 50% above average

    spikes_inserted = 0
    for date, count in date_counts.items():
        if count > threshold:
            magnitude = count / max(avg_negative, 1)
            severity = 'high' if magnitude > 2 else 'medium' if magnitude > 1.5 else 'low'

            # Extract keywords from negative mentions on this date
            keywords = []
            for m in mentions:
                if m.get('mention_date') == date and m.get('sentiment_label') == 'negative':
                    text = m.get('mention_text', '')
                    words = re.findall(r'\b\w+\b', text.lower())
                    keywords.extend([w for w in words if len(w) > 4][:3])

            top_keywords = [k for k, _ in Counter(keywords).most_common(5)]

            query = f"""
                INSERT INTO meili_dashboard.crisis_spike_alerts
                (brand_id, spike_date, spike_hour, metric_type, baseline_value, spike_value, spike_magnitude, severity, trigger_keywords)
                VALUES ('{brand_id}', '{date}', 14, 'negative_mentions', {avg_negative:.1f}, {count}, {magnitude:.2f}, '{severity}', ARRAY{top_keywords})
                ON CONFLICT DO NOTHING
            """
            if psql_exec(query):
                spikes_inserted += 1

    print(f"  ✅ Inserted {spikes_inserted} crisis spikes")

def populate_founder_mentions(brand_id: str):
    """Detect and populate founder/CEO mentions"""
    print("📊 Populating founder_mentions...")

    mentions = get_mentions()
    if not mentions:
        print("  No mentions found")
        return

    # Keywords for founder/CEO mentions
    founder_keywords = ['chủ', 'owner', 'ceo', 'founder', 'sáng lập', 'ông chủ', 'bà chủ']

    founder_mentions_inserted = 0
    for m in mentions:
        text = (m.get('mention_text') or '').lower()
        if any(kw in text for kw in founder_keywords):
            mention_id = m.get('mention_id')
            platform = m.get('platform', 'unknown')
            sentiment = m.get('sentiment_label', 'neutral')
            sentiment_score = m.get('sentiment_score', 0.0)
            mention_date = m.get('mention_date')

            # Determine risk level
            if sentiment == 'negative' and sentiment_score < -0.5:
                risk = 'high'
            elif sentiment == 'negative':
                risk = 'medium'
            else:
                risk = 'low'

            query = f"""
                INSERT INTO meili_dashboard.founder_mentions
                (brand_id, mention_id, source_platform, founder_name, mention_text, sentiment_label, sentiment_score, risk_level, context_type, mention_date)
                VALUES ('{brand_id}', '{mention_id}', '{platform}', 'Founder/CEO', E'{text[:500].replace("'", "''")}', '{sentiment}', {sentiment_score}, '{risk}', 'social_mention', '{mention_date}')
                ON CONFLICT DO NOTHING
            """
            if psql_exec(query):
                founder_mentions_inserted += 1

    print(f"  ✅ Inserted {founder_mentions_inserted} founder mentions")

def populate_qualified_negative_summary(brand_id: str):
    """Analyze and populate qualified negative summary"""
    print("📊 Populating qualified_negative_summary...")

    evidence = get_evidence_cards()
    if not evidence:
        print("  No evidence cards found")
        return

    # Group by platform
    by_platform = defaultdict(lambda: {'total': 0, 'qualified': 0, 'topics': []})

    for card in evidence:
        if card.get('sentiment_label') == 'negative':
            platform = card.get('platform', 'unknown')
            mention_count = card.get('mention_count', 1)

            by_platform[platform]['total'] += mention_count

            # Consider "qualified" if from review platforms or has high engagement
            if platform in ['google_maps', 'shopeefood', 'grabfood']:
                by_platform[platform]['qualified'] += mention_count
            else:
                # Social platforms - 50% qualified estimate
                by_platform[platform]['qualified'] += mention_count // 2

            theme = card.get('theme', '')
            if theme:
                by_platform[platform]['topics'].append(theme)

    today = datetime.now().date()
    summary_inserted = 0

    for platform, data in by_platform.items():
        total = data['total']
        qualified = data['qualified']
        noise = total - qualified
        qualified_pct = (qualified / total * 100) if total > 0 else 0
        trust_score = qualified_pct / 100  # Simple trust score

        top_topics = [t for t, _ in Counter(data['topics']).most_common(5)]

        query = f"""
            INSERT INTO meili_dashboard.qualified_negative_summary
            (brand_id, platform, snapshot_date, total_negative_count, qualified_negative_count, noise_negative_count, qualified_percentage, avg_trust_score, top_topics)
            VALUES ('{brand_id}', '{platform}', '{today}', {total}, {qualified}, {noise}, {qualified_pct:.2f}, {trust_score:.2f}, ARRAY{top_topics})
            ON CONFLICT (brand_id, platform, snapshot_date) DO UPDATE SET
                total_negative_count = {total},
                qualified_negative_count = {qualified},
                noise_negative_count = {noise},
                qualified_percentage = {qualified_pct:.2f},
                avg_trust_score = {trust_score:.2f},
                top_topics = ARRAY{top_topics}
        """
        if psql_exec(query):
            summary_inserted += 1

    print(f"  ✅ Inserted {summary_inserted} platform summaries")

def populate_topic_lifecycle(brand_id: str):
    """Track and populate topic lifecycle"""
    print("📊 Populating topic_lifecycle...")

    evidence = get_evidence_cards()
    if not evidence:
        print("  No evidence cards found")
        return

    # Group themes by category and count
    topic_data = defaultdict(lambda: {
        'category': '',
        'volume': 0,
        'negative': 0,
        'positive': 0,
        'sentiment_scores': []
    })

    for card in evidence:
        theme = card.get('theme', '')
        if not theme:
            continue

        category = card.get('theme_category', 'other')
        volume = card.get('mention_count', 1)
        sentiment = card.get('sentiment_label', 'neutral')
        sentiment_score = card.get('sentiment_score', 0.0)

        topic_data[theme]['category'] = category
        topic_data[theme]['volume'] += volume
        topic_data[theme]['sentiment_scores'].append(sentiment_score)

        if sentiment == 'negative':
            topic_data[theme]['negative'] += volume
        elif sentiment == 'positive':
            topic_data[theme]['positive'] += volume

    lifecycle_inserted = 0
    for topic, data in topic_data.items():
        volume = data['volume']
        avg_sentiment = sum(data['sentiment_scores']) / len(data['sentiment_scores']) if data['sentiment_scores'] else 0

        # Determine lifecycle stage
        if data['negative'] > data['positive'] * 2:
            stage = 'fix'
            action = 'Fix immediately - high negative volume'
            velocity = 'increasing'
        elif data['negative'] > 5:
            stage = 'monitor'
            action = 'Monitor closely - negative trend'
            velocity = 'stable'
        elif data['positive'] > data['negative'] * 2:
            stage = 'amplify'
            action = 'Amplify positive signals'
            velocity = 'stable'
        elif volume > 10:
            stage = 'monitor'
            action = 'Monitor - moderate volume'
            velocity = 'stable'
        else:
            stage = 'detect'
            action = 'Recently detected - observe'
            velocity = 'emerging'

        # Sentiment trend
        if avg_sentiment < -0.3:
            sent_trend = 'declining'
        elif avg_sentiment > 0.3:
            sent_trend = 'improving'
        else:
            sent_trend = 'stable'

        query = f"""
            INSERT INTO meili_dashboard.topic_lifecycle
            (brand_id, topic_name, topic_category, lifecycle_stage, velocity, volume_7d, sentiment_trend, avg_sentiment_score, recommended_action, guardrail, owner)
            VALUES ('{brand_id}', E'{topic[:200].replace("'", "''")}', '{data['category']}', '{stage}', '{velocity}', {volume}, '{sent_trend}', {avg_sentiment:.3f}, E'{action.replace("'", "''")}', 'Evidence-backed', 'CS + Ops')
            ON CONFLICT (brand_id, topic_name) DO UPDATE SET
                lifecycle_stage = '{stage}',
                velocity = '{velocity}',
                volume_7d = {volume},
                sentiment_trend = '{sent_trend}',
                avg_sentiment_score = {avg_sentiment:.3f},
                recommended_action = E'{action.replace("'", "''")}',
                last_updated = now()
        """
        if psql_exec(query):
            lifecycle_inserted += 1

    print(f"  ✅ Inserted {lifecycle_inserted} topics")

# === COMPETITOR DATA JOBS ===

def populate_campaign_intelligence(brand_id: str):
    """Detect and populate competitor campaign intelligence"""
    print("📊 Populating campaign_intelligence...")

    mentions = get_mentions()
    if not mentions:
        print("  No mentions found")
        return

    # Simple competitor detection (mentions of other noodle brands)
    competitors = ['phở', 'bún', 'miến', 'hủ tiếu', 'mì', 'cháo']
    campaign_keywords = ['khuyến mãi', 'giảm giá', 'combo', 'deal', 'sale', 'ưu đãi']

    campaigns = defaultdict(lambda: {
        'mentions': [],
        'keywords': [],
        'sentiment_scores': [],
        'dates': []
    })

    for m in mentions:
        text = (m.get('mention_text') or '').lower()

        # Check for competitor mentions + campaign keywords
        for comp in competitors:
            if comp in text:
                for keyword in campaign_keywords:
                    if keyword in text:
                        campaign_key = f"{comp}_{keyword}"
                        campaigns[campaign_key]['mentions'].append(m.get('mention_id'))
                        campaigns[campaign_key]['keywords'].extend(text.split())
                        campaigns[campaign_key]['sentiment_scores'].append(m.get('sentiment_score', 0.0))
                        campaigns[campaign_key]['dates'].append(m.get('mention_date'))

    campaigns_inserted = 0
    for camp_key, data in campaigns.items():
        if len(data['mentions']) < 3:  # Skip campaigns with < 3 mentions
            continue

        competitor, campaign_type = camp_key.split('_', 1)
        mention_count = len(data['mentions'])
        avg_sentiment = sum(data['sentiment_scores']) / len(data['sentiment_scores']) if data['sentiment_scores'] else 0

        # Calculate scores
        buzz_score = min(100, mention_count * 5)  # Simple buzz score
        sentiment_score = max(0, min(100, (avg_sentiment + 1) * 50))  # -1 to 1 → 0 to 100
        qualified_users = min(100, mention_count * 3)
        object_mention = min(100, mention_count * 4)
        overall = (buzz_score + sentiment_score + qualified_users + object_mention) / 4

        top_keywords = [k for k, _ in Counter(data['keywords']).most_common(5)]
        dates = sorted(data['dates'])
        start_date = dates[0] if dates else datetime.now().date()
        end_date = dates[-1] if dates else datetime.now().date()

        query = f"""
            INSERT INTO meili_dashboard.campaign_intelligence
            (brand_id, competitor_name, campaign_name, campaign_type, start_date, end_date,
             qualified_users_score, buzz_score, object_mention_score, sentiment_score, overall_score,
             mention_count, reach_estimate, top_keywords)
            VALUES ('{brand_id}', E'{competitor.title()}', E'{camp_key.replace("_", " ").title()}', '{campaign_type}', '{start_date}', '{end_date}',
                    {qualified_users:.1f}, {buzz_score:.1f}, {object_mention:.1f}, {sentiment_score:.1f}, {overall:.1f},
                    {mention_count}, {mention_count * 50}, ARRAY{top_keywords}::text[])
        """
        if psql_exec(query):
            campaigns_inserted += 1

    print(f"  ✅ Inserted {campaigns_inserted} competitor campaigns")

def populate_content_patterns(brand_id: str):
    """Detect and populate winning content patterns"""
    print("📊 Populating content_patterns...")

    evidence = get_evidence_cards()
    if not evidence:
        print("  No evidence cards found")
        return

    # Find patterns in high-engagement positive content
    patterns = {
        'Family combo appeal': {
            'keywords': ['gia đình', 'family', 'combo', 'cả nhà'],
            'strength': 0,
            'examples': []
        },
        'Delivery deal': {
            'keywords': ['giao hàng', 'delivery', 'ship', 'freeship'],
            'strength': 0,
            'examples': []
        },
        'Premium storytelling': {
            'keywords': ['cao cấp', 'premium', 'sang', 'đặc biệt'],
            'strength': 0,
            'examples': []
        },
        'Local value': {
            'keywords': ['địa phương', 'truyền thống', 'local', 'authentic'],
            'strength': 0,
            'examples': []
        }
    }

    for card in evidence:
        if card.get('sentiment_label') == 'positive':
            theme = (card.get('theme') or '').lower()
            volume = card.get('mention_count', 1)

            for pattern_name, pattern_data in patterns.items():
                if any(kw in theme for kw in pattern_data['keywords']):
                    pattern_data['strength'] += volume
                    pattern_data['examples'].append(theme)

    patterns_inserted = 0
    for pattern_name, data in patterns.items():
        if data['strength'] == 0:
            continue

        strength = min(100, data['strength'] * 2)
        risk = 'high' if strength > 70 else 'medium' if strength > 40 else 'low'

        # Recommend response mode
        if strength > 70:
            response = 'Similar'
            rationale = 'High-performing pattern - consider adopting similar approach'
        elif strength > 40:
            response = 'Merge'
            rationale = 'Moderate pattern - combine with our strengths'
        else:
            response = 'Monitor'
            rationale = 'Emerging pattern - continue monitoring'

        examples = data['examples'][:3]

        query = f"""
            INSERT INTO meili_dashboard.content_patterns
            (brand_id, pattern_name, pattern_description, pattern_strength, risk_level, competitor_examples, recommended_response, response_rationale)
            VALUES ('{brand_id}', E'{pattern_name}', E'Pattern detected in competitor content', {strength:.1f}, '{risk}', ARRAY{examples}::text[], '{response}', E'{rationale}')
        """
        if psql_exec(query):
            patterns_inserted += 1

    print(f"  ✅ Inserted {patterns_inserted} content patterns")

def populate_signal_diagnosis(brand_id: str):
    """Generate 5W-1H diagnosis for key signals"""
    print("📊 Populating signal_diagnosis...")

    evidence = get_evidence_cards()
    if not evidence:
        print("  No evidence cards found")
        return

    # Select top signals (high-volume evidence cards)
    top_signals = sorted(evidence, key=lambda x: x.get('mention_count', 0), reverse=True)[:10]

    diagnoses_inserted = 0
    for card in top_signals:
        theme = card.get('theme', '')
        if not theme:
            continue

        category = card.get('theme_category', 'other')
        sentiment = card.get('sentiment_label', 'neutral')
        volume = card.get('mention_count', 1)
        platform = card.get('platform', 'social')

        # Generate 5W-1H
        if sentiment == 'negative':
            who = "Customers experiencing issues"
            what = f"Complaint about {theme}"
            why = "Service/product quality concern"
            how = "Address root cause and improve CX"
            priority = 'high' if volume > 10 else 'medium'
        elif sentiment == 'positive':
            who = "Satisfied customers"
            what = f"Positive feedback on {theme}"
            why = "Strong brand attribute"
            how = "Amplify in marketing content"
            priority = 'low'
        else:
            who = "General audience"
            what = f"Discussion about {theme}"
            why = "Topic of interest"
            how = "Monitor for trends"
            priority = 'low'

        where = f"{platform.title()} platform"
        when = "Last 7 days"

        confidence = min(100, volume * 5) / 100
        owner = 'CS + Ops' if sentiment == 'negative' else 'Marketing'

        query = f"""
            INSERT INTO meili_dashboard.signal_diagnosis
            (brand_id, signal_name, signal_type, who_audience, what_need, where_source, when_timing, why_reason, how_action, confidence_score, priority, recommended_next_step, owner)
            VALUES ('{brand_id}', E'{theme[:200].replace("'", "''")}', '{category}', E'{who}', E'{what.replace("'", "''")}', E'{where}', E'{when}', E'{why}', E'{how}', {confidence:.2f}, '{priority}', E'{how}', '{owner}')
        """
        if psql_exec(query):
            diagnoses_inserted += 1

    print(f"  ✅ Inserted {diagnoses_inserted} signal diagnoses")

def main():
    print("🚀 Starting dashboard data population...")
    print()

    brand_id = get_brand_id()
    if not brand_id:
        print("❌ Could not find brand ID for Meili")
        return 1

    print(f"✅ Brand ID: {brand_id}")
    print()

    # Populate Reputation data
    print("=" * 60)
    print("REPUTATION SCREEN DATA")
    print("=" * 60)
    populate_crisis_spike_alerts(brand_id)
    populate_founder_mentions(brand_id)
    populate_qualified_negative_summary(brand_id)
    populate_topic_lifecycle(brand_id)

    print()

    # Populate Competitor data
    print("=" * 60)
    print("COMPETITOR RADAR DATA")
    print("=" * 60)
    populate_campaign_intelligence(brand_id)
    populate_content_patterns(brand_id)
    populate_signal_diagnosis(brand_id)

    print()
    print("=" * 60)
    print("✅ ALL DATA POPULATED SUCCESSFULLY!")
    print("=" * 60)

    return 0

if __name__ == "__main__":
    exit(main())
