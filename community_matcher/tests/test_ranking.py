import pytest
from community_matcher.domain.scoring import CandidateScores
from community_matcher.domain.candidates import CandidateCommunity


def test_candidate_scores_default_total():
    scores = CandidateScores()
    assert scores.total == 0.0


def test_candidate_scores_interest_alignment_weight():
    scores = CandidateScores(interest_alignment=1.0)
    # weight_interest_alignment defaults to 0.25
    assert abs(scores.total - 0.25) < 1e-9


def test_candidate_scores_all_ones_sums_to_one():
    scores = CandidateScores(
        interest_alignment=1.0,
        vibe_alignment=1.0,
        newcomer_friendliness=1.0,
        logistics_fit=1.0,
        language_fit=1.0,
        values_fit=1.0,
        recurrence_strength=1.0,
        risk_sanity=1.0,
    )
    assert abs(scores.total - 1.0) < 1e-9


def test_candidate_community_missing_required_fields():
    with pytest.raises(Exception):
        CandidateCommunity()


def test_candidate_community_valid():
    c = CandidateCommunity(
        id="test-1",
        name="Berlin Python Meetup",
        description="Monthly Python meetup in Berlin",
        category="group",
    )
    assert c.tags == []
    assert c.url is None
    assert c.raw_source == {}


def test_candidate_community_serializes():
    c = CandidateCommunity(
        id="x1", name="Test Group", description="A test", category="event"
    )
    data = c.model_dump()
    assert data["id"] == "x1"
    assert data["category"] == "event"


# Sprint 5 placeholder
@pytest.mark.skip(reason="Sprint 5: real ranking logic not yet implemented")
def test_ranking_agent_orders_by_score():
    pass
