-- Apply on live DB without re-running full schema:
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -c "SET search_path TO galaxy_sl, public" -f sql/migrations/001_gift_leads.sql

CREATE TABLE IF NOT EXISTS gift_leads (
    lead_id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    platform_code       TEXT NOT NULL REFERENCES platforms(platform_code),
    author_key          TEXT NOT NULL DEFAULT '',
    author_name         TEXT,
    profile_url         TEXT,
    entity_type         TEXT NOT NULL DEFAULT 'unknown',
    intent_tag          TEXT NOT NULL,
    signal_score        NUMERIC(8,2) NOT NULL DEFAULT 0,
    evidence_text       TEXT NOT NULL,
    evidence_url        TEXT,
    evidence_at         TIMESTAMPTZ,
    mention_id          UUID REFERENCES mentions(mention_id) ON DELETE SET NULL,
    contact_phone       TEXT,
    contact_email       TEXT,
    contact_zalo        TEXT,
    status              TEXT NOT NULL DEFAULT 'new',
    notes               TEXT,
    matched_keywords    JSONB NOT NULL DEFAULT '[]'::JSONB,
    metadata            JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_gift_leads_entity CHECK (
        entity_type IN ('business', 'individual', 'unknown')
    ),
    CONSTRAINT chk_gift_leads_status CHECK (
        status IN ('new', 'contacted', 'qualified', 'rejected')
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_gift_leads_mention
    ON gift_leads (mention_id);

CREATE UNIQUE INDEX IF NOT EXISTS uq_gift_leads_evidence
    ON gift_leads (platform_code, author_key, evidence_url, intent_tag)
    WHERE evidence_url IS NOT NULL AND evidence_url <> '';

CREATE INDEX IF NOT EXISTS idx_gift_leads_status_score
    ON gift_leads (status, signal_score DESC, evidence_at DESC NULLS LAST);

CREATE INDEX IF NOT EXISTS idx_gift_leads_intent
    ON gift_leads (intent_tag, status);
