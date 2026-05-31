from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = "meili_dashboard"
BRAND_SLUG = "meili-mi-bo-dai-loan"
PGDATABASE = os.getenv("PGDATABASE", "meili_dashboard")
PSQL_BIN = os.getenv("PSQL_BIN", "psql")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build crawl foundation tables for the Meili dashboard")
    parser.add_argument("--skip-schema", action="store_true", help="Do not apply sql/dashboard_crawl_foundation.sql")
    parser.add_argument("--dry-run", action="store_true", help="Print SQL instead of executing it")
    args = parser.parse_args()

    if not args.skip_schema:
        apply_schema(args.dry_run)

    sql = build_sql()
    if args.dry_run:
        print(sql)
        return 0
    run_sql(sql)
    print("crawl_foundation_metrics=built")
    return 0


def apply_schema(dry_run: bool) -> None:
    migration = PROJECT_ROOT / "sql" / "dashboard_crawl_foundation.sql"
    if dry_run:
        print(migration.read_text(encoding="utf-8"))
        return
    subprocess.run(
        [PSQL_BIN, PGDATABASE, "-v", "ON_ERROR_STOP=1", "-f", str(migration)],
        cwd=PROJECT_ROOT,
        check=True,
    )


def run_sql(sql: str) -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".sql", delete=False) as handle:
        handle.write(sql)
        path = Path(handle.name)
    try:
        subprocess.run(
            [PSQL_BIN, PGDATABASE, "-v", "ON_ERROR_STOP=1", "-f", str(path)],
            cwd=PROJECT_ROOT,
            check=True,
        )
    finally:
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def build_sql() -> str:
    return f"""
SET search_path TO {SCHEMA}, public;

WITH branch_terms AS (
  SELECT
    b.branch_id,
    b.branch_slug::text AS matched_text,
    'branch_slug' AS match_rule,
    90.0 AS confidence_score
  FROM branches b
  JOIN brands br ON br.brand_id = b.brand_id
  WHERE br.brand_slug = '{BRAND_SLUG}'
  UNION ALL
  SELECT
    b.branch_id,
    b.branch_name AS matched_text,
    'branch_name' AS match_rule,
    95.0 AS confidence_score
  FROM branches b
  JOIN brands br ON br.brand_id = b.brand_id
  WHERE br.brand_slug = '{BRAND_SLUG}'
  UNION ALL
  SELECT
    b.branch_id,
    alias_text AS matched_text,
    'branch_alias' AS match_rule,
    92.0 AS confidence_score
  FROM branches b
  JOIN brands br ON br.brand_id = b.brand_id
  CROSS JOIN LATERAL jsonb_array_elements_text(COALESCE(b.aliases, '[]'::jsonb)) alias_text
  WHERE br.brand_slug = '{BRAND_SLUG}'
  UNION ALL
  SELECT
    b.branch_id,
    b.address_line AS matched_text,
    'branch_address' AS match_rule,
    88.0 AS confidence_score
  FROM branches b
  JOIN brands br ON br.brand_id = b.brand_id
  WHERE br.brand_slug = '{BRAND_SLUG}' AND COALESCE(b.address_line, '') <> ''
)
INSERT INTO social_mention_branch_candidates (
  mention_id, branch_id, match_rule, confidence_score, matched_text
)
SELECT
  mention_id,
  branch_id,
  match_rule,
  confidence_score,
  matched_text
FROM (
  SELECT DISTINCT ON (m.mention_id, bt.branch_id, bt.match_rule)
    m.mention_id,
    bt.branch_id,
    bt.match_rule,
    bt.confidence_score,
    bt.matched_text
  FROM mentions m
  JOIN brands br ON br.brand_id = m.brand_id
  JOIN branch_terms bt ON CONCAT_WS(
      ' ',
      m.content_text,
      m.page_name,
      m.post_url,
      m.external_parent_id,
      m.raw_payload::text
    ) ILIKE '%' || bt.matched_text || '%'
  WHERE br.brand_slug = '{BRAND_SLUG}'
    AND m.platform IN ('facebook', 'tiktok', 'threads', 'instagram', 'youtube')
    AND LENGTH(COALESCE(bt.matched_text, '')) >= 4
  ORDER BY m.mention_id, bt.branch_id, bt.match_rule, bt.confidence_score DESC
) candidate_rows
ON CONFLICT (mention_id, branch_id, match_rule) DO UPDATE
SET confidence_score = EXCLUDED.confidence_score,
    matched_text = EXCLUDED.matched_text;

WITH ranked AS (
  SELECT
    candidate_id,
    mention_id,
    branch_id,
    ROW_NUMBER() OVER (PARTITION BY mention_id ORDER BY confidence_score DESC, created_at DESC) AS rn
  FROM social_mention_branch_candidates
  WHERE confidence_score >= 90
)
UPDATE mentions m
SET branch_id = ranked.branch_id,
    updated_at = NOW()
FROM ranked
WHERE ranked.mention_id = m.mention_id
  AND ranked.rn = 1
  AND m.branch_id IS NULL
  AND NOT EXISTS (
    SELECT 1
    FROM mentions existing
    WHERE existing.platform = m.platform
      AND existing.content_type = m.content_type
      AND existing.external_post_id = m.external_post_id
      AND existing.branch_id = ranked.branch_id
      AND existing.mention_id <> m.mention_id
  );

UPDATE mention_enrichments e
SET branch_id = m.branch_id
FROM mentions m
WHERE e.mention_id = m.mention_id
  AND e.branch_id IS DISTINCT FROM m.branch_id
  AND m.branch_id IS NOT NULL;

INSERT INTO mention_enrichments (
  mention_id, brand_id, branch_id, is_relevant_fnb, relevance_score, sentiment_label,
  sentiment_score, topic_label, issue_type, confidence_score, evidence_flag,
  needs_response, response_priority, enrichment_version
)
SELECT
  m.mention_id,
  m.brand_id,
  m.branch_id,
  TRUE,
  70,
  CASE
    WHEN lower(COALESCE(m.content_text, '')) ~ '(tệ|dở|lạnh|chậm|mắc|đắt|không ngon|thất vọng|bực|giao hàng|phàn nàn)' THEN 'negative'
    WHEN lower(COALESCE(m.content_text, '')) ~ '(ngon|thích|tuyệt|ổn|đỉnh|recommend|sẽ quay lại|hài lòng)' THEN 'positive'
    WHEN lower(COALESCE(m.content_text, '')) ~ '(muốn|thèm|ăn thử|ở đâu|giá|menu|đặt)' THEN 'demand'
    ELSE 'neutral'
  END,
  CASE
    WHEN lower(COALESCE(m.content_text, '')) ~ '(tệ|dở|lạnh|chậm|mắc|đắt|không ngon|thất vọng|bực|giao hàng|phàn nàn)' THEN -0.65
    WHEN lower(COALESCE(m.content_text, '')) ~ '(ngon|thích|tuyệt|ổn|đỉnh|recommend|sẽ quay lại|hài lòng)' THEN 0.65
    ELSE 0
  END,
  CASE
    WHEN lower(COALESCE(m.content_text, '')) ~ '(giao|ship|delivery|đợi|chờ)' THEN 'delivery_friction'
    WHEN lower(COALESCE(m.content_text, '')) ~ '(giá|mắc|đắt|value|tiền)' THEN 'price_value'
    WHEN lower(COALESCE(m.content_text, '')) ~ '(mì|bò|sủi cảo|phô mai|món|ăn)' THEN 'food_quality'
    WHEN lower(COALESCE(m.content_text, '')) ~ '(nhân viên|phục vụ|service)' THEN 'service'
    ELSE 'general'
  END,
  CASE
    WHEN lower(COALESCE(m.content_text, '')) ~ '(giao|ship|delivery|đợi|chờ)' THEN 'delivery'
    WHEN lower(COALESCE(m.content_text, '')) ~ '(giá|mắc|đắt|value|tiền)' THEN 'pricing'
    WHEN lower(COALESCE(m.content_text, '')) ~ '(mì|bò|sủi cảo|phô mai|món|ăn)' THEN 'menu'
    ELSE 'general'
  END,
  68,
  LENGTH(COALESCE(m.content_text, '')) >= 25,
  lower(COALESCE(m.content_text, '')) ~ '(tệ|dở|lạnh|chậm|thất vọng|bực|phàn nàn|không ngon)',
  CASE
    WHEN lower(COALESCE(m.content_text, '')) ~ '(tệ|dở|lạnh|chậm|thất vọng|bực|phàn nàn)' THEN 'high'
    WHEN lower(COALESCE(m.content_text, '')) ~ '(mắc|đắt|không ngon)' THEN 'medium'
    ELSE NULL
  END,
  'crawl_foundation_v1'
FROM mentions m
JOIN brands br ON br.brand_id = m.brand_id
WHERE br.brand_slug = '{BRAND_SLUG}'
ON CONFLICT (mention_id) DO NOTHING;

INSERT INTO review_enrichments (
  review_id, brand_id, branch_id, sentiment_label, sentiment_score, topic_label, issue_type,
  confidence_score, is_high_risk, needs_response, unanswered_sla_hours
)
SELECT
  r.review_id,
  r.brand_id,
  r.branch_id,
  CASE
    WHEN r.rating <= 3 OR lower(COALESCE(r.review_text, '')) ~ '(tệ|dở|lạnh|chậm|thất vọng|bực|phàn nàn|không ngon)' THEN 'negative'
    WHEN r.rating >= 4 OR lower(COALESCE(r.review_text, '')) ~ '(ngon|thích|tuyệt|ổn|đỉnh|hài lòng)' THEN 'positive'
    ELSE 'neutral'
  END,
  CASE WHEN r.rating IS NOT NULL THEN ROUND(((r.rating - 3) / 2)::numeric, 2) ELSE 0 END,
  CASE
    WHEN lower(COALESCE(r.review_text, '')) ~ '(giao|ship|delivery|đợi|chờ)' THEN 'delivery_friction'
    WHEN lower(COALESCE(r.review_text, '')) ~ '(giá|mắc|đắt|value|tiền)' THEN 'price_value'
    WHEN lower(COALESCE(r.review_text, '')) ~ '(mì|bò|sủi cảo|phô mai|món|ăn)' THEN 'food_quality'
    WHEN lower(COALESCE(r.review_text, '')) ~ '(nhân viên|phục vụ|service)' THEN 'service'
    ELSE 'general'
  END,
  CASE
    WHEN lower(COALESCE(r.review_text, '')) ~ '(giao|ship|delivery|đợi|chờ)' THEN 'delivery'
    WHEN lower(COALESCE(r.review_text, '')) ~ '(giá|mắc|đắt|value|tiền)' THEN 'pricing'
    WHEN lower(COALESCE(r.review_text, '')) ~ '(mì|bò|sủi cảo|phô mai|món|ăn)' THEN 'menu'
    ELSE 'general'
  END,
  CASE WHEN r.platform IN ('google_maps', 'shopeefood', 'grabfood') THEN 85 ELSE 65 END,
  COALESCE(r.rating, 5) <= 3,
  COALESCE(r.rating, 5) <= 3 AND NOT r.owner_replied,
  CASE WHEN COALESCE(r.rating, 5) <= 3 AND NOT r.owner_replied THEN 24 ELSE NULL END
FROM reviews r
JOIN brands br ON br.brand_id = r.brand_id
WHERE br.brand_slug = '{BRAND_SLUG}'
ON CONFLICT (review_id) DO UPDATE
SET branch_id = EXCLUDED.branch_id,
    sentiment_label = EXCLUDED.sentiment_label,
    sentiment_score = EXCLUDED.sentiment_score,
    topic_label = EXCLUDED.topic_label,
    issue_type = EXCLUDED.issue_type,
    confidence_score = EXCLUDED.confidence_score,
    is_high_risk = EXCLUDED.is_high_risk,
    needs_response = EXCLUDED.needs_response,
    unanswered_sla_hours = EXCLUDED.unanswered_sla_hours,
    enriched_at = NOW();

DELETE FROM hourly_signal_metrics h
USING brands br
WHERE h.brand_id = br.brand_id AND br.brand_slug = '{BRAND_SLUG}';

WITH events AS (
  SELECT
    m.brand_id,
    m.branch_id,
    m.platform,
    COALESCE(e.topic_label, 'general') AS topic_label,
    COALESCE(e.issue_type, 'general') AS issue_type,
    date_trunc('hour', COALESCE(m.content_created_at, m.created_at)) AS metric_hour,
    COALESCE(e.sentiment_label, 'neutral') AS sentiment_label,
    NULL::numeric AS rating,
    COALESCE(e.confidence_score, 50) AS confidence_score,
    'mention' AS event_type
  FROM mentions m
  JOIN brands br ON br.brand_id = m.brand_id
  LEFT JOIN mention_enrichments e ON e.mention_id = m.mention_id
  WHERE br.brand_slug = '{BRAND_SLUG}'
  UNION ALL
  SELECT
    r.brand_id,
    r.branch_id,
    r.platform,
    COALESCE(e.topic_label, 'general') AS topic_label,
    COALESCE(e.issue_type, 'general') AS issue_type,
    date_trunc('hour', COALESCE(r.review_created_at, r.created_at)) AS metric_hour,
    COALESCE(e.sentiment_label, CASE WHEN COALESCE(r.rating, 5) <= 3 THEN 'negative' WHEN r.rating >= 4 THEN 'positive' ELSE 'neutral' END),
    r.rating,
    COALESCE(e.confidence_score, 80) AS confidence_score,
    'review' AS event_type
  FROM reviews r
  JOIN brands br ON br.brand_id = r.brand_id
  LEFT JOIN review_enrichments e ON e.review_id = r.review_id
  WHERE br.brand_slug = '{BRAND_SLUG}'
)
INSERT INTO hourly_signal_metrics (
  brand_id, branch_id, platform, topic_label, issue_type, metric_hour,
  mention_count, review_count, positive_count, neutral_count, negative_count,
  demand_count, competitor_count, avg_rating, avg_confidence, source_mix
)
SELECT
  brand_id,
  branch_id,
  platform,
  topic_label,
  issue_type,
  metric_hour,
  COUNT(*) FILTER (WHERE event_type = 'mention'),
  COUNT(*) FILTER (WHERE event_type = 'review'),
  COUNT(*) FILTER (WHERE sentiment_label = 'positive'),
  COUNT(*) FILTER (WHERE sentiment_label IN ('neutral', 'mixed', 'operational')),
  COUNT(*) FILTER (WHERE sentiment_label = 'negative'),
  COUNT(*) FILTER (WHERE sentiment_label = 'demand'),
  COUNT(*) FILTER (WHERE sentiment_label = 'competitor'),
  ROUND(AVG(rating) FILTER (WHERE rating IS NOT NULL), 2),
  ROUND(AVG(confidence_score), 2),
  jsonb_build_object(platform, COUNT(*))
FROM events
WHERE metric_hour IS NOT NULL
GROUP BY brand_id, branch_id, platform, topic_label, issue_type, metric_hour;

INSERT INTO response_tracking (
  brand_id, branch_id, source_record_type, source_record_id, platform, source_url, needs_response,
  responded, responded_at, response_text, sla_target_hours, sla_status, owner_team, priority_score, metadata
)
SELECT
  r.brand_id,
  r.branch_id,
  'review',
  r.review_id,
  r.platform,
  r.review_url,
  e.needs_response,
  r.owner_replied,
  r.owner_replied_at,
  NULL,
  COALESCE(e.unanswered_sla_hours, 24),
  CASE
    WHEN r.owner_replied THEN 'responded'
    WHEN NOT e.needs_response THEN 'not_required'
    WHEN COALESCE(r.review_created_at, r.created_at) < NOW() - (COALESCE(e.unanswered_sla_hours, 24) || ' hours')::interval THEN 'overdue'
    WHEN COALESCE(r.review_created_at, r.created_at) < NOW() - ((COALESCE(e.unanswered_sla_hours, 24) - 4) || ' hours')::interval THEN 'due_soon'
    ELSE 'open'
  END,
  'CS + Ops',
  CASE WHEN e.is_high_risk THEN 90 ELSE 40 END + CASE WHEN r.platform IN ('google_maps', 'shopeefood', 'grabfood') THEN 10 ELSE 0 END,
  jsonb_build_object('generator', 'crawl_foundation', 'rating', r.rating)
FROM reviews r
JOIN brands br ON br.brand_id = r.brand_id
JOIN review_enrichments e ON e.review_id = r.review_id
WHERE br.brand_slug = '{BRAND_SLUG}'
ON CONFLICT (source_record_type, source_record_id) DO UPDATE
SET branch_id = EXCLUDED.branch_id,
    needs_response = EXCLUDED.needs_response,
    responded = EXCLUDED.responded,
    responded_at = EXCLUDED.responded_at,
    sla_status = EXCLUDED.sla_status,
    priority_score = EXCLUDED.priority_score,
    metadata = EXCLUDED.metadata,
    updated_at = NOW();

INSERT INTO response_tracking (
  brand_id, branch_id, source_record_type, source_record_id, platform, source_url, needs_response,
  responded, sla_target_hours, sla_status, owner_team, priority_score, metadata
)
SELECT
  m.brand_id,
  m.branch_id,
  'mention',
  m.mention_id,
  m.platform,
  m.post_url,
  e.needs_response,
  FALSE,
  24,
  CASE
    WHEN NOT e.needs_response THEN 'not_required'
    WHEN COALESCE(m.content_created_at, m.created_at) < NOW() - INTERVAL '24 hours' THEN 'overdue'
    WHEN COALESCE(m.content_created_at, m.created_at) < NOW() - INTERVAL '20 hours' THEN 'due_soon'
    ELSE 'open'
  END,
  CASE WHEN m.branch_id IS NULL THEN 'Listening' ELSE 'CS + Ops' END,
  CASE e.response_priority WHEN 'high' THEN 85 WHEN 'medium' THEN 60 ELSE 30 END,
  jsonb_build_object('generator', 'crawl_foundation', 'topic_label', e.topic_label)
FROM mentions m
JOIN brands br ON br.brand_id = m.brand_id
JOIN mention_enrichments e ON e.mention_id = m.mention_id
WHERE br.brand_slug = '{BRAND_SLUG}'
ON CONFLICT (source_record_type, source_record_id) DO UPDATE
SET branch_id = EXCLUDED.branch_id,
    needs_response = EXCLUDED.needs_response,
    sla_status = EXCLUDED.sla_status,
    owner_team = EXCLUDED.owner_team,
    priority_score = EXCLUDED.priority_score,
    metadata = EXCLUDED.metadata,
    updated_at = NOW();

DELETE FROM action_items a
USING brands br
WHERE a.brand_id = br.brand_id
  AND br.brand_slug = '{BRAND_SLUG}'
  AND a.metadata->>'generator' = 'crawl_foundation';

INSERT INTO action_items (
  brand_id, branch_id, source_record_type, source_record_id, action_kind, title, description,
  owner_team, priority_score, priority_class, sla_target_hours, deadline_at,
  guardrail_status, metadata
)
SELECT
  r.brand_id,
  r.branch_id,
  'review',
  r.review_id,
  'respond',
  'Xử lý review tiêu cực trên ' || r.platform,
  LEFT(COALESCE(r.review_text, ''), 240),
  'CS + Ops',
  rt.priority_score,
  CASE WHEN rt.priority_score >= 90 THEN 'critical' WHEN rt.priority_score >= 75 THEN 'high' ELSE 'medium' END,
  rt.sla_target_hours,
  COALESCE(r.review_created_at, r.created_at) + (rt.sla_target_hours || ' hours')::interval,
  'evidence_required',
  jsonb_build_object('generator', 'crawl_foundation', 'platform', r.platform, 'rating', r.rating)
FROM reviews r
JOIN brands br ON br.brand_id = r.brand_id
JOIN response_tracking rt ON rt.source_record_type = 'review' AND rt.source_record_id = r.review_id
WHERE br.brand_slug = '{BRAND_SLUG}'
  AND rt.needs_response
  AND NOT rt.responded
ON CONFLICT (source_record_type, source_record_id, action_kind) DO UPDATE
SET branch_id = EXCLUDED.branch_id,
    title = EXCLUDED.title,
    description = EXCLUDED.description,
    priority_score = EXCLUDED.priority_score,
    priority_class = EXCLUDED.priority_class,
    deadline_at = EXCLUDED.deadline_at,
    metadata = EXCLUDED.metadata,
    updated_at = NOW();

INSERT INTO action_items (
  brand_id, branch_id, source_record_type, source_record_id, action_kind, title, description,
  owner_team, priority_score, priority_class, sla_target_hours, deadline_at,
  guardrail_status, metadata
)
SELECT
  m.brand_id,
  m.branch_id,
  'mention',
  m.mention_id,
  'triage',
  'Triage mention tiêu cực trên ' || m.platform,
  LEFT(COALESCE(m.content_text, ''), 240),
  CASE WHEN m.branch_id IS NULL THEN 'Listening' ELSE 'CS + Ops' END,
  rt.priority_score,
  CASE WHEN rt.priority_score >= 85 THEN 'high' WHEN rt.priority_score >= 60 THEN 'medium' ELSE 'low' END,
  rt.sla_target_hours,
  COALESCE(m.content_created_at, m.created_at) + (rt.sla_target_hours || ' hours')::interval,
  CASE WHEN m.branch_id IS NULL THEN 'needs_branch_mapping' ELSE 'evidence_required' END,
  jsonb_build_object('generator', 'crawl_foundation', 'platform', m.platform, 'topic_label', e.topic_label)
FROM mentions m
JOIN brands br ON br.brand_id = m.brand_id
JOIN mention_enrichments e ON e.mention_id = m.mention_id
JOIN response_tracking rt ON rt.source_record_type = 'mention' AND rt.source_record_id = m.mention_id
WHERE br.brand_slug = '{BRAND_SLUG}'
  AND rt.needs_response
  AND NOT rt.responded
ON CONFLICT (source_record_type, source_record_id, action_kind) DO UPDATE
SET branch_id = EXCLUDED.branch_id,
    title = EXCLUDED.title,
    description = EXCLUDED.description,
    owner_team = EXCLUDED.owner_team,
    priority_score = EXCLUDED.priority_score,
    priority_class = EXCLUDED.priority_class,
    deadline_at = EXCLUDED.deadline_at,
    guardrail_status = EXCLUDED.guardrail_status,
    metadata = EXCLUDED.metadata,
    updated_at = NOW();

INSERT INTO proof_assets (
  brand_id, branch_id, source_record_type, source_record_id, platform, source_url,
  quote_text, permission_status, usage_rights, quote_quality_score, brand_safety_score, metadata
)
SELECT
  r.brand_id,
  r.branch_id,
  'review',
  r.review_id,
  r.platform,
  r.review_url,
  LEFT(COALESCE(r.review_text, ''), 500),
  'unknown',
  'not_cleared',
  LEAST(100, 45 + LENGTH(COALESCE(r.review_text, '')) / 8.0),
  CASE WHEN COALESCE(r.rating, 5) >= 4 THEN 85 ELSE 55 END,
  jsonb_build_object('generator', 'crawl_foundation', 'rating', r.rating)
FROM reviews r
JOIN brands br ON br.brand_id = r.brand_id
JOIN review_enrichments e ON e.review_id = r.review_id
WHERE br.brand_slug = '{BRAND_SLUG}'
  AND e.sentiment_label = 'positive'
  AND LENGTH(COALESCE(r.review_text, '')) >= 20
ON CONFLICT (source_record_type, source_record_id) DO UPDATE
SET branch_id = EXCLUDED.branch_id,
    quote_text = EXCLUDED.quote_text,
    quote_quality_score = EXCLUDED.quote_quality_score,
    brand_safety_score = EXCLUDED.brand_safety_score,
    metadata = EXCLUDED.metadata,
    updated_at = NOW();

INSERT INTO proof_assets (
  brand_id, branch_id, source_record_type, source_record_id, platform, source_url,
  quote_text, permission_status, usage_rights, quote_quality_score, brand_safety_score, metadata
)
SELECT
  m.brand_id,
  m.branch_id,
  'mention',
  m.mention_id,
  m.platform,
  m.post_url,
  LEFT(COALESCE(m.content_text, ''), 500),
  'unknown',
  'not_cleared',
  LEAST(100, 35 + LENGTH(COALESCE(m.content_text, '')) / 10.0),
  75,
  jsonb_build_object('generator', 'crawl_foundation', 'topic_label', e.topic_label)
FROM mentions m
JOIN brands br ON br.brand_id = m.brand_id
JOIN mention_enrichments e ON e.mention_id = m.mention_id
WHERE br.brand_slug = '{BRAND_SLUG}'
  AND e.sentiment_label = 'positive'
  AND LENGTH(COALESCE(m.content_text, '')) >= 25
ON CONFLICT (source_record_type, source_record_id) DO UPDATE
SET branch_id = EXCLUDED.branch_id,
    quote_text = EXCLUDED.quote_text,
    quote_quality_score = EXCLUDED.quote_quality_score,
    brand_safety_score = EXCLUDED.brand_safety_score,
    metadata = EXCLUDED.metadata,
    updated_at = NOW();

DELETE FROM search_demand_signals s
USING brands br
WHERE s.brand_id = br.brand_id
  AND br.brand_slug = '{BRAND_SLUG}'
  AND s.metadata->>'generator' = 'crawl_foundation_seed'
  AND s.captured_at >= date_trunc('hour', NOW());

WITH menu_terms AS (
  SELECT
    mi.brand_id,
    COALESCE(mi.normalized_item_name, lower(mi.item_name)) AS keyword,
    mi.item_name AS query,
    COUNT(*) AS menu_coverage
  FROM menu_items mi
  JOIN brands br ON br.brand_id = mi.brand_id
  WHERE br.brand_slug = '{BRAND_SLUG}'
  GROUP BY mi.brand_id, COALESCE(mi.normalized_item_name, lower(mi.item_name)), mi.item_name
),
mention_hits AS (
  SELECT
    mt.brand_id,
    mt.keyword,
    mt.query,
    COUNT(m.mention_id) + COUNT(r.review_id) AS result_count
  FROM menu_terms mt
  LEFT JOIN mentions m ON m.brand_id = mt.brand_id AND COALESCE(m.content_text, '') ILIKE '%' || mt.keyword || '%'
  LEFT JOIN reviews r ON r.brand_id = mt.brand_id AND COALESCE(r.review_text, '') ILIKE '%' || mt.keyword || '%'
  GROUP BY mt.brand_id, mt.keyword, mt.query
)
INSERT INTO search_demand_signals (
  brand_id, platform, keyword, query, rank_position, result_count, captured_at, metadata
)
SELECT
  brand_id,
  'internal_social_search',
  keyword,
  query,
  ROW_NUMBER() OVER (ORDER BY result_count DESC),
  result_count,
  date_trunc('hour', NOW()),
  jsonb_build_object('generator', 'crawl_foundation_seed', 'source', 'menu_mentions_reviews')
FROM mention_hits
WHERE result_count > 0
ORDER BY result_count DESC
LIMIT 30;
""".strip() + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
