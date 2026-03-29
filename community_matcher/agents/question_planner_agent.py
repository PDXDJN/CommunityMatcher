"""
QuestionPlanner agent — selects the next 1-3 highest-value clarification
questions given the current profile and missing fields.

Uses the LLM to pick contextually relevant questions. Falls back to the
static QUESTION_BANK if LLM is unavailable.
"""
from __future__ import annotations
import json
import re
import structlog
from community_matcher.agents import tool

log = structlog.get_logger()

_QUESTION_BANK = {
    "primary_goal":   "What brings you here — are you looking for friends, professional connections, or something else?",
    "interest_cluster": "What topics or activities excite you most? (e.g. coding, games, AI, art, music)",
    "social_mode":    "Do you prefer workshops, talks, casual drinks, project nights, or something else?",
    "environment":    "Are you looking for a welcoming newcomer space, or a tight-knit regular community?",
    "logistics":      "Which part of the city are you in, and how far are you willing to travel?",
    "language_pref":  "Do you prefer events in English, German, or are you open to both?",
    "budget":         "Do you need free events, or is a small ticket price okay?",
    "dealbreakers":   "Are there any environments you want to avoid — too corporate, too loud, alcohol-heavy?",
}

_SYSTEM_PROMPT = """\
You are a question selection specialist for CommunityMatcher Berlin.

Given the current user profile and a list of missing profile categories,
select the next 1-3 highest-value clarification questions to ask.

Prioritise questions that will most improve community recommendation quality.
Combine related questions into one natural sentence when possible.
Be concise and friendly. Use plain language.

Output a JSON array of question strings. No explanation. No markdown.
Example: ["What kind of social vibe are you looking for?", "How far are you willing to travel?"]
"""


@tool
def question_planner_tool(profile_json: str) -> str:
    """
    Selects the next 1-3 highest-value clarification questions.

    Uses the LLM to pick contextually relevant questions given the current
    profile state. Falls back to the static question bank on error.

    Args:
        profile_json: JSON string of the current UserProfile.

    Returns:
        JSON array of question strings to ask the user.
    """
    from community_matcher.agents.llm_client import llm_json
    from community_matcher.orchestrator.sufficiency import check_sufficiency
    from community_matcher.domain.profile import UserProfile

    try:
        profile_data = json.loads(profile_json)
        profile = UserProfile(**{k: v for k, v in profile_data.items()
                                 if k in UserProfile.model_fields})
        result = check_sufficiency(profile)
        missing = result.missing_categories

        if not missing:
            return "[]"

        # Try LLM for smarter question selection
        user_msg = (
            f"Profile so far: {profile_json}\n"
            f"Missing categories: {missing}\n"
            f"Available question bank:\n"
            + "\n".join(f"  {k}: {v}" for k, v in _QUESTION_BANK.items() if k in missing)
        )

        raw = llm_json(_SYSTEM_PROMPT, user_msg)
        questions = json.loads(raw)
        if isinstance(questions, list) and all(isinstance(q, str) for q in questions):
            log.info("question_planner.llm_selected", count=len(questions))
            return json.dumps(questions[:3])

    except Exception as exc:
        log.warning("question_planner.llm_fallback", error=str(exc))

    # Fallback: static question bank
    try:
        profile_data = json.loads(profile_json)
        profile = UserProfile(**{k: v for k, v in profile_data.items()
                                 if k in UserProfile.model_fields})
        result = check_sufficiency(profile)
        questions = [_QUESTION_BANK[cat] for cat in result.missing_categories if cat in _QUESTION_BANK]
        return json.dumps(questions[:3])
    except Exception:
        return '["What kind of community are you looking for?"]'
