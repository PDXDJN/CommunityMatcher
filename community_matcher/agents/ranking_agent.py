"""
Ranking agent — scores and orders candidate communities against the user profile.

Computes a CandidateScores vector for each candidate using tag overlap,
vibe classifier output, and profile field matching. Rule-based, no LLM.

Expects candidates to have _vibe and _risk sub-objects embedded by the
orchestrator pipeline (from vibe_classifier_tool and risk_sanity_tool).
"""
from __future__ import annotations
import json
import structlog
from community_matcher.agents import tool
from community_matcher.config.settings import settings

log = structlog.get_logger()

# Tags that indicate English-language events
_ENGLISH_TAGS = {"english_friendly", "english", "international"}
# Tags that indicate free events
_FREE_TAGS = {"free"}
# Tags indicating recurring community (vs one-off event)
_RECURRING_TAGS = {"meetup_event", "community", "barcamp", "coworking"}

# Known Berlin district/neighbourhood names for logistics matching
_BERLIN_DISTRICTS = {
    "mitte", "prenzlauer berg", "kreuzberg", "friedrichshain", "neukölln",
    "neukolln", "schöneberg", "schoneberg", "charlottenburg", "wedding",
    "moabit", "tempelhof", "steglitz", "spandau", "pankow", "reinickendorf",
    "treptow", "köpenick", "kopenick", "marzahn", "lichtenberg", "weißensee",
    "weissensee", "hellersdorf", "wilmersdorf", "zehlendorf", "adlershof",
    "tiergarten", "gesundbrunnen", "prenzlberg",
}


def _parse_tags(tags_field) -> list[str]:
    """Parse tags from either a JSON string array or plain list."""
    if isinstance(tags_field, list):
        return [str(t).lower() for t in tags_field]
    if isinstance(tags_field, str) and tags_field.startswith("["):
        try:
            return [str(t).lower() for t in json.loads(tags_field)]
        except Exception:
            pass
    return []


def _interest_alignment(profile_interests: list[str], candidate_tags: list[str]) -> float:
    """Jaccard-like overlap between profile interests and candidate tags."""
    if not profile_interests:
        return 0.5  # neutral when profile has no interests yet
    profile_set = set(profile_interests)
    tag_set = set(candidate_tags)
    overlap = len(profile_set & tag_set)
    if overlap == 0:
        return 0.1
    return min(1.0, overlap / len(profile_set) * 1.5)  # scale up partial matches


def _vibe_alignment(profile_social_mode: str | None, vibe: dict) -> float:
    base = vibe.get("vibe_alignment", 0.5)
    if profile_social_mode in ("social", "drinks"):
        return base + 0.1 if vibe.get("is_casual") else base - 0.1
    if profile_social_mode in ("workshop", "project"):
        return base + 0.1 if vibe.get("is_technical") else base - 0.05
    return base


def _language_fit(profile_lang: list[str], candidate_tags: list[str]) -> float:
    if not profile_lang:
        return 0.7  # neutral
    tag_set = set(candidate_tags)
    if "english" in profile_lang and tag_set & _ENGLISH_TAGS:
        return 1.0
    if "german" in profile_lang:
        return 0.7  # most Berlin events work for German speakers
    return 0.6


def _logistics_fit(profile_logistics, candidate_tags: list[str], combined_text: str) -> float:
    """
    Score logistics fit based on district overlap.

    - No profile districts → 0.7 neutral
    - Online event → 0.6 (distance irrelevant but not ideal if user wants in-person)
    - Candidate mentions a preferred district → 1.0
    - Candidate mentions no preferred district → 0.4
    """
    preferred = [d.lower() for d in (profile_logistics.get("districts") or [])]
    if not preferred:
        return 0.7  # no preference expressed

    # Online events have no meaningful location
    if "online" in candidate_tags:
        return 0.6

    text_lower = combined_text.lower()
    for district in preferred:
        if district in text_lower:
            return 1.0

    # Check against known Berlin districts appearing in the text — if the
    # candidate is in some other known district the user didn't ask for, give
    # a moderate score; if there's no district signal at all, give a low score.
    known_in_text = any(d in text_lower for d in _BERLIN_DISTRICTS)
    return 0.45 if known_in_text else 0.4


def _values_fit(
    dealbreakers: list[str], combined_text: str, vibe: dict | None = None
) -> tuple[float, bool]:
    """Score values alignment. Also returns whether a dealbreaker was strongly hit.

    Returns (score, dealbreaker_hit) where:
      - score=1.0, hit=False — no dealbreaker match
      - score=0.3, hit=True  — soft hit (vibe dimension in 0.4–0.6 range)
      - score=0.0, hit=True  — hard hit (vibe > 0.6 or text match)

    Callers should apply a further penalty multiplier when hit=True.
    """
    t = combined_text.lower()
    alcohol   = (vibe or {}).get("alcohol_centrality", None)
    corporate = (vibe or {}).get("corporate_ness", None)

    for db in dealbreakers:
        db_lower = db.lower()
        # Structural vibe-dimension checks (more reliable than text matching)
        if db_lower in ("alcohol", "too much alcohol", "alcohol-heavy") and alcohol is not None:
            if alcohol > 0.6:
                return 0.0, True
            if alcohol > 0.4:
                return 0.3, True  # soft hit — still show but demote
            continue
        if db_lower in ("corporate", "too corporate") and corporate is not None:
            if corporate > 0.6:
                return 0.0, True
            if corporate > 0.4:
                return 0.3, True
            continue
        # Text-based fallback for all other dealbreakers
        if db_lower in t:
            return 0.0, True
    return 1.0, False


def _recurrence_strength(candidate_tags: list[str]) -> float:
    tag_set = set(candidate_tags)
    return 0.8 if tag_set & _RECURRING_TAGS else 0.4


def _score_candidate(candidate: dict, profile: dict) -> dict:
    tags = _parse_tags(candidate.get("topic_signals") or candidate.get("tags", []))
    vibe = candidate.get("_vibe", {})
    risk = candidate.get("_risk", {})

    interests    = profile.get("interests", [])
    social_mode  = profile.get("social_mode")
    lang_pref    = profile.get("language_pref", [])
    dealbreakers = profile.get("dealbreakers", [])
    logistics    = profile.get("logistics", {})
    combined_text = (
        (candidate.get("title") or "") + " " +
        (candidate.get("description") or "") + " " +
        (candidate.get("venue") or "")
    )

    values_score, dealbreaker_hit = _values_fit(dealbreakers, combined_text, vibe)

    scores = {
        "interest_alignment":    round(_interest_alignment(interests, tags), 3),
        "vibe_alignment":        round(max(0.0, min(1.0, _vibe_alignment(social_mode, vibe))), 3),
        "newcomer_friendliness": round(vibe.get("newcomer_friendliness", 0.5), 3),
        "logistics_fit":         round(_logistics_fit(logistics, tags, combined_text), 3),
        "language_fit":          round(_language_fit(lang_pref, tags), 3),
        "values_fit":            round(values_score, 3),
        "recurrence_strength":   round(_recurrence_strength(tags), 3),
        "risk_sanity":           round(risk.get("risk_sanity_score", 0.8), 3),
    }
    if dealbreaker_hit:
        scores["dealbreaker_hit"] = True

    s = settings
    total = (
        s.weight_interest_alignment    * scores["interest_alignment"]
        + s.weight_vibe_alignment      * scores["vibe_alignment"]
        + s.weight_newcomer_friendliness * scores["newcomer_friendliness"]
        + s.weight_logistics_fit       * scores["logistics_fit"]
        + s.weight_language_fit        * scores["language_fit"]
        + s.weight_values_fit          * scores["values_fit"]
        + s.weight_recurrence_strength * scores["recurrence_strength"]
        + s.weight_risk_sanity         * scores["risk_sanity"]
    )

    # Apply a strong demotion multiplier when a dealbreaker was matched.
    # This pushes dealbreaker results well below neutral alternatives even if
    # their other dimensions (interest, vibe) score highly.
    if dealbreaker_hit:
        total *= 0.45

    scores["total"] = round(total, 4)
    candidate["_scores"] = scores
    return candidate


@tool
def ranking_tool(candidates_json: str, profile_json: str) -> str:
    """
    Scores and orders candidate communities against the user profile.

    Computes multi-dimensional scores (interest alignment, vibe, newcomer
    friendliness, logistics, language, values, recurrence, risk/sanity)
    and sorts candidates descending by total weighted score.

    Args:
        candidates_json: JSON array of DB row dicts (may include _vibe and
                         _risk sub-objects from the orchestrator pipeline).
        profile_json:    JSON string of the current UserProfile.

    Returns:
        JSON array of candidates with _scores sub-objects, sorted by
        _scores.total descending.
    """
    try:
        candidates = json.loads(candidates_json)
        profile    = json.loads(profile_json)

        if not isinstance(candidates, list):
            return "[]"

        # Filter out candidates that failed risk sanity
        safe = [c for c in candidates if c.get("_risk", {}).get("pass", True)]

        scored = [_score_candidate(c, profile) for c in safe]
        scored.sort(key=lambda c: c["_scores"]["total"], reverse=True)

        # Drop results with zero interest alignment when the profile has explicit
        # interests — this prevents completely off-topic results from surfacing.
        interests = profile.get("interests", [])
        if interests:
            relevant = [c for c in scored if c["_scores"]["interest_alignment"] > 0.1]
            if relevant:  # only apply the filter if it leaves at least one result
                scored = relevant

        log.info("ranking.done", total=len(candidates), kept=len(safe), scored=len(scored))
        return json.dumps(scored)
    except Exception as exc:
        log.warning("ranking.error", error=str(exc))
        return candidates_json  # return unsorted on error
