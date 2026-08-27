-- =============================================================================
-- Galaxy Social Listening — Marketing (Brand Health) schema
-- PostgreSQL
--
-- Mục tiêu: phục vụ Marketing View trong social_listening_mockup_25.html
--  - Brand Health / SoV / Sentiment so sánh thương hiệu
--  - Top CX topics + negative drill-down
--  - Campaign tracking
--  - Owned / Paid / Earned
--  - App Store & Google Play reviews
--
-- KHÔNG dùng schema meili_dashboard (F&B Meili Mì Bò Đài Loan).
-- Database: galaxy_social_listening
-- Schema:   galaxy_sl
--
-- Tạo DB trước (chạy ngoài file này):
--   CREATE DATABASE galaxy_social_listening;
-- rồi:
--   psql -d galaxy_social_listening -f sql/galaxy_mkt_schema.sql
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS citext;

CREATE SCHEMA IF NOT EXISTS galaxy_sl;
SET search_path TO galaxy_sl, public;

-- -----------------------------------------------------------------------------
-- 1) MASTER DATA
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS brands (
    brand_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_slug          CITEXT NOT NULL UNIQUE,          -- glx, cgv, lotte, beta, bhd, cinestar, ncc, others
    brand_name          TEXT NOT NULL,
    brand_code          TEXT,                            -- GLX, CGV...
    cinema_count        INTEGER,                         -- số rạp (master / cập nhật tay)
    is_primary          BOOLEAN NOT NULL DEFAULT FALSE,  -- Galaxy = true
    is_competitor       BOOLEAN NOT NULL DEFAULT TRUE,
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    metadata            JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS regions (
    region_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    region_slug         CITEXT NOT NULL UNIQUE,          -- hcm, hn, central, mekong, north, south
    region_name         TEXT NOT NULL,
    sort_order          INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS cinemas (
    cinema_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id            UUID NOT NULL REFERENCES brands(brand_id) ON DELETE CASCADE,
    region_id           UUID REFERENCES regions(region_id) ON DELETE SET NULL,
    cinema_slug         CITEXT NOT NULL,
    cinema_name         TEXT NOT NULL,                   -- Galaxy Nguyễn Du
    city                TEXT,
    district            TEXT,
    address_line        TEXT,
    screen_count        INTEGER,                         -- optional, cho Dis sau này
    aliases             JSONB NOT NULL DEFAULT '[]'::JSONB,
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    metadata            JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_cinemas_brand_slug UNIQUE (brand_id, cinema_slug)
);

CREATE TABLE IF NOT EXISTS platforms (
    platform_code       TEXT PRIMARY KEY,                -- facebook, tiktok, threads, youtube, instagram, google, news, appstore, google_play
    platform_name       TEXT NOT NULL,
    channel_group       TEXT NOT NULL DEFAULT 'social', -- social | review | app | news
    is_active           BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS topics (
    topic_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    topic_slug          CITEXT NOT NULL UNIQUE,          -- service, ticket_price, merch, booking, facility, fnb, parking, tech
    topic_name          TEXT NOT NULL,                   -- Dịch vụ rạp, Giá vé...
    topic_group         TEXT NOT NULL DEFAULT 'cx',      -- cx | film | brand | campaign | app
    sort_order          INTEGER NOT NULL DEFAULT 0,
    is_active           BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS topic_keywords (
    topic_keyword_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    topic_id            UUID NOT NULL REFERENCES topics(topic_id) ON DELETE CASCADE,
    keyword             TEXT NOT NULL,
    lang                TEXT NOT NULL DEFAULT 'vi',
    weight              NUMERIC(4,2) NOT NULL DEFAULT 1.0,
    CONSTRAINT uq_topic_keywords UNIQUE (topic_id, keyword, lang)
);

-- Listening queries: brand / movie / campaign / crisis / generic
CREATE TABLE IF NOT EXISTS listening_queries (
    query_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    query_type          TEXT NOT NULL,                   -- brand | movie | campaign | crisis | generic
    brand_id            UUID REFERENCES brands(brand_id) ON DELETE SET NULL,
    query_name          TEXT NOT NULL,
    keywords            JSONB NOT NULL DEFAULT '[]'::JSONB,
    hashtags            JSONB NOT NULL DEFAULT '[]'::JSONB,
    platforms           JSONB NOT NULL DEFAULT '[]'::JSONB,
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    metadata            JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_listening_queries_type CHECK (
        query_type IN ('brand', 'movie', 'campaign', 'crisis', 'generic')
    )
);

-- Official / paid / community source whitelist (Owned / Paid / Earned)
CREATE TABLE IF NOT EXISTS source_profiles (
    source_profile_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id            UUID REFERENCES brands(brand_id) ON DELETE SET NULL,
    platform_code       TEXT NOT NULL REFERENCES platforms(platform_code),
    source_key          TEXT NOT NULL,                   -- page_id / channel_id / handle
    source_name         TEXT NOT NULL,
    media_type          TEXT NOT NULL DEFAULT 'earned',  -- owned | paid | earned
    follower_count      BIGINT,
    tier                TEXT,                            -- mega | macro | micro | nano | brand
    source_url          TEXT,
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    metadata            JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_source_profiles_media_type CHECK (
        media_type IN ('owned', 'paid', 'earned')
    ),
    CONSTRAINT uq_source_profiles UNIQUE (platform_code, source_key)
);

-- -----------------------------------------------------------------------------
-- 2) INGEST / RAW
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS ingest_runs (
    ingest_run_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pipeline_name       TEXT NOT NULL,                   -- facebook_crawl, appstore_reviews...
    platform_code       TEXT REFERENCES platforms(platform_code),
    query_id            UUID REFERENCES listening_queries(query_id) ON DELETE SET NULL,
    run_status          TEXT NOT NULL DEFAULT 'running',
    input_file          TEXT,
    output_file         TEXT,
    records_seen        INTEGER NOT NULL DEFAULT 0,
    records_written     INTEGER NOT NULL DEFAULT 0,
    error_message       TEXT,
    started_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at         TIMESTAMPTZ,
    metadata            JSONB NOT NULL DEFAULT '{}'::JSONB,
    CONSTRAINT chk_ingest_runs_status CHECK (
        run_status IN ('running', 'success', 'partial_success', 'failed')
    )
);

CREATE TABLE IF NOT EXISTS raw_documents (
    raw_document_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ingest_run_id       UUID REFERENCES ingest_runs(ingest_run_id) ON DELETE SET NULL,
    platform_code       TEXT NOT NULL REFERENCES platforms(platform_code),
    external_id         TEXT NOT NULL,                   -- post_id / review_id
    document_kind       TEXT NOT NULL DEFAULT 'post',    -- post | comment | review | article
    payload             JSONB NOT NULL,
    content_text        TEXT,
    source_url          TEXT,
    fetched_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_raw_documents UNIQUE (platform_code, document_kind, external_id)
);

-- -----------------------------------------------------------------------------
-- 3) CANONICAL SOCIAL DOCUMENTS (posts + comments)
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS posts (
    post_id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    platform_code       TEXT NOT NULL REFERENCES platforms(platform_code),
    external_post_id    TEXT NOT NULL,
    source_profile_id   UUID REFERENCES source_profiles(source_profile_id) ON DELETE SET NULL,
    author_key          TEXT,                            -- unique author/page key
    author_name         TEXT,
    post_text           TEXT,
    post_url            TEXT,
    media_type          TEXT,                            -- owned | paid | earned (resolved)
    view_count          BIGINT,
    like_count          BIGINT,
    comment_count       INTEGER,
    share_count         INTEGER,
    posted_at           TIMESTAMPTZ,
    cinema_id           UUID REFERENCES cinemas(cinema_id) ON DELETE SET NULL,
    region_id           UUID REFERENCES regions(region_id) ON DELETE SET NULL,
    spam_score          NUMERIC(5,2) NOT NULL DEFAULT 0,
    is_spam             BOOLEAN NOT NULL DEFAULT FALSE,
    raw_document_id     UUID REFERENCES raw_documents(raw_document_id) ON DELETE SET NULL,
    metadata            JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_posts_platform_external UNIQUE (platform_code, external_post_id),
    CONSTRAINT chk_posts_media_type CHECK (
        media_type IS NULL OR media_type IN ('owned', 'paid', 'earned')
    )
);

CREATE INDEX IF NOT EXISTS idx_posts_posted_at ON posts (posted_at DESC);
CREATE INDEX IF NOT EXISTS idx_posts_platform_posted ON posts (platform_code, posted_at DESC);

CREATE TABLE IF NOT EXISTS comments (
    comment_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    post_id             UUID NOT NULL REFERENCES posts(post_id) ON DELETE CASCADE,
    platform_code       TEXT NOT NULL REFERENCES platforms(platform_code),
    external_comment_id TEXT,
    author_key          TEXT,
    author_name         TEXT,
    comment_text        TEXT NOT NULL,
    commented_at        TIMESTAMPTZ,
    like_count          INTEGER,
    spam_score          NUMERIC(5,2) NOT NULL DEFAULT 0,
    is_spam             BOOLEAN NOT NULL DEFAULT FALSE,
    raw_document_id     UUID REFERENCES raw_documents(raw_document_id) ON DELETE SET NULL,
    metadata            JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_comments_post ON comments (post_id);
CREATE INDEX IF NOT EXISTS idx_comments_commented_at ON comments (commented_at DESC);
-- Prevent re-import duplicates (requires external_comment_id always set by importer)
CREATE UNIQUE INDEX IF NOT EXISTS uq_comments_post_external
    ON comments (post_id, external_comment_id)
    WHERE external_comment_id IS NOT NULL AND external_comment_id <> '';

-- Unified mention = post OR comment (đơn vị tính buzz / SoV / sentiment)
CREATE TABLE IF NOT EXISTS mentions (
    mention_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mention_kind        TEXT NOT NULL,                   -- post | comment
    post_id             UUID REFERENCES posts(post_id) ON DELETE CASCADE,
    comment_id          UUID REFERENCES comments(comment_id) ON DELETE CASCADE,
    platform_code       TEXT NOT NULL REFERENCES platforms(platform_code),
    source_profile_id   UUID REFERENCES source_profiles(source_profile_id) ON DELETE SET NULL,
    author_key          TEXT,
    content_text        TEXT NOT NULL,
    media_type          TEXT,                            -- owned | paid | earned
    sentiment           TEXT,                            -- positive | negative | neutral
    sentiment_score     NUMERIC(5,4),
    sentiment_provider  TEXT,                            -- keywords | openai | human
    cinema_id           UUID REFERENCES cinemas(cinema_id) ON DELETE SET NULL,
    region_id           UUID REFERENCES regions(region_id) ON DELETE SET NULL,
    occurred_at         TIMESTAMPTZ NOT NULL,
    is_spam             BOOLEAN NOT NULL DEFAULT FALSE,
    permalink           TEXT,
    metadata            JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_mentions_kind CHECK (mention_kind IN ('post', 'comment')),
    CONSTRAINT chk_mentions_sentiment CHECK (
        sentiment IS NULL OR sentiment IN ('positive', 'negative', 'neutral')
    ),
    CONSTRAINT chk_mentions_media_type CHECK (
        media_type IS NULL OR media_type IN ('owned', 'paid', 'earned')
    ),
    CONSTRAINT chk_mentions_ref CHECK (
        (mention_kind = 'post' AND post_id IS NOT NULL AND comment_id IS NULL)
        OR (mention_kind = 'comment' AND comment_id IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_mentions_occurred_at ON mentions (occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_mentions_platform_time ON mentions (platform_code, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_mentions_sentiment ON mentions (sentiment) WHERE is_spam = FALSE;
-- One buzz unit per post / per comment
CREATE UNIQUE INDEX IF NOT EXISTS uq_mentions_post_kind
    ON mentions (post_id)
    WHERE mention_kind = 'post' AND post_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_mentions_comment_kind
    ON mentions (comment_id)
    WHERE mention_kind = 'comment' AND comment_id IS NOT NULL;

-- One mention can hit multiple brands → SoV
CREATE TABLE IF NOT EXISTS mention_brands (
    mention_id          UUID NOT NULL REFERENCES mentions(mention_id) ON DELETE CASCADE,
    brand_id            UUID NOT NULL REFERENCES brands(brand_id) ON DELETE CASCADE,
    match_method        TEXT NOT NULL DEFAULT 'keyword', -- keyword | ner | human
    confidence          NUMERIC(5,4) NOT NULL DEFAULT 1.0,
    PRIMARY KEY (mention_id, brand_id)
);

CREATE INDEX IF NOT EXISTS idx_mention_brands_brand ON mention_brands (brand_id);

CREATE TABLE IF NOT EXISTS mention_topics (
    mention_id          UUID NOT NULL REFERENCES mentions(mention_id) ON DELETE CASCADE,
    topic_id            UUID NOT NULL REFERENCES topics(topic_id) ON DELETE CASCADE,
    match_method        TEXT NOT NULL DEFAULT 'keyword',
    confidence          NUMERIC(5,4) NOT NULL DEFAULT 1.0,
    PRIMARY KEY (mention_id, topic_id)
);

CREATE INDEX IF NOT EXISTS idx_mention_topics_topic ON mention_topics (topic_id);

-- Human labeling overrides
CREATE TABLE IF NOT EXISTS mention_labels (
    mention_label_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mention_id          UUID NOT NULL REFERENCES mentions(mention_id) ON DELETE CASCADE,
    labeled_by          TEXT,
    sentiment_override  TEXT,
    topic_ids           JSONB NOT NULL DEFAULT '[]'::JSONB,
    risk_level          TEXT,                            -- normal | warning | crisis
    note                TEXT,
    labeled_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_mention_labels_sentiment CHECK (
        sentiment_override IS NULL OR sentiment_override IN ('positive', 'negative', 'neutral')
    ),
    CONSTRAINT chk_mention_labels_risk CHECK (
        risk_level IS NULL OR risk_level IN ('normal', 'warning', 'crisis')
    )
);

-- -----------------------------------------------------------------------------
-- 4) CAMPAIGNS (MKT)
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS campaigns (
    campaign_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id            UUID REFERENCES brands(brand_id) ON DELETE SET NULL,
    campaign_name       TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'running', -- running | ended | draft
    start_date          DATE,
    end_date            DATE,
    primary_platforms   JSONB NOT NULL DEFAULT '[]'::JSONB,
    metadata            JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_campaigns_status CHECK (
        status IN ('draft', 'running', 'ended')
    )
);

CREATE TABLE IF NOT EXISTS campaign_keywords (
    campaign_keyword_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    campaign_id         UUID NOT NULL REFERENCES campaigns(campaign_id) ON DELETE CASCADE,
    keyword             TEXT NOT NULL,
    is_hashtag          BOOLEAN NOT NULL DEFAULT FALSE,
    CONSTRAINT uq_campaign_keywords UNIQUE (campaign_id, keyword)
);

CREATE TABLE IF NOT EXISTS mention_campaigns (
    mention_id          UUID NOT NULL REFERENCES mentions(mention_id) ON DELETE CASCADE,
    campaign_id         UUID NOT NULL REFERENCES campaigns(campaign_id) ON DELETE CASCADE,
    match_method        TEXT NOT NULL DEFAULT 'keyword',
    confidence          NUMERIC(5,4) NOT NULL DEFAULT 1.0,
    PRIMARY KEY (mention_id, campaign_id)
);

-- -----------------------------------------------------------------------------
-- 5) APP REVIEWS (MKT App Store / Google Play)
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS mobile_apps (
    app_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id            UUID NOT NULL REFERENCES brands(brand_id) ON DELETE CASCADE,
    store               TEXT NOT NULL,                   -- appstore | google_play
    store_app_id        TEXT NOT NULL,                   -- 593312549 | com.galaxy.cinema
    app_name            TEXT NOT NULL,
    country_code        TEXT NOT NULL DEFAULT 'vn',
    lang                TEXT NOT NULL DEFAULT 'vi',
    is_primary          BOOLEAN NOT NULL DEFAULT FALSE,  -- Galaxy apps
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    metadata            JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_mobile_apps_store CHECK (store IN ('appstore', 'google_play')),
    CONSTRAINT uq_mobile_apps_store_id UNIQUE (store, store_app_id, country_code)
);

CREATE TABLE IF NOT EXISTS app_reviews (
    app_review_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    app_id              UUID NOT NULL REFERENCES mobile_apps(app_id) ON DELETE CASCADE,
    external_review_id  TEXT,
    author_name         TEXT,
    rating              SMALLINT NOT NULL,
    title               TEXT,
    review_text         TEXT,
    app_version         TEXT,
    reviewed_at         TIMESTAMPTZ,
    thumbs_up_count     INTEGER,
    developer_reply     TEXT,
    developer_replied_at TIMESTAMPTZ,
    topic_id            UUID REFERENCES topics(topic_id) ON DELETE SET NULL,
    sentiment           TEXT,
    permalink           TEXT,
    raw_payload         JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_app_reviews_rating CHECK (rating BETWEEN 1 AND 5),
    CONSTRAINT chk_app_reviews_sentiment CHECK (
        sentiment IS NULL OR sentiment IN ('positive', 'negative', 'neutral')
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_app_reviews_external
    ON app_reviews (app_id, external_review_id)
    WHERE external_review_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_app_reviews_reviewed_at ON app_reviews (reviewed_at DESC);
CREATE INDEX IF NOT EXISTS idx_app_reviews_rating ON app_reviews (app_id, rating);

-- Snapshot rating tổng (đối thủ chỉ cần summary cũng lưu được)
CREATE TABLE IF NOT EXISTS app_rating_snapshots (
    snapshot_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    app_id              UUID NOT NULL REFERENCES mobile_apps(app_id) ON DELETE CASCADE,
    snapshot_date       DATE NOT NULL,
    avg_rating          NUMERIC(3,2),
    ratings_count       INTEGER,
    reviews_count       INTEGER,
    histogram           JSONB NOT NULL DEFAULT '{}'::JSONB, -- {"1":n,"2":n...}
    version_latest      TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_app_rating_snapshots UNIQUE (app_id, snapshot_date)
);

-- -----------------------------------------------------------------------------
-- 6) EXTERNAL IMPORTS (GBO, không crawl social)
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS gbo_snapshots (
    gbo_snapshot_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id            UUID NOT NULL REFERENCES brands(brand_id) ON DELETE CASCADE,
    period_start        DATE NOT NULL,
    period_end          DATE NOT NULL,
    gbo_share_pct       NUMERIC(5,2),
    cinema_count        INTEGER,
    source_name         TEXT,                            -- báo cáo nội bộ
    metadata            JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- -----------------------------------------------------------------------------
-- 7) DAILY AGGREGATES (để chart MKT nhanh)
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS daily_brand_metrics (
    metric_date         DATE NOT NULL,
    brand_id            UUID NOT NULL REFERENCES brands(brand_id) ON DELETE CASCADE,
    platform_code       TEXT NOT NULL DEFAULT 'all',     -- all | facebook | tiktok...
    buzz_count          INTEGER NOT NULL DEFAULT 0,      -- posts + comments (non-spam)
    post_count          INTEGER NOT NULL DEFAULT 0,
    comment_count       INTEGER NOT NULL DEFAULT 0,
    source_count        INTEGER NOT NULL DEFAULT 0,
    positive_count      INTEGER NOT NULL DEFAULT 0,
    negative_count      INTEGER NOT NULL DEFAULT 0,
    neutral_count       INTEGER NOT NULL DEFAULT 0,
    owned_count         INTEGER NOT NULL DEFAULT 0,
    paid_count          INTEGER NOT NULL DEFAULT 0,
    earned_count        INTEGER NOT NULL DEFAULT 0,
    sov_pct             NUMERIC(6,3),                    -- % trong ngày (cùng platform filter)
    unique_authors      INTEGER,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (metric_date, brand_id, platform_code)
);

CREATE TABLE IF NOT EXISTS daily_topic_metrics (
    metric_date         DATE NOT NULL,
    brand_id            UUID NOT NULL REFERENCES brands(brand_id) ON DELETE CASCADE,
    topic_id            UUID NOT NULL REFERENCES topics(topic_id) ON DELETE CASCADE,
    platform_code       TEXT NOT NULL DEFAULT 'all',
    mention_count       INTEGER NOT NULL DEFAULT 0,
    positive_count      INTEGER NOT NULL DEFAULT 0,
    negative_count      INTEGER NOT NULL DEFAULT 0,
    neutral_count       INTEGER NOT NULL DEFAULT 0,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (metric_date, brand_id, topic_id, platform_code)
);

CREATE TABLE IF NOT EXISTS daily_campaign_metrics (
    metric_date         DATE NOT NULL,
    campaign_id         UUID NOT NULL REFERENCES campaigns(campaign_id) ON DELETE CASCADE,
    platform_code       TEXT NOT NULL DEFAULT 'all',
    buzz_count          INTEGER NOT NULL DEFAULT 0,
    positive_count      INTEGER NOT NULL DEFAULT 0,
    negative_count      INTEGER NOT NULL DEFAULT 0,
    neutral_count       INTEGER NOT NULL DEFAULT 0,
    sov_pct             NUMERIC(6,3),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (metric_date, campaign_id, platform_code)
);

-- -----------------------------------------------------------------------------
-- 8) ALERTS (shared, dùng sớm cho MKT)
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS alert_rules (
    alert_rule_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    rule_name           TEXT NOT NULL,
    rule_type           TEXT NOT NULL,                   -- negative_spike | buzz_spike | crisis_keyword | app_low_rating
    brand_id            UUID REFERENCES brands(brand_id) ON DELETE CASCADE,
    config              JSONB NOT NULL DEFAULT '{}'::JSONB,
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS alert_events (
    alert_event_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    alert_rule_id       UUID REFERENCES alert_rules(alert_rule_id) ON DELETE SET NULL,
    brand_id            UUID REFERENCES brands(brand_id) ON DELETE SET NULL,
    severity            TEXT NOT NULL DEFAULT 'warning', -- info | warning | critical
    title               TEXT NOT NULL,
    body                TEXT,
    payload             JSONB NOT NULL DEFAULT '{}'::JSONB,
    is_read             BOOLEAN NOT NULL DEFAULT FALSE,
    fired_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_alert_events_severity CHECK (
        severity IN ('info', 'warning', 'critical')
    )
);

-- -----------------------------------------------------------------------------
-- 9) SEED — brands / platforms / topics tối thiểu
-- -----------------------------------------------------------------------------

INSERT INTO brands (brand_slug, brand_name, brand_code, cinema_count, is_primary, is_competitor)
VALUES
    ('glx', 'Galaxy', 'GLX', 30, TRUE, FALSE),
    ('cgv', 'CGV', 'CGV', 85, FALSE, TRUE),
    ('lotte', 'Lotte', 'LOTTE', 44, FALSE, TRUE),
    ('beta', 'Beta', 'BETA', 21, FALSE, TRUE),
    ('cinestar', 'Cinestar', 'CS', 9, FALSE, TRUE),
    ('bhd', 'BHD Star', 'BHD', 12, FALSE, TRUE),
    ('ncc', 'NCC', 'NCC', 1, FALSE, TRUE),
    ('others', 'Others', 'OTHERS', NULL, FALSE, FALSE)
ON CONFLICT (brand_slug) DO UPDATE
SET brand_name = EXCLUDED.brand_name,
    cinema_count = EXCLUDED.cinema_count,
    updated_at = NOW();

INSERT INTO platforms (platform_code, platform_name, channel_group) VALUES
    ('facebook', 'Facebook', 'social'),
    ('tiktok', 'TikTok', 'social'),
    ('threads', 'Threads', 'social'),
    ('youtube', 'YouTube', 'social'),
    ('instagram', 'Instagram', 'social'),
    ('google', 'Google Reviews', 'review'),
    ('news', 'News', 'news'),
    ('appstore', 'App Store', 'app'),
    ('google_play', 'Google Play', 'app')
ON CONFLICT (platform_code) DO NOTHING;

INSERT INTO topics (topic_slug, topic_name, topic_group, sort_order) VALUES
    ('service', 'Dịch vụ rạp', 'cx', 10),
    ('ticket_price', 'Giá vé', 'cx', 20),
    ('merch', 'Movie Merch', 'cx', 30),
    ('booking', 'App/Booking', 'cx', 40),
    ('facility', 'Cơ sở vật chất', 'cx', 50),
    ('fnb', 'Food & Beverage', 'cx', 60),
    ('parking', 'Parking', 'cx', 70),
    ('tech', 'Công nghệ (IMAX/Dolby)', 'cx', 80),
    ('app_crash', 'App bị crash', 'app', 110),
    ('app_booking_error', 'Đặt vé lỗi', 'app', 120),
    ('app_slow', 'Load chậm', 'app', 130),
    ('app_payment', 'Thanh toán thất bại', 'app', 140),
    ('app_ui', 'UI khó dùng', 'app', 150),
    ('app_login', 'Đăng nhập / OTP', 'app', 160)
ON CONFLICT (topic_slug) DO NOTHING;

INSERT INTO regions (region_slug, region_name, sort_order) VALUES
    ('hcm', 'TP. Hồ Chí Minh', 10),
    ('hn', 'Hà Nội', 20),
    ('central', 'Miền Trung', 30),
    ('mekong_east', 'Miền Tây & Miền Đông', 40),
    ('north', 'Miền Bắc', 50)
ON CONFLICT (region_slug) DO NOTHING;

-- Galaxy + competitor mobile apps
INSERT INTO mobile_apps (brand_id, store, store_app_id, app_name, is_primary)
SELECT b.brand_id, v.store, v.store_app_id, v.app_name, v.is_primary
FROM brands b
JOIN (
    VALUES
        ('glx', 'google_play', 'com.galaxy.cinema', 'Galaxy Cinema', TRUE),
        ('glx', 'appstore', '593312549', 'Galaxy Cinema', TRUE),
        ('cgv', 'google_play', 'com.cgv.cinema.vn', 'CGV Cinemas Vietnam', FALSE),
        ('lotte', 'google_play', 'vn.com.lottecinema.pro', 'Lotte Cinema', FALSE),
        ('beta', 'google_play', 'com.beta.betacineplex', 'Beta Cinemas', FALSE),
        ('bhd', 'google_play', 'io.starec.bhdstarcineplex', 'BHD Star Cineplex', FALSE),
        ('cinestar', 'google_play', 'com.kingprocompany.cinestar', 'Cinestar', FALSE),
        ('cinestar', 'appstore', '1473249809', 'Cinestar', FALSE)
) AS v(brand_slug, store, store_app_id, app_name, is_primary)
  ON b.brand_slug = v.brand_slug
ON CONFLICT (store, store_app_id, country_code) DO NOTHING;

-- -----------------------------------------------------------------------------
-- 10) HELPER VIEWS cho MKT dashboard
-- -----------------------------------------------------------------------------

CREATE OR REPLACE VIEW v_mkt_brand_health_7d AS
SELECT
    b.brand_slug,
    b.brand_name,
    b.cinema_count,
    SUM(m.buzz_count) AS buzz,
    SUM(m.positive_count) AS positive_count,
    SUM(m.negative_count) AS negative_count,
    SUM(m.neutral_count) AS neutral_count,
    CASE WHEN SUM(m.positive_count + m.negative_count + m.neutral_count) > 0
        THEN ROUND(100.0 * SUM(m.positive_count) / SUM(m.positive_count + m.negative_count + m.neutral_count), 2)
        ELSE NULL END AS positive_pct,
    CASE WHEN SUM(m.positive_count + m.negative_count + m.neutral_count) > 0
        THEN ROUND(100.0 * SUM(m.negative_count) / SUM(m.positive_count + m.negative_count + m.neutral_count), 2)
        ELSE NULL END AS negative_pct
FROM daily_brand_metrics m
JOIN brands b ON b.brand_id = m.brand_id
WHERE m.metric_date >= CURRENT_DATE - INTERVAL '7 days'
  AND m.platform_code = 'all'
GROUP BY b.brand_slug, b.brand_name, b.cinema_count;

COMMENT ON SCHEMA galaxy_sl IS 'Galaxy Social Listening — Marketing brand health (cinema). Not Meili F&B.';
