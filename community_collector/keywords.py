"""
Community keyword taxonomy for tagging, filtering, and scoring.

Sources:
  - Event_Finder/app/tagger.py      (general event/community tags)
  - Event_Finder/app/agents/meetup.py (_BERLIN_TOPICS, title-cleaning patterns)
  - Event_Finder/app/scoring.py      (tag scoring weights)
  - Event_Finder/app/preferences.py  (affinity delta model)
  Extended with community-matcher-specific topic, audience, vibe, and format
  vocabulary tuned for tech/maker/startup/social communities.
"""
from __future__ import annotations
import re

# ---------------------------------------------------------------------------
# Default search topics
# Copied from Event_Finder/app/agents/meetup.py :: _BERLIN_TOPICS
# Extended with tech-community-specific terms for CommunityMatcher.
# ---------------------------------------------------------------------------

DEFAULT_BERLIN_TOPICS: list[str] = [
    # Original from Event_Finder
    "music",
    "tech AI",
    "art culture",
    "community social",
    "sport fitness",
    "language exchange",
    "networking",
    "workshop",
    # CommunityMatcher additions
    "machine learning",
    "python",
    "data science",
    "open source",
    "hackerspace",
    "maker",
    "startup founders",
    "cloud devops",
    "cybersecurity",
    "gaming",
    "blockchain web3",
    "design UX",
    "robotics hardware",
    "coworking",
    "demo night",
    "hackathon",
    # Newcomer / social
    "expat Berlin",
    "english speaking Berlin",
    "newcomer Berlin",
    "international community",
    "language café",
    # Diversity & inclusion
    "queer tech",
    "women in tech",
    "LGBTQ Berlin",
    "diversity tech",
    # Tech niches
    "rust programming",
    "golang Berlin",
    "react javascript",
    "TypeScript frontend",
    "LLM agents",
    "computer vision",
    "embedded systems",
    "kubernetes cloud native",
    "DevOps platform engineering",
    "web3 ethereum",
    # Creative / maker niches
    "game development Berlin",
    "indie games",
    "generative art",
    "creative coding",
    "3D printing",
    "electronics Arduino",
    # Professional
    "product management Berlin",
    "UX research",
    "freelancer Berlin",
    "remote work community",
    "founder community",
    # Social / hobby
    "board games Berlin",
    "chess Berlin",
    "photography Berlin",
    "book club",
    "science communication",
    "running club Berlin",
    "climbing bouldering Berlin",
]


# ---------------------------------------------------------------------------
# Title-cleaning patterns
# Copied verbatim from Event_Finder/app/agents/meetup.py
# ---------------------------------------------------------------------------

_DATE_PAT = re.compile(
    r'\s*(?:Monthly|Weekly|Biweekly|Daily)?\s*(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun),.*$',
    re.IGNORECASE,
)
_FREQ_PAT = re.compile(r'\s*(?:Monthly|Weekly|Biweekly|Daily)\s*$', re.IGNORECASE)
_WHITESPACE = re.compile(r'\s+')


def clean_title(raw: str) -> str:
    """
    Clean a raw scraped title.
    Copied from Event_Finder/app/agents/meetup.py :: _clean_title().
    Removes date suffixes, frequency labels, and excess whitespace.
    """
    title = raw.split('\n')[0].strip()
    if '·' in title:
        title = title[:title.index('·')].strip()
    title = _DATE_PAT.sub('', title).strip()
    title = _FREQ_PAT.sub('', title).strip()
    return _WHITESPACE.sub(' ', title).strip()


# ---------------------------------------------------------------------------
# General event/community keyword maps
# Copied from Event_Finder/app/tagger.py, with CommunityMatcher extensions.
# ---------------------------------------------------------------------------

# --- Topic keywords --------------------------------------------------------
# Event_Finder originals kept verbatim; CommunityMatcher additions marked (+)

TOPIC_KEYWORDS: dict[str, list[str]] = {
    # ── From Event_Finder ──────────────────────────────────────────────────
    "music": [
        "dj", "club", "techno", "live music", "concert", "band", "music",
        "musik", "jazz", "classical", "hip hop", "electronic", "singer",
        "choir", "orchestra", "festival",
    ],
    "art": [
        "museum", "gallery", "exhibition", "art", "kunst", "ausstellung",
        "photography", "foto", "painting", "sculpture", "design",
    ],
    "film":         ["film", "cinema", "screening"],
    "food":         ["food", "street food", "tasting", "market"],
    "fitness":      ["fitness", "run club", "yoga"],
    "wellness":     ["wellness", "meditation", "breathwork"],
    "performance":  ["performance", "theatre", "theater", "stage"],
    "market":       ["market", "flohmarkt"],
    "nightlife":    ["party", "afterparty", "club night"],

    # ── CommunityMatcher additions ─────────────────────────────────────────
    "ai": [
        "artificial intelligence", " ai ", "llm", "genai", "machine learning",
        "deep learning", "nlp", "gpt", "neural network", "large language model",
        "diffusion", "rag", "langchain",
    ],
    "data_science": [
        "data science", "data engineering", "analytics", "pandas",
        "jupyter", "tableau", "power bi", "sql", "dbt", "spark",
    ],
    "python": [
        "python", "django", "flask", "fastapi", "pandas", "pydantic",
    ],
    "open_source": [
        "open source", "open-source", "foss", "linux", "github",
        "git", "contributing", "maintainer",
    ],
    "cloud": [
        "cloud", "aws", "azure", "gcp", "kubernetes", "docker",
        "devops", "sre", "platform engineering", "terraform", "helm",
    ],
    "cybersecurity": [
        "security", "cybersecurity", "hacking", "ctf", "infosec",
        "penetration testing", "red team", "blue team", "owasp",
    ],
    "blockchain": [
        "blockchain", "crypto", "web3", "nft", "defi", "ethereum", "bitcoin",
    ],
    "maker": [
        "maker", "makerspace", "arduino", "raspberry pi", "3d print",
        "hardware", "electronics", "robotics", "iot", "embedded",
    ],
    "startup": [
        "startup", "founder", "venture", "pitch", "entrepreneur",
        "saas", "product", "b2b", "scale-up", "vc", "seed",
    ],
    "design": [
        "design", "ux", "ui", "figma", "product design",
        "graphic design", "typography", "user research",
    ],
    "gaming": [
        "gaming", "game dev", "game jam", "indie game", "esports",
        "unity", "unreal", "godot",
    ],
    "social_coding": [
        "coding", "hackathon", "code", "programming",
        "software engineering", "developer", "pair programming",
    ],
    "language_exchange": [
        "language exchange", "tandem", "sprachpartner", "deutsch lernen",
        "english conversation", "polyglot",
    ],
    "community": [
        "community", "neighborhood", "volunteer", "grassroots",
    ],
    "tech": [
        "startup", "founder", "saas", "ai", "machine learning", "tech",
    ],
    "networking": [
        "networking", "mixer", "meet founders",
    ],
}


# --- Format keywords -------------------------------------------------------

FORMAT_KEYWORDS: dict[str, list[str]] = {
    # ── From Event_Finder ──────────────────────────────────────────────────
    "workshop":    ["workshop", "hands-on", "seminar"],
    "talk":        ["talk", "lecture", "panel"],
    "conference":  ["conference", "summit"],

    # ── CommunityMatcher additions ─────────────────────────────────────────
    "meetup_event":  ["meetup", "meet-up"],
    "panel":         ["panel", "roundtable", "discussion"],
    "hackathon":     ["hackathon", "hack day", "build weekend", "build night"],
    "demo_night":    ["demo night", "demo day", "show and tell", "showcase", "show & tell"],
    "networking":    ["networking", "mixer", "happy hour", "drinks", "after work", "afterwork"],
    "coworking":     ["coworking", "co-working", "open studio", "office hours", "work session"],
    "social":        ["social", "gathering", "hangout", "chill", "casual meet"],
    "seminar":       ["seminar", "webinar", "online talk"],
    "barcamp":       ["barcamp", "unconference", "open space", "open space technology"],
}


# --- Audience keywords -----------------------------------------------------

AUDIENCE_KEYWORDS: dict[str, list[str]] = {
    # ── From Event_Finder ──────────────────────────────────────────────────
    "family_friendly": ["kids", "children", "family"],
    "student_friendly": ["student", "uni", "university"],
    "english_friendly": ["english", "international"],
    "german_language":  ["deutsch", "german"],
    "wheelchair_accessible": ["wheelchair", "barrier-free", "accessible"],
    "lgbtq_friendly":  ["queer", "lgbt", "lgbtq"],
    "late_night":      ["late", "23:00", "00:00"],

    # ── CommunityMatcher additions ─────────────────────────────────────────
    "beginner_friendly": [
        "beginner", "newcomer", "intro", "101", "getting started",
        "no experience", "for everyone", "all levels",
    ],
    "advanced":       ["advanced", "expert", "senior", "deep dive"],
    "professional":   ["professional", "career", "industry", "enterprise"],
    "founder_focused":    ["founder", "cto", "ceo", "startup"],
    "developer_focused":  ["developer", "engineer", "programmer", "coder"],
    "research_focused":   ["research", "academic", "paper", "publication", "phd"],
    "after_work":     [
        "after work", "afterwork", "evening", "6pm", "7pm", "18:00", "19:00",
    ],
    "newcomer_city": [
        "new to berlin", "new in berlin", "expat", "newcomer", "just moved",
        "relocation", "international community",
    ],
}


# --- Vibe / environment keywords -------------------------------------------

VIBE_KEYWORDS: dict[str, list[str]] = {
    # ── From Event_Finder ──────────────────────────────────────────────────
    "outdoor":   ["park", "garden", "open air", "outdoor"],
    "indoor":    ["indoor", "hall", "studio"],

    # ── CommunityMatcher additions ─────────────────────────────────────────
    "technical":       ["technical", "in-depth", "engineering", "architecture"],
    "casual":          ["casual", "relaxed", "informal", "chill", "no agenda"],
    "career_oriented": ["career", "job", "hiring", "recruitment", "networking"],
    "community_driven": ["community", "grassroots", "volunteer", "open to all"],
    "social_drinking": [
        "bar", "brewery", "pub", "drinks", "beer", "wine", "cocktail",
    ],
    "structured":  ["agenda", "schedule", "registration required", "tickets", "rsvp"],
    "experimental": [
        "experimental", "unconference", "barcamp", "open space", "self-organised",
    ],
    "grassroots":  ["grassroots", "independent", "self-organised", "diy", "community-run"],
    "queer_inclusive": ["queer", "lgbtq", "lgbt", "pride", "inclusive", "safe space"],
    "newcomer_friendly": [
        "newcomer", "expat", "international", "english-speaking",
        "new to berlin", "new to the city", "open to all",
    ],
    "alcohol_light": ["alcohol-free", "sober", "no drinks", "soft drinks only"],
    "corporate":   ["corporate", "enterprise", "b2b", "sponsored by", "brought to you by"],
}


# --- Location / accessibility keywords ------------------------------------

LOCATION_KEYWORDS: dict[str, list[str]] = {
    # ── From Event_Finder (Berlin districts) ───────────────────────────────
    "mitte":           ["mitte"],
    "kreuzberg":       ["kreuzberg"],
    "neukolln":        ["neukölln", "neukolln"],
    "friedrichshain":  ["friedrichshain"],
    "prenzlauer_berg": ["prenzlauer berg"],
    "charlottenburg":  ["charlottenburg"],

    # ── CommunityMatcher additions ─────────────────────────────────────────
    "online":         ["online", "virtual", "remote", "zoom", "teams", "livestream", "hybrid"],
    "in_person":      ["in person", "in-person", "on-site", "venue"],
    "free":           ["free", "kostenlos", "gratis", "no cost", "€0"],
    "paid":           ["ticket", "registration fee", "€", "eur"],
    "evening_event":  ["evening", "6pm", "7pm", "8pm", "18:00", "19:00", "20:00"],
    "weekend_event":  ["saturday", "sunday", "weekend"],
    "central_berlin": ["mitte", "unter den linden", "alexanderplatz", "hackescher markt"],
}


# ---------------------------------------------------------------------------
# Category map  (tag → normalized category)
# Copied from Event_Finder/app/tagger.py :: _CATEGORY_MAP
# Extended for community-matcher categories.
# ---------------------------------------------------------------------------

CATEGORY_MAP: list[tuple[str, list[str]]] = [
    # ── From Event_Finder ──────────────────────────────────────────────────
    ("music",       ["music", "nightlife", "late_night"]),
    ("arts",        ["art", "film", "performance", "market"]),
    ("sports",      ["fitness", "wellness"]),
    ("food_drink",  ["food", "market"]),
    ("family",      ["family_friendly"]),
    ("culture",     ["art", "performance"]),
    # ── CommunityMatcher additions ─────────────────────────────────────────
    ("tech",        ["ai", "data_science", "python", "cloud", "cybersecurity",
                     "blockchain", "maker", "social_coding", "open_source", "tech"]),
    ("startup",     ["startup", "founder_focused", "career_oriented"]),
    ("community",   [
        "community", "networking", "talk", "workshop", "social",
        "language_exchange", "newcomer_friendly", "newcomer_city",
    ]),
    ("gaming",      ["gaming"]),
    ("design",      ["design"]),
]


def normalize_category(tags: list[str]) -> str | None:
    """
    Map a list of tags to a single normalized category string.
    First match wins. Copied from Event_Finder/app/tagger.py :: _normalize_category().
    """
    tag_set = set(tags)
    for category, triggers in CATEGORY_MAP:
        if tag_set & set(triggers):
            return category
    return None


# ---------------------------------------------------------------------------
# Scoring constants
# Copied from Event_Finder/app/scoring.py :: score_event()
# Used as base boosts when computing tag-based affinity scores.
# ---------------------------------------------------------------------------

TAG_SCORE_BOOSTS: dict[str, float] = {
    "community":       5.0,
    "free":            4.0,
    "english_friendly": 3.0,
    # CommunityMatcher additions
    "newcomer_friendly": 4.0,
    "beginner_friendly": 3.0,
    "newcomer_city":     3.5,
    "in_person":         2.0,
    "tech":              2.0,
    "ai":                2.0,
    "open_source":       1.5,
    "grassroots":        2.0,
    "queer_inclusive":   2.0,
}

QUERY_TITLE_BOOST   = 30.0  # exact query match in title
QUERY_DESC_BOOST    = 15.0  # exact query match in description
DISTANCE_BOOST_MAX  = 25.0  # max boost for distance (closer = higher)
TAG_MATCH_BOOST     = 12.0  # per matched user tag


# ---------------------------------------------------------------------------
# Affinity delta model
# Copied from Event_Finder/app/preferences.py
# Used by the CommunityMatcher ranking and feedback loop.
# ---------------------------------------------------------------------------

TAG_BOOKMARK_DELTA    = +3.0   # user bookmarks/saves → each tag gains this
TAG_UNBOOKMARK_DELTA  = -2.0   # user removes bookmark → each tag loses this
SRC_BOOKMARK_DELTA    = +2.0   # source gains affinity on bookmark
SRC_UNBOOKMARK_DELTA  = -1.0   # source loses affinity on unbookmark
FOR_YOU_WEIGHT        = 1.0    # multiplier blending affinity into score
AFFINITY_CLAMP_MIN    = 0.0    # negative affinity not shown
AFFINITY_CLAMP_MAX    = 20.0   # display cap


# ---------------------------------------------------------------------------
# All flat tag lists (used for autocomplete, validation, DB seed)
# ---------------------------------------------------------------------------

ALL_TOPIC_TAGS: list[str]   = sorted(TOPIC_KEYWORDS.keys())
ALL_FORMAT_TAGS: list[str]  = sorted(FORMAT_KEYWORDS.keys())
ALL_AUDIENCE_TAGS: list[str] = sorted(AUDIENCE_KEYWORDS.keys())
ALL_VIBE_TAGS: list[str]    = sorted(VIBE_KEYWORDS.keys())
ALL_LOCATION_TAGS: list[str] = sorted(LOCATION_KEYWORDS.keys())

ALL_TAGS: list[str] = sorted(set(
    ALL_TOPIC_TAGS + ALL_FORMAT_TAGS + ALL_AUDIENCE_TAGS +
    ALL_VIBE_TAGS + ALL_LOCATION_TAGS
))
