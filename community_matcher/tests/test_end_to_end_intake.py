import pytest
from community_matcher.orchestrator.orchestrator_agent import OrchestratorAgent
from community_matcher.orchestrator.session_state import SessionState, OrchestratorPhase


def test_orchestrator_initializes():
    agent = OrchestratorAgent()
    assert agent.state.session_id != ""
    assert agent.state.phase == OrchestratorPhase.INTAKE


def test_orchestrator_with_provided_state():
    state = SessionState()
    agent = OrchestratorAgent(state=state)
    assert agent.state is state


def test_orchestrator_returns_string_response():
    agent = OrchestratorAgent()
    response = agent.process_turn("I am new to Berlin and want to find my people.")
    assert isinstance(response, str)
    assert len(response) > 0


def test_orchestrator_advances_past_intake():
    agent = OrchestratorAgent()
    agent.process_turn("I am new to Berlin.")
    assert agent.state.phase != OrchestratorPhase.INTAKE


def test_session_state_records_history():
    agent = OrchestratorAgent()
    agent.process_turn("Hello")
    assert len(agent.state.conversation_history) == 2
    assert agent.state.conversation_history[0]["role"] == "user"
    assert agent.state.conversation_history[1]["role"] == "assistant"


def test_multiple_turns_accumulate_history():
    agent = OrchestratorAgent()
    agent.process_turn("Hello")
    agent.process_turn("I like coding")
    assert len(agent.state.conversation_history) == 4


# Sprint 1 placeholder
@pytest.mark.skip(reason="Sprint 1: real profile extraction not yet implemented")
def test_intake_extracts_goals_from_message():
    pass
