-- Galaxy Distribution — film listening (extends galaxy_sl)
-- Apply after galaxy_mkt_schema.sql:
--   psql -d galaxy_social_listening -f sql/galaxy_dis_schema.sql

SET search_path TO galaxy_sl, public;

CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS citext;

-- -----------------------------------------------------------------------------
-- Films catalog
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS films (
    film_id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    film_slug           CITEXT NOT NULL UNIQUE,
    film_title          TEXT NOT NULL,
    short_title         TEXT,
    status              TEXT NOT NULL DEFAULT 'upcoming',  -- upcoming | in_release | ended
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    release_date        DATE,
    trailer_date        DATE,
    distributor         TEXT,
    compare_group       TEXT,
    metadata            JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_films_status CHECK (
        status IN ('upcoming', 'in_release', 'ended')
    )
);

CREATE TABLE IF NOT EXISTS film_aliases (
    film_alias_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    film_id             UUID NOT NULL REFERENCES films(film_id) ON DELETE CASCADE,
    alias               TEXT NOT NULL,
    alias_norm          TEXT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_film_aliases_norm UNIQUE (alias_norm)
);

CREATE INDEX IF NOT EXISTS idx_film_aliases_film ON film_aliases (film_id);

CREATE TABLE IF NOT EXISTS film_milestones (
    film_milestone_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    film_id             UUID NOT NULL REFERENCES films(film_id) ON DELETE CASCADE,
    label               TEXT NOT NULL,
    milestone_date      DATE NOT NULL,
    color               TEXT,
    sort_order          INTEGER NOT NULL DEFAULT 0,
    metadata            JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_film_milestones_film_date
    ON film_milestones (film_id, milestone_date);

-- mention → film (SoV / compare multi-film)
CREATE TABLE IF NOT EXISTS mention_films (
    mention_id          UUID NOT NULL REFERENCES mentions(mention_id) ON DELETE CASCADE,
    film_id             UUID NOT NULL REFERENCES films(film_id) ON DELETE CASCADE,
    match_method        TEXT NOT NULL DEFAULT 'keyword',  -- keyword | path | alias | human
    confidence          NUMERIC(5,4) NOT NULL DEFAULT 1.0,
    PRIMARY KEY (mention_id, film_id)
);

CREATE INDEX IF NOT EXISTS idx_mention_films_film ON mention_films (film_id);

-- Daily aggregates for Distribution KPIs
CREATE TABLE IF NOT EXISTS daily_film_metrics (
    metric_date         DATE NOT NULL,
    film_id             UUID NOT NULL REFERENCES films(film_id) ON DELETE CASCADE,
    platform_code       TEXT NOT NULL DEFAULT 'all',
    buzz_count          INTEGER NOT NULL DEFAULT 0,
    post_count          INTEGER NOT NULL DEFAULT 0,
    comment_count       INTEGER NOT NULL DEFAULT 0,
    positive_count      INTEGER NOT NULL DEFAULT 0,
    negative_count      INTEGER NOT NULL DEFAULT 0,
    neutral_count       INTEGER NOT NULL DEFAULT 0,
    unique_authors      INTEGER,
    view_count          BIGINT NOT NULL DEFAULT 0,
    sov_pct             NUMERIC(6,3),
    intent_want_count   INTEGER NOT NULL DEFAULT 0,
    intent_total        INTEGER NOT NULL DEFAULT 0,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (metric_date, film_id, platform_code)
);

CREATE INDEX IF NOT EXISTS idx_daily_film_metrics_film_date
    ON daily_film_metrics (film_id, metric_date DESC);

-- Optional: intent label on mentions (WOM)
ALTER TABLE mentions
    ADD COLUMN IF NOT EXISTS intent TEXT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'chk_mentions_intent'
    ) THEN
        ALTER TABLE mentions
            ADD CONSTRAINT chk_mentions_intent CHECK (
                intent IS NULL OR intent IN (
                    'want_to_see',
                    'watched_praise',
                    'watched_criticize',
                    'will_recommend',
                    'not_interested'
                )
            );
    END IF;
END $$;

CREATE OR REPLACE VIEW v_dis_film_health_7d AS
SELECT
    f.film_slug,
    f.film_title,
    f.short_title,
    f.status,
    SUM(m.buzz_count) AS buzz_7d,
    SUM(m.post_count) AS posts_7d,
    SUM(m.comment_count) AS comments_7d,
    SUM(m.positive_count) AS positive_7d,
    SUM(m.negative_count) AS negative_7d,
    SUM(m.unique_authors) AS unique_authors_7d,
    SUM(m.view_count) AS views_7d
FROM daily_film_metrics m
JOIN films f ON f.film_id = m.film_id
WHERE m.metric_date >= CURRENT_DATE - INTERVAL '7 days'
  AND m.platform_code = 'all'
GROUP BY f.film_slug, f.film_title, f.short_title, f.status;

COMMENT ON TABLE films IS 'Distribution — theatrical / release titles (not cinema brands)';
COMMENT ON TABLE daily_film_metrics IS 'Distribution KPIs: buzz, sentiment, unique voices, views by film/day';
