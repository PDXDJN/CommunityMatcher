from __future__ import annotations
from community_matcher.domain.profile import UserProfile

QUESTION_BANK: dict[str, str] = {
    "primary_goal": "What brings you here — are you looking for friends, professional connections, or something else?",
    "interest_cluster": "What topics or activities excite you most? (e.g. coding, games, AI, art)",
    "social_mode": "Do you prefer workshops, talks, casual drinks, project nights, or something else?",
    "environment": "Are you looking for a welcoming newcomer space, or a tight-knit regular community?",
    "logistics": "Which part of the city are you in, and how long are you willing to travel?",
    "language_pref": "Do you prefer events in English, German, or are you open to both?",
    "budget": "Do you need free events, or is a small ticket price okay?",
    "dealbreakers": "Are there any environments you want to avoid — too corporate, too loud, alcohol-heavy?",
}


def select_next_questions(
    profile: UserProfile,
    missing_categories: list[str],
    max_questions: int = 3,
) -> list[str]:
    """
    Sprint 0: returns the first N questions from the missing category list.
    Sprint 3 will replace with information-gain-based selection.
    """
    questions = []
    for category in missing_categories[:max_questions]:
        if category in QUESTION_BANK:
            questions.append(QUESTION_BANK[category])
    return questions
