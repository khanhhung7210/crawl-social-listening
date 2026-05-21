"""
Reputation Intelligence Repository Methods

Add these methods to PostgresDashboardRepository class in repository.py

These methods fetch reputation intelligence data from:
- crisis_spike_alerts
- founder_mentions
- qualified_negative_summary
- topic_lifecycle
- campaign_intelligence
- content_patterns
- signal_diagnosis
"""

# ============================================================
# REPUTATION SCREEN - NEW MODULES
# ============================================================

def _fetch_crisis_spikes(self, days: int = 7) -> list[dict]:
    """Fetch recent crisis spikes for monitoring"""
    return self._query_json(
        f"""
        SELECT COALESCE(json_agg(row_to_json(t) ORDER BY spike_date DESC, detected_at DESC), '[]'::json)
        FROM (
          SELECT
            spike_date,
            spike_hour,
            metric_type,
            baseline_value::float,
            spike_value::float,
            spike_magnitude::float,
            severity,
            trigger_keywords,
            status
          FROM {self.schema}.crisis_spike_alerts
          WHERE brand_id = (SELECT brand_id FROM {self.schema}.brands WHERE brand_slug = {sql_str(self.brand_slug)})
            AND spike_date >= CURRENT_DATE - INTERVAL '{days} days'
          ORDER BY spike_date DESC, detected_at DESC
          LIMIT 30
        ) t;
        """
    )

def _fetch_founder_mentions(self, days: int = 42) -> list[dict]:
    """Fetch founder/CEO mentions for reputation watch"""
    return self._query_json(
        f"""
        SELECT COALESCE(json_agg(row_to_json(t) ORDER BY mention_date DESC), '[]'::json)
        FROM (
          SELECT
            founder_name,
            sentiment_label,
            sentiment_score::float,
            risk_level,
            context_type,
            mention_date,
            mention_text
          FROM {self.schema}.founder_mentions
          WHERE brand_id = (SELECT brand_id FROM {self.schema}.brands WHERE brand_slug = {sql_str(self.brand_slug)})
            AND mention_date >= CURRENT_DATE - INTERVAL '{days} days'
          ORDER BY mention_date DESC
          LIMIT 100
        ) t;
        """
    )

def _fetch_qualified_negative_summary(self) -> list[dict]:
    """Fetch qualified negative signal summary by platform"""
    return self._query_json(
        f"""
        SELECT COALESCE(json_agg(row_to_json(t) ORDER BY qualified_percentage DESC), '[]'::json)
        FROM (
          SELECT
            platform,
            total_negative_count::int,
            qualified_negative_count::int,
            noise_negative_count::int,
            qualified_percentage::float,
            avg_trust_score::float,
            top_topics
          FROM {self.schema}.qualified_negative_summary
          WHERE brand_id = (SELECT brand_id FROM {self.schema}.brands WHERE brand_slug = {sql_str(self.brand_slug)})
            AND snapshot_date = (
              SELECT MAX(snapshot_date)
              FROM {self.schema}.qualified_negative_summary
              WHERE brand_id = (SELECT brand_id FROM {self.schema}.brands WHERE brand_slug = {sql_str(self.brand_slug)})
            )
        ) t;
        """
    )

def _fetch_topic_lifecycle(self) -> list[dict]:
    """Fetch topics in lifecycle stages"""
    return self._query_json(
        f"""
        SELECT COALESCE(json_agg(row_to_json(t) ORDER BY
          CASE lifecycle_stage
            WHEN 'detect' THEN 1
            WHEN 'monitor' THEN 2
            WHEN 'fix' THEN 3
            WHEN 'recover' THEN 4
            WHEN 'amplify' THEN 5
          END,
          volume_7d DESC
        ), '[]'::json)
        FROM (
          SELECT
            topic_name,
            topic_category,
            lifecycle_stage,
            velocity,
            volume_7d::int,
            volume_change_pct::float,
            sentiment_trend,
            avg_sentiment_score::float,
            recommended_action,
            guardrail,
            owner
          FROM {self.schema}.topic_lifecycle
          WHERE brand_id = (SELECT brand_id FROM {self.schema}.brands WHERE brand_slug = {sql_str(self.brand_slug)})
          ORDER BY last_updated DESC
          LIMIT 20
        ) t;
        """
    )

# Reputation module builders

def _build_crisis_spike_module(self) -> dict:
    """Build Crisis Spike Monitor module"""
    spikes = self._fetch_crisis_spikes(days=7)

    if not spikes:
        return {
            "title": "Crisis Spike Monitor",
            "takeaway": "Chart đầu tiên phải cho thấy có spike bất thường hay không.",
            "chart": "line",
            "data": {"labels": [], "series": []},
            "analysis": ["No spikes detected in the last 7 days", "System is monitoring for volume and sentiment anomalies"],
            "action": {
                "guardrail": "Evidence-backed module",
                "owner": "CS + Ops",
                "cta": "Open Evidence"
            },
            "evidence_query": "Crisis Spike Monitor",
        }

    # Aggregate by date for chart
    spike_by_date = {}
    for spike in spikes:
        date = spike['spike_date']
        if date not in spike_by_date:
            spike_by_date[date] = {'count': 0, 'max_magnitude': 0}
        spike_by_date[date]['count'] += 1
        spike_by_date[date]['max_magnitude'] = max(
            spike_by_date[date]['max_magnitude'],
            spike['spike_magnitude']
        )

    dates = sorted(spike_by_date.keys())
    labels = dates[-7:] if len(dates) > 7 else dates
    values = [spike_by_date[d]['count'] for d in labels]

    high_severity = [s for s in spikes if s.get('severity') == 'high']

    analysis = []
    if high_severity:
        analysis.append(f"{len(high_severity)} high-severity spikes detected")
        top_spike = high_severity[0]
        analysis.append(f"Latest spike: {top_spike['metric_type']} on {top_spike['spike_date']}")
        if top_spike.get('trigger_keywords'):
            keywords = ', '.join(top_spike['trigger_keywords'][:3])
            analysis.append(f"Trigger keywords: {keywords}")
    else:
        analysis.append("No high-severity spikes in recent period")
        analysis.append("Monitoring continues for volume and sentiment anomalies")

    return {
        "title": "Crisis Spike Monitor",
        "takeaway": "Chart đầu tiên phải cho thấy có spike bất thường hay không.",
        "chart": "line",
        "data": {
            "labels": labels,
            "series": [{
                "name": "Spike count",
                "values": values,
                "color": "#d94444"
            }]
        },
        "analysis": analysis,
        "action": {
            "guardrail": "Evidence-backed module",
            "owner": "CS + Ops",
            "cta": "Open Evidence"
        },
        "evidence_query": "Crisis Spike Monitor",
    }

def _build_founder_watch_module(self) -> dict:
    """Build Founder/CEO Reputation Watch module"""
    mentions = self._fetch_founder_mentions(days=42)

    if not mentions:
        return {
            "title": "Founder / CEO Reputation Watch",
            "takeaway": "Với founder-led brand, sentiment quanh CEO/founder có thể ảnh hưởng trực tiếp đến brand trust.",
            "chart": "line",
            "data": {"labels": [], "series": []},
            "analysis": ["No founder mentions detected", "Consider adding founder name to tracking keywords"],
            "action": {
                "guardrail": "Monitor First",
                "owner": "CEO + PR",
                "cta": "Open Founder Watch"
            },
            "evidence_query": "Founder Watch",
        }

    # Aggregate by week
    import datetime
    week_data = {}
    for mention in mentions:
        date = datetime.datetime.strptime(mention['mention_date'], '%Y-%m-%d').date()
        week_num = date.isocalendar()[1]
        week_key = f"W{week_num}"

        if week_key not in week_data:
            week_data[week_key] = {'total': 0, 'negative': 0}
        week_data[week_key]['total'] += 1
        if mention['sentiment_label'] == 'negative':
            week_data[week_key]['negative'] += 1

    weeks = sorted(week_data.keys())[-6:]
    total_values = [week_data[w]['total'] for w in weeks]
    negative_values = [week_data[w]['negative'] for w in weeks]

    negative_count = sum(1 for m in mentions if m.get('sentiment_label') == 'negative')
    high_risk = [m for m in mentions if m.get('risk_level') == 'high']

    analysis = []
    analysis.append(f"Founder mention đang {'tăng' if len(total_values) > 1 and total_values[-1] > total_values[-2] else 'ổn định'}")
    if high_risk:
        analysis.append(f"{len(high_risk)} mentions có risk level cao, cần theo dõi")
    else:
        analysis.append("Negative risk chưa vượt ngưỡng crisis")
    analysis.append("Không nên action nếu chưa có velocity/confidence đủ cao")

    return {
        "title": "Founder / CEO Reputation Watch",
        "takeaway": "Với founder-led brand, sentiment quanh CEO/founder có thể ảnh hưởng trực tiếp đến brand trust.",
        "chart": "line",
        "data": {
            "labels": weeks,
            "series": [
                {"name": "Founder mentions", "values": total_values, "color": "#1f66f5"},
                {"name": "Negative risk", "values": negative_values, "color": "#d94444"}
            ]
        },
        "analysis": analysis,
        "action": {
            "guardrail": "Monitor First",
            "owner": "CEO + PR",
            "cta": "Open Founder Watch"
        },
        "evidence_query": "Founder Watch",
    }

def _build_qualified_negative_module(self) -> dict:
    """Build Qualified Negative Signal module"""
    summary = self._fetch_qualified_negative_summary()

    if not summary:
        return {
            "title": "Qualified Negative Signal",
            "takeaway": "Một negative từ khách thật/review thật quan trọng hơn nhiều negative từ noise.",
            "chart": "stacked",
            "data": [],
            "analysis": ["No qualified negative data available", "Run analysis to classify negative signals by trust level"],
            "action": {
                "guardrail": "Prioritize high-trust negative",
                "owner": "CS + Ops + PR",
                "cta": "Open Qualified Negative"
            },
            "evidence_query": "Qualified Negative",
        }

    # Build stacked bar data: [platform, qualified, noise, qualified_pct]
    data = []
    for row in summary[:5]:
        data.append([
            row['platform'].title(),
            row['qualified_negative_count'],
            row['noise_negative_count'],
            int(row['qualified_percentage'])
        ])

    high_trust = [r for r in summary if r['avg_trust_score'] > 0.7]

    analysis = []
    if high_trust:
        platforms = ', '.join(r['platform'].title() for r in high_trust[:2])
        analysis.append(f"{platforms} có qualified negative cao, cần ưu tiên fix")

    low_trust = [r for r in summary if r['avg_trust_score'] < 0.6]
    if low_trust:
        platforms = ', '.join(r['platform'].title() for r in low_trust[:2])
        analysis.append(f"{platforms} có nhiều noise hơn, cần monitor velocity trước")

    analysis.append("PR/news dù volume thấp nhưng impact cao nếu xuất hiện")

    return {
        "title": "Qualified Negative Signal",
        "takeaway": "Một negative từ khách thật/review thật quan trọng hơn nhiều negative từ noise. Cụm 1 cần ưu tiên theo chất lượng nguồn.",
        "chart": "stacked",
        "data": data,
        "analysis": analysis,
        "action": {
            "guardrail": "Prioritize high-trust negative",
            "owner": "CS + Ops + PR",
            "cta": "Open Qualified Negative"
        },
        "evidence_query": "Qualified Negative",
    }

def _build_topic_lifecycle_module(self) -> dict:
    """Build Sensitive Topic Lifecycle module"""
    topics = self._fetch_topic_lifecycle()

    if not topics:
        return {
            "title": "Sensitive Topic Lifecycle",
            "takeaway": "Các keyword nhạy cảm cần được xem theo lifecycle: mới nổi, tăng tốc, lan rộng hay đã giảm.",
            "chart": "timeline",
            "data": [],
            "analysis": ["No topics tracked in lifecycle", "System will auto-detect emerging topics"],
            "action": {
                "guardrail": "Contain -> Fix -> Recover",
                "owner": "MKT + CS + Ops",
                "cta": "Open Sensitive Topic"
            },
            "evidence_query": "Topic Lifecycle",
        }

    # Build timeline data: [stage, topic_name, description]
    stage_map = {
        'detect': 'Detect',
        'monitor': 'Monitor',
        'fix': 'Fix',
        'recover': 'Recover',
        'amplify': 'Amplify'
    }

    data = []
    for topic in topics[:5]:
        stage = stage_map.get(topic['lifecycle_stage'], topic['lifecycle_stage'].title())
        description = f"{topic.get('recommended_action', 'Track topic evolution')}"
        data.append([stage, topic['topic_name'], description])

    detect_stage = [t for t in topics if t['lifecycle_stage'] == 'detect']
    fix_stage = [t for t in topics if t['lifecycle_stage'] == 'fix']

    analysis = []
    if detect_stage:
        analysis.append(f"{len(detect_stage)} topics in detect stage - monitor velocity")
    if fix_stage:
        analysis.append(f"{len(fix_stage)} topics need fixing - high priority action")
    analysis.append("Lifecycle giúp chọn đúng guardrail: Monitor First, Fix First hoặc Recover")
    analysis.append("Sau fix cần đo trust recovery, không chỉ đóng ticket")

    return {
        "title": "Sensitive Topic Lifecycle",
        "takeaway": "Các keyword nhạy cảm cần được xem theo lifecycle: mới nổi, tăng tốc, lan rộng hay đã giảm.",
        "chart": "timeline",
        "data": data,
        "analysis": analysis,
        "action": {
            "guardrail": "Contain -> Fix -> Recover",
            "owner": "MKT + CS + Ops",
            "cta": "Open Sensitive Topic"
        },
        "evidence_query": "Topic Lifecycle",
    }

# ============================================================
# COMPETITOR SCREEN - NEW MODULES
# ============================================================

def _fetch_campaign_intelligence(self) -> list[dict]:
    """Fetch competitor campaign intelligence"""
    return self._query_json(
        f"""
        SELECT COALESCE(json_agg(row_to_json(t) ORDER BY overall_score DESC), '[]'::json)
        FROM (
          SELECT
            competitor_name,
            campaign_name,
            campaign_type,
            qualified_users_score::float,
            buzz_score::float,
            object_mention_score::float,
            sentiment_score::float,
            overall_score::float
          FROM {self.schema}.campaign_intelligence
          WHERE brand_id = (SELECT brand_id FROM {self.schema}.brands WHERE brand_slug = {sql_str(self.brand_slug)})
          ORDER BY overall_score DESC
          LIMIT 10
        ) t;
        """
    )

def _fetch_content_patterns(self) -> list[dict]:
    """Fetch winning content patterns"""
    return self._query_json(
        f"""
        SELECT COALESCE(json_agg(row_to_json(t) ORDER BY pattern_strength DESC), '[]'::json)
        FROM (
          SELECT
            pattern_name,
            pattern_description,
            pattern_strength::float,
            risk_level,
            recommended_response,
            response_rationale
          FROM {self.schema}.content_patterns
          WHERE brand_id = (SELECT brand_id FROM {self.schema}.brands WHERE brand_slug = {sql_str(self.brand_slug)})
          ORDER BY pattern_strength DESC
          LIMIT 10
        ) t;
        """
    )

def _fetch_signal_diagnosis(self, limit: int = 5) -> list[dict]:
    """Fetch 5W-1H signal diagnosis"""
    return self._query_json(
        f"""
        SELECT COALESCE(json_agg(row_to_json(t) ORDER BY
          CASE priority WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
          confidence_score DESC
        ), '[]'::json)
        FROM (
          SELECT
            signal_name,
            signal_type,
            who_audience,
            what_need,
            where_source,
            when_timing,
            why_reason,
            how_action,
            confidence_score::float,
            priority,
            recommended_next_step,
            owner
          FROM {self.schema}.signal_diagnosis
          WHERE brand_id = (SELECT brand_id FROM {self.schema}.brands WHERE brand_slug = {sql_str(self.brand_slug)})
          ORDER BY created_at DESC
          LIMIT {int(limit)}
        ) t;
        """
    )

# Competitor module builders

def _build_campaign_ranking_module(self) -> dict:
    """Build Competitor Campaign Ranking module"""
    campaigns = self._fetch_campaign_intelligence()

    if not campaigns:
        return {
            "title": "Competitor Campaign Ranking",
            "takeaway": "Không chỉ xem đối thủ có campaign gì, mà phải benchmark campaign đó thắng nhờ qualified users, buzz, object mention hay sentiment.",
            "chart": "groupedColumns",
            "data": {"labels": [], "series": []},
            "analysis": ["No competitor campaigns detected", "Run campaign intelligence jobs to track competitor activities"],
            "action": {
                "guardrail": "Learn pattern, do not copy blindly",
                "owner": "Marketing",
                "cta": "Open Campaign Benchmark"
            },
            "evidence_query": "Campaign Benchmark",
        }

    # Build grouped columns data
    labels = ["Qualified users", "Buzz", "Object mention", "Sentiment"]
    series = []
    colors = ["#1f66f5", "#d94444", "#16a26a", "#6952d8"]

    for i, campaign in enumerate(campaigns[:3]):
        series.append({
            "name": f"{campaign['competitor_name']} {campaign['campaign_name'][:20]}",
            "values": [
                campaign.get('qualified_users_score', 0),
                campaign.get('buzz_score', 0),
                campaign.get('object_mention_score', 0),
                campaign.get('sentiment_score', 0)
            ],
            "color": colors[i % len(colors)]
        })

    # Analysis
    analysis = []
    if campaigns:
        top = campaigns[0]
        analysis.append(f"{top['competitor_name']} leads with overall score {top['overall_score']:.0f}")

        # Find dimension winners
        if any(c.get('buzz_score', 0) > 75 for c in campaigns):
            buzz_winner = max(campaigns, key=lambda x: x.get('buzz_score', 0))
            analysis.append(f"{buzz_winner['competitor_name']} thắng buzz với {buzz_winner['buzz_score']:.0f}/100")

        if any(c.get('sentiment_score', 0) > 75 for c in campaigns):
            sent_winner = max(campaigns, key=lambda x: x.get('sentiment_score', 0))
            analysis.append(f"{sent_winner['competitor_name']} thắng sentiment với {sent_winner['sentiment_score']:.0f}/100")

    return {
        "title": "Competitor Campaign Ranking",
        "takeaway": "Không chỉ xem đối thủ có campaign gì, mà phải benchmark campaign đó thắng nhờ qualified users, buzz, object mention hay sentiment.",
        "chart": "groupedColumns",
        "data": {"labels": labels, "series": series},
        "analysis": analysis,
        "action": {
            "guardrail": "Learn pattern, do not copy blindly",
            "owner": "Marketing",
            "cta": "Open Campaign Benchmark"
        },
        "evidence_query": "Campaign Benchmark",
    }

def _build_content_pattern_module(self) -> dict:
    """Build Winning Content Pattern module"""
    patterns = self._fetch_content_patterns()

    if not patterns:
        return {
            "title": "Winning Content Pattern",
            "takeaway": "Tìm pattern nội dung đang thắng theo category để quyết định Similar, Different, Merge, Counter hay Exploit.",
            "chart": "hbar",
            "data": [],
            "analysis": ["No content patterns detected", "Run pattern analysis to identify winning content strategies"],
            "action": {
                "guardrail": "Choose one response mode",
                "owner": "Marketing",
                "cta": "Choose Response Mode"
            },
            "evidence_query": "Content Patterns",
        }

    # Build horizontal bar data: [pattern_name, strength, risk_level]
    data = []
    for pattern in patterns[:5]:
        data.append([
            pattern['pattern_name'].replace('_', ' ').title(),
            int(pattern['pattern_strength']),
            pattern.get('risk_level', 'medium')
        ])

    # Analysis
    analysis = []
    high_strength = [p for p in patterns if p['pattern_strength'] > 70]
    if high_strength:
        top = high_strength[0]
        analysis.append(f"{top['pattern_name'].replace('_', ' ').title()} là pattern đáng học với strength {top['pattern_strength']:.0f}")

    high_risk = [p for p in patterns if p.get('risk_level') == 'high']
    if high_risk:
        analysis.append(f"{len(high_risk)} patterns có risk cao, cẩn thận khi copy")

    low_risk = [p for p in patterns if p.get('risk_level') == 'low']
    if low_risk:
        top_safe = low_risk[0]
        analysis.append(f"{top_safe['pattern_name'].replace('_', ' ').title()} là vùng an toàn để phản ứng")

    return {
        "title": "Winning Content Pattern",
        "takeaway": "Tìm pattern nội dung đang thắng theo category để quyết định Similar, Different, Merge, Counter hay Exploit.",
        "chart": "hbar",
        "data": data,
        "analysis": analysis,
        "action": {
            "guardrail": "Choose one response mode",
            "owner": "Marketing",
            "cta": "Choose Response Mode"
        },
        "evidence_query": "Content Patterns",
    }

def _build_5w1h_diagnosis_module(self) -> dict:
    """Build 5W-1H Signal Diagnosis module"""
    diagnoses = self._fetch_signal_diagnosis(limit=3)

    if not diagnoses:
        return {
            "title": "5W-1H Signal Diagnosis",
            "takeaway": "Biến một signal/cơ hội thành brief chiến lược ngắn: ai nói, nói gì, ở đâu, khi nào, vì sao, và phản ứng thế nào.",
            "chart": "modeMap",
            "data": [],
            "analysis": ["No signal diagnosis available", "Run diagnosis to generate decision briefs"],
            "action": {
                "guardrail": "Decision brief before campaign",
                "owner": "Marketing + CEO",
                "cta": "Generate 5W-1H Brief"
            },
            "evidence_query": "5W-1H Diagnosis",
        }

    # Use the top diagnosis for the mode map
    top = diagnoses[0]

    data = [
        ["Who", top.get('who_audience', 'Target audience'), "Audience identified"],
        ["What", top.get('what_need', 'Customer need'), "Value proposition"],
        ["Where", top.get('where_source', 'Source mix'), "Channel insight"],
        ["When", top.get('when_timing', 'Timing window'), "Optimal timing"],
        ["Why", top.get('why_reason', 'Root cause'), "Motivation analysis"],
        ["How", top.get('how_action', 'Recommended action'), "Next step"],
    ]

    # Analysis
    analysis = []
    analysis.append(f"Signal: {top['signal_name']}")
    analysis.append(f"Confidence: {top.get('confidence_score', 0):.0f}/100")
    if top.get('priority') == 'high':
        analysis.append("High priority - ready for action")
    analysis.append("5W-1H giúp Cụm 1 tạo brief đủ rõ để chuyển sang Cụm 2")
    analysis.append("Mỗi 5W-1H phải có evidence và measurement")

    return {
        "title": "5W-1H Signal Diagnosis",
        "takeaway": "Biến một signal/cơ hội thành brief chiến lược ngắn: ai nói, nói gì, ở đâu, khi nào, vì sao, và phản ứng thế nào.",
        "chart": "modeMap",
        "data": data,
        "analysis": analysis,
        "action": {
            "guardrail": "Decision brief before campaign",
            "owner": "Marketing + CEO",
            "cta": "Generate 5W-1H Brief"
        },
        "evidence_query": "5W-1H Diagnosis",
    }
