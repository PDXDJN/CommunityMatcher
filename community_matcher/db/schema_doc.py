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

════════════════════════════════════════════════════════
KNOWN TAG VALUES  (use exactly these strings in queries)
════════════════════════════════════════════════════════

── TOPIC TAGS (stored in topic_signals and tags) ──────────────────────────────

  Tech & software:
    ai              Artificial Intelligence, ML, LLMs, GenAI, deep learning, NLP
    data_science    Data science, analytics, data engineering, pandas, SQL, dbt
    python          Python programming: Django, Flask, FastAPI, pandas
    open_source     Open source / FOSS, Linux, GitHub, contributing
    cloud           Cloud computing, DevOps, Kubernetes, Docker, AWS, Azure, GCP
    cybersecurity   Security, infosec, CTF, penetration testing, red team
    blockchain      Blockchain, crypto, Web3, DeFi, NFT, Ethereum
    maker           Maker/hardware: Arduino, Raspberry Pi, 3D printing, robotics, IoT
    design          UX/UI, product design, graphic design, Figma, typography
    gaming          Gaming, game development (Unity/Unreal/Godot), game jams, esports
    social_coding   Coding meetups, hackathons, pair programming, open-source sprints
    language_exchange  Language exchange, tandem, Sprachpartner, polyglot cafés
    startup         Startups, founders, entrepreneurship, venture, pitch nights
    tech            General tech community (umbrella tag)
    networking      Professional networking, mixers, career events
    community       Community building, volunteering, grassroots organising
    music           Music events, concerts, DJs, live performances (general)
    art             Art galleries, exhibitions, visual arts (general)
    fitness         Fitness, run clubs, yoga, sport (general)
    wellness        Wellness, meditation, mindfulness, breathwork
    film            Film screenings, cinema, short films
    performance     Theatre, stage performance, live shows

  Arts & lifestyle:
    arts_crafts     Painting, drawing, watercolour, pottery/ceramics, knitting, sewing,
                    embroidery, crochet, printmaking (linocut/screen print), textile art,
                    illustration, urban sketching, life drawing, collage, mosaic, sculpture
    photography     Photography walks, photo clubs, film/analog/street photography,
                    darkroom, Lightroom editing, photo tours, Fotowalks
    board_games     Board game nights, tabletop RPGs, Dungeons & Dragons, Warhammer,
                    card games, chess, Go, strategy games, Spieleabend, Pen & Paper
    sports          Cycling, hiking, running, marathon, volleyball, football/soccer,
                    basketball, badminton, tennis, swimming, rowing, kayak, martial arts,
                    karate, judo, boxing, CrossFit, climbing, bouldering, sportverein
    dance           Salsa, tango, bachata, swing, lindy hop, ballet, contemporary dance,
                    hip-hop dance, ballroom, social dance, Tanzclub
    music_social    Choir, singing groups, open mic, jam sessions, ukulele circles,
                    guitar groups, orchestra, ensemble, acapella, karaoke, Chor, Singen
    outdoor_nature  Urban gardening, birdwatching, nature walks, foraging, permaculture,
                    allotment/Kleingarten, park clean-ups, Naturschutz

── FORMAT TAGS (stored in format_signals) ─────────────────────────────────────

    workshop        Hands-on workshops, training sessions, skill labs
    talk            Talks, lectures, presentations, keynotes
    panel           Panel discussions, roundtables, Q&A sessions
    conference      Conferences, summits, symposia
    hackathon       Hackathons, hack days, build weekends
    demo_night      Demo nights, showcase events, show-and-tell
    barcamp         Barcamps, unconferences, open space events
    coworking       Coworking sessions, open studio, office hours
    social          Casual social gatherings, hangouts, mixers
    seminar         Seminars, webinars, online talks
    meetup_event    General meetup / meet-up format
    game_night      Board game nights, spieleabend, tabletop game sessions
    sports_session  Training sessions, practice matches, run/ride/hike events
    craft_session   Craft nights, make sessions, creative group sessions
    photo_walk      Photography walks, Fotowalks, photo tours
    open_mic        Open mic nights, open stage, jam sessions, open call

── AUDIENCE TAGS (stored in audience_signals) ─────────────────────────────────

    beginner_friendly   Welcoming to beginners; no prior experience required
    newcomer_city       Specifically for people new to Berlin / the city
    newcomer_friendly   Welcoming to newcomers to the community
    english_friendly    Conducted in or friendly to English speakers
    german_language     Conducted in German
    lgbtq_friendly      LGBTQ+ inclusive space
    after_work          Evening / after-work timing
    family_friendly     Suitable for families with children
    student_friendly    Open to / targeted at students
    advanced            Advanced / expert level content
    professional        Professional / industry audience
    founder_focused     Targeted at founders, CTOs, startup leaders
    developer_focused   Targeted at developers and engineers
    research_focused    Academic / research-oriented audience

── VIBE TAGS (stored in vibe_signals) ─────────────────────────────────────────

    grassroots          Independently organised, community-driven, non-corporate
    technical           Deep technical content, in-depth engineering talks
    casual              Relaxed, informal, no agenda, chill atmosphere
    career_oriented     Career / job / hiring focus
    queer_inclusive     Explicitly LGBTQ+-safe and inclusive
    newcomer_friendly   Warm and welcoming to newcomers (also in audience_signals)
    alcohol_light       Alcohol-free or minimal-alcohol environment
    social_drinking     Bar / pub / drinks-centred social
    corporate           Corporate-sponsored or enterprise-flavoured event
    outdoor             Held outdoors (park, open air)
    indoor              Indoor venue (studio, hall, café)
    community_driven    Volunteer-run, open-to-all, grassroots
    structured          Has agenda, registration, scheduled sessions
    experimental        Unconference / barcamp / self-organised / open space format

── LOGISTICS TAGS ─────────────────────────────────────────────────────────────

    free        Free / no admission cost (kostenlos)
    paid        Paid ticket or registration required
    online      Virtual / remote / Zoom event
    in_person   In-person, at a physical venue

════════════════════════════════════════════════════════
EXAMPLE QUERIES BY TOPIC
════════════════════════════════════════════════════════

-- Photography communities:
SELECT title, source_url FROM scrape_record
WHERE topic_signals LIKE '%"photography"%'
   OR tags LIKE '%"photography"%'
   OR format_signals LIKE '%"photo_walk"%'
   OR title LIKE '%photo%' OR title LIKE '%fotograf%' OR title LIKE '%fotowalk%'
LIMIT 20;

-- Arts & crafts workshops:
SELECT title, source_url FROM scrape_record
WHERE topic_signals LIKE '%"arts_crafts"%'
   OR format_signals LIKE '%"craft_session"%'
   OR title LIKE '%craft%' OR title LIKE '%painting%' OR title LIKE '%pottery%'
   OR title LIKE '%knitting%' OR title LIKE '%drawing%' OR title LIKE '%watercolor%'
LIMIT 20;

-- Board games / tabletop:
SELECT title, source_url FROM scrape_record
WHERE topic_signals LIKE '%"board_games"%'
   OR format_signals LIKE '%"game_night"%'
   OR tags LIKE '%"board_games"%'
   OR title LIKE '%board game%' OR title LIKE '%tabletop%'
   OR title LIKE '%spieleabend%' OR title LIKE '%dungeons%'
LIMIT 20;

-- Dance communities:
SELECT title, source_url FROM scrape_record
WHERE topic_signals LIKE '%"dance"%'
   OR tags LIKE '%"dance"%'
   OR title LIKE '%salsa%' OR title LIKE '%tango%' OR title LIKE '%bachata%'
   OR title LIKE '%swing%' OR title LIKE '%lindy%' OR title LIKE '%ballet%'
LIMIT 20;

-- Sports and active groups:
SELECT title, source_url FROM scrape_record
WHERE topic_signals LIKE '%"sports"%'
   OR format_signals LIKE '%"sports_session"%'
   OR title LIKE '%cycling%' OR title LIKE '%hiking%' OR title LIKE '%running%'
   OR title LIKE '%volleyball%' OR title LIKE '%climbing%' OR title LIKE '%bouldering%'
LIMIT 20;

-- Music social groups (choir, open mic, jam):
SELECT title, source_url FROM scrape_record
WHERE topic_signals LIKE '%"music_social"%'
   OR format_signals LIKE '%"open_mic"%'
   OR title LIKE '%choir%' OR title LIKE '%open mic%' OR title LIKE '%jam session%'
   OR title LIKE '%chor%' OR title LIKE '%singen%' OR title LIKE '%karaoke%'
LIMIT 20;

-- Outdoor & nature groups:
SELECT title, source_url FROM scrape_record
WHERE topic_signals LIKE '%"outdoor_nature"%'
   OR title LIKE '%garden%' OR title LIKE '%birdwatch%' OR title LIKE '%nature walk%'
   OR title LIKE '%foraging%' OR title LIKE '%permaculture%'
LIMIT 20;

-- AI and machine learning meetups:
SELECT title, source_url FROM scrape_record
WHERE topic_signals LIKE '%"ai"%'
   OR tags LIKE '%"ai"%'
   OR title LIKE '%machine learning%' OR title LIKE '%llm%' OR title LIKE '%genai%'
LIMIT 20;

-- Startup / founder networking:
SELECT title, source_url FROM scrape_record
WHERE topic_signals LIKE '%"startup"%'
   OR tags LIKE '%"startup"%'
   OR format_signals LIKE '%"networking"%'
   OR title LIKE '%founder%' OR title LIKE '%startup%' OR title LIKE '%entrepreneur%'
LIMIT 20;

-- Newcomer-friendly English events:
SELECT title, source_url FROM scrape_record
WHERE audience_signals LIKE '%"newcomer_city"%'
   OR audience_signals LIKE '%"english_friendly"%'
   OR audience_signals LIKE '%"beginner_friendly"%'
LIMIT 20;
"""
