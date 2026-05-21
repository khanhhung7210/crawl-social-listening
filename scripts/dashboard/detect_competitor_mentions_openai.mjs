#!/usr/bin/env node
/**
 * Competitor Mention Detection with OpenAI
 *
 * Scans mentions and reviews to detect competitor references, comparisons,
 * and competitive pressure indicators.
 *
 * Usage:
 *   node scripts/dashboard/detect_competitor_mentions_openai.mjs
 *
 * Environment:
 *   OPENAI_API_KEY - Required
 *   PGDATABASE - Default: meili_dashboard
 *   PGSCHEMA - Default: meili_dashboard
 *   BRAND_SLUG - Default: meili-mi-bo-dai-loan
 *   OPENAI_MODEL - Default: gpt-4o-mini
 *   DRY_RUN - Set to '1' for dry run
 */

import { createHash } from 'crypto';
import { existsSync, mkdirSync, readFileSync, unlinkSync, writeFileSync } from 'fs';
import { tmpdir } from 'os';
import { resolve } from 'path';
import { execFileSync } from 'child_process';

const SCHEMA = process.env.PGSCHEMA || 'meili_dashboard';
const PGDATABASE = process.env.PGDATABASE || 'meili_dashboard';
const PSQL_BIN = process.env.PSQL_BIN || 'psql';
const BRAND_SLUG = process.env.BRAND_SLUG || 'meili-mi-bo-dai-loan';
const OPENAI_API_KEY = String(process.env.OPENAI_API_KEY || '').trim();
const OPENAI_MODEL = String(process.env.OPENAI_MODEL || 'gpt-4o-mini').trim() || 'gpt-4o-mini';
const OPENAI_BATCH_SIZE = Math.max(1, Number(process.env.OPENAI_BATCH_SIZE || 20));
const MAX_ITEMS = Math.max(0, Number(process.env.MAX_ITEMS || 2000));
const DRY_RUN = String(process.env.DRY_RUN || '').trim() === '1';
const CACHE_DIR = resolve(process.cwd(), 'tmp', 'competitor-detection');
const CACHE_PATH = resolve(CACHE_DIR, 'competitor_detection_cache.json');

// Competitor keywords to filter relevant mentions
const COMPETITOR_KEYWORDS = [
  'domino',
  'pizza hut',
  'pizza 4p',
  '4ps',
  'local pizza',
  'dominos',
  'pizzahut',
  'đối thủ',
  'competitor',
  'so với',
  'compare',
  'vs',
  'better than',
  'worse than',
  'giá rẻ hơn',
  'nhanh hơn',
  'chậm hơn',
  'ngon hơn',
];

const COMPARISON_TYPES = ['competitor_better', 'we_better', 'neutral'];
const TOPICS = [
  'delivery_speed',
  'delivery_quality',
  'price',
  'value_for_money',
  'taste',
  'quality',
  'service',
  'menu_variety',
  'family_offers',
  'combos',
  'promotions',
  'location',
  'ambiance',
  'experience',
  'premium_positioning',
  'brand_perception',
  'other',
];

async function main() {
  const brandId = fetchBrandId();
  if (!brandId) {
    throw new Error(`Brand not found: ${BRAND_SLUG}`);
  }

  const mentions = fetchPendingMentions(brandId, MAX_ITEMS);
  const reviews = fetchPendingReviews(brandId, MAX_ITEMS);

  console.log(
    JSON.stringify(
      {
        pg_database: PGDATABASE,
        schema: SCHEMA,
        brand_slug: BRAND_SLUG,
        model: OPENAI_MODEL,
        pending_mentions: mentions.length,
        pending_reviews: reviews.length,
      },
      null,
      2,
    ),
  );

  if (DRY_RUN) {
    console.log('DRY_RUN mode - no actual processing');
    return;
  }

  if (!OPENAI_API_KEY) {
    throw new Error('OPENAI_API_KEY is required');
  }

  mkdirSync(CACHE_DIR, { recursive: true });
  const cache = loadCache(CACHE_PATH);

  const mentionResults = await classifyCompetitorMentions(mentions, 'mention', cache, brandId);
  const reviewResults = await classifyCompetitorMentions(reviews, 'review', cache, brandId);

  saveCache(CACHE_PATH, cache);

  const sqlParts = [
    `SET search_path TO ${SCHEMA}, public;`,
    ...buildDetectionInserts(mentionResults, brandId),
    ...buildDetectionInserts(reviewResults, brandId),
  ];

  runSql(sqlParts.join('\n') + '\n');

  console.log(
    JSON.stringify(
      {
        mentions_detected: mentionResults.length,
        reviews_detected: reviewResults.length,
        cache_path: CACHE_PATH,
      },
      null,
      2,
    ),
  );
}

function fetchBrandId() {
  const sql = `
SELECT brand_id::text
FROM ${SCHEMA}.brands
WHERE brand_slug = ${sqlStr(BRAND_SLUG)}
LIMIT 1;
`;
  return runPsqlText(sql).trim();
}

function fetchPendingMentions(brandId, limit) {
  const keywordFilter = COMPETITOR_KEYWORDS.map((kw) => `LOWER(m.content_text) LIKE ${sqlStr('%' + kw + '%')}`).join(
    ' OR ',
  );

  const sql = `
SELECT COALESCE(json_agg(row_to_json(t)), '[]'::json)::text
FROM (
  SELECT
    m.mention_id::text,
    m.brand_id::text,
    m.platform,
    COALESCE(m.content_text, '') AS content_text,
    COALESCE(m.page_name, '') AS page_name,
    COALESCE(m.author_name, '') AS author_name
  FROM ${SCHEMA}.mentions m
  LEFT JOIN ${SCHEMA}.competitor_mention_detections cmd ON cmd.mention_id = m.mention_id
  WHERE m.brand_id = ${sqlStr(brandId)}::uuid
    AND cmd.detection_id IS NULL
    AND NULLIF(BTRIM(COALESCE(m.content_text, '')), '') IS NOT NULL
    AND (${keywordFilter})
  ORDER BY m.content_created_at NULLS LAST, m.created_at DESC
  LIMIT ${Number(limit)}
) t;
`;
  return queryJson(sql);
}

function fetchPendingReviews(brandId, limit) {
  const keywordFilter = COMPETITOR_KEYWORDS.map((kw) => `LOWER(r.review_text) LIKE ${sqlStr('%' + kw + '%')}`).join(
    ' OR ',
  );

  const sql = `
SELECT COALESCE(json_agg(row_to_json(t)), '[]'::json)::text
FROM (
  SELECT
    r.review_id::text,
    r.brand_id::text,
    r.platform,
    COALESCE(r.review_text, '') AS review_text,
    COALESCE(r.reviewer_name, '') AS reviewer_name,
    COALESCE(r.rating, 0)::text AS rating
  FROM ${SCHEMA}.reviews r
  LEFT JOIN ${SCHEMA}.competitor_mention_detections cmd ON cmd.review_id = r.review_id
  WHERE r.brand_id = ${sqlStr(brandId)}::uuid
    AND cmd.detection_id IS NULL
    AND NULLIF(BTRIM(COALESCE(r.review_text, '')), '') IS NOT NULL
    AND (${keywordFilter})
  ORDER BY r.review_created_at NULLS LAST, r.created_at DESC
  LIMIT ${Number(limit)}
) t;
`;
  return queryJson(sql);
}

async function classifyCompetitorMentions(items, mode, cache, brandId) {
  const uniqueInputs = [];
  const seenKeys = new Set();
  const itemsByKey = new Map();

  for (const item of items) {
    const cacheKey = buildCacheKey(mode, item);
    if (!itemsByKey.has(cacheKey)) itemsByKey.set(cacheKey, []);
    itemsByKey.get(cacheKey).push(item);
    if (seenKeys.has(cacheKey)) continue;
    seenKeys.add(cacheKey);
    uniqueInputs.push({ cacheKey, item });
  }

  const resultsByKey = new Map();
  const pending = [];

  for (const entry of uniqueInputs) {
    const cached = cache[entry.cacheKey];
    if (cached && isValidDetection(cached)) {
      resultsByKey.set(entry.cacheKey, cached);
      continue;
    }
    pending.push(entry);
  }

  for (const batch of chunkArray(pending, OPENAI_BATCH_SIZE)) {
    const classified = await classifyBatch(batch, mode);
    for (const entry of classified) {
      cache[entry.cacheKey] = entry.detection;
      resultsByKey.set(entry.cacheKey, entry.detection);
    }
  }

  const finalResults = [];
  for (const [cacheKey, sourceItems] of itemsByKey.entries()) {
    const detection = resultsByKey.get(cacheKey);
    if (!detection) continue;
    for (const item of sourceItems) {
      finalResults.push({ item, detection, mode, brandId });
    }
  }
  return finalResults;
}

async function classifyBatch(batch, mode) {
  const promptLines = batch.map((entry, index) => {
    if (mode === 'mention') {
      return `${index + 1}. platform=${entry.item.platform}; page=${entry.item.page_name}; author=${entry.item.author_name}; text=${entry.item.content_text}`;
    }
    return `${index + 1}. platform=${entry.item.platform}; rating=${entry.item.rating}; reviewer=${entry.item.reviewer_name}; text=${entry.item.review_text}`;
  });

  const schema = competitorDetectionResponseSchema();
  const response = await fetchResponseApi({
    model: OPENAI_MODEL,
    input: [
      {
        role: 'system',
        content: [
          {
            type: 'input_text',
            text: 'You are analyzing social listening data for an F&B brand in Vietnam. Detect competitor references and classify comparisons. Return strict JSON only.',
          },
        ],
      },
      {
        role: 'user',
        content: [
          {
            type: 'input_text',
            text: `Classify competitor mentions:

Identify:
1. competitor_name: Competitor mentioned (Domino's, Pizza Hut, local pizza shop, etc.)
2. comparison_type: ${COMPARISON_TYPES.join(', ')}
3. topic: ${TOPICS.join(', ')}
4. strength_score: 0-100 (how strong the competitive pressure is)
5. evidence_quote: Relevant quote from text (max 200 chars)

Items:
${promptLines.join('\n')}`,
          },
        ],
      },
    ],
    text: {
      format: {
        type: 'json_schema',
        name: 'competitor_detection_batch',
        strict: true,
        schema,
      },
    },
  });

  const payload = JSON.parse(extractResponseText(response));
  const items = Array.isArray(payload.items) ? payload.items : [];
  const result = [];

  for (const item of items) {
    const source = batch[Number(item.index) - 1];
    if (!source) continue;
    const detection = normalizeDetection(item);
    if (!isValidDetection(detection)) continue;
    result.push({ cacheKey: source.cacheKey, detection });
  }
  return result;
}

function normalizeDetection(item) {
  return {
    competitor_name: String(item.competitor_name || '').trim(),
    comparison_type: String(item.comparison_type || 'neutral').trim(),
    topic: String(item.topic || 'other').trim(),
    strength_score: Number(item.strength_score || 0),
    evidence_quote: String(item.evidence_quote || '').trim().slice(0, 200),
  };
}

function isValidDetection(detection) {
  return (
    detection &&
    typeof detection === 'object' &&
    detection.competitor_name &&
    COMPARISON_TYPES.includes(detection.comparison_type)
  );
}

function buildDetectionInserts(results, brandId) {
  return results.map(({ item, detection, mode }) => {
    const mentionId = mode === 'mention' ? item.mention_id : null;
    const reviewId = mode === 'review' ? item.review_id : null;

    return `
INSERT INTO ${SCHEMA}.competitor_mention_detections (
  mention_id, review_id, brand_id, competitor_name, comparison_type, topic, strength_score, evidence_quote, detected_at
)
VALUES (
  ${mentionId ? `${sqlStr(mentionId)}::uuid` : 'NULL'},
  ${reviewId ? `${sqlStr(reviewId)}::uuid` : 'NULL'},
  ${sqlStr(brandId)}::uuid,
  ${sqlStr(detection.competitor_name)},
  ${sqlStr(detection.comparison_type)},
  ${sqlStr(detection.topic)},
  ${sqlNum(detection.strength_score)},
  ${sqlStr(detection.evidence_quote)},
  NOW()
)
ON CONFLICT DO NOTHING;
`.trim();
  });
}

function competitorDetectionResponseSchema() {
  return {
    type: 'object',
    additionalProperties: false,
    properties: {
      items: {
        type: 'array',
        items: {
          type: 'object',
          additionalProperties: false,
          properties: {
            index: { type: 'integer' },
            competitor_name: { type: 'string' },
            comparison_type: { type: 'string', enum: COMPARISON_TYPES },
            topic: { type: 'string', enum: TOPICS },
            strength_score: { type: 'number' },
            evidence_quote: { type: 'string' },
          },
          required: ['index', 'competitor_name', 'comparison_type', 'topic', 'strength_score', 'evidence_quote'],
        },
      },
    },
    required: ['items'],
  };
}

async function fetchResponseApi(body) {
  const response = await fetch('https://api.openai.com/v1/responses', {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${OPENAI_API_KEY}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new Error(`OpenAI API error ${response.status}: ${await response.text()}`);
  }
  return response.json();
}

function extractResponseText(payload) {
  if (typeof payload.output_text === 'string' && payload.output_text.trim()) {
    return payload.output_text.trim();
  }
  const outputs = Array.isArray(payload.output) ? payload.output : [];
  for (const item of outputs) {
    const contents = Array.isArray(item.content) ? item.content : [];
    for (const content of contents) {
      if (typeof content.text === 'string' && content.text.trim()) {
        return content.text.trim();
      }
    }
  }
  throw new Error('No response text returned by OpenAI');
}

function buildCacheKey(mode, item) {
  const text = mode === 'mention' ? item.content_text : item.review_text;
  return `${mode}:${createHash('sha1').update(String(text || '')).digest('hex')}`;
}

function loadCache(cachePath) {
  if (!existsSync(cachePath)) return {};
  try {
    const payload = JSON.parse(readFileSync(cachePath, 'utf8'));
    return payload && typeof payload === 'object' ? payload : {};
  } catch {
    return {};
  }
}

function saveCache(cachePath, cache) {
  writeFileSync(cachePath, JSON.stringify(cache, null, 2), 'utf8');
}

function chunkArray(items, size) {
  const chunks = [];
  for (let index = 0; index < items.length; index += size) {
    chunks.push(items.slice(index, index + size));
  }
  return chunks;
}

function queryJson(sql) {
  const output = execFileSync(PSQL_BIN, [PGDATABASE, '-Atqc', sql], { encoding: 'utf8' }).trim();
  if (!output) return [];
  return JSON.parse(output);
}

function runSql(sql) {
  const sqlPath = resolve(tmpdir(), `competitor-detection-${Date.now()}.sql`);
  writeFileSync(sqlPath, sql, 'utf8');
  try {
    execFileSync(PSQL_BIN, [PGDATABASE, '-f', sqlPath], { stdio: 'pipe', encoding: 'utf8' });
  } finally {
    try {
      unlinkSync(sqlPath);
    } catch {
      // ignore
    }
  }
}

function runPsqlText(sql) {
  return execFileSync(PSQL_BIN, [PGDATABASE, '-Atqc', sql], { encoding: 'utf8' });
}

function sqlStr(value) {
  return `'${String(value ?? '').replace(/'/g, "''")}'`;
}

function sqlNum(value) {
  const num = Number(value);
  return Number.isFinite(num) ? String(num) : 'NULL';
}

await main();
