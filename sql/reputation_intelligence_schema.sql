-- Reputation Intelligence Schema
-- Tables for Crisis Spike Monitor, Founder Watch, Qualified Negative, Topic Lifecycle

SET search_path TO meili_dashboard, public;

-- 1. Crisis Spike Alerts
-- Stores detected spikes in mention volume or negative sentiment
CREATE TABLE IF NOT EXISTS meili_dashboard.crisis_spike_alerts (
  spike_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  brand_id UUID NOT NULL,
  spike_date DATE NOT NULL,
  spike_hour INT, -- Hour of day (0-23) if hourly granularity
  metric_type TEXT NOT NULL, -- 'volume', 'negative_sentiment', 'rating_drop'
  baseline_value FLOAT NOT NULL,
  spike_value FLOAT NOT NULL,
  spike_magnitude FLOAT NOT NULL, -- How many std deviations above baseline
  severity TEXT NOT NULL, -- 'high', 'medium', 'low'
  trigger_keywords TEXT[], -- Keywords associated with spike
  evidence_mention_ids UUID[], -- Link to mentions that triggered spike
  status TEXT DEFAULT 'active', -- 'active', 'acknowledged', 'resolved'
  detected_at TIMESTAMP DEFAULT NOW(),
  CONSTRAINT fk_spike_brand FOREIGN KEY (brand_id) REFERENCES meili_dashboard.brands(brand_id) ON DELETE CASCADE
);

COMMENT ON TABLE meili_dashboard.crisis_spike_alerts IS 'Crisis spike detection for volume, sentiment, and rating anomalies';
COMMENT ON COLUMN meili_dashboard.crisis_spike_alerts.spike_magnitude IS 'Z-score or std deviations above baseline';
COMMENT ON COLUMN meili_dashboard.crisis_spike_alerts.severity IS 'high (>3 std), medium (2-3 std), low (1.5-2 std)';

CREATE INDEX idx_crisis_spike_brand_date ON meili_dashboard.crisis_spike_alerts(brand_id, spike_date DESC);
CREATE INDEX idx_crisis_spike_severity ON meili_dashboard.crisis_spike_alerts(severity, detected_at DESC);
CREATE INDEX idx_crisis_spike_status ON meili_dashboard.crisis_spike_alerts(status);

-- 2. Founder/CEO Mentions
-- Tracks mentions of brand founder or CEO
CREATE TABLE IF NOT EXISTS meili_dashboard.founder_mentions (
  founder_mention_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  brand_id UUID NOT NULL,
  mention_id UUID, -- Link to original mention
  review_id UUID, -- Link to original review
  source_platform TEXT NOT NULL, -- 'tiktok', 'facebook', etc.
  founder_name TEXT NOT NULL, -- Detected founder name
  mention_text TEXT NOT NULL,
  sentiment_label TEXT NOT NULL, -- 'positive', 'negative', 'neutral', 'mixed'
  sentiment_score FLOAT, -- -1 to 1
  risk_level TEXT, -- 'high', 'medium', 'low' (based on negative sentiment + reach)
  context_type TEXT, -- 'brand_association', 'personal_attack', 'praise', 'neutral_mention'
  detected_at TIMESTAMP DEFAULT NOW(),
  mention_date DATE NOT NULL,
  CONSTRAINT fk_founder_brand FOREIGN KEY (brand_id) REFERENCES meili_dashboard.brands(brand_id) ON DELETE CASCADE
);

COMMENT ON TABLE meili_dashboard.founder_mentions IS 'Track founder/CEO mentions for reputation monitoring';
COMMENT ON COLUMN meili_dashboard.founder_mentions.context_type IS 'Type of founder mention context';

CREATE INDEX idx_founder_brand_date ON meili_dashboard.founder_mentions(brand_id, mention_date DESC);
CREATE INDEX idx_founder_risk ON meili_dashboard.founder_mentions(risk_level, detected_at DESC);
CREATE INDEX idx_founder_sentiment ON meili_dashboard.founder_mentions(sentiment_label);

-- 3. Source Quality Scores
-- Assigns trust/quality scores to different platforms and sources
CREATE TABLE IF NOT EXISTS meili_dashboard.source_quality_config (
  source_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  platform TEXT NOT NULL UNIQUE, -- 'google_maps', 'shopeefood', 'facebook', etc.
  trust_score FLOAT NOT NULL DEFAULT 0.5, -- 0.0 (low trust) to 1.0 (high trust)
  noise_level TEXT NOT NULL DEFAULT 'medium', -- 'low', 'medium', 'high'
  weight_multiplier FLOAT NOT NULL DEFAULT 1.0, -- How much to weight this source
  is_review_platform BOOLEAN DEFAULT FALSE, -- True for Google/delivery apps
  requires_verification BOOLEAN DEFAULT FALSE, -- True for user-generated content
  created_at TIMESTAMP DEFAULT NOW()
);

COMMENT ON TABLE meili_dashboard.source_quality_config IS 'Platform trust scores for qualified negative analysis';

-- Insert default quality scores
INSERT INTO meili_dashboard.source_quality_config (platform, trust_score, noise_level, is_review_platform, weight_multiplier)
VALUES
  ('google_maps', 0.90, 'low', TRUE, 1.5),
  ('shopeefood', 0.85, 'low', TRUE, 1.4),
  ('grabfood', 0.85, 'low', TRUE, 1.4),
  ('facebook', 0.50, 'high', FALSE, 0.7),
  ('tiktok', 0.45, 'high', FALSE, 0.6),
  ('instagram', 0.55, 'medium', FALSE, 0.8),
  ('threads', 0.50, 'medium', FALSE, 0.7),
  ('youtube', 0.60, 'medium', FALSE, 0.9)
ON CONFLICT (platform) DO NOTHING;

-- 4. Qualified Negative Summary
-- Aggregated qualified negative metrics by source
CREATE TABLE IF NOT EXISTS meili_dashboard.qualified_negative_summary (
  summary_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  brand_id UUID NOT NULL,
  platform TEXT NOT NULL,
  snapshot_date DATE NOT NULL,
  total_negative_count INT NOT NULL DEFAULT 0,
  qualified_negative_count INT NOT NULL DEFAULT 0, -- High-trust negatives
  noise_negative_count INT NOT NULL DEFAULT 0, -- Low-trust negatives
  qualified_percentage FLOAT NOT NULL DEFAULT 0, -- % of qualified negatives
  avg_trust_score FLOAT NOT NULL DEFAULT 0,
  top_topics TEXT[], -- Top topics in qualified negatives
  created_at TIMESTAMP DEFAULT NOW(),
  CONSTRAINT fk_qualified_brand FOREIGN KEY (brand_id) REFERENCES meili_dashboard.brands(brand_id) ON DELETE CASCADE,
  UNIQUE(brand_id, platform, snapshot_date)
);

COMMENT ON TABLE meili_dashboard.qualified_negative_summary IS 'Daily summary of qualified vs noisy negative signals';

CREATE INDEX idx_qualified_brand_date ON meili_dashboard.qualified_negative_summary(brand_id, snapshot_date DESC);
CREATE INDEX idx_qualified_platform ON meili_dashboard.qualified_negative_summary(platform);

-- 5. Topic Lifecycle
-- Tracks topics through their lifecycle stages
CREATE TABLE IF NOT EXISTS meili_dashboard.topic_lifecycle (
  lifecycle_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  brand_id UUID NOT NULL,
  topic_name TEXT NOT NULL,
  topic_category TEXT, -- 'price_value', 'delivery', 'food_quality', etc.
  lifecycle_stage TEXT NOT NULL, -- 'detect', 'monitor', 'fix', 'recover', 'amplify'
  velocity TEXT, -- 'rising', 'stable', 'declining'
  volume_7d INT NOT NULL DEFAULT 0, -- Volume in last 7 days
  volume_change_pct FLOAT, -- % change vs previous period
  sentiment_trend TEXT, -- 'improving', 'stable', 'worsening'
  avg_sentiment_score FLOAT,
  recommended_action TEXT, -- Action description
  guardrail TEXT, -- 'Monitor First', 'Fix First', 'Contain', etc.
  owner TEXT, -- Team responsible
  evidence_mention_ids UUID[], -- Link to supporting mentions
  last_updated TIMESTAMP DEFAULT NOW(),
  stage_entered_at TIMESTAMP DEFAULT NOW(),
  CONSTRAINT fk_topic_brand FOREIGN KEY (brand_id) REFERENCES meili_dashboard.brands(brand_id) ON DELETE CASCADE,
  UNIQUE(brand_id, topic_name)
);

COMMENT ON TABLE meili_dashboard.topic_lifecycle IS 'Track topics through lifecycle stages for proactive management';
COMMENT ON COLUMN meili_dashboard.topic_lifecycle.lifecycle_stage IS 'detect: new emerging, monitor: watching, fix: action needed, recover: measuring recovery, amplify: promote positive';

CREATE INDEX idx_topic_brand_stage ON meili_dashboard.topic_lifecycle(brand_id, lifecycle_stage);
CREATE INDEX idx_topic_velocity ON meili_dashboard.topic_lifecycle(velocity, volume_7d DESC);
CREATE INDEX idx_topic_updated ON meili_dashboard.topic_lifecycle(last_updated DESC);

-- 6. Campaign Intelligence
-- Tracks competitor campaigns for benchmark
CREATE TABLE IF NOT EXISTS meili_dashboard.campaign_intelligence (
  campaign_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  brand_id UUID NOT NULL, -- Our brand (for context)
  competitor_name TEXT NOT NULL,
  campaign_name TEXT NOT NULL,
  campaign_type TEXT, -- 'delivery_deal', 'family_combo', 'premium_launch', etc.
  start_date DATE,
  end_date DATE,
  -- Benchmark metrics
  qualified_users_score FLOAT, -- 0-100 score for target audience quality
  buzz_score FLOAT, -- 0-100 score for social buzz volume
  object_mention_score FLOAT, -- 0-100 score for product/offer clarity
  sentiment_score FLOAT, -- 0-100 score for sentiment
  overall_score FLOAT, -- Weighted average
  -- Evidence
  mention_count INT DEFAULT 0,
  reach_estimate INT DEFAULT 0,
  top_keywords TEXT[],
  evidence_mention_ids UUID[],
  detected_at TIMESTAMP DEFAULT NOW(),
  CONSTRAINT fk_campaign_brand FOREIGN KEY (brand_id) REFERENCES meili_dashboard.brands(brand_id) ON DELETE CASCADE
);

COMMENT ON TABLE meili_dashboard.campaign_intelligence IS 'Competitor campaign tracking and benchmarking';

CREATE INDEX idx_campaign_brand ON meili_dashboard.campaign_intelligence(brand_id, detected_at DESC);
CREATE INDEX idx_campaign_competitor ON meili_dashboard.campaign_intelligence(competitor_name);
CREATE INDEX idx_campaign_score ON meili_dashboard.campaign_intelligence(overall_score DESC);

-- 7. Content Pattern Analysis
-- Winning content patterns from competitors
CREATE TABLE IF NOT EXISTS meili_dashboard.content_patterns (
  pattern_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  brand_id UUID NOT NULL,
  pattern_name TEXT NOT NULL, -- 'clear_combo_mechanic', 'fast_delivery_promise', etc.
  pattern_description TEXT,
  pattern_strength FLOAT NOT NULL, -- 0-100 score
  risk_level TEXT, -- 'high', 'medium', 'low' (risk if we copy this pattern)
  competitor_examples TEXT[], -- Examples from competitors
  recommended_response TEXT, -- 'similar', 'different', 'merge', 'counter', 'exploit'
  response_rationale TEXT, -- Why this response mode
  evidence_mention_ids UUID[],
  detected_at TIMESTAMP DEFAULT NOW(),
  CONSTRAINT fk_pattern_brand FOREIGN KEY (brand_id) REFERENCES meili_dashboard.brands(brand_id) ON DELETE CASCADE
);

COMMENT ON TABLE meili_dashboard.content_patterns IS 'Winning content patterns for competitive response';

CREATE INDEX idx_pattern_brand ON meili_dashboard.content_patterns(brand_id, pattern_strength DESC);
CREATE INDEX idx_pattern_response ON meili_dashboard.content_patterns(recommended_response);

-- 8. Signal Diagnosis (5W-1H)
-- Structured signal diagnosis for decision briefs
CREATE TABLE IF NOT EXISTS meili_dashboard.signal_diagnosis (
  diagnosis_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  brand_id UUID NOT NULL,
  signal_name TEXT NOT NULL, -- e.g., "Office Lunch Set Opportunity"
  signal_type TEXT, -- 'opportunity', 'threat', 'trend'
  -- 5W-1H breakdown
  who_audience TEXT, -- Target audience identified
  what_need TEXT, -- What customer needs/wants
  where_source TEXT, -- Where signals come from
  when_timing TEXT, -- When this matters (time window)
  why_reason TEXT, -- Why this is happening
  how_action TEXT, -- How to respond
  -- Metrics
  confidence_score FLOAT, -- 0-100
  priority TEXT, -- 'high', 'medium', 'low'
  evidence_mention_ids UUID[],
  recommended_next_step TEXT,
  owner TEXT,
  created_at TIMESTAMP DEFAULT NOW(),
  CONSTRAINT fk_diagnosis_brand FOREIGN KEY (brand_id) REFERENCES meili_dashboard.brands(brand_id) ON DELETE CASCADE
);

COMMENT ON TABLE meili_dashboard.signal_diagnosis IS '5W-1H structured signal diagnosis for decision briefs';

CREATE INDEX idx_diagnosis_brand ON meili_dashboard.signal_diagnosis(brand_id, created_at DESC);
CREATE INDEX idx_diagnosis_priority ON meili_dashboard.signal_diagnosis(priority, confidence_score DESC);

-- Grant permissions
GRANT SELECT, INSERT, UPDATE, DELETE ON meili_dashboard.crisis_spike_alerts TO PUBLIC;
GRANT SELECT, INSERT, UPDATE, DELETE ON meili_dashboard.founder_mentions TO PUBLIC;
GRANT SELECT ON meili_dashboard.source_quality_config TO PUBLIC;
GRANT SELECT, INSERT, UPDATE, DELETE ON meili_dashboard.qualified_negative_summary TO PUBLIC;
GRANT SELECT, INSERT, UPDATE, DELETE ON meili_dashboard.topic_lifecycle TO PUBLIC;
GRANT SELECT, INSERT, UPDATE, DELETE ON meili_dashboard.campaign_intelligence TO PUBLIC;
GRANT SELECT, INSERT, UPDATE, DELETE ON meili_dashboard.content_patterns TO PUBLIC;
GRANT SELECT, INSERT, UPDATE, DELETE ON meili_dashboard.signal_diagnosis TO PUBLIC;
