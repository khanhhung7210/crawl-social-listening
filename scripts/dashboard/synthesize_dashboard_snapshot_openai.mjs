import { execFileSync } from 'child_process';

const SCHEMA = process.env.PGSCHEMA || 'meili_dashboard';
const PGDATABASE = process.env.PGDATABASE || 'meili_dashboard';
const PSQL_BIN = process.env.PSQL_BIN || 'psql';
const BRAND_SLUG = process.env.BRAND_SLUG || 'meili-mi-bo-dai-loan';
const OPENAI_API_KEY = String(process.env.OPENAI_API_KEY || '').trim();
const OPENAI_MODEL = String(process.env.OPENAI_MODEL || 'gpt-4o-mini').trim() || 'gpt-4o-mini';
const DRY_RUN = String(process.env.DRY_RUN || '').trim() === '1';

async function main() {
  const basePayload = loadBasePayload();
  if (DRY_RUN) {
    console.log(JSON.stringify(buildAiInput(basePayload), null, 2));
    return;
  }
  if (!OPENAI_API_KEY) {
    throw new Error('OPENAI_API_KEY is required. Export it in your shell before running this job.');
  }

  const promptInput = buildAiInput(basePayload);
  const aiPayload = await synthesizeSnapshot(promptInput);
  const brandId = fetchBrandId();
  upsertSnapshot(brandId, aiPayload);
  console.log(
    JSON.stringify(
      {
        pg_database: PGDATABASE,
        schema: SCHEMA,
        brand_slug: BRAND_SLUG,
        model: OPENAI_MODEL,
        snapshot_written: true,
        overview_cards: (aiPayload.overview?.top_cards || []).length,
        screens_overridden: Object.keys(aiPayload.screens || {}).length,
      },
      null,
      2,
    ),
  );
}

function loadBasePayload() {
  const code = `
import json
from social_listening.dashboard.repository import PostgresDashboardRepository
repo = PostgresDashboardRepository(database='${PGDATABASE}', schema='${SCHEMA}', brand_slug='${BRAND_SLUG}')
print(json.dumps(repo.get_dashboard_payload(), ensure_ascii=False))
  `.trim();
  const text = execFileSync('python3', ['-c', code], {
    cwd: process.cwd(),
    env: { ...process.env, PYTHONPATH: `${process.cwd()}/src` },
    encoding: 'utf8',
  });
  return JSON.parse(text);
}

function buildAiInput(payload) {
  return {
    brand: payload.brand,
    date_range: payload.date_range,
    platform_summary: (payload.platform_summary || []).map((row) => ({
      platform: row.platform,
      relevant_count: row.relevant_count,
      positive_count: row.positive_count,
      negative_count: row.negative_count,
      review_count: row.review_count,
      readiness_score: row.readiness_score,
      status: row.status,
    })),
    branches: (payload.branch_intelligence || []).slice(0, 6).map((row) => ({
      branch_name: row.branch_name,
      risk_score: row.risk_score,
      risk_level: row.risk_level,
      avg_rating: row.avg_rating,
      review_count: row.review_count,
      negative_count: row.negative_count,
      top_topics: row.top_topics,
      watchout: row.watchout,
    })),
    evidence_cards: (payload.evidence_cards || []).slice(0, 18).map((row) => ({
      platform: row.platform,
      metric_label: row.metric_label,
      sentiment_label: row.sentiment_label,
      confidence_score: row.confidence_score,
      evidence_quote: row.evidence_quote,
      source_url: row.source_url,
    })),
    mentions_feed: (payload.mentions_feed || []).slice(0, 12),
    current_screens: payload.screens,
  };
}

async function synthesizeSnapshot(input) {
  const response = await fetchResponseApi({
    model: OPENAI_MODEL,
    input: [
      {
        role: 'system',
        content: [
          {
            type: 'input_text',
            text:
              'You are synthesizing a restaurant growth dashboard for Vietnam. Produce strict JSON only. Keep everything evidence-backed, concise, and business-readable. Do not invent metrics that contradict the source payload. You may rewrite, prioritize, cluster, and summarize. Prefer Vietnamese copy for customer-facing dashboard text.',
          },
        ],
      },
      {
        role: 'user',
        content: [
          {
            type: 'input_text',
            text: `Using this dashboard payload as source truth, rewrite only the parts that benefit from AI synthesis: overview headline, overview top cards, Lost Customer Signals module, Today's Action Timeline module, and a concise Dotn Listen headline. Preserve the general structure and chart types. Source payload:\n${JSON.stringify(input)}`,
          },
        ],
      },
    ],
    text: {
      format: {
        type: 'json_schema',
        name: 'dashboard_snapshot_override',
        strict: true,
        schema: snapshotSchema(),
      },
    },
  });
  return JSON.parse(extractResponseText(response));
}

function snapshotSchema() {
  return {
    type: 'object',
    additionalProperties: false,
    properties: {
      overview: {
        type: 'object',
        additionalProperties: false,
        properties: {
          headline: { type: 'string' },
          top_cards: {
            type: 'array',
            items: {
              type: 'object',
              additionalProperties: false,
              properties: {
                tag: { type: 'string' },
                title: { type: 'string' },
                value: { type: 'string' },
                desc: { type: 'string' },
                severity: { type: 'string', enum: ['high', 'medium', 'low'] },
                owner: { type: 'string' },
                guardrail: { type: 'string' },
                evidence_kind: { type: 'string' },
                evidence_branch: { type: 'string' },
                evidence_platform: { type: 'string' },
              },
              required: ['tag', 'title', 'value', 'desc', 'severity', 'owner', 'guardrail', 'evidence_kind', 'evidence_branch', 'evidence_platform'],
            },
          },
        },
        required: ['headline', 'top_cards'],
      },
      screens: {
        type: 'object',
        additionalProperties: false,
        properties: {
          overview: {
            type: 'object',
            additionalProperties: false,
            properties: {
              headline: { type: 'string' },
              modules: {
                type: 'array',
                items: {
                  type: 'object',
                  additionalProperties: false,
                  properties: {
                    title: { type: 'string', enum: ['Lost Customer Signals', "Today's Action Timeline"] },
                    takeaway: { type: 'string' },
                    chart: { type: 'string', enum: ['hbar', 'timeline'] },
                    data: {
                      type: 'array',
                      items: {
                        type: 'array',
                        items: { type: ['string', 'number'] },
                      },
                    },
                    analysis: { type: 'array', items: { type: 'string' } },
                    action: {
                      type: 'object',
                      additionalProperties: false,
                      properties: {
                        guardrail: { type: 'string' },
                        owner: { type: 'string' },
                        cta: { type: 'string' },
                      },
                      required: ['guardrail', 'owner', 'cta'],
                    },
                    evidence_query: { type: 'string' },
                  },
                  required: ['title', 'takeaway', 'chart', 'data', 'analysis', 'action', 'evidence_query'],
                },
              },
            },
            required: ['headline', 'modules'],
          },
          listen: {
            type: 'object',
            additionalProperties: false,
            properties: {
              headline: { type: 'string' },
            },
            required: ['headline'],
          },
        },
        required: ['overview', 'listen'],
      },
    },
    required: ['overview', 'screens'],
  };
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

function upsertSnapshot(brandId, payload) {
  const sql = `
INSERT INTO ${SCHEMA}.dashboard_snapshots (
  brand_id, snapshot_date, scope_type, scope_key, payload
)
VALUES (
  ${sqlStr(brandId)},
  CURRENT_DATE,
  'brand',
  'all',
  ${sqlJson(payload)}::jsonb
)
ON CONFLICT (brand_id, snapshot_date, scope_type, scope_key)
DO UPDATE SET payload = EXCLUDED.payload, created_at = NOW();
`;
  runPsqlText(sql);
}

function runPsqlText(sql) {
  return execFileSync(PSQL_BIN, [PGDATABASE, '-Atqc', sql], {
    cwd: process.cwd(),
    env: process.env,
    encoding: 'utf8',
  });
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
    const text = await response.text();
    throw new Error(`OpenAI API error ${response.status}: ${text}`);
  }
  return response.json();
}

function extractResponseText(response) {
  if (typeof response.output_text === 'string' && response.output_text.trim()) {
    return response.output_text;
  }
  const parts = [];
  for (const item of response.output || []) {
    for (const content of item.content || []) {
      if (content.type === 'output_text' && typeof content.text === 'string') {
        parts.push(content.text);
      }
    }
  }
  const text = parts.join('\n').trim();
  if (!text) throw new Error('OpenAI response did not contain output_text');
  return text;
}

function sqlStr(value) {
  return `'${String(value ?? '').replaceAll("'", "''")}'`;
}

function sqlJson(value) {
  return sqlStr(JSON.stringify(value));
}

main().catch((error) => {
  console.error(error?.message || error);
  process.exit(1);
});
