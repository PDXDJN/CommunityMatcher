"""
SearchPlanner agent — converts UserProfile and archetype weights into a
structured SearchBrief with concrete query intents for txt2sql.

Rule-based (no LLM). Generates natural-language query intents that are
passed to txt2sql_tool to retrieve matching community records.
"""
from __future__ import annotations
import json
import structlog
from community_matcher.agents import tool

log = structlog.get_logger()

# DB tags that can be searched directly (must exist in scrape_record.topic_signals)
_VALID_TAGS = {
    "ai", "python", "data_science", "startup", "cloud", "cybersecurity",
    "blockchain", "maker", "design", "gaming", "social_coding",
    "language_exchange", "music", "art", "fitness", "wellness",
    "networking", "community", "tech",
    "workshop", "talk", "conference", "hackathon", "demo_night",
    "barcamp", "coworking", "social", "seminar", "panel",
    "beginner_friendly", "newcomer_city", "english_friendly",
    "after_work", "free", "paid", "online", "in_person", "grassroots",
    "technical", "casual", "career_oriented",
}

# Map archetypes to query intent templates
_ARCHETYPE_QUERIES: dict[str, str] = {
    "hacker_maker":         "Find maker spaces, hackathons, project nights and technical workshops",
    "ai_data":              "Find AI, machine learning, and data science meetups and talks",
    "startup_professional": "Find startup networking events, founder meetups and entrepreneur gatherings",
    "nerdy_social":         "Find nerdy social events, tech community hangouts and game nights",
    "creative_design":      "Find design, art and creative community events",
    "wellness_fitness":     "Find fitness, wellness and sport community events",
    "grassroots_activist":  "Find grassroots tech community events and activist-tech meetups",
}


@tool
def search_planner_tool(profile_json: str) -> str:
    """
    Converts a UserProfile and archetype weights into a SearchBrief JSON.

    Selects the top archetypes, maps them to query intents, and adds
    interest-based and constraint-based query modifiers.

    Args:
        profile_json: JSON string of the current UserProfile (may include
                      archetype_weights from a prior archetype_tool call).

    Returns:
        JSON string conforming to SearchBrief schema with query_intents list.
    """
    try:
        profile = json.loads(profile_json)
        interests      = profile.get("interests", [])
        goals          = profile.get("goals", [])
        social_mode    = profile.get("social_mode")
        language_pref  = profile.get("language_pref", [])
        budget         = profile.get("budget", "any")
        dealbreakers   = profile.get("dealbreakers", [])
        archetype_wts  = profile.get("archetype_weights", {})

        query_intents: list[str] = []

        # Top archetype queries (up to 2)
        top_archetypes = sorted(archetype_wts.items(), key=lambda x: -x[1])[:2]
        for arch_name, weight in top_archetypes:
            if weight > 0.2 and arch_name in _ARCHETYPE_QUERIES:
                query_intents.append(_ARCHETYPE_QUERIES[arch_name])

        # Interest-based query
        valid_interests = [i for i in interests if i in _VALID_TAGS]
        if valid_interests:
            tags = ", ".join(valid_interests[:4])
            query_intents.append(f"Find communities with topics: {tags} (use OR between topics)")

        # Social mode qualifier
        if social_mode and social_mode in _VALID_TAGS:
            query_intents.append(f"Find {social_mode} style events in Berlin")

        # Budget constraint
        if budget == "free_only":
            query_intents.append("Find free community events")

        # Language preference
        if "english" in language_pref:
            query_intents.append("Find english_friendly events")

        # Fallback
        if not query_intents:
            query_intents.append("Find tech communities and events in Berlin")

        brief = {
            "profile_summary": f"Goals: {goals}; Interests: {interests}; Mode: {social_mode}",
            "archetypes": archetype_wts,
            "query_intents": query_intents[:4],  # max 4 intents
            "constraints": {
                "budget":    budget,
                "language":  language_pref,
                "no_go":     dealbreakers,
            },
        }
        log.info("search_planner.brief", intents=query_intents[:4])
        return json.dumps(brief)
    except Exception as exc:
        log.warning("search_planner.error", error=str(exc))
        return json.dumps({"query_intents": ["Find tech communities and events in Berlin"]})
