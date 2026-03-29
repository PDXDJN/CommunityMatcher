"""
Integration tests for the txt2sql tool and orchestrator search phase.

These tests require:
  - The collector SQLite DB to exist at community_collector/output/communitymatcher.db
  - The Ollama server to be reachable at http://ai.cbrp3.c-base.org:11434

Run with:
    pytest community_matcher/tests/test_integration_txt2sql.py -v -s
"""
from __future__ import annotations
import json
import pytest
from pathlib import Path

# DB path for all tests
_DB = Path(__file__).parent.parent.parent / "community_collector" / "output" / "communitymatcher.db"

pytestmark = pytest.mark.skipif(
    not _DB.exists(),
    reason="Collector DB not found — run the collector first",
)


# ── 1. DB layer ────────────────────────────────────────────────────────────────

class TestSQLiteConnection:
    def test_db_exists(self):
        assert _DB.exists(), f"DB not found at {_DB}"

    def test_execute_query_returns_rows(self):
        from community_matcher.db.connection import execute_query
        rows = execute_query("SELECT COUNT(*) AS n FROM community", db_path=_DB)
        assert rows, "Expected at least one row"
        assert rows[0]["n"] > 0, "Expected community table to have records"

    def test_scrape_record_has_data(self):
        from community_matcher.db.connection import execute_query
        rows = execute_query(
            "SELECT title, source_url, tags FROM scrape_record LIMIT 5",
            db_path=_DB,
        )
        assert len(rows) == 5
        assert all(r["title"] for r in rows), "All records should have a title"

    def test_blocks_non_select(self):
        from community_matcher.db.connection import execute_query
        with pytest.raises(ValueError, match="Only SELECT"):
            execute_query("DELETE FROM community WHERE 1=1")

    def test_rows_to_json_serializable(self):
        from community_matcher.db.connection import execute_query, rows_to_json
        rows = execute_query(
            "SELECT idx, name, cost_factor FROM community LIMIT 3",
            db_path=_DB,
        )
        j = rows_to_json(rows)
        parsed = json.loads(j)
        assert isinstance(parsed, list)
        assert len(parsed) == 3


# ── 2. SQL generation (Ollama) ─────────────────────────────────────────────────

class TestSQLGeneration:
    """Tests that _generate_sql returns valid SQLite SELECT statements."""

    def _gen(self, question: str) -> str:
        from community_matcher.agents.txt2sql_agent import _generate_sql
        return _generate_sql(question)

    def test_generates_select(self):
        sql = self._gen("Find AI meetups in Berlin")
        assert sql.strip().upper().startswith("SELECT"), f"Not a SELECT: {sql}"

    def test_generates_valid_sql(self):
        from community_matcher.db.connection import _execute_sqlite
        sql = self._gen("List free workshops")
        # Should execute without error
        rows = _execute_sqlite(sql, None, _DB)
        assert isinstance(rows, list)

    def test_no_markdown_fences(self):
        sql = self._gen("Show startup networking events")
        assert "```" not in sql, f"SQL contains markdown fences: {sql}"

    def test_includes_limit(self):
        sql = self._gen("Find all tech events")
        assert "LIMIT" in sql.upper(), f"Expected LIMIT in: {sql}"


# ── 3. txt2sql_tool end-to-end ────────────────────────────────────────────────

class TestTxt2SqlTool:
    """Tests the full txt2sql_tool: question → SQL → execute → JSON."""

    def test_returns_json(self):
        from community_matcher.agents.txt2sql_agent import txt2sql_tool
        result = txt2sql_tool("Find AI or machine learning events")
        parsed = json.loads(result)
        assert isinstance(parsed, (list, dict))

    def test_ai_query_returns_results(self):
        from community_matcher.agents.txt2sql_agent import txt2sql_tool
        result = txt2sql_tool("Find AI or tech meetups")
        parsed = json.loads(result)
        assert isinstance(parsed, list), f"Expected list, got: {result[:200]}"
        assert len(parsed) > 0, "Expected results for AI/tech query"

    def test_free_events_query(self):
        from community_matcher.agents.txt2sql_agent import txt2sql_tool
        result = txt2sql_tool("Which communities are free to attend?")
        parsed = json.loads(result)
        assert isinstance(parsed, list)

    def test_startup_query(self):
        from community_matcher.agents.txt2sql_agent import txt2sql_tool
        result = txt2sql_tool("Find startup or entrepreneurship networking events")
        parsed = json.loads(result)
        assert isinstance(parsed, list)

    def test_error_response_is_json(self):
        """Even on error, the tool should return valid JSON."""
        from community_matcher.agents.txt2sql_agent import txt2sql_tool
        # Extremely vague question — should still return JSON
        result = txt2sql_tool("???")
        json.loads(result)  # must not raise


# ── 4. Orchestrator integration ───────────────────────────────────────────────

class TestOrchestratorWithTxt2Sql:
    """Tests the orchestrator's SEARCHING phase calling txt2sql_tool."""

    def _make_agent_at_searching(self):
        """Create an orchestrator already in SEARCHING phase."""
        from community_matcher.orchestrator.orchestrator_agent import OrchestratorAgent
        from community_matcher.orchestrator.session_state import SessionState, OrchestratorPhase

        state = SessionState(phase=OrchestratorPhase.SEARCHING)
        state.add_turn("user", "I'm new to Berlin and want to find AI and tech meetups")
        return OrchestratorAgent(state=state)

    def test_searching_phase_returns_results(self):
        agent = self._make_agent_at_searching()
        response = agent.process_turn("Please search for AI events")
        assert response, "Expected non-empty response"
        # Should not be the stub string from Sprint 0
        assert "stub" not in response.lower()

    def test_searching_phase_advances_to_recommending(self):
        from community_matcher.orchestrator.session_state import OrchestratorPhase
        agent = self._make_agent_at_searching()
        agent.process_turn("Find tech communities")
        assert agent.state.phase == OrchestratorPhase.RECOMMENDING

    def test_full_intake_to_search_flow(self):
        """
        Simulate a user who provides enough profile info on turn 1.
        The orchestrator should ask questions, then (once forced to search)
        return real DB results.
        """
        from community_matcher.orchestrator.orchestrator_agent import OrchestratorAgent
        from community_matcher.orchestrator.session_state import SessionState, OrchestratorPhase
        from community_matcher.domain.profile import UserProfile

        # Pre-populate a sufficient profile so orchestrator skips questioning
        profile = UserProfile(
            goals=["meet other developers", "join the AI community"],
            interests=["AI", "machine learning", "python"],
            social_mode="group",
        )
        state = SessionState(profile=profile, phase=OrchestratorPhase.SEARCHING)
        state.add_turn("user", "I want to find AI meetups in Berlin")
        agent = OrchestratorAgent(state=state)

        response = agent.process_turn("Please find me something")
        assert response
        assert agent.state.phase == OrchestratorPhase.RECOMMENDING

    def test_response_contains_urls_or_titles(self):
        """Results should mention at least a title or URL from the DB."""
        agent = self._make_agent_at_searching()
        response = agent.process_turn("Find python or data science meetups")
        # The response should include at least one real-looking URL or title
        has_url = "http" in response or "meetup.com" in response or "eventbrite" in response or "lu.ma" in response
        has_numbered = "1." in response or "Found" in response
        assert has_url or has_numbered, f"Response looks empty/generic: {response[:300]}"
