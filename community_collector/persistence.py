"""
SQLite persistence for the community collector.

Schema mirrors community_matcher/db/schema.sql (PostgreSQL) so data can be
migrated directly. Adds two collector-specific tables:
  scrape_record — full CommunityEventRecord (all fields)
  scrape_run    — run metadata and summary
"""
from __future__ import annotations
import json
import sqlite3
from pathlib import Path
from datetime import datetime
from community_collector.models import CommunityEventRecord, CollectionResult

# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

_SCHEMA_SQL = """
-- ── CommunityMatcher core schema (mirrors PostgreSQL) ──────────────────────
CREATE TABLE IF NOT EXISTS community (
    idx         INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    url         TEXT,
    description TEXT,
    activity    TEXT,
    cost_factor REAL
);

CREATE TABLE IF NOT EXISTS social (
    idx        INTEGER PRIMARY KEY AUTOINCREMENT,
    c_idx      INTEGER NOT NULL REFERENCES community(idx) ON DELETE CASCADE,
    url        TEXT NOT NULL,
    annotation TEXT
);

CREATE TABLE IF NOT EXISTS keyword (
    idx   INTEGER PRIMARY KEY AUTOINCREMENT,
    short TEXT NOT NULL UNIQUE,
    long  TEXT
);

CREATE TABLE IF NOT EXISTS factoid (
    idx        INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_idx INTEGER REFERENCES factoid(idx) ON DELETE SET NULL,
    short      TEXT NOT NULL,
    long       TEXT,
    url        TEXT
);

CREATE TABLE IF NOT EXISTS kw_affinity (
    c_idx      INTEGER NOT NULL REFERENCES community(idx) ON DELETE CASCADE,
    k_idx      INTEGER NOT NULL REFERENCES keyword(idx) ON DELETE CASCADE,
    aff_value  REAL NOT NULL DEFAULT 0.0,
    annotation TEXT,
    PRIMARY KEY (c_idx, k_idx)
);

CREATE TABLE IF NOT EXISTS fc_affinity (
    c_idx      INTEGER NOT NULL REFERENCES community(idx) ON DELETE CASCADE,
    f_idx      INTEGER NOT NULL REFERENCES factoid(idx) ON DELETE CASCADE,
    aff_value  REAL NOT NULL DEFAULT 0.0,
    annotation TEXT,
    PRIMARY KEY (c_idx, f_idx)
);

-- ── Collector-specific tables ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS scrape_record (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    source               TEXT NOT NULL,
    source_record_id     TEXT,
    source_url           TEXT NOT NULL UNIQUE,
    canonical_url        TEXT,
    title                TEXT NOT NULL,
    description          TEXT,
    organizer_name       TEXT,
    community_name       TEXT,
    event_datetime_start TEXT,
    event_datetime_end   TEXT,
    timezone             TEXT,
    activity             TEXT,
    venue_name           TEXT,
    venue_address        TEXT,
    city                 TEXT,
    country              TEXT,
    is_online            INTEGER,    -- 0/1/NULL
    latitude             REAL,
    longitude            REAL,
    cost_text            TEXT,
    cost_factor          REAL,
    currency             TEXT,
    tags                 TEXT,       -- JSON array
    topic_signals        TEXT,       -- JSON array
    audience_signals     TEXT,       -- JSON array
    format_signals       TEXT,       -- JSON array
    vibe_signals         TEXT,       -- JSON array
    raw_category         TEXT,
    language             TEXT,
    detected_language    TEXT,
    title_en             TEXT,
    description_en       TEXT,
    title_de             TEXT,
    description_de       TEXT,
    extraction_timestamp TEXT,
    search_term          TEXT,
    c_idx                INTEGER REFERENCES community(idx),
    raw_payload          TEXT        -- JSON blob
);

CREATE TABLE IF NOT EXISTS scrape_run (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id           TEXT NOT NULL UNIQUE,
    started_at       TEXT,
    finished_at      TEXT,
    duration_seconds REAL,
    location         TEXT,
    search_terms     TEXT,           -- JSON array
    sources_run      TEXT,           -- JSON array
    records_per_src  TEXT,           -- JSON object
    normalized_total INTEGER,
    errors           TEXT,           -- JSON object
    output_dir       TEXT,
    db_path          TEXT
);

-- ── Indexes ─────────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_social_c_idx       ON social(c_idx);
CREATE INDEX IF NOT EXISTS idx_kw_affinity_k_idx  ON kw_affinity(k_idx);
CREATE INDEX IF NOT EXISTS idx_kw_affinity_c_idx  ON kw_affinity(c_idx);
CREATE INDEX IF NOT EXISTS idx_scrape_source      ON scrape_record(source);
CREATE INDEX IF NOT EXISTS idx_scrape_city        ON scrape_record(city);
"""

# Default affinity value assigned when a tag is linked to a community
_DEFAULT_AFFINITY = 0.6


# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------

def _connect(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: str) -> None:
    """Create all tables if they don't exist, and migrate existing ones."""
    with _connect(db_path) as conn:
        conn.executescript(_SCHEMA_SQL)
        # Idempotent column migrations for translation fields
        _migrate_add_column(conn, "scrape_record", "detected_language", "TEXT")
        _migrate_add_column(conn, "scrape_record", "title_en",          "TEXT")
        _migrate_add_column(conn, "scrape_record", "description_en",    "TEXT")
        _migrate_add_column(conn, "scrape_record", "title_de",          "TEXT")
        _migrate_add_column(conn, "scrape_record", "description_de",    "TEXT")
        _migrate_add_column(conn, "scrape_record", "latitude",          "REAL")
        _migrate_add_column(conn, "scrape_record", "longitude",         "REAL")


def _migrate_add_column(conn: sqlite3.Connection, table: str, column: str, col_type: str) -> None:
    """Add a column to an existing table if it doesn't already exist."""
    cur = conn.execute(f"PRAGMA table_info({table})")
    existing = {row[1] for row in cur.fetchall()}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")


# ---------------------------------------------------------------------------
# Upsert helpers
# ---------------------------------------------------------------------------

def _upsert_community(cur: sqlite3.Cursor, rec: CommunityEventRecord) -> int:
    """
    Insert or update the community row. Returns community idx.
    On conflict (same name + url) updates description and cost_factor.
    """
    cur.execute(
        """
        INSERT INTO community (name, url, description, activity, cost_factor)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT DO NOTHING
        """,
        (
            rec.title,
            rec.canonical_url or rec.source_url,
            rec.description,
            rec.activity,
            rec.cost_factor,
        ),
    )
    # Fetch the idx (may have been inserted or already existed)
    cur.execute(
        "SELECT idx FROM community WHERE name = ? AND url = ?",
        (rec.title, rec.canonical_url or rec.source_url),
    )
    row = cur.fetchone()
    if row:
        return row[0]
    # Fallback: last inserted
    return cur.lastrowid


def _upsert_social(cur: sqlite3.Cursor, c_idx: int, rec: CommunityEventRecord) -> None:
    """Insert social links for the community if not already present."""
    links = []
    if rec.source_url:
        links.append((rec.source_url, rec.source))
    if rec.canonical_url and rec.canonical_url != rec.source_url:
        links.append((rec.canonical_url, "canonical"))
    for url, annotation in links:
        cur.execute(
            """
            INSERT INTO social (c_idx, url, annotation)
            VALUES (?, ?, ?)
            ON CONFLICT DO NOTHING
            """,
            (c_idx, url, annotation),
        )


def _upsert_keyword(cur: sqlite3.Cursor, short: str) -> int:
    """Find or create a keyword row. Returns keyword idx."""
    cur.execute(
        "INSERT INTO keyword (short) VALUES (?) ON CONFLICT(short) DO NOTHING",
        (short,),
    )
    cur.execute("SELECT idx FROM keyword WHERE short = ?", (short,))
    return cur.fetchone()[0]


def _upsert_kw_affinity(
    cur: sqlite3.Cursor, c_idx: int, k_idx: int, aff_value: float, annotation: str
) -> None:
    cur.execute(
        """
        INSERT INTO kw_affinity (c_idx, k_idx, aff_value, annotation)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(c_idx, k_idx) DO UPDATE SET
            aff_value  = MAX(excluded.aff_value, kw_affinity.aff_value),
            annotation = excluded.annotation
        """,
        (c_idx, k_idx, aff_value, annotation),
    )


def _insert_scrape_record(
    cur: sqlite3.Cursor, rec: CommunityEventRecord, c_idx: int
) -> None:
    cur.execute(
        """
        INSERT INTO scrape_record (
            source, source_record_id, source_url, canonical_url,
            title, description, organizer_name, community_name,
            event_datetime_start, event_datetime_end, timezone, activity,
            venue_name, venue_address, city, country, is_online,
            latitude, longitude,
            cost_text, cost_factor, currency,
            tags, topic_signals, audience_signals, format_signals, vibe_signals,
            raw_category, language, detected_language,
            title_en, description_en, title_de, description_de,
            extraction_timestamp, search_term,
            c_idx, raw_payload
        ) VALUES (
            ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?
        )
        ON CONFLICT(source_url) DO UPDATE SET
            description          = excluded.description,
            extraction_timestamp = excluded.extraction_timestamp,
            tags                 = excluded.tags,
            cost_factor          = excluded.cost_factor,
            title_en             = excluded.title_en,
            description_en       = excluded.description_en,
            title_de             = excluded.title_de,
            description_de       = excluded.description_de,
            detected_language    = excluded.detected_language,
            latitude             = COALESCE(excluded.latitude, scrape_record.latitude),
            longitude            = COALESCE(excluded.longitude, scrape_record.longitude)
        """,
        (
            rec.source, rec.source_record_id, rec.source_url, rec.canonical_url,
            rec.title, rec.description, rec.organizer_name, rec.community_name,
            rec.event_datetime_start, rec.event_datetime_end, rec.timezone, rec.activity,
            rec.venue_name, rec.venue_address, rec.city, rec.country,
            None if rec.is_online is None else int(rec.is_online),
            rec.latitude, rec.longitude,
            rec.cost_text, rec.cost_factor, rec.currency,
            json.dumps(rec.tags),
            json.dumps(rec.topic_signals),
            json.dumps(rec.audience_signals),
            json.dumps(rec.format_signals),
            json.dumps(rec.vibe_signals),
            rec.raw_category, rec.language, rec.detected_language,
            rec.title_en, rec.description_en, rec.title_de, rec.description_de,
            rec.extraction_timestamp, rec.search_term,
            c_idx,
            json.dumps(rec.raw_payload, default=str),
        ),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def save_records(records: list[CommunityEventRecord], db_path: str) -> int:
    """
    Persist a list of normalized records to SQLite.
    Returns the number of successfully written records.
    """
    init_db(db_path)
    saved = 0
    with _connect(db_path) as conn:
        cur = conn.cursor()
        for rec in records:
            try:
                c_idx = _upsert_community(cur, rec)
                _upsert_social(cur, c_idx, rec)

                # Keyword affinities: topic signals get higher confidence
                for tag in rec.topic_signals:
                    k_idx = _upsert_keyword(cur, tag)
                    _upsert_kw_affinity(cur, c_idx, k_idx, 0.75, "topic_signal")
                for tag in rec.tags:
                    if tag not in rec.topic_signals:
                        k_idx = _upsert_keyword(cur, tag)
                        _upsert_kw_affinity(cur, c_idx, k_idx, _DEFAULT_AFFINITY, "tag")

                _insert_scrape_record(cur, rec, c_idx)
                saved += 1
            except Exception as exc:
                from community_collector.utils.logging_utils import get_logger
                get_logger("persistence").warning(
                    "persistence.record_failed",
                    title=rec.title, error=str(exc)
                )
        conn.commit()
    return saved


def save_run_summary(result: CollectionResult, db_path: str) -> None:
    """Persist the run summary to scrape_run table."""
    init_db(db_path)
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO scrape_run (
                run_id, started_at, finished_at, duration_seconds,
                location, search_terms, sources_run, records_per_src,
                normalized_total, errors, output_dir, db_path
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(run_id) DO NOTHING
            """,
            (
                result.run_id,
                result.started_at,
                result.finished_at,
                result.duration_seconds,
                result.location,
                json.dumps(result.search_terms),
                json.dumps(result.sources_attempted),
                json.dumps(result.records_per_source),
                result.normalized_total,
                json.dumps(result.errors),
                result.output_dir,
                result.db_path,
            ),
        )
        conn.commit()
