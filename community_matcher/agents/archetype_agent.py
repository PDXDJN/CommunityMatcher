"""
Archetype agent — maps UserProfile signals to community archetype weights.

Rule-based (no LLM). Archetypes represent the type of community the user
is most likely to enjoy.
"""
from __future__ import annotations
import json
import structlog
from community_matcher.agents import tool

log = structlog.get_logger()

# Each archetype has interests, goals, and social_modes that boost its weight.
# Weights sum contributions then normalise to [0, 1].
_ARCHETYPES: dict[str, dict] = {
    "hacker_maker": {
        "interests":    {"maker": 1.0, "gaming": 0.6, "python": 0.5, "cybersecurity": 0.4, "tech": 0.3},
        "goals":        {},
        "social_modes": {"project": 0.8, "workshop": 0.6},
    },
    "ai_data": {
        "interests":    {"ai": 1.0, "data_science": 1.0, "python": 0.6, "cloud": 0.4, "tech": 0.3},
        "goals":        {"learning": 0.5},
        "social_modes": {"talk": 0.6, "workshop": 0.5},
    },
    "startup_professional": {
        "interests":    {"startup": 1.0, "tech": 0.3, "cloud": 0.3},
        "goals":        {"networking": 1.0},
        "social_modes": {"talk": 0.5, "conference": 0.8},
    },
    "nerdy_social": {
        "interests":    {"gaming": 0.8, "tech": 0.6, "social_coding": 0.8, "maker": 0.4},
        "goals":        {"friends": 0.8},
        "social_modes": {"social": 0.8, "project": 0.5},
    },
    "creative_design": {
        "interests":    {"design": 1.0, "art": 0.8, "music": 0.6},
        "goals":        {"friends": 0.4, "community": 0.6},
        "social_modes": {"social": 0.5, "workshop": 0.6},
    },
    "wellness_fitness": {
        "interests":    {"fitness": 1.0, "wellness": 1.0},
        "goals":        {"friends": 0.5},
        "social_modes": {"social": 0.4},
    },
    "grassroots_activist": {
        "interests":    {"blockchain": 0.6, "cybersecurity": 0.5},
        "goals":        {"community": 1.0},
        "social_modes": {"talk": 0.5, "workshop": 0.5},
    },
    "arts_crafts": {
        "interests":    {
            "arts_crafts": 1.0, "photography": 0.9, "design": 0.6,
            "music_social": 0.5, "dance": 0.5,
        },
        "goals":        {"friends": 0.6, "community": 0.5, "learning": 0.4},
        "social_modes": {"workshop": 0.8, "social": 0.6},
    },
    "board_games_social": {
        "interests":    {"board_games": 1.0, "gaming": 0.7},
        "goals":        {"friends": 1.0},
        "social_modes": {"social": 1.0},
    },
    "sports_active": {
        "interests":    {"sports": 1.0, "outdoor_nature": 0.7, "dance": 0.4},
        "goals":        {"friends": 0.6, "community": 0.4},
        "social_modes": {"social": 0.6},
    },
    "music_performance": {
        "interests":    {"music_social": 1.0, "dance": 0.7, "arts_crafts": 0.3},
        "goals":        {"friends": 0.5, "community": 0.5},
        "social_modes": {"social": 0.7, "workshop": 0.4},
    },
}


def _score_archetype(archetype: dict, interests: list[str], goals: list[str], social_mode: str | None) -> float:
    total = 0.0
    for interest in interests:
        total += archetype["interests"].get(interest, 0.0)
    for goal in goals:
        total += archetype["goals"].get(goal, 0.0)
    if social_mode:
        total += archetype["social_modes"].get(social_mode, 0.0)
    return total


@tool
def archetype_tool(profile_json: str) -> str:
    """
    Maps profile signals to community archetype weights.

    Scores each archetype based on the user's stated interests, goals, and
    preferred social mode. Weights are normalised so the highest-scoring
    archetype receives 1.0.

    Args:
        profile_json: JSON string of the current UserProfile.

    Returns:
        JSON object mapping archetype names to normalised weights (0.0–1.0).
    """
    try:
        profile = json.loads(profile_json)
        interests   = profile.get("interests", [])
        goals       = profile.get("goals", [])
        social_mode = profile.get("social_mode")

        scores: dict[str, float] = {}
        for name, rules in _ARCHETYPES.items():
            scores[name] = _score_archetype(rules, interests, goals, social_mode)

        max_score = max(scores.values()) if scores else 1.0
        if max_score > 0:
            scores = {k: round(v / max_score, 3) for k, v in scores.items()}

        log.info("archetype.scored", top=sorted(scores.items(), key=lambda x: -x[1])[:3])
        return json.dumps(scores)
    except Exception as exc:
        log.warning("archetype.error", error=str(exc))
        return '{"hacker_maker": 0.5}'
