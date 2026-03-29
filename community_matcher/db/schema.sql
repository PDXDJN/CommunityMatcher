-- CommunityMatcher database schema
-- PostgreSQL DDL

CREATE TABLE IF NOT EXISTS community (
    idx         SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    url         TEXT,
    description TEXT,
    activity    TEXT,           -- e.g. "monthly", "weekly", "one-off"
    cost_factor NUMERIC(6, 2)  -- 0 = free, higher = paid; NULL = unknown
);

CREATE TABLE IF NOT EXISTS social (
    idx        SERIAL PRIMARY KEY,
    c_idx      INTEGER NOT NULL REFERENCES community(idx) ON DELETE CASCADE,
    url        TEXT NOT NULL,
    annotation TEXT            -- e.g. "Meetup", "Telegram", "Discord"
);

CREATE TABLE IF NOT EXISTS keyword (
    idx   SERIAL PRIMARY KEY,
    short TEXT NOT NULL,       -- short label, e.g. "AI"
    long  TEXT                 -- full description, e.g. "Artificial Intelligence and Machine Learning"
);

CREATE TABLE IF NOT EXISTS factoid (
    idx        SERIAL PRIMARY KEY,
    parent_idx INTEGER REFERENCES factoid(idx) ON DELETE SET NULL,  -- self-referential hierarchy
    short      TEXT NOT NULL,
    long       TEXT,
    url        TEXT
);

CREATE TABLE IF NOT EXISTS kw_affinity (
    c_idx      INTEGER NOT NULL REFERENCES community(idx) ON DELETE CASCADE,
    k_idx      INTEGER NOT NULL REFERENCES keyword(idx) ON DELETE CASCADE,
    aff_value  NUMERIC(4, 3) NOT NULL DEFAULT 0.0,  -- 0.000 to 1.000
    annotation TEXT,
    PRIMARY KEY (c_idx, k_idx)
);

CREATE TABLE IF NOT EXISTS fc_affinity (
    c_idx      INTEGER NOT NULL REFERENCES community(idx) ON DELETE CASCADE,
    f_idx      INTEGER NOT NULL REFERENCES factoid(idx) ON DELETE CASCADE,
    aff_value  NUMERIC(4, 3) NOT NULL DEFAULT 0.0,  -- 0.000 to 1.000
    annotation TEXT,
    PRIMARY KEY (c_idx, f_idx)
);

-- Indexes for common join and filter patterns
CREATE INDEX IF NOT EXISTS idx_social_c_idx        ON social(c_idx);
CREATE INDEX IF NOT EXISTS idx_kw_affinity_k_idx   ON kw_affinity(k_idx);
CREATE INDEX IF NOT EXISTS idx_kw_affinity_c_idx   ON kw_affinity(c_idx);
CREATE INDEX IF NOT EXISTS idx_fc_affinity_f_idx   ON fc_affinity(f_idx);
CREATE INDEX IF NOT EXISTS idx_fc_affinity_c_idx   ON fc_affinity(c_idx);
CREATE INDEX IF NOT EXISTS idx_factoid_parent_idx  ON factoid(parent_idx);
