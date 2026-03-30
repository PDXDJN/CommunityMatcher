"""
Human-readable schema documentation embedded as a string constant.
Used by the txt2sql agent as part of its system prompt.
"""

SCHEMA_DOC = """
SQLite database schema for CommunityMatcher (also mirrors PostgreSQL in production).

TABLE community
  idx         INTEGER PRIMARY KEY AUTOINCREMENT
  name        TEXT NOT NULL      -- community or event name
  url         TEXT               -- primary website
  description TEXT               -- scraped description
  activity    TEXT               -- recurrence pattern: "monthly", "weekly", "one-off"
  cost_factor REAL               -- approximate cost; 0 = free, NULL = unknown

TABLE scrape_record              -- rich per-record data from the collector (most useful for search)
  id                    INTEGER PRIMARY KEY
  source                TEXT     -- "meetup", "eventbrite", "luma"
  source_url            TEXT     -- original source URL
  canonical_url         TEXT     -- deduplicated URL
  title                 TEXT     -- event/community title
  description           TEXT     -- scraped description text
  organizer_name        TEXT
  community_name        TEXT
  event_datetime_start  TEXT     -- ISO datetime string
  activity              TEXT     -- recurrence pattern
  venue_name            TEXT
  city                  TEXT
  country               TEXT
  is_online             INTEGER  -- 0 = in-person, 1 = online
  cost_text             TEXT
  cost_factor           REAL
  title_en              TEXT     -- English title (original or translated)
  description_en        TEXT     -- English description
  title_de              TEXT     -- German title (original or translated)
  description_de        TEXT     -- German description
  detected_language     TEXT     -- "en" or "de" (auto-detected source language)
  tags                  TEXT     -- JSON array of all tags, e.g. '["ai","tech","workshop"]'
  topic_signals         TEXT     -- JSON array, e.g. '["ai","python","startup"]'
  audience_signals      TEXT     -- JSON array, e.g. '["beginner_friendly","english_friendly"]'
  format_signals        TEXT     -- JSON array, e.g. '["workshop","talk"]'
  vibe_signals          TEXT     -- JSON array, e.g. '["technical","grassroots"]'
  search_term           TEXT     -- which search term found this record
  c_idx                 INTEGER  -- FK → community.idx

TABLE social
  idx        INTEGER PRIMARY KEY
  c_idx      INTEGER FK → community.idx
  url        TEXT              -- social media / chat link
  annotation TEXT              -- platform label: "Meetup", "Telegram", "Discord"

TABLE keyword
  idx   INTEGER PRIMARY KEY
  short TEXT   -- tag slug, e.g. "ai", "python", "gaming"
  long  TEXT   -- longer description

TABLE kw_affinity                -- community ↔ keyword relevance scores
  c_idx      INTEGER FK → community.idx  \\ composite PK
  k_idx      INTEGER FK → keyword.idx   /
  aff_value  REAL   -- 0.0 to 1.0 (higher = more relevant)
  annotation TEXT

TABLE factoid
  idx        INTEGER PRIMARY KEY
  parent_idx INTEGER FK → factoid.idx (self-referential)
  short      TEXT
  long       TEXT
  url        TEXT

TABLE fc_affinity                -- community ↔ factoid relevance
  c_idx      INTEGER FK → community.idx
  f_idx      INTEGER FK → factoid.idx
  aff_value  REAL

COMMON QUERY PATTERNS:

-- Find events/communities by topic tag (most reliable):
SELECT sr.title, sr.source_url, sr.tags, sr.topic_signals
FROM scrape_record sr
WHERE sr.topic_signals LIKE '%"ai"%'
   OR sr.tags LIKE '%"ai"%'
LIMIT 20;

-- Find by keyword affinity (ranked):
SELECT c.name, c.url, ka.aff_value, k.short as keyword
FROM community c
JOIN kw_affinity ka ON c.idx = ka.c_idx
JOIN keyword k ON ka.k_idx = k.idx
WHERE k.short IN ('ai', 'python', 'startup')
ORDER BY ka.aff_value DESC
LIMIT 20;

-- Free events:
SELECT title, source_url, cost_factor FROM scrape_record
WHERE cost_factor = 0 OR cost_text LIKE '%free%' OR cost_text LIKE '%kostenlos%'
LIMIT 20;

-- Workshops and talks:
SELECT title, source_url, format_signals FROM scrape_record
WHERE format_signals LIKE '%"workshop"%' OR format_signals LIKE '%"talk"%'
LIMIT 20;

-- Beginner-friendly or newcomer-friendly:
SELECT title, source_url, audience_signals FROM scrape_record
WHERE audience_signals LIKE '%"beginner_friendly"%'
   OR audience_signals LIKE '%"newcomer_city"%'
LIMIT 20;

-- Combine topic + format + audience:
SELECT title, source_url, tags FROM scrape_record
WHERE topic_signals LIKE '%"startup"%'
  AND format_signals LIKE '%"networking"%'
LIMIT 20;

NOTE: tags, topic_signals, audience_signals, format_signals, vibe_signals are stored
as JSON arrays (TEXT). Use LIKE '%"tagname"%' to search within them.
Known topic tag values include:
  Tech: ai, python, data_science, startup, cloud, cybersecurity, blockchain, maker,
        design, gaming, social_coding, language_exchange, open_source, tech, networking
  Arts & lifestyle: arts_crafts, photography, board_games, sports, dance, music_social,
                    outdoor_nature
  Formats: workshop, talk, conference, hackathon, demo_night, barcamp, coworking, social,
           game_night, sports_session, craft_session, photo_walk, open_mic
  Audience: beginner_friendly, newcomer_city, english_friendly, lgbtq_friendly, after_work,
            family_friendly, professional, developer_focused, founder_focused
  Vibe: grassroots, technical, casual, career_oriented, queer_inclusive, newcomer_friendly,
        alcohol_light, social_drinking, corporate
  Logistics: free, paid, online, in_person

Example queries for non-tech interests:
-- Photography communities:
SELECT title, source_url FROM scrape_record
WHERE topic_signals LIKE '%"photography"%'
   OR tags LIKE '%"photography"%'
   OR title LIKE '%photo%' OR title LIKE '%fotograf%'
LIMIT 20;

-- Board games / tabletop:
SELECT title, source_url FROM scrape_record
WHERE topic_signals LIKE '%"board_games"%'
   OR tags LIKE '%"board_games"%'
   OR title LIKE '%board game%' OR title LIKE '%tabletop%' OR title LIKE '%spieleabend%'
LIMIT 20;

-- Sports and active groups:
SELECT title, source_url FROM scrape_record
WHERE topic_signals LIKE '%"sports"%'
   OR tags LIKE '%"sports"%'
   OR format_signals LIKE '%"sports_session"%'
LIMIT 20;

-- Arts and crafts workshops:
SELECT title, source_url FROM scrape_record
WHERE topic_signals LIKE '%"arts_crafts"%'
   OR format_signals LIKE '%"craft_session"%'
   OR title LIKE '%craft%' OR title LIKE '%painting%' OR title LIKE '%pottery%'
LIMIT 20;
"""
