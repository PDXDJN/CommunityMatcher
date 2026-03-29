import pytest
from community_matcher.domain.profile import (
    UserProfile,
    FieldConfidence,
    LogisticsPrefs,
    BudgetSensitivity,
)


def test_user_profile_defaults():
    profile = UserProfile()
    assert profile.is_empty()
    assert profile.goals == []
    assert profile.interests == []
    assert profile.budget == BudgetSensitivity.ANY


def test_user_profile_with_goals_not_empty():
    profile = UserProfile(goals=["find friends"])
    assert not profile.is_empty()


def test_user_profile_with_social_mode_not_empty():
    profile = UserProfile(social_mode="workshops")
    assert not profile.is_empty()


def test_field_confidence_enum_values():
    assert FieldConfidence.EXPLICIT == "explicit"
    assert FieldConfidence.INFERRED_HIGH == "inferred_high"
    assert FieldConfidence.INFERRED_LOW == "inferred_low"
    assert FieldConfidence.UNKNOWN == "unknown"


def test_logistics_prefs_defaults():
    prefs = LogisticsPrefs()
    assert prefs.districts == []
    assert prefs.max_travel_minutes is None
    assert prefs.available_days == []


def test_profile_serializes_to_json():
    profile = UserProfile(goals=["networking"], interests=["AI"])
    data = profile.model_dump()
    assert data["goals"] == ["networking"]
    assert data["budget"] == "any"


# Sprint 1 placeholder
@pytest.mark.skip(reason="Sprint 1: profile builder agent not yet implemented")
def test_profile_builder_extracts_goals():
    pass
