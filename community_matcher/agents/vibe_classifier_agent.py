"""
VibeClassifier agent — scores newcomer-friendliness, social vibe, and atmosphere
from candidate description text.

Primary path: LLM-powered scoring (understands nuance, context, implicit signals).
Fallback: keyword-based scoring when LLM is unavailable.

New dimensions vs. the original rule-based version:
  alcohol_centrality — how central alcohol is to the event (0=none, 1=drinks-focused)
  corporate_ness     — how corporate/formal the vibe is (0=grassroots, 1=enterprise)

These feed directly into dealbreaker filtering ("too corporate", "alcohol").
"""
from __future__ import annotations
import json
import structlog
from community_matcher.agents import tool

log = structlog.get_logger()

_SYSTEM_PROMPT = """\
You are a community vibe classifier for CommunityMatcher Berlin.

Given a description of a community event or group, score the following dimensions.
Return ONLY a JSON object with these exact keys and float values 0.0–1.0:

  newcomer_friendliness : 1.0 = very welcoming to newcomers, 0.0 = exclusive/cliquey
  vibe_alignment        : 1.0 = positive social/nerdy vibe, 0.0 = boring/corporate/off-putting
  is_casual             : true if relaxed/social, false if formal/structured
  is_technical          : true if coding/engineering/maker focus
  is_creative           : true if art/music/design focus
  alcohol_centrality    : 1.0 = drinks/pub-crawl centred, 0.0 = no alcohol mentioned
  corporate_ness        : 1.0 = enterprise/investor/B2B, 0.0 = grassroots/community-run

Rules:
- Score based on what the text actually says. Absence of alcohol ≠ high alcohol_centrality.
- Newcomer-friendly signals: "open to all", "beginners welcome", "first time", "join us", "newcomer".
- Corporate signals: "enterprise", "investors", "B2B", "pitch deck", "VC", "networking for professionals".
- Grassroots signals: "community", "volunteers", "open source", "hack", "hackerspace", "barcamp".
- Output ONLY the JSON object. No explanation. No markdown fences.

Example:
{"newcomer_friendliness": 0.8, "vibe_alignment": 0.75, "is_casual": true,
 "is_technical": true, "is_creative": false, "alcohol_centrality": 0.1, "corporate_ness": 0.1}
"""

# ── Keyword fallback (used when LLM is unavailable) ───────────────────────────

_NEWCOMER_POSITIVE = [
    "newcomer", "beginner", "welcome", "all level", "first time",
    "open to all", "no experience", "friendly", "inclusive", "english",
    "intro", "getting started", "first step", "join us",
]
_NEWCOMER_NEGATIVE = [
    "expert only", "senior", "advanced only", "experienced", "members only",
    "clique", "exclusive",
]
_CASUAL_SIGNALS    = ["drinks", "casual", "social", "hangout", "fun", "games", "chill"]
_FORMAL_SIGNALS    = ["corporate", "enterprise", "b2b", "pitch", "vc", "investor"]
_TECHNICAL_SIGNALS = ["coding", "hackathon", "workshop", "hands-on", "project", "build"]
_CREATIVE_SIGNALS  = ["art", "music", "design", "creative", "gallery"]
_ALCOHOL_SIGNALS   = ["drinks", "beer", "wine", "bar", "pub", "cocktail", "brewery"]
_GRASSROOTS_SIGNALS = ["community", "volunteer", "open source", "hackerspace", "barcamp", "grassroots"]


def _keyword_fallback(text: str) -> dict:
    t = text.lower()

    def _score(positives, negatives=None):
        pos = sum(1 for kw in positives if kw in t)
        neg = sum(1 for kw in (negatives or []) if kw in t)
        return max(0.0, min(1.0, 0.5 + pos * 0.1 - neg * 0.2))

    casual_count    = sum(1 for kw in _CASUAL_SIGNALS if kw in t)
    formal_count    = sum(1 for kw in _FORMAL_SIGNALS if kw in t)
    technical_count = sum(1 for kw in _TECHNICAL_SIGNALS if kw in t)
    creative_count  = sum(1 for kw in _CREATIVE_SIGNALS if kw in t)
    alcohol_count   = sum(1 for kw in _ALCOHOL_SIGNALS if kw in t)
    grassroots_count = sum(1 for kw in _GRASSROOTS_SIGNALS if kw in t)

    return {
        "newcomer_friendliness": round(_score(_NEWCOMER_POSITIVE, _NEWCOMER_NEGATIVE), 2),
        "vibe_alignment":        round(max(0.0, min(1.0, 0.5 + casual_count * 0.1 - formal_count * 0.15 + technical_count * 0.05)), 2),
        "is_casual":             casual_count > formal_count,
        "is_technical":          technical_count > 0,
        "is_creative":           creative_count > 0,
        "alcohol_centrality":    round(min(1.0, alcohol_count * 0.25), 2),
        "corporate_ness":        round(max(0.0, min(1.0, formal_count * 0.3 - grassroots_count * 0.15)), 2),
    }


@tool
def vibe_classifier_tool(description: str) -> str:
    """
    Classifies newcomer-friendliness, social vibe, and atmosphere from a
    candidate community description or title.

    Uses the LLM for nuanced scoring; falls back to keyword matching if the
    LLM is unavailable. Scores each dimension on a 0.0–1.0 scale.

    New vs. previous version:
      - alcohol_centrality: how central alcohol is to the event
      - corporate_ness: how enterprise/formal vs grassroots the vibe is

    These dimensions feed directly into dealbreaker matching in the ranking agent.

    Args:
        description: Combined title + description text of the community/event.

    Returns:
        JSON object with vibe dimension scores (0.0–1.0).
    """
    from community_matcher.agents.llm_client import llm_json

    text = (description or "").strip()
    if not text:
        return json.dumps({
            "newcomer_friendliness": 0.5, "vibe_alignment": 0.5,
            "is_casual": False, "is_technical": False, "is_creative": False,
            "alcohol_centrality": 0.0, "corporate_ness": 0.0,
        })

    # Primary: LLM scoring
    try:
        raw = llm_json(_SYSTEM_PROMPT, text[:600])  # cap input length
        parsed = json.loads(raw)
        if isinstance(parsed, dict) and "newcomer_friendliness" in parsed:
            # Coerce all float fields, booleans stay as-is
            result = {
                "newcomer_friendliness": round(float(parsed.get("newcomer_friendliness", 0.5)), 2),
                "vibe_alignment":        round(float(parsed.get("vibe_alignment", 0.5)), 2),
                "is_casual":             bool(parsed.get("is_casual", False)),
                "is_technical":          bool(parsed.get("is_technical", False)),
                "is_creative":           bool(parsed.get("is_creative", False)),
                "alcohol_centrality":    round(float(parsed.get("alcohol_centrality", 0.0)), 2),
                "corporate_ness":        round(float(parsed.get("corporate_ness", 0.0)), 2),
            }
            log.debug("vibe_classifier.llm_scored",
                      newcomer=result["newcomer_friendliness"],
                      vibe=result["vibe_alignment"])
            return json.dumps(result)
    except Exception as exc:
        log.debug("vibe_classifier.llm_fallback", error=str(exc))

    # Fallback: keyword scoring
    result = _keyword_fallback(text)
    log.debug("vibe_classifier.keyword_fallback",
              newcomer=result["newcomer_friendliness"],
              vibe=result["vibe_alignment"])
    return json.dumps(result)
