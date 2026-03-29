"""
Semantic search fallback for the community database.

When txt2sql misses queries like "I want to tinker with hardware"
(not a known tag), this tool:
  1. Expands the query via a static synonym map (phrase → known DB tags)
  2. Falls back to free-text LIKE search on title + description
  3. Merges and deduplicates both result sets

No external ML libraries required — runs entirely against the existing SQLite DB.
"""
from __future__ import annotations

import json
import re
import structlog
from community_matcher.agents import tool

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Synonym map: natural-language concepts → known DB tag values
# Keys are lowercased substrings; values are tag slugs from the DB vocabulary.
# ---------------------------------------------------------------------------
_SYNONYM_MAP: dict[str, list[str]] = {
    # maker / hardware
    "hardware": ["maker"],
    "tinker": ["maker"],
    "tinkering": ["maker"],
    "solder": ["maker"],
    "soldering": ["maker"],
    "3d print": ["maker"],
    "robotics": ["maker"],
    "robot": ["maker"],
    "electronics": ["maker"],
    "circuit": ["maker"],
    "arduino": ["maker"],
    "raspberry pi": ["maker"],
    "raspberry": ["maker"],
    "diy": ["maker"],
    "hackspace": ["maker"],
    "hackerspace": ["maker"],
    "makerspace": ["maker"],
    "fabricat": ["maker"],
    # AI / data
    "machine learning": ["ai", "data_science"],
    "neural network": ["ai"],
    "deep learning": ["ai"],
    "large language model": ["ai"],
    "llm": ["ai"],
    "gpt": ["ai"],
    "nlp": ["ai"],
    "natural language": ["ai"],
    "computer vision": ["ai"],
    "data science": ["data_science"],
    "data engineering": ["data_science"],
    "analytics": ["data_science"],
    # coding / software
    "code": ["python", "tech"],
    "coding": ["python", "tech"],
    "programming": ["python", "tech"],
    "developer": ["tech"],
    "software": ["tech"],
    "open source": ["tech", "social_coding"],
    "open-source": ["tech", "social_coding"],
    # cloud / devops
    "kubernetes": ["cloud"],
    "docker": ["cloud"],
    "devops": ["cloud"],
    "aws": ["cloud"],
    "azure": ["cloud"],
    "infrastructure": ["cloud"],
    # gaming
    "game": ["gaming"],
    "gaming": ["gaming"],
    "tabletop": ["gaming", "social"],
    "board game": ["gaming", "social"],
    "rpg": ["gaming"],
    "video game": ["gaming"],
    "videogame": ["gaming"],
    "esport": ["gaming"],
    # security
    "security": ["cybersecurity"],
    "hacking": ["cybersecurity"],
    "hacker": ["cybersecurity"],
    "ctf": ["cybersecurity"],
    "infosec": ["cybersecurity"],
    "penetration test": ["cybersecurity"],
    # startup / professional
    "startup": ["startup"],
    "founder": ["startup"],
    "entrepreneur": ["startup"],
    "venture": ["startup"],
    "professional": ["networking", "career_oriented"],
    "career": ["career_oriented"],
    "networking": ["networking"],
    # newcomer / social
    "newcomer": ["newcomer_city"],
    "new to berlin": ["newcomer_city"],
    "expat": ["newcomer_city", "english_friendly"],
    "make friend": ["social"],
    "meet people": ["social"],
    "community": ["community"],
    # design / creative
    "design": ["design"],
    "ux": ["design"],
    "user experience": ["design"],
    "ui ": ["design"],
    "user interface": ["design"],
    "product design": ["design"],
    "creative": ["design"],
    # blockchain / web3
    "blockchain": ["blockchain"],
    "crypto": ["blockchain"],
    "web3": ["blockchain"],
    "nft": ["blockchain"],
    # format signals
    "workshop": ["workshop"],
    "talk": ["talk"],
    "conference": ["conference"],
    "hackathon": ["hackathon"],
    "demo": ["demo_night"],
    "barcamp": ["barcamp"],
    "coworking": ["coworking"],
    # audience signals
    "beginner": ["beginner_friendly"],
    "newcomer friendly": ["newcomer_city", "beginner_friendly"],
    "english": ["english_friendly"],
    "lgbtq": ["lgbtq_friendly"],
    "queer": ["lgbtq_friendly"],
    "free event": ["free"],
    "cost free": ["free"],
    "no cost": ["free"],
    "grassroots": ["grassroots"],
    "casual": ["casual"],
    "technical": ["technical"],
}

# Maximum results from each search path before merge
_MAX_TAG_RESULTS = 30
_MAX_TEXT_RESULTS = 20
_MAX_TOTAL = 40


def _expand_to_tags(query: str) -> list[str]:
    """Map a free-text query to known DB tag slugs via the synonym map."""
    q = query.lower()
    matched: list[str] = []
    seen: set[str] = set()
    for phrase, tags in _SYNONYM_MAP.items():
        if phrase in q:
            for t in tags:
                if t not in seen:
                    matched.append(t)
                    seen.add(t)
    return matched


def _words_from_query(query: str) -> list[str]:
    """Extract meaningful words (≥4 chars) from the query for LIKE search."""
    stop = {
        "with", "that", "this", "from", "have", "want", "find", "show",
        "like", "into", "about", "would", "also", "some", "more", "very",
        "there", "their", "when", "what", "which", "where", "will", "just",
        "than", "then", "them", "they", "were", "been", "being",
    }
    words = re.findall(r"\b[a-zA-Z]{4,}\b", query.lower())
    return [w for w in words if w not in stop][:8]  # cap at 8 search terms


def _build_tag_sql(tags: list[str]) -> str | None:
    if not tags:
        return None
    clauses = []
    for tag in tags[:6]:  # cap at 6 tags in SQL
        safe = tag.replace("'", "''")
        clauses.append(f'sr.topic_signals LIKE \'%"{safe}"%\'')
        clauses.append(f'sr.tags LIKE \'%"{safe}"%\'')
    where = " OR ".join(clauses)
    return (
        f"SELECT sr.id, sr.title, sr.source_url, sr.description, "
        f"sr.topic_signals, sr.tags, sr.vibe_signals, sr.audience_signals, "
        f"sr.format_signals, sr.organizer_name, sr.city, sr.cost_factor, sr.is_online "
        f"FROM scrape_record sr "
        f"WHERE {where} "
        f"LIMIT {_MAX_TAG_RESULTS}"
    )


def _build_text_sql(words: list[str]) -> str | None:
    if not words:
        return None
    clauses = []
    for w in words[:6]:
        safe = w.replace("'", "''")
        clauses.append(f"sr.title LIKE '%{safe}%'")
        clauses.append(f"sr.description LIKE '%{safe}%'")
    where = " OR ".join(clauses)
    return (
        f"SELECT sr.id, sr.title, sr.source_url, sr.description, "
        f"sr.topic_signals, sr.tags, sr.vibe_signals, sr.audience_signals, "
        f"sr.format_signals, sr.organizer_name, sr.city, sr.cost_factor, sr.is_online "
        f"FROM scrape_record sr "
        f"WHERE {where} "
        f"LIMIT {_MAX_TEXT_RESULTS}"
    )


@tool
def semantic_search_tool(query: str) -> str:
    """
    Semantic keyword search over community/event title and description text.

    Complements txt2sql when the query uses natural language that doesn't map
    directly to known database tags. For example:
      - "I want to tinker with hardware"  → finds maker/electronics events
      - "meet people who love board games" → finds gaming/social communities
      - "newcomer looking for English-speaking tech scene" → newcomer + English results

    Strategy:
      1. Expand query phrases to known DB tags via synonym map.
      2. Run LIKE search on title + description for remaining terms.
      3. Merge and deduplicate by source_url.

    Args:
        query: Natural language description of what the user is looking for.

    Returns:
        JSON array of matching scrape_record rows, or JSON error object.
    """
    from community_matcher.db.connection import execute_query, rows_to_json

    try:
        tags = _expand_to_tags(query)
        words = _words_from_query(query)

        tag_rows: list[dict] = []
        text_rows: list[dict] = []

        if tags:
            tag_sql = _build_tag_sql(tags)
            if tag_sql:
                tag_rows = execute_query(tag_sql)
                log.info(
                    "semantic_search.tag_expansion",
                    query=query[:80],
                    expanded_tags=tags,
                    row_count=len(tag_rows),
                )

        if words:
            text_sql = _build_text_sql(words)
            if text_sql:
                text_rows = execute_query(text_sql)
                log.info(
                    "semantic_search.text_search",
                    query=query[:80],
                    words=words,
                    row_count=len(text_rows),
                )

        # Merge: tag rows first (higher relevance), then text rows for new URLs
        seen_urls: set[str] = set()
        merged: list[dict] = []
        for row in tag_rows + text_rows:
            url = row.get("source_url", "")
            if url not in seen_urls:
                seen_urls.add(url)
                merged.append(row)
            if len(merged) >= _MAX_TOTAL:
                break

        log.info(
            "semantic_search.done",
            query=query[:80],
            tags_found=len(tags),
            total_results=len(merged),
        )
        return rows_to_json(merged)

    except Exception as exc:
        log.warning("semantic_search.error", query=query[:80], error=str(exc))
        return json.dumps({"error": "semantic_search_failed", "detail": str(exc)})
