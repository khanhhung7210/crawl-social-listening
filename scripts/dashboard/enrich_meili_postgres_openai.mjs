import { createHash } from 'crypto';
import { existsSync, mkdirSync, readFileSync, unlinkSync, writeFileSync } from 'fs';
import { tmpdir } from 'os';
import { resolve } from 'path';
import { execFileSync } from 'child_process';

const SCHEMA = process.env.PGSCHEMA || 'meili_dashboard';
const PGDATABASE = process.env.PGDATABASE || 'meili_dashboard';
const PSQL_BIN = process.env.PSQL_BIN || 'psql';
const OPENAI_API_KEY = String(process.env.OPENAI_API_KEY || '').trim();
const OPENAI_MODEL = String(process.env.OPENAI_MODEL || 'gpt-4o-mini').trim() || 'gpt-4o-mini';
const OPENAI_BATCH_SIZE = Math.max(1, Number(process.env.OPENAI_BATCH_SIZE || 20));
const OPENAI_MAX_MENTIONS = Math.max(0, Number(process.env.OPENAI_MAX_MENTIONS || 5000));
const OPENAI_MAX_REVIEWS = Math.max(0, Number(process.env.OPENAI_MAX_REVIEWS || 5000));
const DRY_RUN = String(process.env.DRY_RUN || '').trim() === '1';
const CACHE_DIR = resolve(process.cwd(), 'tmp', 'openai-enrichment');
const CACHE_PATH = resolve(CACHE_DIR, 'meili_pg_enrichment_cache.json');

const MENTION_SENTIMENTS = ['positive', 'negative', 'neutral', 'mixed', 'demand', 'competitor', 'operational'];
const REVIEW_SENTIMENTS = ['positive', 'negative', 'neutral', 'mixed', 'operational'];
const TOPICS = [
  'food_quality',
  'taste',
  'price_value',
  'service_speed',
  'staff_service',
  'delivery',
  'location',
  'ambiance',
  'cleanliness',
  'menu_variety',
  'promotion',
  'branch_experience',
  'general_buzz',
  'unknown',
];
const ISSUE_TYPES = [
  'praise',
  'complaint',
  'question',
  'request',
  'competitor_reference',
  'operational_issue',
  'recommendation',
  'none',
];
const PRIORITIES = ['high', 'medium', 'low'];

async function main() {
  const mentionRows = fetchPendingMentions(OPENAI_MAX_MENTIONS);
  const reviewRows = fetchPendingReviews(OPENAI_MAX_REVIEWS);

  if (DRY_RUN) {
    console.log(
      JSON.stringify(
        {
          pg_database: PGDATABASE,
          schema: SCHEMA,
          model: OPENAI_MODEL,
          pending_mentions: mentionRows.length,
          pending_reviews: reviewRows.length,
          dry_run: true,
        },
        null,
        2,
      ),
    );
    return;
  }

  if (!OPENAI_API_KEY) {
    throw new Error('OPENAI_API_KEY is required. Export it in your shell before running this job.');
  }

  mkdirSync(CACHE_DIR, { recursive: true });
  const cache = loadCache(CACHE_PATH);

  const mentionResults = await classifyRecords(mentionRows, 'mention', cache);
  const reviewResults = await classifyRecords(reviewRows, 'review', cache);
  saveCache(CACHE_PATH, cache);

  const sqlParts = [
    `SET search_path TO ${SCHEMA}, public;`,
    ...buildMentionUpserts(mentionResults),
    ...buildReviewUpserts(reviewResults),
  ];
  runSql(sqlParts.join('\n') + '\n');

  console.log(
    JSON.stringify(
      {
        pg_database: PGDATABASE,
        schema: SCHEMA,
        model: OPENAI_MODEL,
        mentions_enriched: mentionResults.length,
        reviews_enriched: reviewResults.length,
        cache_path: CACHE_PATH,
      },
      null,
      2,
    ),
  );
}

function fetchPendingMentions(limit) {
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
  WHERE COALESCE(me.sentiment_label, '') = ''
    AND NULLIF(BTRIM(COALESCE(m.content_text, '')), '') IS NOT NULL
  ORDER BY m.content_created_at NULLS LAST, m.created_at
  LIMIT ${Number(limit)}
) t;
`;
  return queryJson(sql);
}

function fetchPendingReviews(limit) {
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
  WHERE COALESCE(re.sentiment_label, '') = ''
    AND NULLIF(BTRIM(COALESCE(r.review_text, '')), '') IS NOT NULL
  ORDER BY r.review_created_at NULLS LAST, r.created_at
  LIMIT ${Number(limit)}
) t;
`;
  return queryJson(sql);
}

async function classifyRecords(rows, mode, cache) {
  const uniqueInputs = [];
  const seenKeys = new Set();
  const recordsByKey = new Map();

  for (const row of rows) {
    const cacheKey = buildCacheKey(mode, row);
    if (!recordsByKey.has(cacheKey)) recordsByKey.set(cacheKey, []);
    recordsByKey.get(cacheKey).push(row);
    if (seenKeys.has(cacheKey)) continue;
    seenKeys.add(cacheKey);
    uniqueInputs.push({ cacheKey, row });
  }

  const resultsByKey = new Map();
  const pending = [];

  for (const item of uniqueInputs) {
    const cached = cache[item.cacheKey];
    if (cached && isValidClassification(mode, cached)) {
      resultsByKey.set(item.cacheKey, cached);
      continue;
    }
    pending.push(item);
  }

  for (const batch of chunkArray(pending, OPENAI_BATCH_SIZE)) {
    const classified = await classifyBatch(batch, mode);
    for (const entry of classified) {
      cache[entry.cacheKey] = entry.classification;
      resultsByKey.set(entry.cacheKey, entry.classification);
    }
  }

  const finalRows = [];
  for (const [cacheKey, sourceRows] of recordsByKey.entries()) {
    const classification = resultsByKey.get(cacheKey);
    if (!classification) continue;
    for (const row of sourceRows) {
      finalRows.push({ row, classification });
    }
  }
  return finalRows;
}

async function classifyBatch(batch, mode) {
  const promptLines = batch.map((item, index) => {
    if (mode === 'mention') {
      return `${index + 1}. platform=${item.row.platform}; content_type=${item.row.content_type}; page=${item.row.page_name}; author=${item.row.author_name}; text=${item.row.content_text}`;
    }
    return `${index + 1}. platform=${item.row.platform}; rating=${item.row.rating}; reviewer=${item.row.reviewer_name}; text=${item.row.review_text}`;
  });

  const schema = mode === 'mention' ? mentionResponseSchema() : reviewResponseSchema();
  const response = await fetchResponseApi({
    model: OPENAI_MODEL,
    input: [
      {
        role: 'system',
        content: [
          {
            type: 'input_text',
            text:
              mode === 'mention'
                ? 'You classify social listening records for an F&B brand in Vietnam. Return strict JSON only. Focus on restaurant-related feedback, customer demand, competitor mentions, and operational issues.'
                : 'You classify F&B customer reviews for a restaurant brand in Vietnam. Return strict JSON only. Focus on food quality, service, delivery, pricing, and operational issues.',
          },
        ],
      },
      {
        role: 'user',
        content: [
          {
            type: 'input_text',
            text:
              mode === 'mention'
                ? `Classify each mention. Allowed sentiment labels: ${MENTION_SENTIMENTS.join(', ')}. Allowed topic labels: ${TOPICS.join(', ')}. Allowed issue types: ${ISSUE_TYPES.join(', ')}. Allowed response priorities: ${PRIORITIES.join(', ')}. Confidence and relevance are numbers from 0 to 1. Comments:\n${promptLines.join('\n')}`
                : `Classify each review. Allowed sentiment labels: ${REVIEW_SENTIMENTS.join(', ')}. Allowed topic labels: ${TOPICS.join(', ')}. Allowed issue types: ${ISSUE_TYPES.join(', ')}. Confidence is a number from 0 to 1. Comments:\n${promptLines.join('\n')}`,
          },
        ],
      },
    ],
    text: {
      format: {
        type: 'json_schema',
        name: mode === 'mention' ? 'mention_enrichment_batch' : 'review_enrichment_batch',
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
    const classification = normalizeClassification(mode, item);
    if (!isValidClassification(mode, classification)) continue;
    result.push({ cacheKey: source.cacheKey, classification });
  }
  return result;
}

function normalizeClassification(mode, item) {
  if (mode === 'mention') {
    return {
      sentiment_label: String(item.sentiment_label || '').trim(),
      sentiment_score: Number(item.sentiment_score || 0),
      topic_label: String(item.topic_label || 'unknown').trim(),
      subtopic_label: String(item.subtopic_label || '').trim(),
      issue_type: String(item.issue_type || 'none').trim(),
      confidence_score: Number(item.confidence_score || 0),
      is_relevant_fnb: Boolean(item.is_relevant_fnb),
      relevance_score: Number(item.relevance_score || 0),
      relevance_reason: Array.isArray(item.relevance_reason) ? item.relevance_reason.map(String) : [],
      evidence_flag: Boolean(item.evidence_flag),
      needs_response: Boolean(item.needs_response),
      response_priority: String(item.response_priority || 'low').trim(),
    };
  }
  return {
    sentiment_label: String(item.sentiment_label || '').trim(),
    sentiment_score: Number(item.sentiment_score || 0),
    topic_label: String(item.topic_label || 'unknown').trim(),
    issue_type: String(item.issue_type || 'none').trim(),
    confidence_score: Number(item.confidence_score || 0),
    is_high_risk: Boolean(item.is_high_risk),
    needs_response: Boolean(item.needs_response),
    unanswered_sla_hours: Number.isFinite(Number(item.unanswered_sla_hours))
      ? Number(item.unanswered_sla_hours)
      : null,
  };
}

function isValidClassification(mode, classification) {
  if (!classification || typeof classification !== 'object') return false;
  if (mode === 'mention') {
    return MENTION_SENTIMENTS.includes(classification.sentiment_label);
  }
  return REVIEW_SENTIMENTS.includes(classification.sentiment_label);
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
  ${sqlJson(classification.relevance_reason)},
  ${sqlStr(classification.sentiment_label)},
  ${sqlNum(classification.sentiment_score)},
  ${sqlStr(classification.topic_label)},
  ${sqlStr(classification.subtopic_label)},
  ${sqlStr(classification.issue_type)},
  ${sqlNum(classification.confidence_score)},
  ${sqlBool(classification.evidence_flag)},
  ${sqlBool(classification.needs_response)},
  ${sqlStr(classification.response_priority)},
  'openai-v1',
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

function mentionResponseSchema() {
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
            sentiment_label: { type: 'string', enum: MENTION_SENTIMENTS },
            sentiment_score: { type: 'number' },
            topic_label: { type: 'string', enum: TOPICS },
            subtopic_label: { type: 'string' },
            issue_type: { type: 'string', enum: ISSUE_TYPES },
            confidence_score: { type: 'number' },
            is_relevant_fnb: { type: 'boolean' },
            relevance_score: { type: 'number' },
            relevance_reason: { type: 'array', items: { type: 'string' } },
            evidence_flag: { type: 'boolean' },
            needs_response: { type: 'boolean' },
            response_priority: { type: 'string', enum: PRIORITIES },
          },
          required: [
            'index',
            'sentiment_label',
            'sentiment_score',
            'topic_label',
            'subtopic_label',
            'issue_type',
            'confidence_score',
            'is_relevant_fnb',
            'relevance_score',
            'relevance_reason',
            'evidence_flag',
            'needs_response',
            'response_priority',
          ],
        },
      },
    },
    required: ['items'],
  };
}

function reviewResponseSchema() {
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
            sentiment_label: { type: 'string', enum: REVIEW_SENTIMENTS },
            sentiment_score: { type: 'number' },
            topic_label: { type: 'string', enum: TOPICS },
            issue_type: { type: 'string', enum: ISSUE_TYPES },
            confidence_score: { type: 'number' },
            is_high_risk: { type: 'boolean' },
            needs_response: { type: 'boolean' },
            unanswered_sla_hours: { anyOf: [{ type: 'integer' }, { type: 'null' }] },
          },
          required: [
            'index',
            'sentiment_label',
            'sentiment_score',
            'topic_label',
            'issue_type',
            'confidence_score',
            'is_high_risk',
            'needs_response',
            'unanswered_sla_hours',
          ],
        },
      },
    },
    required: ['items'],
  };
}

function fetchResponseApi(body) {
  const response = fetch('https://api.openai.com/v1/responses', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${OPENAI_API_KEY}`,
    },
    body: JSON.stringify(body),
  });
  return response.then(async (res) => {
    if (!res.ok) {
      throw new Error(`OpenAI API error ${res.status}: ${await res.text()}`);
    }
    return res.json();
  });
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

function buildCacheKey(mode, row) {
  const text = mode === 'mention' ? row.content_text : row.review_text;
  const platform = row.platform || '';
  return `${mode}:${platform}:${createHash('sha1').update(String(text || '')).digest('hex')}`;
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
  const output = execFileSync(
    PSQL_BIN,
    [PGDATABASE, '-Atqc', sql],
    { encoding: 'utf8' },
  ).trim();
  if (!output) return [];
  return JSON.parse(output);
}

function runSql(sql) {
  const sqlPath = resolve(tmpdir(), `meili-openai-enrichment-${Date.now()}.sql`);
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

function sqlStr(value) {
  return `'${String(value ?? '').replace(/'/g, "''")}'`;
}

function sqlBool(value) {
  return value ? 'TRUE' : 'FALSE';
}

function sqlNum(value) {
  const num = Number(value);
  return Number.isFinite(num) ? String(num) : 'NULL';
}

function sqlJson(value) {
  return `${sqlStr(JSON.stringify(value ?? null))}::jsonb`;
}

await main();
