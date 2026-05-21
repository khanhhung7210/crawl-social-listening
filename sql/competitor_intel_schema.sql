-- Competitor Intelligence Schema for Meili Dashboard
-- Stores competitive analysis data extracted from mentions and reviews

-- 1. Competitor Intelligence Scores
CREATE TABLE IF NOT EXISTS meili_dashboard.competitor_intel (
  intel_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  brand_id UUID NOT NULL REFERENCES meili_dashboard.brands(brand_id) ON DELETE CASCADE,
  competitor_name TEXT NOT NULL,
  dimension TEXT NOT NULL, -- 'delivery', 'value', 'family', 'experience', 'social_buzz', 'premium'
  our_score FLOAT NOT NULL DEFAULT 0,
  competitor_score FLOAT NOT NULL DEFAULT 0,
  pressure_level TEXT, -- 'high', 'medium', 'low'
  source_mention_count INT DEFAULT 0,
  evidence_quotes JSONB DEFAULT '[]'::jsonb,
  analyzed_at TIMESTAMP DEFAULT NOW(),
  created_at TIMESTAMP DEFAULT NOW(),
  UNIQUE (brand_id, competitor_name, dimension)
);

COMMENT ON TABLE meili_dashboard.competitor_intel IS 'Competitive pressure scores across multiple dimensions';
COMMENT ON COLUMN meili_dashboard.competitor_intel.dimension IS 'Competitive dimension: delivery, value, family, experience, social_buzz, premium';
COMMENT ON COLUMN meili_dashboard.competitor_intel.our_score IS 'Our brand score (0-100) in this dimension';
COMMENT ON COLUMN meili_dashboard.competitor_intel.competitor_score IS 'Competitor score (0-100) in this dimension';
COMMENT ON COLUMN meili_dashboard.competitor_intel.pressure_level IS 'High if competitor_score > our_score + 20, Medium if gap < 20, Low otherwise';

CREATE INDEX IF NOT EXISTS idx_competitor_intel_brand ON meili_dashboard.competitor_intel(brand_id);
CREATE INDEX IF NOT EXISTS idx_competitor_intel_dimension ON meili_dashboard.competitor_intel(dimension);
CREATE INDEX IF NOT EXISTS idx_competitor_intel_pressure ON meili_dashboard.competitor_intel(pressure_level);

-- 2. Competitor Response Recommendations
CREATE TABLE IF NOT EXISTS meili_dashboard.competitor_responses (
  response_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  brand_id UUID NOT NULL REFERENCES meili_dashboard.brands(brand_id) ON DELETE CASCADE,
  competitor_name TEXT NOT NULL,
  threat_or_pattern TEXT NOT NULL,
  response_mode TEXT NOT NULL, -- 'similar', 'different', 'merge', 'counter', 'exploit'
  action_recommendation TEXT NOT NULL,
  priority TEXT NOT NULL, -- 'high', 'medium', 'low'
  evidence_mentions JSONB DEFAULT '[]'::jsonb,
  confidence_score FLOAT,
  generated_at TIMESTAMP DEFAULT NOW(),
  created_at TIMESTAMP DEFAULT NOW()
);

COMMENT ON TABLE meili_dashboard.competitor_responses IS 'AI-generated competitive response recommendations';
COMMENT ON COLUMN meili_dashboard.competitor_responses.response_mode IS 'Strategic response: similar (copy), different (differentiate), merge (combine), counter (attack), exploit (weakness)';
COMMENT ON COLUMN meili_dashboard.competitor_responses.action_recommendation IS 'Specific actionable recommendation';
COMMENT ON COLUMN meili_dashboard.competitor_responses.evidence_mentions IS 'Array of mention IDs supporting this recommendation';

CREATE INDEX IF NOT EXISTS idx_competitor_responses_brand ON meili_dashboard.competitor_responses(brand_id);
CREATE INDEX IF NOT EXISTS idx_competitor_responses_mode ON meili_dashboard.competitor_responses(response_mode);
CREATE INDEX IF NOT EXISTS idx_competitor_responses_priority ON meili_dashboard.competitor_responses(priority);

-- 3. Competitor Mention Detections
CREATE TABLE IF NOT EXISTS meili_dashboard.competitor_mention_detections (
  detection_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  mention_id UUID REFERENCES meili_dashboard.mentions(mention_id) ON DELETE CASCADE,
  review_id UUID REFERENCES meili_dashboard.reviews(review_id) ON DELETE CASCADE,
  brand_id UUID NOT NULL REFERENCES meili_dashboard.brands(brand_id) ON DELETE CASCADE,
  competitor_name TEXT NOT NULL,
  comparison_type TEXT NOT NULL, -- 'competitor_better', 'we_better', 'neutral'
  topic TEXT, -- 'delivery', 'price', 'taste', 'quality', 'service', etc.
  strength_score FLOAT, -- 0-100
  evidence_quote TEXT,
  detected_at TIMESTAMP DEFAULT NOW(),
  created_at TIMESTAMP DEFAULT NOW(),
  CHECK (mention_id IS NOT NULL OR review_id IS NOT NULL)
);

COMMENT ON TABLE meili_dashboard.competitor_mention_detections IS 'Individual mentions/reviews that reference competitors';
COMMENT ON COLUMN meili_dashboard.competitor_mention_detections.comparison_type IS 'competitor_better: Competitor portrayed better | we_better: We are better | neutral: No comparison';
COMMENT ON COLUMN meili_dashboard.competitor_mention_detections.strength_score IS 'How strong the competitive pressure is (0-100)';

CREATE INDEX IF NOT EXISTS idx_competitor_detections_brand ON meili_dashboard.competitor_mention_detections(brand_id);
CREATE INDEX IF NOT EXISTS idx_competitor_detections_competitor ON meili_dashboard.competitor_mention_detections(competitor_name);
CREATE INDEX IF NOT EXISTS idx_competitor_detections_topic ON meili_dashboard.competitor_mention_detections(topic);
CREATE INDEX IF NOT EXISTS idx_competitor_detections_mention ON meili_dashboard.competitor_mention_detections(mention_id) WHERE mention_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_competitor_detections_review ON meili_dashboard.competitor_mention_detections(review_id) WHERE review_id IS NOT NULL;

-- 4. Competitor Patterns (Winning tactics observed)
CREATE TABLE IF NOT EXISTS meili_dashboard.competitor_patterns (
  pattern_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  brand_id UUID NOT NULL REFERENCES meili_dashboard.brands(brand_id) ON DELETE CASCADE,
  competitor_name TEXT NOT NULL,
  pattern_name TEXT NOT NULL, -- 'family_combo', 'delivery_deal', 'premium_storytelling', 'local_value', etc.
  pattern_strength FLOAT, -- 0-100
  mention_count INT DEFAULT 0,
  description TEXT,
  examples JSONB DEFAULT '[]'::jsonb,
  analyzed_at TIMESTAMP DEFAULT NOW(),
  created_at TIMESTAMP DEFAULT NOW(),
  UNIQUE (brand_id, competitor_name, pattern_name)
);

COMMENT ON TABLE meili_dashboard.competitor_patterns IS 'Winning patterns/tactics observed from competitors';
COMMENT ON COLUMN meili_dashboard.competitor_patterns.pattern_strength IS 'How effective/strong this pattern is (0-100)';

CREATE INDEX IF NOT EXISTS idx_competitor_patterns_brand ON meili_dashboard.competitor_patterns(brand_id);
CREATE INDEX IF NOT EXISTS idx_competitor_patterns_competitor ON meili_dashboard.competitor_patterns(competitor_name);

-- Grants
GRANT SELECT, INSERT, UPDATE, DELETE ON meili_dashboard.competitor_intel TO PUBLIC;
GRANT SELECT, INSERT, UPDATE, DELETE ON meili_dashboard.competitor_responses TO PUBLIC;
GRANT SELECT, INSERT, UPDATE, DELETE ON meili_dashboard.competitor_mention_detections TO PUBLIC;
GRANT SELECT, INSERT, UPDATE, DELETE ON meili_dashboard.competitor_patterns TO PUBLIC;
