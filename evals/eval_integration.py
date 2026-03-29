"""
Integration-level Strands Evals for CommunityMatcher.

Tests that components work together correctly:
- txt2sql_tool returns real results from the SQLite DB
- Orchestrator SEARCHING phase produces DB-backed responses
- DB layer rejects non-SELECT statements

Run:
    python evals/eval_integration.py
"""
from __future__ import annotations
import json
import sys
sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from pathlib import Path
from strands_evals.types import EvaluationData, EvaluationOutput
from strands_evals.evaluators import Evaluator

_DB = Path("community_collector/output/communitymatcher.db")

if not _DB.exists():
    print(f"ERROR: DB not found at {_DB}. Run the collector first.")
    sys.exit(1)


# ── Custom evaluators ─────────────────────────────────────────────────────────

class ReturnsResultsEvaluator(Evaluator):
    def __init__(self, min_results: int = 1):
        self.min_results = min_results

    def evaluate(self, data: EvaluationData) -> EvaluationOutput:
        try:
            rows = json.loads(str(data.actual_output))
        except Exception as exc:
            return EvaluationOutput(score=0.0, test_pass=False,
                                    reason=f"Not valid JSON: {exc}", label="fail")
        if isinstance(rows, dict) and "error" in rows:
            return EvaluationOutput(score=0.0, test_pass=False,
                                    reason=f"DB error: {rows}", label="error")
        if not isinstance(rows, list):
            return EvaluationOutput(score=0.0, test_pass=False,
                                    reason=f"Expected list, got {type(rows).__name__}", label="fail")
        n = len(rows)
        passes = n >= self.min_results
        return EvaluationOutput(
            score=min(1.0, n / max(self.min_results, 5)),
            test_pass=passes,
            reason=f"Returned {n} rows (min={self.min_results})",
            label="pass" if passes else "fail",
        )


class ResponseMentionsURLEvaluator(Evaluator):
    def evaluate(self, data: EvaluationData) -> EvaluationOutput:
        text = str(data.actual_output)
        has_url = any(kw in text for kw in ["http", "meetup.com", "eventbrite", "lu.ma"])
        has_result = "Found" in text or "1." in text
        passes = has_url or has_result
        return EvaluationOutput(
            score=1.0 if passes else 0.0,
            test_pass=passes,
            reason="has URLs/numbered results" if passes else "empty/generic response",
            label="pass" if passes else "fail",
        )


# ── Test functions ─────────────────────────────────────────────────────────────

def run_db_layer_evals():
    print("\n=== DB Layer Evals ===")
    from community_matcher.db.connection import execute_query

    cases = [
        ("SELECT COUNT(*) AS n FROM community",          "community-count",        lambda r: r[0]["n"] >= 100),
        ("SELECT title FROM scrape_record LIMIT 10",     "scrape-titles",          lambda r: len(r) == 10 and all(row["title"] for row in r)),
        ("SELECT COUNT(*) AS n FROM kw_affinity",        "kw-affinity-populated",  lambda r: r[0]["n"] >= 1000),
        ("SELECT COUNT(DISTINCT source_url) AS n FROM scrape_record", "unique-urls", lambda r: r[0]["n"] >= 100),
    ]

    for sql, name, check in cases:
        try:
            rows = execute_query(sql, db_path=_DB)
            passes = check(rows)
            status = "PASS" if passes else "FAIL"
            detail = rows[0] if rows else "no rows"
            print(f"  [{status}] {name}: {detail}")
        except Exception as exc:
            print(f"  [ERROR] {name}: {exc}")

    # Security guard
    try:
        execute_query("DELETE FROM community WHERE 1=1")
        print("  [FAIL] select-guard: DELETE was allowed!")
    except ValueError:
        print("  [PASS] select-guard: ValueError raised for DELETE")


def run_txt2sql_integration_evals():
    print("\n=== txt2sql Integration Evals ===")
    from community_matcher.agents.txt2sql_agent import txt2sql_tool

    cases = [
        ("Find AI or tech meetups",                           "ai-tech-query",     1),
        ("Find startup or entrepreneurship networking events", "startup-query",     1),
        ("Show workshops and learning events",                 "workshop-query",    0),  # may be 0 - ok
        ("List events from meetup.com",                       "meetup-source",     1),
    ]

    for question, name, min_results in cases:
        try:
            result = txt2sql_tool(question)
            ev = ReturnsResultsEvaluator(min_results=min_results)
            eval_result = ev.evaluate(EvaluationData(input=question, actual_output=result))
            status = "PASS" if eval_result.test_pass else "FAIL"
            print(f"  [{status}] {name}: {eval_result.reason}")
            if eval_result.test_pass:
                rows = json.loads(result)
                if rows:
                    sample = rows[0].get("title") or rows[0].get("name") or str(rows[0])
                    print(f"          Sample: {str(sample)[:70]}")
        except Exception as exc:
            print(f"  [ERROR] {name}: {exc}")


def run_orchestrator_searching_evals():
    print("\n=== Orchestrator Searching Phase Evals ===")
    from community_matcher.orchestrator.orchestrator_agent import OrchestratorAgent
    from community_matcher.orchestrator.session_state import SessionState, OrchestratorPhase
    from community_matcher.domain.profile import UserProfile

    cases = [
        (["ai"],               "Find AI events for me",                    "ai-search"),
        (["python"],           "Find Python or data science meetups",       "python-search"),
        (["startup"],          "I want startup networking events",          "startup-search"),
        ([],                   "I'm new here, find beginner-friendly events","newcomer-search"),
    ]

    ev = ResponseMentionsURLEvaluator()

    for interests, user_input, name in cases:
        try:
            profile = UserProfile(interests=interests)
            state = SessionState(profile=profile, phase=OrchestratorPhase.SEARCHING)
            state.add_turn("user", user_input)
            agent = OrchestratorAgent(state=state)
            response = agent.process_turn(user_input)

            eval_result = ev.evaluate(EvaluationData(input=user_input, actual_output=response))
            status = "PASS" if eval_result.test_pass else "FAIL"
            print(f"  [{status}] {name}: {eval_result.reason}")
            print(f"          Response[:100]: {response[:100]}")
        except Exception as exc:
            print(f"  [ERROR] {name}: {exc}")


if __name__ == "__main__":
    run_db_layer_evals()
    run_txt2sql_integration_evals()
    run_orchestrator_searching_evals()
    print("\nIntegration evals complete.")
