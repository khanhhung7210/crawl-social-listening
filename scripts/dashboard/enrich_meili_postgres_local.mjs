import {
  BRAND_SLUG,
  SCHEMA,
  clamp,
  compactWhitespace,
  countMatches,
  includesAny,
  normalizeText,
  queryJson,
  runPsqlText,
  sqlBool,
  sqlJson,
  sqlNum,
  sqlStr,
  titleCase,
} from './dashboard_local_lib.mjs';

const MAX_MENTIONS = Math.max(0, Number(process.env.LOCAL_MAX_MENTIONS || 5000));
const MAX_REVIEWS = Math.max(0, Number(process.env.LOCAL_MAX_REVIEWS || 5000));
const REENRICH = String(process.env.LOCAL_REENRICH || '').trim() === '1';
const ENRICHMENT_VERSION = 'local-v1';

const BRAND_KEYWORDS = ['meili', 'mei li', 'my li', 'mi bo dai loan', 'mi sui cao', 'mi bo', 'dimsum', 'dimsum', 'banh bao kep'];
const FOOD_KEYWORDS = [
  'mon', 'quan', 'nha hang', 'ship', 'giao hang', 'delivery', 'an trua', 'an toi',
  'beef noodle', 'taiwanese', 'noodle', 'bun', 'pho', 'dumpling', 'sui cao', 'bao',
  'price', 'gia', 'menu', 'review', 'rating', 'ngon', 'do an', 'thuc don',
];
const COMPETITOR_KEYWORDS = ['bun bo hue ty loan', 'zo zo', 'nuong ngoi 133', 'grabfood', 'shopeefood competitor'];
const POSITIVE_KEYWORDS = [
  'ngon', 'rat ngon', 'tot', 'ok', 'okay', 'ổn', 'on', 'tuyet voi', 'tuyệt vời', 'yeu thich', 'thich',
  'recommended', 're recommend', 'recommend', 'cheap', 'worth', 'gia hop ly', 'hài lòng', 'hai long',
  'friendly', 'nhanh', 'sach', 'clean', 'amazing', 'love', 'favorite',
];
const NEGATIVE_KEYWORDS = [
  'do te', 'toi se khong quay lai', 'khong quay lai', 'khong ngon', 'te', 'do', 'dở', 'do an nguoi',
  'lau', 'cham', 'mặn', 'man', 'nhat', 'hoi', 'nguoi', 'khong sach', 'bẩn', 'ban',
  'expensive', 'dat', 'gia cao', 'that vong', 'thất vọng', 'bad', 'awful', 'terrible', 'never return',
  'ship cham', 'giao cham', 'thiếu', 'thieu', 'sai mon', 'wrong order', 'cold',
];
const DEMAND_KEYWORDS = [
  'co ai biet', 'co ngon khong', 'nen an mon nao', 'nen order mon nao', 'recommend giup', 'xin review',
  'muon thu', 'thèm', 'them', 'order thu', 'an thu', 'lunch', 'combo', 'deal', 'khuyen mai', 'promo',
];
const QUESTION_KEYWORDS = ['?', 'co ai', 'sao', 'khong biet', 'cho hoi', 'where', 'what', 'how'];
const DELIVERY_KEYWORDS = ['ship', 'giao hang', 'delivery', 'tai xe', 'app', 'freeship'];
const PRICE_KEYWORDS = ['gia', 'price', 'rẻ', 're', 'dat', 'expensive', 'value', 'portion', 'combo'];
const SERVICE_KEYWORDS = ['nhan vien', 'staff', 'service', 'phuc vu', 'thái độ', 'thai do', 'owner'];
const LOCATION_KEYWORDS = ['chi nhanh', 'branch', 'quan', 'go vap', 'phu nhuan', 'quan 7', 'binh thanh', 'dia chi', 'address'];
const CLEANLINESS_KEYWORDS = ['sach', 'clean', 've sinh', 'ban', 'dirty'];
const MENU_KEYWORDS = ['menu', 'mon', 'dish', 'sui cao', 'mi bo', 'dimsum', 'banh bao', 'bao'];
const PROMOTION_KEYWORDS = ['khuyen mai', 'promo', 'discount', 'voucher', 'deal'];

async function main() {
  const mentionRows = fetchMentionRows(MAX_MENTIONS);
  const reviewRows = fetchReviewRows(MAX_REVIEWS);
  const mentionResults = mentionRows.map((row) => ({ row, classification: classifyMention(row) }));
  const reviewResults = reviewRows.map((row) => ({ row, classification: classifyReview(row) }));

  const sqlParts = [
    `SET search_path TO ${SCHEMA}, public;`,
    ...buildMentionUpserts(mentionResults),
    ...buildReviewUpserts(reviewResults),
  ];
  runSql(sqlParts.join('\n') + '\n');

  console.log(
    JSON.stringify(
      {
        mode: 'local',
        brand_slug: BRAND_SLUG,
        mentions_enriched: mentionResults.length,
        reviews_enriched: reviewResults.length,
        re_enrich: REENRICH,
        enrichment_version: ENRICHMENT_VERSION,
      },
      null,
      2,
    ),
  );
}

function fetchMentionRows(limit) {
  const whereClause = REENRICH
    ? `NULLIF(BTRIM(COALESCE(m.content_text, '')), '') IS NOT NULL`
    : `COALESCE(me.sentiment_label, '') = '' AND NULLIF(BTRIM(COALESCE(m.content_text, '')), '') IS NOT NULL`;
  const sql = `
SELECT COALESCE(json_agg(row_to_json(t)), '[]'::json)::text
FROM (
  SELECT
    m.mention_id::text,
    m.brand_id::text,
    COALESCE(m.branch_id::text, '') AS branch_id,
    m.platform,
    m.content_type,
    COALESCE(m.page_name, '') AS page_name,
    COALESCE(m.author_name, '') AS author_name,
    COALESCE(m.post_url, '') AS source_url,
    COALESCE(m.content_text, '') AS content_text
  FROM ${SCHEMA}.mentions m
  LEFT JOIN ${SCHEMA}.mention_enrichments me ON me.mention_id = m.mention_id
  WHERE ${whereClause}
  ORDER BY m.content_created_at NULLS LAST, m.created_at
  LIMIT ${Number(limit)}
) t;
`;
  return queryJson(sql);
}

function fetchReviewRows(limit) {
  const whereClause = REENRICH
    ? `NULLIF(BTRIM(COALESCE(r.review_text, '')), '') IS NOT NULL`
    : `COALESCE(re.sentiment_label, '') = '' AND NULLIF(BTRIM(COALESCE(r.review_text, '')), '') IS NOT NULL`;
  const sql = `
SELECT COALESCE(json_agg(row_to_json(t)), '[]'::json)::text
FROM (
  SELECT
    r.review_id::text,
    r.brand_id::text,
    COALESCE(r.branch_id::text, '') AS branch_id,
    r.platform,
    COALESCE(r.review_url, '') AS source_url,
    COALESCE(r.reviewer_name, '') AS reviewer_name,
    COALESCE(r.review_text, '') AS review_text,
    COALESCE(r.rating, 0)::text AS rating
  FROM ${SCHEMA}.reviews r
  LEFT JOIN ${SCHEMA}.review_enrichments re ON re.review_id = r.review_id
  WHERE ${whereClause}
  ORDER BY r.review_created_at NULLS LAST, r.created_at
  LIMIT ${Number(limit)}
) t;
`;
  return queryJson(sql);
}

function classifyMention(row) {
  const text = compactWhitespace(row.content_text);
  const normalized = normalizeText([row.page_name, row.author_name, text].filter(Boolean).join(' | '));
  const platform = String(row.platform || '').trim().toLowerCase();
  const positiveHits = countMatches(normalized, POSITIVE_KEYWORDS);
  const negativeHits = countMatches(normalized, NEGATIVE_KEYWORDS);
  const demandHits = countMatches(normalized, DEMAND_KEYWORDS);
  const competitorHits = countMatches(normalized, COMPETITOR_KEYWORDS);
  const deliveryHits = countMatches(normalized, DELIVERY_KEYWORDS);
  const brandHits = countMatches(normalized, BRAND_KEYWORDS);
  const foodHits = countMatches(normalized, FOOD_KEYWORDS);
  const questionHits = countMatches(normalized, QUESTION_KEYWORDS);

  let sentimentLabel = 'neutral';
  if (competitorHits > 0 && brandHits === 0) {
    sentimentLabel = 'competitor';
  } else if (negativeHits > 0 && deliveryHits > 0 && negativeHits >= positiveHits) {
    sentimentLabel = 'operational';
  } else if (demandHits > 0 && negativeHits === 0 && positiveHits <= 1) {
    sentimentLabel = 'demand';
  } else if (negativeHits > positiveHits + 1) {
    sentimentLabel = 'negative';
  } else if (positiveHits > negativeHits + 1) {
    sentimentLabel = 'positive';
  } else if (positiveHits > 0 && negativeHits > 0) {
    sentimentLabel = 'mixed';
  }

  const isDeliveryPlatform = ['shopeefood', 'grabfood', 'google_maps'].includes(platform);
  const isRelevant = isDeliveryPlatform || brandHits > 0 || (foodHits > 1 && questionHits >= 0);
  const relevanceReasons = [];
  if (brandHits > 0) relevanceReasons.push('brand_match');
  if (foodHits > 0) relevanceReasons.push('food_context');
  if (isDeliveryPlatform) relevanceReasons.push('trusted_platform');
  if (deliveryHits > 0) relevanceReasons.push('delivery_context');
  if (!relevanceReasons.length) relevanceReasons.push('weak_context');

  const topicLabel = inferTopic(normalized, { deliveryHits, platform, contentType: row.content_type });
  const issueType = inferMentionIssueType(sentimentLabel, questionHits, competitorHits, negativeHits, demandHits);
  const sentimentScore = clamp((positiveHits - negativeHits + (sentimentLabel === 'demand' ? 0.3 : 0)) / 4, -1, 1);
  const confidenceScore = clamp(0.45 + Math.max(positiveHits, negativeHits, demandHits, competitorHits) * 0.08 + (isRelevant ? 0.12 : 0), 0.35, 0.96);
  const relevanceScore = clamp((brandHits * 0.35) + (foodHits * 0.12) + (isDeliveryPlatform ? 0.35 : 0) + (deliveryHits * 0.08), 0, 1);
  const evidenceFlag = text.length >= 24 && (negativeHits > 0 || positiveHits > 1 || platform === 'google_maps');
  const needsResponse = ['negative', 'operational'].includes(sentimentLabel) || (questionHits > 0 && isRelevant);
  const responsePriority = needsResponse
    ? negativeHits > 1 || sentimentLabel === 'operational'
      ? 'high'
      : 'medium'
    : 'low';

  return {
    sentiment_label: sentimentLabel,
    sentiment_score: Number(sentimentScore.toFixed(3)),
    topic_label: topicLabel,
    subtopic_label: inferSubtopic(normalized, topicLabel),
    issue_type: issueType,
    confidence_score: Number(confidenceScore.toFixed(3)),
    is_relevant_fnb: isRelevant,
    relevance_score: Number(relevanceScore.toFixed(3)),
    relevance_reason: relevanceReasons,
    evidence_flag: evidenceFlag,
    needs_response: needsResponse,
    response_priority: responsePriority,
  };
}

function classifyReview(row) {
  const text = compactWhitespace(row.review_text);
  const normalized = normalizeText(text);
  const rating = Number(row.rating || 0);
  const positiveHits = countMatches(normalized, POSITIVE_KEYWORDS);
  const negativeHits = countMatches(normalized, NEGATIVE_KEYWORDS);
  let sentimentLabel = 'neutral';
  if (rating >= 4.5 && negativeHits === 0) {
    sentimentLabel = 'positive';
  } else if (rating > 0 && rating <= 2.5) {
    sentimentLabel = 'negative';
  } else if (negativeHits > positiveHits) {
    sentimentLabel = 'negative';
  } else if (positiveHits > negativeHits) {
    sentimentLabel = 'positive';
  } else if (positiveHits > 0 && negativeHits > 0) {
    sentimentLabel = 'mixed';
  } else if (rating >= 4) {
    sentimentLabel = 'positive';
  } else if (rating > 0 && rating < 4) {
    sentimentLabel = 'mixed';
  }

  const topicLabel = inferTopic(normalized, { deliveryHits: countMatches(normalized, DELIVERY_KEYWORDS), platform: row.platform, contentType: 'review' });
  const issueType = sentimentLabel === 'negative' ? 'complaint' : sentimentLabel === 'positive' ? 'praise' : 'none';
  const confidenceScore = clamp(0.56 + Math.max(positiveHits, negativeHits) * 0.09 + (rating ? 0.12 : 0), 0.45, 0.97);
  const scoreBase = rating ? (rating - 3) / 2 : (positiveHits - negativeHits) / 4;
  const sentimentScore = clamp(scoreBase, -1, 1);
  const isHighRisk = sentimentLabel === 'negative' && (rating <= 2.5 || negativeHits >= 2);
  const needsResponse = sentimentLabel === 'negative' || (sentimentLabel === 'mixed' && rating <= 3);
  const unansweredSlaHours = !needsResponse ? null : isHighRisk ? 4 : 12;

  return {
    sentiment_label: sentimentLabel,
    sentiment_score: Number(sentimentScore.toFixed(3)),
    topic_label: topicLabel,
    issue_type: issueType,
    confidence_score: Number(confidenceScore.toFixed(3)),
    is_high_risk: isHighRisk,
    needs_response: needsResponse,
    unanswered_sla_hours: unansweredSlaHours,
  };
}

function inferTopic(normalized, context) {
  if (includesAny(normalized, DELIVERY_KEYWORDS)) return 'delivery';
  if (includesAny(normalized, PRICE_KEYWORDS)) return 'price_value';
  if (includesAny(normalized, SERVICE_KEYWORDS)) return 'staff_service';
  if (includesAny(normalized, LOCATION_KEYWORDS)) return 'location';
  if (includesAny(normalized, CLEANLINESS_KEYWORDS)) return 'cleanliness';
  if (includesAny(normalized, PROMOTION_KEYWORDS)) return 'promotion';
  if (includesAny(normalized, MENU_KEYWORDS)) return 'menu_variety';
  if (context.platform === 'google_maps') return 'branch_experience';
  if (context.platform === 'shopeefood' || context.platform === 'grabfood') return 'delivery';
  return 'general_buzz';
}

function inferSubtopic(normalized, topicLabel) {
  if (topicLabel === 'delivery' && includesAny(normalized, ['cham', 'lau', 'delay', 'cold'])) return 'delivery_delay';
  if (topicLabel === 'price_value' && includesAny(normalized, ['dat', 'expensive', 'gia cao'])) return 'high_price';
  if (topicLabel === 'staff_service' && includesAny(normalized, ['thai do', 'rude'])) return 'staff_attitude';
  if (topicLabel === 'menu_variety' && includesAny(normalized, ['mi bo', 'sui cao', 'dimsum'])) return 'signature_menu';
  if (topicLabel === 'branch_experience' && includesAny(normalized, ['quan 7', 'go vap', 'phu nhuan', 'binh thanh'])) return titleCase(normalized.match(/quan 7|go vap|phu nhuan|binh thanh/)?.[0] || '');
  return '';
}

function inferMentionIssueType(sentimentLabel, questionHits, competitorHits, negativeHits, demandHits) {
  if (competitorHits > 0) return 'competitor_reference';
  if (questionHits > 0 && demandHits > 0) return 'request';
  if (questionHits > 0) return 'question';
  if (sentimentLabel === 'operational') return 'operational_issue';
  if (sentimentLabel === 'negative' || negativeHits > 0) return 'complaint';
  if (sentimentLabel === 'positive') return 'praise';
  if (sentimentLabel === 'demand') return 'recommendation';
  return 'none';
}

function buildMentionUpserts(records) {
  return records.map(({ row, classification }) => `
INSERT INTO ${SCHEMA}.mention_enrichments (
  mention_id, brand_id, branch_id, is_relevant_fnb, relevance_score, relevance_reason,
  sentiment_label, sentiment_score, topic_label, subtopic_label, issue_type, confidence_score,
  evidence_flag, needs_response, response_priority, enrichment_version, enriched_at
)
VALUES (
  ${sqlStr(row.mention_id)},
  ${sqlStr(row.brand_id)}::uuid,
  ${row.branch_id ? `${sqlStr(row.branch_id)}::uuid` : 'NULL'},
  ${sqlBool(classification.is_relevant_fnb)},
  ${sqlNum(classification.relevance_score)},
  ${sqlJson(classification.relevance_reason)}::jsonb,
  ${sqlStr(classification.sentiment_label)},
  ${sqlNum(classification.sentiment_score)},
  ${sqlStr(classification.topic_label)},
  ${sqlStr(classification.subtopic_label)},
  ${sqlStr(classification.issue_type)},
  ${sqlNum(classification.confidence_score)},
  ${sqlBool(classification.evidence_flag)},
  ${sqlBool(classification.needs_response)},
  ${sqlStr(classification.response_priority)},
  ${sqlStr(ENRICHMENT_VERSION)},
  NOW()
)
ON CONFLICT (mention_id) DO UPDATE
SET is_relevant_fnb = EXCLUDED.is_relevant_fnb,
    relevance_score = EXCLUDED.relevance_score,
    relevance_reason = EXCLUDED.relevance_reason,
    sentiment_label = EXCLUDED.sentiment_label,
    sentiment_score = EXCLUDED.sentiment_score,
    topic_label = EXCLUDED.topic_label,
    subtopic_label = EXCLUDED.subtopic_label,
    issue_type = EXCLUDED.issue_type,
    confidence_score = EXCLUDED.confidence_score,
    evidence_flag = EXCLUDED.evidence_flag,
    needs_response = EXCLUDED.needs_response,
    response_priority = EXCLUDED.response_priority,
    enrichment_version = EXCLUDED.enrichment_version,
    enriched_at = NOW();
`.trim());
}

function buildReviewUpserts(records) {
  return records.map(({ row, classification }) => `
INSERT INTO ${SCHEMA}.review_enrichments (
  review_id, brand_id, branch_id, sentiment_label, sentiment_score, topic_label,
  issue_type, confidence_score, is_high_risk, needs_response, unanswered_sla_hours, enriched_at
)
VALUES (
  ${sqlStr(row.review_id)},
  ${sqlStr(row.brand_id)}::uuid,
  ${row.branch_id ? `${sqlStr(row.branch_id)}::uuid` : 'NULL'},
  ${sqlStr(classification.sentiment_label)},
  ${sqlNum(classification.sentiment_score)},
  ${sqlStr(classification.topic_label)},
  ${sqlStr(classification.issue_type)},
  ${sqlNum(classification.confidence_score)},
  ${sqlBool(classification.is_high_risk)},
  ${sqlBool(classification.needs_response)},
  ${classification.unanswered_sla_hours == null ? 'NULL' : Number(classification.unanswered_sla_hours)},
  NOW()
)
ON CONFLICT (review_id) DO UPDATE
SET sentiment_label = EXCLUDED.sentiment_label,
    sentiment_score = EXCLUDED.sentiment_score,
    topic_label = EXCLUDED.topic_label,
    issue_type = EXCLUDED.issue_type,
    confidence_score = EXCLUDED.confidence_score,
    is_high_risk = EXCLUDED.is_high_risk,
    needs_response = EXCLUDED.needs_response,
    unanswered_sla_hours = EXCLUDED.unanswered_sla_hours,
    enriched_at = NOW();
`.trim());
}

function runSql(sql) {
  runPsqlText(sql);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
