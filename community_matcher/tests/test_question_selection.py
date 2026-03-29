import pytest
from community_matcher.domain.profile import UserProfile
from community_matcher.orchestrator.question_selection import (
    select_next_questions,
    QUESTION_BANK,
)


def test_returns_questions_for_missing_categories():
    questions = select_next_questions(
        UserProfile(), ["primary_goal", "interest_cluster"], max_questions=3
    )
    assert len(questions) == 2
    assert all(isinstance(q, str) for q in questions)


def test_respects_max_questions_limit():
    all_missing = list(QUESTION_BANK.keys())
    questions = select_next_questions(UserProfile(), all_missing, max_questions=2)
    assert len(questions) <= 2


def test_unknown_category_is_skipped():
    questions = select_next_questions(
        UserProfile(), ["nonexistent_category", "primary_goal"], max_questions=3
    )
    assert len(questions) == 1


def test_question_bank_covers_required_categories():
    required = {"primary_goal", "interest_cluster", "social_mode", "logistics"}
    assert required.issubset(set(QUESTION_BANK.keys()))


def test_empty_missing_returns_empty():
    questions = select_next_questions(UserProfile(), [], max_questions=3)
    assert questions == []


# Sprint 3 placeholder
@pytest.mark.skip(reason="Sprint 3: information-gain question selection not yet implemented")
def test_question_selection_prioritizes_high_value():
    pass
