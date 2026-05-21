"""
Competitor Intelligence Repository Methods

Add these methods to PostgresDashboardRepository class in repository.py

These methods fetch competitor data from:
- competitor_intel
- competitor_responses
- competitor_patterns
- competitor_mention_detections
"""

# Helper methods to fetch competitor data from PostgreSQL

def _fetch_competitor_pressure(self) -> list[dict]:
    """Fetch competitive pressure scores across dimensions"""
    return self._query_json(
        f"""
        SELECT COALESCE(json_agg(row_to_json(t) ORDER BY pressure_level, (competitor_score - our_score) DESC), '[]'::json)
        FROM (
          SELECT
            competitor_name,
            dimension,
            our_score::float,
            competitor_score::float,
            pressure_level,
            source_mention_count::int
          FROM {self.schema}.competitor_intel
          WHERE brand_id = (SELECT brand_id FROM {self.schema}.brands WHERE brand_slug = {sql_str(self.brand_slug)})
            AND competitor_name != '__our_brand__'
        ) t;
        """
    )

def _fetch_our_brand_scores(self) -> dict:
    """Fetch our brand's scores across dimensions"""
    rows = self._query_json(
        f"""
        SELECT COALESCE(json_agg(row_to_json(t)), '[]'::json)
        FROM (
          SELECT
            dimension,
            our_score::float
          FROM {self.schema}.competitor_intel
          WHERE brand_id = (SELECT brand_id FROM {self.schema}.brands WHERE brand_slug = {sql_str(self.brand_slug)})
            AND competitor_name = '__our_brand__'
        ) t;
        """
    )
    return {row['dimension']: row['our_score'] for row in rows}

def _fetch_competitor_responses(self) -> list[dict]:
    """Fetch AI-generated competitive response recommendations"""
    return self._query_json(
        f"""
        SELECT COALESCE(json_agg(row_to_json(t) ORDER BY
          CASE priority WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
          generated_at DESC
        ), '[]'::json)
        FROM (
          SELECT
            competitor_name,
            threat_or_pattern,
            response_mode,
            action_recommendation,
            priority,
            evidence_mentions::jsonb,
            confidence_score::float
          FROM {self.schema}.competitor_responses
          WHERE brand_id = (SELECT brand_id FROM {self.schema}.brands WHERE brand_slug = {sql_str(self.brand_slug)})
          LIMIT 20
        ) t;
        """
    )

def _fetch_competitor_patterns(self) -> list[dict]:
    """Fetch winning patterns identified from competitors"""
    return self._query_json(
        f"""
        SELECT COALESCE(json_agg(row_to_json(t) ORDER BY pattern_strength DESC), '[]'::json)
        FROM (
          SELECT
            competitor_name,
            pattern_name,
            pattern_strength::float,
            description
          FROM {self.schema}.competitor_patterns
          WHERE brand_id = (SELECT brand_id FROM {self.schema}.brands WHERE brand_slug = {sql_str(self.brand_slug)})
        ) t;
        """
    )

def _fetch_top_competitor_detections(self, limit: int = 20) -> list[dict]:
    """Fetch recent high-strength competitor mentions"""
    return self._query_json(
        f"""
        SELECT COALESCE(json_agg(row_to_json(t) ORDER BY strength_score DESC, detected_at DESC), '[]'::json)
        FROM (
          SELECT
            competitor_name,
            comparison_type,
            topic,
            strength_score::float,
            evidence_quote,
            detected_at
          FROM {self.schema}.competitor_mention_detections
          WHERE brand_id = (SELECT brand_id FROM {self.schema}.brands WHERE brand_slug = {sql_str(self.brand_slug)})
          ORDER BY strength_score DESC, detected_at DESC
          LIMIT {int(limit)}
        ) t;
        """
    )

# Replace existing _competitor_top_cards method

def _competitor_top_cards(self, platform_summary: list[dict], branch_intelligence: list[dict]) -> list[dict]:
    """Build top cards for Competitor Radar screen from real competitor data"""
    pressure_data = self._fetch_competitor_pressure()
    responses = self._fetch_competitor_responses()

    if not pressure_data and not responses:
        # Fallback to placeholder if no competitor data yet
        return [
            {
                "tag": "NO DATA",
                "title": "Run competitor analysis first",
                "value": "0",
                "desc": "Execute: node scripts/dashboard/detect_competitor_mentions_openai.mjs",
                "owner": "Data Team",
                "guardrail": "Setup Required",
                "sev": "medium",
                "evidence_query": "Competitor setup",
                "evidence_kind": "competitor_setup",
            }
        ]

    # Find highest pressure threats
    high_pressure = [row for row in pressure_data if row.get('pressure_level') == 'high']
    medium_pressure = [row for row in pressure_data if row.get('pressure_level') == 'medium']

    # Find high priority recommendations
    high_priority_responses = [row for row in responses if row.get('priority') == 'high']

    # Our strengths (dimensions where we score > 70)
    our_scores = self._fetch_our_brand_scores()
    our_strengths = [(dim, score) for dim, score in our_scores.items() if score > 70]

    cards = []

    # Card 1: Highest pressure threat
    if high_pressure:
        top_threat = high_pressure[0]
        cards.append({
            "tag": "PRESSURE",
            "title": f"{top_threat['competitor_name']} {top_threat['dimension']}",
            "value": "High",
            "desc": f"Competitor score {top_threat['competitor_score']:.0f} vs our {top_threat['our_score']:.0f}",
            "owner": "Ops + Marketing",
            "guardrail": "Fix First" if top_threat['dimension'] == 'delivery' else "Monitor First",
            "sev": "high",
            "evidence_query": f"{top_threat['competitor_name']} pressure",
            "evidence_kind": f"competitor_pressure_{top_threat['dimension']}",
        })

    # Card 2: Top recommended response
    if high_priority_responses:
        top_response = high_priority_responses[0]
        cards.append({
            "tag": "PATTERN" if top_response['response_mode'] in ['similar', 'merge'] else "THREAT",
            "title": top_response['threat_or_pattern'][:50],
            "value": top_response['response_mode'].title(),
            "desc": top_response['action_recommendation'][:100],
            "owner": "Marketing",
            "guardrail": f"{top_response['response_mode'].title()} Mode",
            "sev": "high" if top_response['priority'] == 'high' else "medium",
            "evidence_query": top_response['threat_or_pattern'],
            "evidence_kind": f"competitor_response_{top_response['response_mode']}",
        })

    # Card 3: Medium pressure (value/family opportunity)
    if medium_pressure:
        for row in medium_pressure:
            if row['dimension'] in ['value', 'family']:
                cards.append({
                    "tag": "VALUE THREAT" if row['dimension'] == 'value' else "PATTERN",
                    "title": f"{row['competitor_name']} {row['dimension']}",
                    "value": "Medium",
                    "desc": f"Gap: {row['competitor_score'] - row['our_score']:.0f} points",
                    "owner": "Marketing",
                    "guardrail": "Monitor First",
                    "sev": "medium",
                    "evidence_query": f"{row['competitor_name']} {row['dimension']}",
                    "evidence_kind": f"competitor_{row['dimension']}_threat",
                })
                break

    # Card 4: Our strength
    if our_strengths:
        top_strength = max(our_strengths, key=lambda x: x[1])
        cards.append({
            "tag": "OWN STRENGTH",
            "title": f"Our {top_strength[0]} advantage",
            "value": "Strong",
            "desc": f"Score: {top_strength[1]:.0f}/100 - Amplify this strength",
            "owner": "Marketing",
            "guardrail": "Safe to Amplify",
            "sev": "low",
            "evidence_query": f"Our {top_strength[0]} strength",
            "evidence_kind": f"our_strength_{top_strength[0]}",
        })

    # Ensure we have 4 cards
    while len(cards) < 4:
        cards.append({
            "tag": "INFO",
            "title": "More data needed",
            "value": "N/A",
            "desc": "Run competitor analysis jobs to see more insights",
            "owner": "Data Team",
            "guardrail": "Monitor",
            "sev": "low",
            "evidence_query": "Competitor data",
            "evidence_kind": "competitor_info",
        })

    return cards[:4]

# Replace existing _competitor_headline method

def _competitor_headline(self, platform_summary: list[dict]) -> str:
    """Generate headline for Competitor Radar screen from real data"""
    responses = self._fetch_competitor_responses()
    pressure_data = self._fetch_competitor_pressure()

    if not responses and not pressure_data:
        return "Competitor Radar: Chạy competitor analysis jobs để hiển thị insights về đối thủ và chiến lược phản ứng."

    high_priority = [r for r in responses if r.get('priority') == 'high']
    high_pressure = [p for p in pressure_data if p.get('pressure_level') == 'high']

    threats = ", ".join(set(r['competitor_name'] for r in high_pressure[:3])) if high_pressure else "competitors"
    modes = ", ".join(set(r['response_mode'] for r in high_priority[:3])) if high_priority else "strategic responses"

    return f"Competitor insight: {len(high_pressure)} high-pressure threats from {threats}. Recommended modes: {modes}. Action-ready recommendations: {len(responses)}."

# Replace existing _competitor_modules method

def _competitor_modules(self, platform_summary: list[dict], branch_intelligence: list[dict], menu_highlights: list[dict]) -> list[dict]:
    """Build modules for Competitor Radar screen from real data"""
    pressure_data = self._fetch_competitor_pressure()
    patterns = self._fetch_competitor_patterns()
    responses = self._fetch_competitor_responses()
    our_scores = self._fetch_our_brand_scores()

    modules = []

    # Module 1: Competitive Pressure Radar
    if pressure_data and our_scores:
        radar_data = self._build_radar_chart_data(pressure_data, our_scores)
        modules.append({
            "title": "Competitive Pressure Radar",
            "takeaway": "So sánh brand với competitors trên 6 dimensions: Delivery, Value, Family, Experience, Social Buzz, Premium",
            "chart": "radar",
            "data": radar_data,
            "analysis": self._analyze_pressure_radar(pressure_data, our_scores),
            "action": {
                "guardrail": "Pressure-led response",
                "owner": "Marketing + Ops",
                "cta": "Prioritize Competitor Response",
            },
            "evidence_query": "Competitive Pressure Radar",
        })

    # Module 2: Winning Pattern Comparison
    if patterns:
        pattern_data = self._build_pattern_chart_data(patterns)
        modules.append({
            "title": "Winning Pattern Comparison",
            "takeaway": "Patterns nào competitors đang thắng: Family combo, Delivery deal, Premium storytelling, Local value",
            "chart": "groupedColumns",
            "data": pattern_data,
            "analysis": self._analyze_patterns(patterns),
            "action": {
                "guardrail": "Brand-fit before copy",
                "owner": "Marketing",
                "cta": "Select Response Mode",
            },
            "evidence_query": "Winning Pattern Comparison",
        })

    # Module 3: 5-Mode Response Map
    if responses:
        mode_map_data = self._build_mode_map_data(responses)
        modules.append({
            "title": "5-Mode Response Map",
            "takeaway": "Strategic responses: Similar (copy), Different (differentiate), Merge (combine), Counter (attack), Exploit (weakness)",
            "chart": "modeMap",
            "data": mode_map_data,
            "analysis": self._analyze_response_modes(responses),
            "action": {
                "guardrail": "Choose one mode clearly",
                "owner": "Marketing",
                "cta": "Execute Response",
            },
            "evidence_query": "5-Mode Response Map",
        })

    # Module 4: 7-Day Audit Funnel (mock for now, can be replaced with real metrics)
    modules.append({
        "title": "Competitive Intelligence Readiness",
        "takeaway": "Mức độ sẵn sàng của competitor data: Detections → Pressure Analysis → Responses → Execution",
        "chart": "funnel",
        "data": self._build_audit_funnel_data(pressure_data, patterns, responses),
        "analysis": [
            f"Đã phát hiện {len(pressure_data)} competitive pressure points",
            f"Đã trích xuất {len(patterns)} winning patterns",
            f"Đã tạo {len(responses)} response recommendations",
            "Ready để chuyển insights thành action",
        ],
        "action": {
            "guardrail": "Data-driven decisions",
            "owner": "Strategy",
            "cta": "Review Recommendations",
        },
        "evidence_query": "Competitive Intelligence Readiness",
    })

    return modules

# Helper methods for building chart data

def _build_radar_chart_data(self, pressure_data: list[dict], our_scores: dict) -> dict:
    """Build radar chart data structure"""
    dimensions = ['delivery', 'value', 'family', 'experience', 'social_buzz', 'premium']

    # Group by competitor
    competitors = {}
    for row in pressure_data:
        comp_name = row['competitor_name']
        if comp_name not in competitors:
            competitors[comp_name] = {}
        competitors[comp_name][row['dimension']] = row['competitor_score']

    # Build series
    series = []

    # Our brand
    series.append({
        "name": "Our Brand",
        "values": [our_scores.get(dim, 0) for dim in dimensions],
        "color": "#1f66f5"  # Blue
    })

    # Top 3 competitors by total score
    comp_totals = [(name, sum(scores.values())) for name, scores in competitors.items()]
    comp_totals.sort(key=lambda x: x[1], reverse=True)

    colors = ["#16a26a", "#d94444", "#6952d8"]  # Green, Red, Purple
    for i, (comp_name, _) in enumerate(comp_totals[:3]):
        series.append({
            "name": comp_name,
            "values": [competitors[comp_name].get(dim, 0) for dim in dimensions],
            "color": colors[i]
        })

    return {
        "axes": [dim.replace('_', ' ').title() for dim in dimensions],
        "series": series
    }

def _build_pattern_chart_data(self, patterns: list[dict]) -> dict:
    """Build grouped columns chart data for pattern comparison"""
    pattern_types = ['family_combo', 'delivery_deal', 'premium_storytelling', 'local_value']

    # Group by competitor
    by_competitor = {}
    for row in patterns:
        comp = row['competitor_name']
        if comp not in by_competitor:
            by_competitor[comp] = {}
        by_competitor[comp][row['pattern_name']] = row['pattern_strength']

    # Build series
    series = []
    colors = ["#1f66f5", "#16a26a", "#d94444", "#6952d8"]

    for i, (comp_name, comp_patterns) in enumerate(list(by_competitor.items())[:4]):
        series.append({
            "name": comp_name,
            "values": [comp_patterns.get(pt, 0) for pt in pattern_types],
            "color": colors[i % len(colors)]
        })

    return {
        "labels": [pt.replace('_', ' ').title() for pt in pattern_types],
        "series": series
    }

def _build_mode_map_data(self, responses: list[dict]) -> list[dict]:
    """Build 5-mode response map data"""
    mode_descriptions = {
        'similar': {'when': 'Pattern fits our brand DNA', 'example': ''},
        'different': {'when': "Don't compete directly (price war)", 'example': ''},
        'merge': {'when': 'Combine their pattern with our strength', 'example': ''},
        'counter': {'when': 'Attack after fixing internal issues', 'example': ''},
        'exploit': {'when': 'Highlight competitor weakness', 'example': ''},
    }

    # Fill in examples from actual responses
    for response in responses:
        mode = response['response_mode']
        if mode in mode_descriptions and not mode_descriptions[mode]['example']:
            mode_descriptions[mode]['example'] = response['action_recommendation'][:80]

    return [
        {
            'mode': mode.title(),
            'when': desc['when'],
            'example': desc['example'] or 'No example yet',
        }
        for mode, desc in mode_descriptions.items()
    ]

def _build_audit_funnel_data(self, pressure_data: list[dict], patterns: list[dict], responses: list[dict]) -> list[list]:
    """Build funnel data for competitive intelligence readiness"""
    total_detections = len(pressure_data) * 10  # Rough estimate
    total_pressure = len(pressure_data)
    total_patterns = len(patterns)
    total_responses = len(responses)

    return [
        ["Competitor mentions detected", 100],
        ["Pressure analyzed", int(total_pressure / max(total_detections / 100, 1) * 100) if total_detections else 0],
        ["Patterns identified", int(total_patterns / max(total_pressure, 1) * 100) if total_pressure else 0],
        ["Responses recommended", int(total_responses / max(total_patterns, 1) * 100) if total_patterns else 0],
        ["Ready for execution", 80 if responses else 0],
    ]

def _analyze_pressure_radar(self, pressure_data: list[dict], our_scores: dict) -> list[str]:
    """Generate analysis points for pressure radar"""
    high_pressure = [row for row in pressure_data if row.get('pressure_level') == 'high']
    our_strengths = [dim for dim, score in our_scores.items() if score > 70]

    analysis = []

    if high_pressure:
        threats = ", ".join(set(f"{row['competitor_name']} ({row['dimension']})" for row in high_pressure[:3]))
        analysis.append(f"High pressure from: {threats}")

    if our_strengths:
        analysis.append(f"Our strengths: {', '.join(our_strengths[:3])}")

    for row in high_pressure[:2]:
        gap = row['competitor_score'] - row['our_score']
        analysis.append(f"{row['competitor_name']} leads by {gap:.0f} points in {row['dimension']}")

    return analysis or ["No significant pressure detected"]

def _analyze_patterns(self, patterns: list[dict]) -> list[str]:
    """Generate analysis points for winning patterns"""
    analysis = []

    # Group by pattern type
    by_pattern = {}
    for row in patterns:
        pt = row['pattern_name']
        if pt not in by_pattern:
            by_pattern[pt] = []
        by_pattern[pt].append(row)

    for pattern_type, entries in by_pattern.items():
        strongest = max(entries, key=lambda x: x['pattern_strength'])
        analysis.append(f"{pattern_type.replace('_', ' ').title()}: {strongest['competitor_name']} leads with {strongest['pattern_strength']:.0f}/100")

    return analysis or ["No patterns identified yet"]

def _analyze_response_modes(self, responses: list[dict]) -> list[str]:
    """Generate analysis points for response modes"""
    by_mode = {}
    for row in responses:
        mode = row['response_mode']
        if mode not in by_mode:
            by_mode[mode] = 0
        by_mode[mode] += 1

    analysis = [
        f"{mode.title()}: {count} recommendation(s)"
        for mode, count in sorted(by_mode.items(), key=lambda x: x[1], reverse=True)
    ]

    high_priority = [r for r in responses if r.get('priority') == 'high']
    if high_priority:
        analysis.append(f"{len(high_priority)} high-priority actions to execute immediately")

    return analysis or ["No response recommendations yet"]
