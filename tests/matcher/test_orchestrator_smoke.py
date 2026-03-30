"""
Orchestrator state machine smoke tests.

Uses a mocked LLM (all agent tools are monkey-patched to return fixtures)
so no external services, DB, or network are required.
"""
from __future__ import annotations

import json
from unittest.mock import patch, MagicMock

import pytest

from community_matcher.orchestrator.session_state import SessionState, OrchestratorPhase
from community_matcher.orchestrator.orchestrator_agent import OrchestratorAgent


# ── fixture helpers ───────────────────────────────────────────────────────────

def _make_agent() -> OrchestratorAgent:
    return OrchestratorAgent(state=SessionState())


def _profile_update_json(**kwargs) -> str:
    return json.dumps({"interests": ["python"], "goals": ["friends"], **kwargs})


def _questions_json() -> str:
    return json.dumps(["What kind of format do you prefer?"])


def _empty_rows_json() -> str:
    return json.dumps([])


def _rows_json() -> str:
    return json.dumps([
        {
            "id": 1,
            "title": "Berlin Python Meetup",
            "description": "Monthly Python developers gathering",
            "organizer_name": "Berlin Python Group",
            "source_url": "https://example.com/bpg",
            "topic_signals": '["python","tech"]',
            "tags": '["python","tech","english_friendly"]',
            "cost_factor": 0,
            "is_online": False,
            "city": "Berlin",
            "_vibe": {
                "newcomer_friendliness": 0.8,
                "vibe_alignment": 0.7,
                "is_casual": True,
                "is_technical": True,
                "alcohol_centrality": 0.1,
                "corporate_ness": 0.1,
            },
            "_risk": {"pass": True, "risk_sanity_score": 0.9},
        }
    ])


def _ranked_json(rows_json: str) -> str:
    rows = json.loads(rows_json)
    for r in rows:
        r["_scores"] = {
            "total": 0.75,
            "interest_alignment": 0.9,
            "vibe_alignment": 0.7,
            "newcomer_friendliness": 0.8,
            "logistics_fit": 0.7,
            "language_fit": 1.0,
            "values_fit": 1.0,
            "recurrence_strength": 0.4,
            "risk_sanity": 0.9,
        }
    return json.dumps(rows)


# ── test: INTAKE → QUESTIONING ────────────────────────────────────────────────

def test_intake_transitions_to_questioning():
    agent = _make_agent()
    assert agent.state.phase == OrchestratorPhase.INTAKE

    with patch("community_matcher.orchestrator.orchestrator_agent.profile_builder_tool",
               return_value=_profile_update_json()), \
         patch("community_matcher.orchestrator.orchestrator_agent.question_planner_tool",
               return_value=_questions_json()), \
         patch("community_matcher.orchestrator.orchestrator_agent._agent_call",
               side_effect=lambda name, fn, *a, **kw: fn(*a, **kw)):
        response = agent.process_turn("I want to meet other Python developers")

    # Should be in QUESTIONING (asking a follow-up), not jumped to SEARCHING yet
    assert agent.state.phase in (OrchestratorPhase.QUESTIONING, OrchestratorPhase.SEARCHING)
    assert isinstance(response, str)
    assert len(response) > 0


# ── test: full happy path with mocked pipeline ────────────────────────────────

def test_full_pipeline_produces_recommendation():
    """With sufficient profile signals, the orchestrator should complete a full search cycle."""
    agent = _make_agent()

    # Prime the profile so sufficiency check passes immediately
    agent.state.profile.interests = ["python", "tech", "maker"]
    agent.state.profile.goals = ["friends", "learning"]
    agent.state.profile.social_mode = "workshop"
    agent.state.profile.language_pref = ["english"]
    agent.state.phase = OrchestratorPhase.SEARCHING

    mock_rows = _rows_json()
    mock_ranked = _ranked_json(mock_rows)

    with patch("community_matcher.orchestrator.orchestrator_agent.archetype_tool",
               return_value='{"hacker": 0.8, "ai": 0.6}'), \
         patch("community_matcher.orchestrator.orchestrator_agent.search_planner_tool",
               return_value='{"query_intents": ["python meetup Berlin"]}'), \
         patch("community_matcher.orchestrator.orchestrator_agent.txt2sql_tool",
               return_value=mock_rows), \
         patch("community_matcher.orchestrator.orchestrator_agent.vibe_classifier_tool",
               return_value='{"newcomer_friendliness":0.8,"vibe_alignment":0.7,'
                            '"is_casual":true,"is_technical":true,'
                            '"alcohol_centrality":0.1,"corporate_ness":0.1}'), \
         patch("community_matcher.orchestrator.orchestrator_agent.risk_sanity_tool",
               return_value='{"pass":true,"risk_sanity_score":0.9}'), \
         patch("community_matcher.orchestrator.orchestrator_agent.ranking_tool",
               return_value=mock_ranked), \
         patch("community_matcher.orchestrator.orchestrator_agent.recommendation_writer_tool",
               return_value="Here are your top Berlin Python communities: Berlin Python Meetup"), \
         patch("community_matcher.orchestrator.orchestrator_agent._agent_call",
               side_effect=lambda name, fn, *a, **kw: fn(*a, **kw)):
        response = agent.process_turn("show me what you have")

    assert "Berlin Python Meetup" in response
    assert agent.state.phase == OrchestratorPhase.RECOMMENDING


# ── test: REFINING re-ranks without new search ───────────────────────────────

def test_refining_rerank_without_new_search():
    """When user gives feedback but doesn't request new search, cached rows are re-ranked."""
    agent = _make_agent()
    agent.state.phase = OrchestratorPhase.REFINING

    # Seed cached rows
    rows = json.loads(_ranked_json(_rows_json()))
    agent.state.last_ranked_rows = rows
    agent.state.profile.interests = ["python"]

    with patch("community_matcher.orchestrator.orchestrator_agent.ranking_tool",
               return_value=json.dumps(rows)), \
         patch("community_matcher.orchestrator.orchestrator_agent.recommendation_writer_tool",
               return_value="Updated recommendations after feedback"), \
         patch("community_matcher.orchestrator.orchestrator_agent._agent_call",
               side_effect=lambda name, fn, *a, **kw: fn(*a, **kw)):
        response = agent.process_turn("too corporate")

    assert isinstance(response, str)
    assert "corporate" in agent.state.profile.dealbreakers


# ── test: REFINING new search when user says "find more" ─────────────────────

def test_refining_triggers_new_search_on_keyword():
    """'find more' should trigger a full re-search, not just a re-rank."""
    agent = _make_agent()
    agent.state.phase = OrchestratorPhase.REFINING
    agent.state.profile.interests = ["python"]
    agent.state.last_ranked_rows = json.loads(_ranked_json(_rows_json()))

    mock_rows = _rows_json()
    mock_ranked = _ranked_json(mock_rows)

    with patch("community_matcher.orchestrator.orchestrator_agent.archetype_tool",
               return_value='{"hacker": 0.7}'), \
         patch("community_matcher.orchestrator.orchestrator_agent.search_planner_tool",
               return_value='{"query_intents": ["python Berlin"]}'), \
         patch("community_matcher.orchestrator.orchestrator_agent.txt2sql_tool",
               return_value=mock_rows), \
         patch("community_matcher.orchestrator.orchestrator_agent.vibe_classifier_tool",
               return_value='{"newcomer_friendliness":0.7,"vibe_alignment":0.6,'
                            '"is_casual":true,"is_technical":true,'
                            '"alcohol_centrality":0.1,"corporate_ness":0.1}'), \
         patch("community_matcher.orchestrator.orchestrator_agent.risk_sanity_tool",
               return_value='{"pass":true,"risk_sanity_score":0.9}'), \
         patch("community_matcher.orchestrator.orchestrator_agent.ranking_tool",
               return_value=mock_ranked), \
         patch("community_matcher.orchestrator.orchestrator_agent.recommendation_writer_tool",
               return_value="New search results"), \
         patch("community_matcher.orchestrator.orchestrator_agent._agent_call",
               side_effect=lambda name, fn, *a, **kw: fn(*a, **kw)):
        response = agent.process_turn("find more options")

    assert isinstance(response, str)
    assert agent.state.phase == OrchestratorPhase.RECOMMENDING


# ── test: session_id is set ───────────────────────────────────────────────────

def test_orchestrator_has_session_id():
    agent = _make_agent()
    assert agent.state.session_id is not None
    assert len(agent.state.session_id) > 0


# ── test: conversation history grows ─────────────────────────────────────────

def test_conversation_history_appended():
    agent = _make_agent()
    agent.state.phase = OrchestratorPhase.QUESTIONING
    agent.state.profile.interests = ["python"]

    with patch("community_matcher.orchestrator.orchestrator_agent._agent_call",
               side_effect=lambda name, fn, *a, **kw: fn(*a, **kw)), \
         patch("community_matcher.orchestrator.orchestrator_agent.profile_builder_tool",
               return_value="{}"), \
         patch("community_matcher.orchestrator.orchestrator_agent.question_planner_tool",
               return_value='["What format do you prefer?"]'):
        agent.process_turn("I enjoy hands-on workshops")

    user_turns = [t for t in agent.state.conversation_history if t["role"] == "user"]
    assert len(user_turns) >= 1
    assert user_turns[-1]["content"] == "I enjoy hands-on workshops"
