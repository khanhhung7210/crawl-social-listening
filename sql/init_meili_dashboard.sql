CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS citext;

CREATE SCHEMA IF NOT EXISTS meili_dashboard;

SET search_path TO meili_dashboard, public;

CREATE TABLE IF NOT EXISTS brands (
    brand_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_slug CITEXT NOT NULL UNIQUE,
    brand_name TEXT NOT NULL,
    vertical TEXT NOT NULL DEFAULT 'fnb',
    country_code TEXT NOT NULL DEFAULT 'VN',
    timezone_name TEXT NOT NULL DEFAULT 'Asia/Ho_Chi_Minh',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS branches (
    branch_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id UUID NOT NULL REFERENCES brands(brand_id) ON DELETE CASCADE,
    branch_slug CITEXT NOT NULL,
    branch_name TEXT NOT NULL,
    external_branch_key TEXT NOT NULL,
    address_line TEXT,
    ward TEXT,
    district TEXT,
    city TEXT,
    latitude NUMERIC(9, 6),
    longitude NUMERIC(9, 6),
    google_maps_url TEXT,
    shopeefood_url TEXT,
    aliases JSONB NOT NULL DEFAULT '[]'::JSONB,
    metadata JSONB NOT NULL DEFAULT '{}'::JSONB,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_branches_brand_slug UNIQUE (brand_id, branch_slug),
    CONSTRAINT uq_branches_brand_external_key UNIQUE (brand_id, external_branch_key)
);

CREATE TABLE IF NOT EXISTS branch_platform_refs (
    branch_platform_ref_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    branch_id UUID NOT NULL REFERENCES branches(branch_id) ON DELETE CASCADE,
    platform TEXT NOT NULL,
    platform_entity_id TEXT,
    platform_entity_name TEXT,
    platform_url TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_branch_platform_refs_platform CHECK (
        platform IN ('facebook', 'tiktok', 'threads', 'instagram', 'google_maps', 'shopeefood', 'grabfood', 'youtube')
    ),
    CONSTRAINT uq_branch_platform_refs UNIQUE (branch_id, platform, platform_url)
);

CREATE TABLE IF NOT EXISTS brand_source_configs (
    brand_source_config_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id UUID NOT NULL REFERENCES brands(brand_id) ON DELETE CASCADE,
    platform TEXT NOT NULL,
    channel_name TEXT NOT NULL DEFAULT '',
    source_url TEXT NOT NULL,
    source_type TEXT NOT NULL DEFAULT 'official_brand',
    priority TEXT NOT NULL DEFAULT 'core',
    include_in_dashboard BOOLEAN NOT NULL DEFAULT TRUE,
    crawl_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    metadata JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_brand_source_configs_platform CHECK (
        platform IN ('facebook', 'tiktok', 'threads', 'instagram', 'google_maps', 'shopeefood', 'grabfood', 'youtube')
    ),
    CONSTRAINT chk_brand_source_configs_type CHECK (
        source_type IN ('official_brand', 'store_branch', 'community_source', 'competitor')
    ),
    CONSTRAINT chk_brand_source_configs_priority CHECK (
        priority IN ('core', 'secondary', 'reference_only')
    ),
    CONSTRAINT uq_brand_source_configs UNIQUE (brand_id, platform, source_url)
);

CREATE INDEX IF NOT EXISTS idx_brand_source_configs_brand_platform
    ON brand_source_configs (brand_id, platform, include_in_dashboard, crawl_enabled);

CREATE TABLE IF NOT EXISTS ingest_runs (
    ingest_run_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id UUID REFERENCES brands(brand_id) ON DELETE SET NULL,
    source_type TEXT NOT NULL,
    platform TEXT NOT NULL,
    pipeline_name TEXT NOT NULL,
    input_file TEXT,
    output_file TEXT,
    run_status TEXT NOT NULL DEFAULT 'running',
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    records_seen INTEGER NOT NULL DEFAULT 0,
    records_written INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::JSONB,
    CONSTRAINT chk_ingest_runs_source_type CHECK (
        source_type IN ('social', 'maps', 'delivery_review', 'delivery_store', 'internal')
    ),
    CONSTRAINT chk_ingest_runs_platform CHECK (
        platform IN ('facebook', 'tiktok', 'threads', 'instagram', 'google_maps', 'shopeefood', 'youtube', 'system')
    ),
    CONSTRAINT chk_ingest_runs_status CHECK (
        run_status IN ('running', 'success', 'partial_success', 'failed')
    )
);

CREATE TABLE IF NOT EXISTS raw_documents (
    raw_document_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ingest_run_id UUID REFERENCES ingest_runs(ingest_run_id) ON DELETE SET NULL,
    brand_id UUID REFERENCES brands(brand_id) ON DELETE CASCADE,
    branch_id UUID REFERENCES branches(branch_id) ON DELETE SET NULL,
    source_type TEXT NOT NULL,
    platform TEXT NOT NULL,
    document_kind TEXT NOT NULL,
    natural_key TEXT NOT NULL,
    source_url TEXT,
    captured_at TIMESTAMPTZ,
    payload JSONB NOT NULL,
    content_text TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_raw_documents UNIQUE (platform, document_kind, natural_key),
    CONSTRAINT chk_raw_documents_source_type CHECK (
        source_type IN ('social', 'maps', 'delivery_review', 'delivery_store')
    )
);

CREATE INDEX IF NOT EXISTS idx_raw_documents_brand_platform
    ON raw_documents (brand_id, platform, document_kind);

CREATE INDEX IF NOT EXISTS idx_raw_documents_payload_gin
    ON raw_documents USING GIN (payload);

CREATE TABLE IF NOT EXISTS mentions (
    mention_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ingest_run_id UUID REFERENCES ingest_runs(ingest_run_id) ON DELETE SET NULL,
    brand_id UUID NOT NULL REFERENCES brands(brand_id) ON DELETE CASCADE,
    branch_id UUID REFERENCES branches(branch_id) ON DELETE SET NULL,
    source_type TEXT NOT NULL,
    platform TEXT NOT NULL,
    content_type TEXT NOT NULL,
    external_post_id TEXT NOT NULL,
    external_parent_id TEXT,
    page_id TEXT,
    page_name TEXT,
    author_name TEXT,
    post_url TEXT,
    content_text TEXT,
    language_code TEXT,
    content_created_at TIMESTAMPTZ,
    content_created_date DATE GENERATED ALWAYS AS ((content_created_at AT TIME ZONE 'Asia/Ho_Chi_Minh')::DATE) STORED,
    post_keyword_match BOOLEAN NOT NULL DEFAULT FALSE,
    parent_keyword_match BOOLEAN NOT NULL DEFAULT FALSE,
    engagement JSONB NOT NULL DEFAULT '{}'::JSONB,
    raw_document_id UUID REFERENCES raw_documents(raw_document_id) ON DELETE SET NULL,
    raw_payload JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_mentions_source_type CHECK (
        source_type IN ('social', 'maps', 'delivery_review')
    ),
    CONSTRAINT chk_mentions_platform CHECK (
        platform IN ('facebook', 'tiktok', 'threads', 'instagram', 'google_maps', 'shopeefood', 'youtube')
    ),
    CONSTRAINT chk_mentions_content_type CHECK (
        content_type IN ('post', 'comment', 'review', 'reply')
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_mentions_natural_key
    ON mentions (
        platform,
        content_type,
        external_post_id,
        COALESCE(branch_id, '00000000-0000-0000-0000-000000000000'::UUID)
    );

CREATE INDEX IF NOT EXISTS idx_mentions_brand_date
    ON mentions (brand_id, content_created_date DESC, platform);

CREATE INDEX IF NOT EXISTS idx_mentions_branch_date
    ON mentions (branch_id, content_created_date DESC);

CREATE INDEX IF NOT EXISTS idx_mentions_keyword_flags
    ON mentions (parent_keyword_match, post_keyword_match);

CREATE INDEX IF NOT EXISTS idx_mentions_text_search
    ON mentions USING GIN (to_tsvector('simple', COALESCE(content_text, '')));

CREATE TABLE IF NOT EXISTS reviews (
    review_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ingest_run_id UUID REFERENCES ingest_runs(ingest_run_id) ON DELETE SET NULL,
    brand_id UUID NOT NULL REFERENCES brands(brand_id) ON DELETE CASCADE,
    branch_id UUID REFERENCES branches(branch_id) ON DELETE SET NULL,
    platform TEXT NOT NULL,
    external_review_id TEXT NOT NULL,
    external_post_id TEXT,
    reviewer_name TEXT,
    review_url TEXT,
    review_text TEXT,
    rating NUMERIC(3, 2),
    review_created_at TIMESTAMPTZ,
    review_created_date DATE GENERATED ALWAYS AS ((review_created_at AT TIME ZONE 'Asia/Ho_Chi_Minh')::DATE) STORED,
    owner_replied BOOLEAN NOT NULL DEFAULT FALSE,
    owner_replied_at TIMESTAMPTZ,
    review_status TEXT NOT NULL DEFAULT 'captured',
    raw_document_id UUID REFERENCES raw_documents(raw_document_id) ON DELETE SET NULL,
    raw_payload JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_reviews_platform CHECK (
        platform IN ('google_maps', 'shopeefood', 'facebook')
    ),
    CONSTRAINT chk_reviews_status CHECK (
        review_status IN ('captured', 'enriched', 'hidden', 'discarded')
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_reviews_natural_key
    ON reviews (
        platform,
        external_review_id,
        COALESCE(branch_id, '00000000-0000-0000-0000-000000000000'::UUID)
    );

CREATE INDEX IF NOT EXISTS idx_reviews_branch_date
    ON reviews (branch_id, review_created_date DESC);

CREATE INDEX IF NOT EXISTS idx_reviews_rating
    ON reviews (platform, rating, review_created_date DESC);

CREATE TABLE IF NOT EXISTS menu_items (
    menu_item_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ingest_run_id UUID REFERENCES ingest_runs(ingest_run_id) ON DELETE SET NULL,
    brand_id UUID NOT NULL REFERENCES brands(brand_id) ON DELETE CASCADE,
    branch_id UUID REFERENCES branches(branch_id) ON DELETE SET NULL,
    platform TEXT NOT NULL,
    external_item_id TEXT,
    item_name TEXT NOT NULL,
    normalized_item_name TEXT,
    item_description TEXT,
    price_amount NUMERIC(12, 2),
    price_currency TEXT NOT NULL DEFAULT 'VND',
    is_available BOOLEAN NOT NULL DEFAULT TRUE,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    raw_document_id UUID REFERENCES raw_documents(raw_document_id) ON DELETE SET NULL,
    raw_payload JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_menu_items_platform CHECK (
        platform IN ('shopeefood', 'google_maps', 'facebook', 'instagram')
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_menu_items_natural_key
    ON menu_items (
        platform,
        COALESCE(external_item_id, normalized_item_name, item_name),
        COALESCE(branch_id, '00000000-0000-0000-0000-000000000000'::UUID)
    );

CREATE INDEX IF NOT EXISTS idx_menu_items_branch_platform
    ON menu_items (branch_id, platform, item_name);

CREATE TABLE IF NOT EXISTS mention_enrichments (
    mention_id UUID PRIMARY KEY REFERENCES mentions(mention_id) ON DELETE CASCADE,
    brand_id UUID NOT NULL REFERENCES brands(brand_id) ON DELETE CASCADE,
    branch_id UUID REFERENCES branches(branch_id) ON DELETE SET NULL,
    is_relevant_fnb BOOLEAN NOT NULL DEFAULT FALSE,
    relevance_score NUMERIC(5, 2) NOT NULL DEFAULT 0,
    relevance_reason JSONB NOT NULL DEFAULT '[]'::JSONB,
    sentiment_label TEXT,
    sentiment_score NUMERIC(5, 2),
    topic_label TEXT,
    subtopic_label TEXT,
    issue_type TEXT,
    confidence_score NUMERIC(5, 2),
    evidence_flag BOOLEAN NOT NULL DEFAULT FALSE,
    needs_response BOOLEAN NOT NULL DEFAULT FALSE,
    response_priority TEXT,
    enrichment_version TEXT NOT NULL DEFAULT 'v1',
    enriched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_mention_enrichments_sentiment CHECK (
        sentiment_label IS NULL OR sentiment_label IN (
            'positive', 'negative', 'neutral', 'mixed', 'demand', 'competitor', 'operational'
        )
    ),
    CONSTRAINT chk_mention_enrichments_priority CHECK (
        response_priority IS NULL OR response_priority IN ('high', 'medium', 'low')
    )
);

CREATE INDEX IF NOT EXISTS idx_mention_enrichments_relevance
    ON mention_enrichments (is_relevant_fnb, relevance_score DESC);

CREATE INDEX IF NOT EXISTS idx_mention_enrichments_topic
    ON mention_enrichments (topic_label, sentiment_label, response_priority);

CREATE TABLE IF NOT EXISTS review_enrichments (
    review_id UUID PRIMARY KEY REFERENCES reviews(review_id) ON DELETE CASCADE,
    brand_id UUID NOT NULL REFERENCES brands(brand_id) ON DELETE CASCADE,
    branch_id UUID REFERENCES branches(branch_id) ON DELETE SET NULL,
    sentiment_label TEXT,
    sentiment_score NUMERIC(5, 2),
    topic_label TEXT,
    issue_type TEXT,
    confidence_score NUMERIC(5, 2),
    is_high_risk BOOLEAN NOT NULL DEFAULT FALSE,
    needs_response BOOLEAN NOT NULL DEFAULT FALSE,
    unanswered_sla_hours INTEGER,
    enriched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_review_enrichments_sentiment CHECK (
        sentiment_label IS NULL OR sentiment_label IN ('positive', 'negative', 'neutral', 'mixed', 'operational')
    )
);

CREATE TABLE IF NOT EXISTS evidence_cards (
    evidence_card_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id UUID NOT NULL REFERENCES brands(brand_id) ON DELETE CASCADE,
    branch_id UUID REFERENCES branches(branch_id) ON DELETE SET NULL,
    source_record_type TEXT NOT NULL,
    source_record_id UUID NOT NULL,
    platform TEXT NOT NULL,
    evidence_date TIMESTAMPTZ,
    sentiment_label TEXT,
    confidence_score NUMERIC(5, 2),
    metric_label TEXT,
    evidence_quote TEXT NOT NULL,
    source_url TEXT,
    tags JSONB NOT NULL DEFAULT '[]'::JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_evidence_cards_record_type CHECK (
        source_record_type IN ('mention', 'review', 'menu_item', 'metric')
    )
);

CREATE INDEX IF NOT EXISTS idx_evidence_cards_brand_branch
    ON evidence_cards (brand_id, branch_id, platform, evidence_date DESC);

CREATE TABLE IF NOT EXISTS daily_branch_metrics (
    daily_branch_metric_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id UUID NOT NULL REFERENCES brands(brand_id) ON DELETE CASCADE,
    branch_id UUID REFERENCES branches(branch_id) ON DELETE SET NULL,
    metric_date DATE NOT NULL,
    mention_count INTEGER NOT NULL DEFAULT 0,
    relevant_mention_count INTEGER NOT NULL DEFAULT 0,
    positive_count INTEGER NOT NULL DEFAULT 0,
    neutral_count INTEGER NOT NULL DEFAULT 0,
    negative_count INTEGER NOT NULL DEFAULT 0,
    demand_count INTEGER NOT NULL DEFAULT 0,
    competitor_count INTEGER NOT NULL DEFAULT 0,
    review_count INTEGER NOT NULL DEFAULT 0,
    unanswered_review_count INTEGER NOT NULL DEFAULT 0,
    avg_rating NUMERIC(4, 2),
    net_sentiment_score NUMERIC(6, 2),
    top_topics JSONB NOT NULL DEFAULT '[]'::JSONB,
    source_mix JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_daily_branch_metrics UNIQUE (brand_id, branch_id, metric_date)
);

CREATE INDEX IF NOT EXISTS idx_daily_branch_metrics_brand_date
    ON daily_branch_metrics (brand_id, metric_date DESC);

CREATE TABLE IF NOT EXISTS dashboard_snapshots (
    dashboard_snapshot_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id UUID NOT NULL REFERENCES brands(brand_id) ON DELETE CASCADE,
    snapshot_date DATE NOT NULL,
    scope_type TEXT NOT NULL DEFAULT 'brand',
    scope_key TEXT NOT NULL DEFAULT 'all',
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_dashboard_snapshots UNIQUE (brand_id, snapshot_date, scope_type, scope_key)
);

INSERT INTO brands (brand_slug, brand_name)
VALUES ('meili-mi-bo-dai-loan', 'Meili 美丽 - Mì Bò Đài Loan')
ON CONFLICT (brand_slug) DO UPDATE
SET brand_name = EXCLUDED.brand_name,
    updated_at = NOW();
