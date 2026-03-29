import pytest
from community_matcher.domain.profile import UserProfile, LogisticsPrefs
from community_matcher.orchestrator.sufficiency import check_sufficiency


def test_empty_profile_not_sufficient():
    result = check_sufficiency(UserProfile())
    assert not result.is_sufficient
    assert result.score == 0.0
    assert "primary_goal" in result.missing_categories
    assert "interest_cluster" in result.missing_categories
    assert "social_mode" in result.missing_categories
    assert "logistics" in result.missing_categories


def test_partial_profile_one_field():
    profile = UserProfile(goals=["find friends"])
    result = check_sufficiency(profile)
    assert not result.is_sufficient
    # goals set with no confidence → credit=0.7 (benefit-of-doubt), weight=0.30
    # score = 0.30 * 0.7 = 0.21
    assert result.score == 0.21
    assert "primary_goal" not in result.missing_categories
    assert "interest_cluster" in result.missing_categories


def test_full_profile_is_sufficient():
    profile = UserProfile(
        goals=["find friends"],
        interests=["coding"],
        social_mode="workshops",
        logistics=LogisticsPrefs(districts=["Mitte"]),
    )
    result = check_sufficiency(profile)
    assert result.is_sufficient
    # All fields set without extraction pipeline → confidence=None → credit=0.7 each
    # score = (0.30 + 0.30 + 0.25 + 0.15) * 0.7 = 1.0 * 0.7 = 0.70
    assert result.score == 0.7
    assert result.missing_categories == []


def test_logistics_via_max_travel_minutes():
    profile = UserProfile(
        goals=["networking"],
        interests=["AI"],
        social_mode="talks",
        logistics=LogisticsPrefs(max_travel_minutes=30),
    )
    result = check_sufficiency(profile)
    assert result.is_sufficient


def test_sufficiency_result_has_reason():
    result = check_sufficiency(UserProfile())
    assert "Missing" in result.reason


# Sprint 2 placeholder
@pytest.mark.skip(reason="Sprint 2: information-gain sufficiency not yet implemented")
def test_sufficiency_with_confidence_weighting():
    pass
