"""
Unit tests for the ranking agent and organizer aggregation.

These tests are fully self-contained — no DB, no LLM, no external services.
"""
from __future__ import annotations

import json
import pytest

from community_matcher.agents.ranking_agent import (
    _interest_alignment,
    _language_fit,
    _logistics_fit,
    _recurrence_strength,
    _values_fit,
    _score_candidate,
    ranking_tool,
)
from community_matcher.orchestrator.orchestrator_agent import _aggregate_by_organizer


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_candidate(
    title="Test Event",
    tags=None,
    organizer="Org A",
    vibe=None,
    risk=None,
) -> dict:
    return {
        "id": 1,
        "title": title,
        "description": "A Berlin tech event",
        "organizer_name": organizer,
        "topic_signals": json.dumps(tags or ["python", "tech"]),
        "tags": json.dumps(tags or ["python", "tech"]),
        "city": "Berlin",
        "cost_factor": 0,
        "is_online": False,
        "_vibe": vibe or {
            "newcomer_friendliness": 0.7,
            "vibe_alignment": 0.6,
            "is_casual": True,
            "is_technical": True,
            "alcohol_centrality": 0.1,
            "corporate_ness": 0.1,
        },
        "_risk": risk or {"pass": True, "risk_sanity_score": 0.9},
    }


def _make_profile(
    interests=None,
    social_mode="workshop",
    language_pref=None,
    dealbreakers=None,
    logistics=None,
    budget=None,
) -> dict:
    return {
        "interests": interests or ["python", "tech"],
        "social_mode": social_mode,
        "language_pref": language_pref or ["english"],
        "dealbreakers": dealbreakers or [],
        "logistics": logistics or {"districts": []},
        "budget": budget,
        "values": [],
    }


# ── interest_alignment ────────────────────────────────────────────────────────

def test_interest_alignment_full_overlap():
    assert _interest_alignment(["python", "tech"], ["python", "tech"]) == pytest.approx(1.0)


def test_interest_alignment_no_overlap():
    score = _interest_alignment(["python"], ["dance", "music"])
    assert score == pytest.approx(0.1)


def test_interest_alignment_empty_profile():
    # neutral when no interests set
    assert _interest_alignment([], ["python"]) == pytest.approx(0.5)


def test_interest_alignment_partial():
    score = _interest_alignment(["python", "ai", "data_science"], ["python"])
    assert 0.1 < score < 1.0


# ── language_fit ──────────────────────────────────────────────────────────────

def test_language_fit_english_tag_match():
    assert _language_fit(["english"], ["english_friendly", "tech"]) == pytest.approx(1.0)


def test_language_fit_no_preference():
    assert _language_fit([], ["python"]) == pytest.approx(0.7)


def test_language_fit_german_preference():
    score = _language_fit(["german"], ["tech"])
    assert score == pytest.approx(0.7)


# ── logistics_fit ─────────────────────────────────────────────────────────────

def test_logistics_fit_no_preference():
    profile_logistics = {"districts": []}
    assert _logistics_fit(profile_logistics, [], "anything") == pytest.approx(0.7)


def test_logistics_fit_district_match():
    profile_logistics = {"districts": ["kreuzberg"]}
    score = _logistics_fit(profile_logistics, [], "event in Kreuzberg Berlin")
    assert score == pytest.approx(1.0)


def test_logistics_fit_online_with_preference():
    profile_logistics = {"districts": ["mitte"]}
    score = _logistics_fit(profile_logistics, ["online"], "online event")
    assert score == pytest.approx(0.6)


# ── recurrence_strength ───────────────────────────────────────────────────────

def test_recurrence_strong_for_recurring_tags():
    assert _recurrence_strength(["community", "tech"]) == pytest.approx(0.8)


def test_recurrence_weak_for_one_off():
    assert _recurrence_strength(["python", "workshop"]) == pytest.approx(0.4)


# ── values_fit / dealbreaker demotion ─────────────────────────────────────────

def test_values_fit_no_dealbreakers():
    score, hit = _values_fit([], "any event text")
    assert score == pytest.approx(1.0)
    assert hit is False


def test_values_fit_alcohol_hard_hit():
    vibe = {"alcohol_centrality": 0.8}
    score, hit = _values_fit(["alcohol"], "beer tasting", vibe)
    assert score == pytest.approx(0.0)
    assert hit is True


def test_values_fit_alcohol_soft_hit():
    vibe = {"alcohol_centrality": 0.5}
    score, hit = _values_fit(["alcohol"], "social event", vibe)
    assert score == pytest.approx(0.3)
    assert hit is True


def test_values_fit_corporate_hard_hit():
    vibe = {"corporate_ness": 0.75}
    score, hit = _values_fit(["corporate"], "enterprise summit", vibe)
    assert score == pytest.approx(0.0)
    assert hit is True


def test_values_fit_corporate_soft_hit():
    vibe = {"corporate_ness": 0.45}
    score, hit = _values_fit(["corporate"], "startup pitch", vibe)
    assert score == pytest.approx(0.3)
    assert hit is True


def test_values_fit_text_match():
    score, hit = _values_fit(["loud"], "very loud noisy bar event")
    assert score == pytest.approx(0.0)
    assert hit is True


def test_values_fit_no_match():
    vibe = {"alcohol_centrality": 0.2, "corporate_ness": 0.1}
    score, hit = _values_fit(["alcohol", "corporate"], "quiet coding night", vibe)
    assert score == pytest.approx(1.0)
    assert hit is False


# ── _score_candidate / dealbreaker multiplier ────────────────────────────────

def test_score_candidate_dealbreaker_multiplies_down():
    """A dealbreaker hit should cut the total score by the 0.45x multiplier."""
    profile = _make_profile(dealbreakers=["alcohol"])
    candidate = _make_candidate(
        vibe={"newcomer_friendliness": 0.8, "vibe_alignment": 0.8,
              "is_casual": True, "is_technical": True,
              "alcohol_centrality": 0.9, "corporate_ness": 0.1}
    )
    result = _score_candidate(candidate, profile)
    scores = result["_scores"]
    assert scores["dealbreaker_hit"] is True
    # total must be well below neutral (0.5) due to multiplier
    assert scores["total"] < 0.4


def test_score_candidate_no_dealbreaker_full_score():
    profile = _make_profile(dealbreakers=[])
    candidate = _make_candidate()
    result = _score_candidate(candidate, profile)
    scores = result["_scores"]
    assert "dealbreaker_hit" not in scores
    assert scores["total"] > 0.4


# ── ranking_tool (integration of scoring + sort) ─────────────────────────────

def test_ranking_tool_sorts_by_total():
    profile = _make_profile()
    c1 = _make_candidate(title="High Match", tags=["python", "tech"])
    c2 = _make_candidate(title="Low Match", tags=["dance", "music"])
    c2["id"] = 2
    ranked = json.loads(ranking_tool(json.dumps([c1, c2]), json.dumps(profile)))
    assert ranked[0]["title"] == "High Match"


def test_ranking_tool_filters_risk_failures():
    profile = _make_profile()
    c1 = _make_candidate(title="Safe")
    c2 = _make_candidate(title="Unsafe", risk={"pass": False, "risk_sanity_score": 0.1})
    c2["id"] = 2
    ranked = json.loads(ranking_tool(json.dumps([c1, c2]), json.dumps(profile)))
    titles = [r["title"] for r in ranked]
    assert "Unsafe" not in titles
    assert "Safe" in titles


def test_ranking_tool_empty_input():
    profile = _make_profile()
    result = ranking_tool("[]", json.dumps(profile))
    assert json.loads(result) == []


def test_ranking_tool_dealbreaker_pushed_to_bottom():
    profile = _make_profile(dealbreakers=["corporate"])
    c_clean = _make_candidate(title="Clean Event", tags=["python"])
    c_corporate = _make_candidate(
        title="Corporate Event",
        tags=["python"],
        vibe={"newcomer_friendliness": 0.8, "vibe_alignment": 0.8,
              "is_casual": False, "is_technical": True,
              "alcohol_centrality": 0.1, "corporate_ness": 0.9},
    )
    c_corporate["id"] = 2
    ranked = json.loads(ranking_tool(json.dumps([c_corporate, c_clean]), json.dumps(profile)))
    assert ranked[0]["title"] == "Clean Event"
    assert ranked[-1]["title"] == "Corporate Event"


# ── _aggregate_by_organizer ───────────────────────────────────────────────────

def _scored(row: dict, total: float) -> dict:
    row["_scores"] = {"total": total, "recurrence_strength": 0.4}
    return row


def test_aggregate_collapses_same_organizer():
    rows = [
        _scored(_make_candidate(title="Event A", organizer="Berlin Python"), 0.8),
        _scored(_make_candidate(title="Event B", organizer="Berlin Python"), 0.75),
        _scored(_make_candidate(title="Event C", organizer="Other Group"), 0.6),
    ]
    rows[1]["id"] = 2
    rows[2]["id"] = 3
    result = _aggregate_by_organizer(rows)
    titles = [r["title"] for r in result]
    assert "Event B" not in titles   # lower-scored dupe removed
    assert "Event A" in titles        # best kept
    assert "Event C" in titles        # different organizer kept
    assert len(result) == 2


def test_aggregate_boosts_recurrence_for_multi_event_organizer():
    rows = [
        _scored(_make_candidate(title="Event A", organizer="Recurring Org"), 0.8),
        _scored(_make_candidate(title="Event B", organizer="Recurring Org"), 0.7),
    ]
    rows[1]["id"] = 2
    result = _aggregate_by_organizer(rows)
    assert len(result) == 1
    assert result[0]["_event_count"] == 2
    # Recurrence score must have been boosted
    assert result[0]["_scores"]["recurrence_strength"] > 0.4


def test_aggregate_preserves_single_event_organizer():
    rows = [_scored(_make_candidate(title="Solo Event", organizer="Solo Org"), 0.6)]
    result = _aggregate_by_organizer(rows)
    assert len(result) == 1
    assert result[0].get("_event_count", 1) == 1


def test_aggregate_ungrouped_rows_kept():
    rows = [
        _scored(_make_candidate(title="No Org", organizer=""), 0.5),
        _scored(_make_candidate(title="Also No Org", organizer="  "), 0.4),
    ]
    rows[1]["id"] = 2
    result = _aggregate_by_organizer(rows)
    assert len(result) == 2


def test_aggregate_empty_input():
    assert _aggregate_by_organizer([]) == []
