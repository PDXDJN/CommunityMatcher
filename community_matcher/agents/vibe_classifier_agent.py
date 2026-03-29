"""
VibeClassifier agent — scores newcomer-friendliness and social vibe from
candidate description text and tags. Rule-based, no LLM.
"""
from __future__ import annotations
import json
import re
import structlog
from community_matcher.agents import tool

log = structlog.get_logger()

# Keywords that boost newcomer-friendliness
_NEWCOMER_POSITIVE = [
    "newcomer", "beginner", "welcome", "all level", "first time",
    "open to all", "no experience", "friendly", "inclusive", "english",
    "intro", "getting started", "first step",
]
_NEWCOMER_NEGATIVE = [
    "expert only", "senior", "advanced only", "experienced", "members only",
    "clique", "exclusive",
]

# Vibe dimension keywords
_CASUAL_SIGNALS   = ["drinks", "casual", "social", "hangout", "fun", "games", "chill"]
_FORMAL_SIGNALS   = ["corporate", "enterprise", "b2b", "pitch", "vc", "investor"]
_TECHNICAL_SIGNALS = ["coding", "hackathon", "workshop", "hands-on", "project", "build"]
_CREATIVE_SIGNALS  = ["art", "music", "design", "creative", "gallery"]


def _keyword_score(text: str, positives: list[str], negatives: list[str]) -> float:
    t = text.lower()
    pos = sum(1 for kw in positives if kw in t)
    neg = sum(1 for kw in negatives if kw in t)
    raw = pos - neg * 2
    return max(0.0, min(1.0, 0.5 + raw * 0.1))


@tool
def vibe_classifier_tool(description: str) -> str:
    """
    Classifies newcomer-friendliness, social vibe, and atmosphere from a
    candidate community description or title.

    Scores each dimension on a 0.0–1.0 scale using keyword matching.

    Args:
        description: Combined title + description text of the community/event.

    Returns:
        JSON object with vibe dimension scores (0.0–1.0).
    """
    try:
        text = (description or "").lower()

        newcomer_friendliness = _keyword_score(text, _NEWCOMER_POSITIVE, _NEWCOMER_NEGATIVE)

        casual_score    = sum(1 for kw in _CASUAL_SIGNALS if kw in text)
        formal_score    = sum(1 for kw in _FORMAL_SIGNALS if kw in text)
        technical_score = sum(1 for kw in _TECHNICAL_SIGNALS if kw in text)
        creative_score  = sum(1 for kw in _CREATIVE_SIGNALS if kw in text)

        # Vibe alignment: casual/social events score higher by default
        vibe_alignment = min(1.0, 0.5 + casual_score * 0.1 - formal_score * 0.15 + technical_score * 0.05)

        return json.dumps({
            "newcomer_friendliness": round(newcomer_friendliness, 2),
            "vibe_alignment":        round(max(0.0, vibe_alignment), 2),
            "is_casual":             casual_score > formal_score,
            "is_technical":          technical_score > 0,
            "is_creative":           creative_score > 0,
        })
    except Exception as exc:
        log.warning("vibe_classifier.error", error=str(exc))
        return '{"newcomer_friendliness": 0.5, "vibe_alignment": 0.5}'
