#!/usr/bin/env node
/**
 * Competitor Pressure Analysis with OpenAI
 *
 * Aggregates competitor mention detections and uses OpenAI to calculate
 * competitive pressure scores across 6 dimensions for radar chart visualization.
 *
 * Dimensions:
 * - Delivery (speed, quality, reliability)
 * - Value (price, worth for money)
 * - Family (family occasions, group dining, combos)
 * - Experience (ambiance, service, premium feel)
 * - Social Buzz (visibility, mentions, engagement)
 * - Premium (brand perception, quality positioning)
 *
 * Usage:
 *   node scripts/dashboard/analyze_competitor_pressure_openai.mjs
 *
 * Environment:
 *   OPENAI_API_KEY - Required
 *   PGDATABASE - Default: meili_dashboard
 *   PGSCHEMA - Default: meili_dashboard
 *   BRAND_SLUG - Default: meili-mi-bo-dai-loan
 *   OPENAI_MODEL - Default: gpt-4o-mini
 */

import { execFileSync } from 'child_process';
import { tmpdir } from 'os';
import { resolve } from 'path';
import { unlinkSync, writeFileSync } from 'fs';

const SCHEMA = process.env.PGSCHEMA || 'meili_dashboard';
const PGDATABASE = process.env.PGDATABASE || 'meili_dashboard';
const PSQL_BIN = process.env.PSQL_BIN || 'psql';
const BRAND_SLUG = process.env.BRAND_SLUG || 'meili-mi-bo-dai-loan';
const OPENAI_API_KEY = String(process.env.OPENAI_API_KEY || '').trim();
const OPENAI_MODEL = String(process.env.OPENAI_MODEL || 'gpt-4o-mini').trim() || 'gpt-4o-mini';
const DRY_RUN = String(process.env.DRY_RUN || '').trim() === '1';

const DIMENSIONS = ['delivery', 'value', 'family', 'experience', 'social_buzz', 'premium'];

async function main() {
  const brandId = fetchBrandId();
  if (!brandId) {
    throw new Error(`Brand not found: ${BRAND_SLUG}`);
  }

  const brandName = fetchBrandName(brandId);
  const competitorDetections = fetchCompetitorDetections(brandId);

  if (competitorDetections.length === 0) {
    console.log(
      JSON.stringify(
        {
          pg_database: PGDATABASE,
          schema: SCHEMA,
          brand_slug: BRAND_SLUG,
          message: 'No competitor detections found. Run detect_competitor_mentions_openai.mjs first.',
        },
        null,
        2,
      ),
    );
    return;
  }

  const aggregated = aggregateByCompetitorAndDimension(competitorDetections);

  console.log(
    JSON.stringify(
      {
        pg_database: PGDATABASE,
        schema: SCHEMA,
        brand_slug: BRAND_SLUG,
        brand_name: brandName,
        model: OPENAI_MODEL,
        total_detections: competitorDetections.length,
        unique_competitors: Object.keys(aggregated).length,
        dry_run: DRY_RUN,
      },
      null,
      2,
    ),
  );

  if (DRY_RUN) {
    console.log('DRY_RUN mode - aggregated data:');
    console.log(JSON.stringify(aggregated, null, 2));
    return;
  }

  if (!OPENAI_API_KEY) {
    throw new Error('OPENAI_API_KEY is required');
  }

  const pressureScores = await analyzePressureWithOpenAI(brandName, aggregated);

  const sqlParts = [`SET search_path TO ${SCHEMA}, public;`, ...buildPressureUpserts(brandId, pressureScores)];

  runSql(sqlParts.join('\n') + '\n');

  // Also aggregate patterns
  const patterns = await extractCompetitorPatterns(brandName, competitorDetections);
  const patternSql = [`SET search_path TO ${SCHEMA}, public;`, ...buildPatternUpserts(brandId, patterns)];
  runSql(patternSql.join('\n') + '\n');

  console.log(
    JSON.stringify(
      {
        competitors_analyzed: Object.keys(pressureScores).length,
        patterns_extracted: patterns.length,
        dimensions: DIMENSIONS,
      },
      null,
      2,
    ),
  );
}

function fetchBrandId() {
  const sql = `SELECT brand_id::text FROM ${SCHEMA}.brands WHERE brand_slug = ${sqlStr(BRAND_SLUG)} LIMIT 1;`;
  return runPsqlText(sql).trim();
}

function fetchBrandName(brandId) {
  const sql = `SELECT brand_name FROM ${SCHEMA}.brands WHERE brand_id = ${sqlStr(brandId)}::uuid LIMIT 1;`;
  return runPsqlText(sql).trim();
}

function fetchCompetitorDetections(brandId) {
  const sql = `
SELECT COALESCE(json_agg(row_to_json(t)), '[]'::json)::text
FROM (
  SELECT
    competitor_name,
    comparison_type,
    topic,
    strength_score,
    evidence_quote
  FROM ${SCHEMA}.competitor_mention_detections
  WHERE brand_id = ${sqlStr(brandId)}::uuid
  ORDER BY detected_at DESC
) t;
`;
  return queryJson(sql);
}

function aggregateByCompetitorAndDimension(detections) {
  const aggregated = {};

  for (const detection of detections) {
    const competitor = detection.competitor_name;
    if (!aggregated[competitor]) {
      aggregated[competitor] = {
        delivery: [],
        value: [],
        family: [],
        experience: [],
        social_buzz: [],
        premium: [],
      };
    }

    // Map topics to dimensions
    const dimension = mapTopicToDimension(detection.topic);
    if (dimension && aggregated[competitor][dimension]) {
      aggregated[competitor][dimension].push({
        comparison_type: detection.comparison_type,
        topic: detection.topic,
        strength_score: detection.strength_score,
        evidence_quote: detection.evidence_quote,
      });
    }
  }

  return aggregated;
}

function mapTopicToDimension(topic) {
  const mapping = {
    delivery_speed: 'delivery',
    delivery_quality: 'delivery',
    price: 'value',
    value_for_money: 'value',
    taste: 'premium',
    quality: 'premium',
    service: 'experience',
    menu_variety: 'family',
    family_offers: 'family',
    combos: 'family',
    promotions: 'value',
    location: 'social_buzz',
    ambiance: 'experience',
    experience: 'experience',
    premium_positioning: 'premium',
    brand_perception: 'social_buzz',
  };
  return mapping[topic] || 'social_buzz';
}

async function analyzePressureWithOpenAI(brandName, aggregated) {
  const competitors = Object.keys(aggregated);
  if (competitors.length === 0) {
    return {};
  }

  const inputData = competitors.map((competitor) => {
    const dimensionSummaries = {};
    for (const dimension of DIMENSIONS) {
      const mentions = aggregated[competitor][dimension] || [];
      dimensionSummaries[dimension] = {
        count: mentions.length,
        competitor_better_count: mentions.filter((m) => m.comparison_type === 'competitor_better').length,
        we_better_count: mentions.filter((m) => m.comparison_type === 'we_better').length,
        avg_strength: mentions.length
          ? mentions.reduce((sum, m) => sum + m.strength_score, 0) / mentions.length
          : 0,
        sample_quotes: mentions.slice(0, 3).map((m) => m.evidence_quote),
      };
    }
    return { competitor, dimensions: dimensionSummaries };
  });

  const prompt = `You are analyzing competitive intelligence for "${brandName}", an F&B brand in Vietnam.

Given competitor mention data, calculate competitive pressure scores (0-100) across these 6 dimensions:
1. **Delivery**: Speed, quality, reliability of delivery service
2. **Value**: Price perception, value for money, promotions
3. **Family**: Family occasions, group dining, combo offers
4. **Experience**: Dining ambiance, service quality, premium feel
5. **Social Buzz**: Social media visibility, mentions, brand awareness
6. **Premium**: Quality perception, ingredient quality, brand prestige

For OUR BRAND ("${brandName}") and each competitor, return scores for all 6 dimensions.

**Scoring logic:**
- Higher score = stronger in that dimension
- Consider:
  - Mention volume (more mentions = higher visibility/pressure)
  - Comparison type (competitor_better vs we_better)
  - Average strength score
  - Sample evidence

**Input data:**
${JSON.stringify(inputData, null, 2)}

Return strict JSON with this structure:
{
  "our_brand": {
    "delivery": 0-100,
    "value": 0-100,
    "family": 0-100,
    "experience": 0-100,
    "social_buzz": 0-100,
    "premium": 0-100
  },
  "competitors": [
    {
      "name": "Competitor Name",
      "delivery": 0-100,
      "value": 0-100,
      "family": 0-100,
      "experience": 0-100,
      "social_buzz": 0-100,
      "premium": 0-100
    }
  ]
}`;

  const response = await fetchResponseApi({
    model: OPENAI_MODEL,
    input: [
      {
        role: 'system',
        content: [
          {
            type: 'input_text',
            text: 'You are a competitive intelligence analyst for F&B brands. Return strict JSON only.',
          },
        ],
      },
      {
        role: 'user',
        content: [{ type: 'input_text', text: prompt }],
      },
    ],
    text: {
      format: {
        type: 'json_schema',
        name: 'competitive_pressure_scores',
        strict: true,
        schema: pressureScoreSchema(),
      },
    },
  });

  const result = JSON.parse(extractResponseText(response));
  return result;
}

async function extractCompetitorPatterns(brandName, detections) {
  if (detections.length === 0) return [];

  const competitorGroups = {};
  for (const detection of detections) {
    const competitor = detection.competitor_name;
    if (!competitorGroups[competitor]) {
      competitorGroups[competitor] = [];
    }
    competitorGroups[competitor].push(detection);
  }

  const prompt = `You are analyzing competitor patterns for "${brandName}", an F&B brand in Vietnam.

From competitor mentions, identify winning patterns/tactics:

**Common patterns to look for:**
1. **family_combo**: Strong family/group offers and combo deals
2. **delivery_deal**: Delivery promotions, speed advantages
3. **premium_storytelling**: Premium brand storytelling, quality narratives
4. **local_value**: Local convenience, neighborhood presence, affordability

For each competitor, identify which patterns they are strong in (score 0-100).

**Input:**
${JSON.stringify(
    Object.entries(competitorGroups).map(([competitor, mentions]) => ({
      competitor,
      sample_mentions: mentions.slice(0, 10).map((m) => ({
        topic: m.topic,
        evidence: m.evidence_quote,
      })),
    })),
    null,
    2,
  )}

Return strict JSON array of patterns.`;

  const response = await fetchResponseApi({
    model: OPENAI_MODEL,
    input: [
      {
        role: 'system',
        content: [{ type: 'input_text', text: 'You are a marketing pattern analyst. Return strict JSON only.' }],
      },
      {
        role: 'user',
        content: [{ type: 'input_text', text: prompt }],
      },
    ],
    text: {
      format: {
        type: 'json_schema',
        name: 'competitor_patterns',
        strict: true,
        schema: competitorPatternsSchema(),
      },
    },
  });

  const result = JSON.parse(extractResponseText(response));
  return result.patterns || [];
}

function buildPressureUpserts(brandId, scores) {
  const statements = [];

  // Our brand scores
  if (scores.our_brand) {
    for (const dimension of DIMENSIONS) {
      const ourScore = scores.our_brand[dimension] || 0;
      statements.push(`
INSERT INTO ${SCHEMA}.competitor_intel (
  brand_id, competitor_name, dimension, our_score, competitor_score, pressure_level, analyzed_at
)
VALUES (
  ${sqlStr(brandId)}::uuid,
  '__our_brand__',
  ${sqlStr(dimension)},
  ${sqlNum(ourScore)},
  0,
  'low',
  NOW()
)
ON CONFLICT (brand_id, competitor_name, dimension)
DO UPDATE SET
  our_score = EXCLUDED.our_score,
  analyzed_at = NOW();
`.trim());
    }
  }

  // Competitor scores
  const competitors = scores.competitors || [];
  for (const competitor of competitors) {
    const competitorName = competitor.name;
    for (const dimension of DIMENSIONS) {
      const ourScore = scores.our_brand ? scores.our_brand[dimension] || 0 : 0;
      const compScore = competitor[dimension] || 0;
      const pressureLevel = getPressureLevel(ourScore, compScore);

      statements.push(`
INSERT INTO ${SCHEMA}.competitor_intel (
  brand_id, competitor_name, dimension, our_score, competitor_score, pressure_level, analyzed_at
)
VALUES (
  ${sqlStr(brandId)}::uuid,
  ${sqlStr(competitorName)},
  ${sqlStr(dimension)},
  ${sqlNum(ourScore)},
  ${sqlNum(compScore)},
  ${sqlStr(pressureLevel)},
  NOW()
)
ON CONFLICT (brand_id, competitor_name, dimension)
DO UPDATE SET
  our_score = EXCLUDED.our_score,
  competitor_score = EXCLUDED.competitor_score,
  pressure_level = EXCLUDED.pressure_level,
  analyzed_at = NOW();
`.trim());
    }
  }

  return statements;
}

function buildPatternUpserts(brandId, patterns) {
  return patterns.map(
    (pattern) => `
INSERT INTO ${SCHEMA}.competitor_patterns (
  brand_id, competitor_name, pattern_name, pattern_strength, description, analyzed_at
)
VALUES (
  ${sqlStr(brandId)}::uuid,
  ${sqlStr(pattern.competitor_name)},
  ${sqlStr(pattern.pattern_name)},
  ${sqlNum(pattern.strength)},
  ${sqlStr(pattern.description || '')},
  NOW()
)
ON CONFLICT (brand_id, competitor_name, pattern_name)
DO UPDATE SET
  pattern_strength = EXCLUDED.pattern_strength,
  description = EXCLUDED.description,
  analyzed_at = NOW();
`.trim(),
  );
}

function getPressureLevel(ourScore, competitorScore) {
  const gap = competitorScore - ourScore;
  if (gap > 20) return 'high';
  if (gap > 0) return 'medium';
  return 'low';
}

function pressureScoreSchema() {
  const dimensionSchema = {
    type: 'object',
    additionalProperties: false,
    properties: {
      delivery: { type: 'number' },
      value: { type: 'number' },
      family: { type: 'number' },
      experience: { type: 'number' },
      social_buzz: { type: 'number' },
      premium: { type: 'number' },
    },
    required: ['delivery', 'value', 'family', 'experience', 'social_buzz', 'premium'],
  };

  return {
    type: 'object',
    additionalProperties: false,
    properties: {
      our_brand: dimensionSchema,
      competitors: {
        type: 'array',
        items: {
          type: 'object',
          additionalProperties: false,
          properties: {
            name: { type: 'string' },
            delivery: { type: 'number' },
            value: { type: 'number' },
            family: { type: 'number' },
            experience: { type: 'number' },
            social_buzz: { type: 'number' },
            premium: { type: 'number' },
          },
          required: ['name', 'delivery', 'value', 'family', 'experience', 'social_buzz', 'premium'],
        },
      },
    },
    required: ['our_brand', 'competitors'],
  };
}

function competitorPatternsSchema() {
  return {
    type: 'object',
    additionalProperties: false,
    properties: {
      patterns: {
        type: 'array',
        items: {
          type: 'object',
          additionalProperties: false,
          properties: {
            competitor_name: { type: 'string' },
            pattern_name: {
              type: 'string',
              enum: ['family_combo', 'delivery_deal', 'premium_storytelling', 'local_value', 'other'],
            },
            strength: { type: 'number' },
            description: { type: 'string' },
          },
          required: ['competitor_name', 'pattern_name', 'strength', 'description'],
        },
      },
    },
    required: ['patterns'],
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

function queryJson(sql) {
  const output = execFileSync(PSQL_BIN, [PGDATABASE, '-Atqc', sql], { encoding: 'utf8' }).trim();
  if (!output) return [];
  return JSON.parse(output);
}

function runSql(sql) {
  const sqlPath = resolve(tmpdir(), `competitor-pressure-${Date.now()}.sql`);
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
