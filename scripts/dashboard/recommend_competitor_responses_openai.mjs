#!/usr/bin/env node
/**
 * Competitor Response Recommendations with OpenAI
 *
 * Analyzes competitive threats and opportunities to generate strategic
 * response recommendations using 5 response modes:
 *
 * 1. **Similar**: Copy the pattern if it fits our brand DNA
 * 2. **Different**: Differentiate when we shouldn't compete directly
 * 3. **Merge**: Combine competitor pattern with our unique strength
 * 4. **Counter**: Attack after fixing internal issues first
 * 5. **Exploit**: Highlight competitor weakness (brand-safe tone)
 *
 * Usage:
 *   node scripts/dashboard/recommend_competitor_responses_openai.mjs
 *
 * Environment:
 *   OPENAI_API_KEY - Required
 *   PGDATABASE - Default: meili_dashboard
 *   PGSCHEMA - Default: meili_dashboard
 *   BRAND_SLUG - Default: meili-mi-bo-dai-loan
 *   OPENAI_MODEL - Default: gpt-4o
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
const OPENAI_MODEL = String(process.env.OPENAI_MODEL || 'gpt-4o').trim() || 'gpt-4o'; // Use smarter model for strategic analysis
const DRY_RUN = String(process.env.DRY_RUN || '').trim() === '1';

const RESPONSE_MODES = ['similar', 'different', 'merge', 'counter', 'exploit'];
const PRIORITIES = ['high', 'medium', 'low'];

async function main() {
  const brandId = fetchBrandId();
  if (!brandId) {
    throw new Error(`Brand not found: ${BRAND_SLUG}`);
  }

  const brandName = fetchBrandName(brandId);
  const pressureData = fetchCompetitorPressure(brandId);
  const patterns = fetchCompetitorPatterns(brandId);
  const ourStrengths = identifyOurStrengths(pressureData, brandName);

  if (pressureData.length === 0 && patterns.length === 0) {
    console.log(
      JSON.stringify(
        {
          pg_database: PGDATABASE,
          schema: SCHEMA,
          brand_slug: BRAND_SLUG,
          message: 'No competitor pressure data found. Run analyze_competitor_pressure_openai.mjs first.',
        },
        null,
        2,
      ),
    );
    return;
  }

  console.log(
    JSON.stringify(
      {
        pg_database: PGDATABASE,
        schema: SCHEMA,
        brand_slug: BRAND_SLUG,
        brand_name: brandName,
        model: OPENAI_MODEL,
        pressure_points: pressureData.length,
        patterns_identified: patterns.length,
        our_strengths: ourStrengths,
        dry_run: DRY_RUN,
      },
      null,
      2,
    ),
  );

  if (DRY_RUN) {
    console.log('DRY_RUN mode - input data:');
    console.log(JSON.stringify({ pressureData, patterns, ourStrengths }, null, 2));
    return;
  }

  if (!OPENAI_API_KEY) {
    throw new Error('OPENAI_API_KEY is required');
  }

  const recommendations = await generateResponseRecommendations(brandName, pressureData, patterns, ourStrengths);

  // Clear old recommendations and insert new ones
  const sqlParts = [
    `SET search_path TO ${SCHEMA}, public;`,
    `DELETE FROM ${SCHEMA}.competitor_responses WHERE brand_id = ${sqlStr(brandId)}::uuid;`,
    ...buildResponseInserts(brandId, recommendations),
  ];

  runSql(sqlParts.join('\n') + '\n');

  console.log(
    JSON.stringify(
      {
        recommendations_generated: recommendations.length,
        high_priority: recommendations.filter((r) => r.priority === 'high').length,
        medium_priority: recommendations.filter((r) => r.priority === 'medium').length,
        low_priority: recommendations.filter((r) => r.priority === 'low').length,
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

function fetchCompetitorPressure(brandId) {
  const sql = `
SELECT COALESCE(json_agg(row_to_json(t)), '[]'::json)::text
FROM (
  SELECT
    competitor_name,
    dimension,
    our_score,
    competitor_score,
    pressure_level
  FROM ${SCHEMA}.competitor_intel
  WHERE brand_id = ${sqlStr(brandId)}::uuid
    AND competitor_name != '__our_brand__'
  ORDER BY
    CASE pressure_level
      WHEN 'high' THEN 1
      WHEN 'medium' THEN 2
      ELSE 3
    END,
    (competitor_score - our_score) DESC
) t;
`;
  return queryJson(sql);
}

function fetchCompetitorPatterns(brandId) {
  const sql = `
SELECT COALESCE(json_agg(row_to_json(t)), '[]'::json)::text
FROM (
  SELECT
    competitor_name,
    pattern_name,
    pattern_strength,
    description
  FROM ${SCHEMA}.competitor_patterns
  WHERE brand_id = ${sqlStr(brandId)}::uuid
  ORDER BY pattern_strength DESC
) t;
`;
  return queryJson(sql);
}

function identifyOurStrengths(pressureData, brandName) {
  const ourScores = {};

  for (const row of pressureData) {
    if (!ourScores[row.dimension]) {
      ourScores[row.dimension] = row.our_score;
    }
  }

  const strengths = Object.entries(ourScores)
    .filter(([_, score]) => score > 60)
    .map(([dimension, score]) => ({ dimension, score }))
    .sort((a, b) => b.score - a.score);

  return strengths;
}

async function generateResponseRecommendations(brandName, pressureData, patterns, ourStrengths) {
  const prompt = `You are a competitive strategy consultant for "${brandName}", an F&B brand in Vietnam.

**Task:** Generate strategic response recommendations for competitive threats and opportunities.

**Response Modes (choose ONE per recommendation):**

1. **similar** - Copy competitor pattern if it fits our brand
   - When: Pattern is working well and aligns with our positioning
   - Example: "Create lunch set bundles like competitor X"

2. **different** - Differentiate instead of competing directly
   - When: Competing directly would hurt margins or brand
   - Example: "Don't do price war, emphasize premium quality instead"

3. **merge** - Combine competitor tactic with our unique strength
   - When: We can do their pattern BETTER using our strengths
   - Example: "Do family combo but with premium ingredients"

4. **counter** - Attack competitor after fixing internal issues
   - When: We need to fix our problems first before counter-marketing
   - Example: "Fix delivery speed first, THEN launch delivery campaign"

5. **exploit** - Highlight competitor weakness (brand-safe)
   - When: Competitor has clear weakness we can contrast
   - Example: "Emphasize consistency vs competitor's quality variation"

**Input Data:**

**Competitive Pressure:**
${JSON.stringify(pressureData.slice(0, 15), null, 2)}

**Competitor Patterns:**
${JSON.stringify(patterns, null, 2)}

**Our Strengths:**
${JSON.stringify(ourStrengths, null, 2)}

**Instructions:**
- Generate 3-8 recommendations
- Each recommendation must have:
  - competitor_name
  - threat_or_pattern (what we're responding to)
  - response_mode (one of: similar, different, merge, counter, exploit)
  - action_recommendation (specific actionable step)
  - priority (high/medium/low)
  - reasoning (why this mode and priority)
- Prioritize high-pressure threats first
- Consider our brand strengths in recommendations
- Be specific and actionable

Return strict JSON.`;

  const response = await fetchResponseApi({
    model: OPENAI_MODEL,
    input: [
      {
        role: 'system',
        content: [
          {
            type: 'input_text',
            text: 'You are a competitive strategy consultant specializing in F&B brands. Return strict JSON only.',
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
        name: 'competitor_response_recommendations',
        strict: true,
        schema: responseRecommendationsSchema(),
      },
    },
  });

  const result = JSON.parse(extractResponseText(response));
  return result.recommendations || [];
}

function buildResponseInserts(brandId, recommendations) {
  return recommendations.map(
    (rec) => `
INSERT INTO ${SCHEMA}.competitor_responses (
  brand_id, competitor_name, threat_or_pattern, response_mode,
  action_recommendation, priority, evidence_mentions, confidence_score, generated_at
)
VALUES (
  ${sqlStr(brandId)}::uuid,
  ${sqlStr(rec.competitor_name)},
  ${sqlStr(rec.threat_or_pattern)},
  ${sqlStr(rec.response_mode)},
  ${sqlStr(rec.action_recommendation)},
  ${sqlStr(rec.priority)},
  ${sqlJson({ reasoning: rec.reasoning || '' })}::jsonb,
  ${sqlNum(rec.confidence_score || 0.85)},
  NOW()
);
`.trim(),
  );
}

function responseRecommendationsSchema() {
  return {
    type: 'object',
    additionalProperties: false,
    properties: {
      recommendations: {
        type: 'array',
        items: {
          type: 'object',
          additionalProperties: false,
          properties: {
            competitor_name: { type: 'string' },
            threat_or_pattern: { type: 'string' },
            response_mode: { type: 'string', enum: RESPONSE_MODES },
            action_recommendation: { type: 'string' },
            priority: { type: 'string', enum: PRIORITIES },
            reasoning: { type: 'string' },
            confidence_score: { type: 'number' },
          },
          required: [
            'competitor_name',
            'threat_or_pattern',
            'response_mode',
            'action_recommendation',
            'priority',
            'reasoning',
          ],
        },
      },
    },
    required: ['recommendations'],
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
  const sqlPath = resolve(tmpdir(), `competitor-responses-${Date.now()}.sql`);
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

function sqlJson(value) {
  return `'${JSON.stringify(value ?? {}).replace(/'/g, "''")}'`;
}

await main();
