"""
Code snippet để add vào _reputation_modules trong repository.py

Insert ngay trước dòng return modules (line 2101)
"""

# Add 4 new modules từ mockup
# 1. Crisis Spike Monitor (with real data)
crisis_module = self._build_crisis_spike_module_v2()
modules.append(crisis_module)

# 2. Founder/CEO Watch
founder_module = self._build_founder_watch_module_v2()
modules.append(founder_module)

# 3. Qualified Negative Signal
qualified_module = self._build_qualified_negative_module_v2()
modules.append(qualified_module)

# 4. Topic Lifecycle
lifecycle_module = self._build_topic_lifecycle_module_v2()
modules.append(lifecycle_module)

return modules


# ===== BUILD METHODS (add sau _fetch methods) =====

def _build_crisis_spike_module_v2(self) -> dict:
    """Build Crisis Spike Monitor module with real spike data"""
    spikes = self._fetch_crisis_spikes(days=7)

    if not spikes:
        # Fallback với mock data nếu chưa có spikes
        return {
            "title": "Crisis Spike Monitor",
            "takeaway": "Chart đầu tiên phải cho thấy có spike bất thường hay không.",
            "chart": "line",
            "data": {
                "labels": ["10:00", "11:00", "12:00", "13:00", "14:00", "15:00", "16:00", "17:00"],
                "series": [{"name": "Mentions", "values": [4, 5, 6, 7, 8, 9, 10, 12], "color": "#1f66f5"}]
            },
            "analysis": ["No crisis spikes detected", "System monitoring for anomalies"],
            "action": {"guardrail": "Monitor First", "owner": "CS + Ops", "cta": "Open Evidence"},
            "evidence_query": "Crisis Spike Monitor",
        }

    # Build từ real data
    from collections import defaultdict
    spike_by_hour = defaultdict(int)
    for spike in spikes:
        hour = spike.get('spike_hour', 12)
        spike_by_hour[hour] += 1

    hours = sorted(spike_by_hour.keys())[-8:] if spike_by_hour else list(range(10, 18))
    labels = [f"{h}:00" for h in hours]
    values = [spike_by_hour.get(h, 0) for h in hours]

    high_severity = [s for s in spikes if s.get('severity') == 'high']
    analysis = []
    if high_severity:
        analysis.append(f"{len(high_severity)} high-severity spikes detected in last 7 days")
        top = high_severity[0]
        if top.get('trigger_keywords'):
            keywords = ', '.join(top['trigger_keywords'][:3])
            analysis.append(f"Trigger: {keywords}")
    else:
        analysis.append("Biểu đồ này dùng để phát hiện spike bất thường")
        analysis.append("Chưa có spike đáng lo ngại trong 7 ngày gần đây")

    return {
        "title": "Crisis Spike Monitor",
        "takeaway": "Chart đầu tiên phải cho thấy có spike bất thường hay không.",
        "chart": "line",
        "data": {
            "labels": labels,
            "series": [{"name": "Spike alerts", "values": values, "color": "#d94444"}]
        },
        "analysis": analysis,
        "action": {"guardrail": "Evidence-backed module", "owner": "CS + Ops", "cta": "Open Evidence"},
        "evidence_query": "Crisis Spike Monitor",
    }

def _build_founder_watch_module_v2(self) -> dict:
    """Build Founder/CEO Watch with real mentions"""
    mentions = self._fetch_founder_mentions(days=42)

    if not mentions:
        return {
            "title": "Founder / CEO Reputation Watch",
            "takeaway": "Với founder-led brand, sentiment quanh CEO/founder có thể ảnh hưởng trực tiếp đến brand trust.",
            "chart": "line",
            "data": {
                "labels": ["W1", "W2", "W3", "W4", "W5", "W6"],
                "series": [
                    {"name": "Founder mentions", "values": [0, 0, 0, 0, 0, 0], "color": "#1f66f5"},
                    {"name": "Negative risk", "values": [0, 0, 0, 0, 0, 0], "color": "#d94444"}
                ]
            },
            "analysis": ["No founder mentions detected", "Add founder name to tracking if needed"],
            "action": {"guardrail": "Monitor First", "owner": "CEO + PR", "cta": "Open Founder Watch"},
            "evidence_query": "Founder Watch",
        }

    # Group by week
    from collections import defaultdict
    from datetime import datetime, timedelta

    week_data = defaultdict(lambda: {'total': 0, 'negative': 0})
    for m in mentions:
        try:
            date = datetime.strptime(m['mention_date'], '%Y-%m-%d')
            week_num = date.isocalendar()[1]
            week_key = f"W{week_num}"
            week_data[week_key]['total'] += 1
            if m.get('sentiment_label') == 'negative':
                week_data[week_key]['negative'] += 1
        except:
            pass

    weeks = sorted(week_data.keys())[-6:]
    total_values = [week_data[w]['total'] for w in weeks]
    negative_values = [week_data[w]['negative'] for w in weeks]

    high_risk = [m for m in mentions if m.get('risk_level') == 'high']
    analysis = []
    if high_risk:
        analysis.append(f"{len(high_risk)} high-risk mentions cần theo dõi")
    else:
        analysis.append("Founder mentions đang ổn định, chưa có risk cao")
    analysis.append("Không action nếu chưa vượt ngưỡng crisis")

    return {
        "title": "Founder / CEO Reputation Watch",
        "takeaway": "Với founder-led brand, sentiment quanh CEO/founder có thể ảnh hưởng trực tiếp đến brand trust.",
        "chart": "line",
        "data": {
            "labels": weeks if weeks else ["W1", "W2", "W3", "W4", "W5", "W6"],
            "series": [
                {"name": "Founder mentions", "values": total_values if total_values else [0]*6, "color": "#1f66f5"},
                {"name": "Negative risk", "values": negative_values if negative_values else [0]*6, "color": "#d94444"}
            ]
        },
        "analysis": analysis,
        "action": {"guardrail": "Monitor First", "owner": "CEO + PR", "cta": "Open Founder Watch"},
        "evidence_query": "Founder Watch",
    }

def _build_qualified_negative_module_v2(self) -> dict:
    """Build Qualified Negative Signal with trust scores"""
    summary = self._fetch_qualified_negative_summary()

    if not summary:
        return {
            "title": "Qualified Negative Signal",
            "takeaway": "Một negative từ khách thật/review thật quan trọng hơn nhiều negative từ noise.",
            "chart": "stacked",
            "data": [
                ["Google Review", 12, 18, 70],
                ["Delivery app", 8, 12, 80],
                ["Facebook Group", 25, 45, 30],
                ["TikTok Comment", 34, 46, 20],
            ],
            "analysis": ["Chưa có qualified negative data", "Chạy analysis jobs để phân loại"],
            "action": {"guardrail": "Prioritize high-trust negative", "owner": "CS + Ops", "cta": "Run Analysis"},
            "evidence_query": "Qualified Negative",
        }

    # Build stacked data from real summary
    data = []
    for row in summary[:5]:
        platform_name = row['platform'].replace('_', ' ').title()
        data.append([
            platform_name,
            row['qualified_negative_count'],
            row['noise_negative_count'],
            int(row['qualified_percentage'])
        ])

    high_trust = [r for r in summary if r.get('avg_trust_score', 0) > 0.7]
    analysis = []
    if high_trust:
        platforms = ', '.join(r['platform'].title() for r in high_trust[:2])
        analysis.append(f"{platforms} có qualified negative cao → ưu tiên fix")
    else:
        analysis.append("Review platforms có trust score cao nhất")
    analysis.append("Facebook/TikTok có nhiều noise, cần monitor velocity")

    return {
        "title": "Qualified Negative Signal",
        "takeaway": "Một negative từ khách thật/review thật quan trọng hơn nhiều negative từ noise. Cụm 1 cần ưu tiên theo chất lượng nguồn.",
        "chart": "stacked",
        "data": data,
        "analysis": analysis,
        "action": {"guardrail": "Prioritize high-trust negative", "owner": "CS + Ops + PR", "cta": "Open Qualified Negative"},
        "evidence_query": "Qualified Negative",
    }

def _build_topic_lifecycle_module_v2(self) -> dict:
    """Build Topic Lifecycle tracker"""
    topics = self._fetch_topic_lifecycle()

    if not topics:
        return {
            "title": "Sensitive Topic Lifecycle",
            "takeaway": "Các keyword nhạy cảm cần được xem theo lifecycle: mới nổi, tăng tốc, lan rộng hay đã giảm.",
            "chart": "timeline",
            "data": [
                ["Detect", "Giá cao / không đáng tiền", "Topic rising, cần value proof"],
                ["Monitor", "Thái độ nhân viên", "Volume thấp nhưng sentiment xấu"],
                ["Fix", "Giao nguội", "High trust negative từ delivery app"],
            ],
            "analysis": ["Chưa có topic lifecycle data", "System sẽ tự detect emerging topics"],
            "action": {"guardrail": "Contain -> Fix -> Recover", "owner": "MKT + CS + Ops", "cta": "Track Topics"},
            "evidence_query": "Topic Lifecycle",
        }

    # Build timeline từ real topics
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
        description = topic.get('recommended_action', 'Monitor topic')
        data.append([stage, topic['topic_name'], description])

    fix_stage = [t for t in topics if t['lifecycle_stage'] == 'fix']
    analysis = []
    if fix_stage:
        analysis.append(f"{len(fix_stage)} topics cần fix ngay - high priority")
    else:
        analysis.append("Topics đang được monitor, chưa có vấn đề cấp bách")
    analysis.append("Lifecycle giúp chọn guardrail đúng: Monitor/Fix/Recover")

    return {
        "title": "Sensitive Topic Lifecycle",
        "takeaway": "Các keyword nhạy cảm cần được xem theo lifecycle: mới nổi, tăng tốc, lan rộng hay đã giảm.",
        "chart": "timeline",
        "data": data,
        "analysis": analysis,
        "action": {"guardrail": "Contain -> Fix -> Recover", "owner": "MKT + CS + Ops", "cta": "Open Sensitive Topic"},
        "evidence_query": "Topic Lifecycle",
    }
