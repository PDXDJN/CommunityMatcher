"""
End-to-End Strands Evals for CommunityMatcher.

Simulates complete user conversations from intake through to recommendations,
evaluating the full orchestrator pipeline including:
- Phase transitions (INTAKE → QUESTIONING → SEARCHING → RECOMMENDING)
- Profile signal accumulation over multiple turns
- Real DB results in final recommendations

Run:
    python evals/eval_e2e.py
"""
from __future__ import annotations
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

class ReachesRecommendingEvaluator(Evaluator):
    """Passes if the orchestrator reaches RECOMMENDING within max_turns."""

    def __init__(self, max_turns: int = 6):
        self.max_turns = max_turns

    def evaluate(self, data: EvaluationData) -> EvaluationOutput:
        final_phase, turns = data.actual_output
        reached = final_phase == "recommending"
        efficiency = max(0.0, 1.0 - turns / self.max_turns)
        score = (1.0 if reached else 0.0) * 0.7 + efficiency * 0.3
        return EvaluationOutput(
            score=score,
            test_pass=reached,
            reason=f"phase={final_phase} after {turns} turns",
            label="pass" if reached else "loop",
        )


class RecommendationQualityEvaluator(Evaluator):
    """Scores the final response on URL presence, result count, no errors."""

    def evaluate(self, data: EvaluationData) -> EvaluationOutput:
        text = str(data.actual_output)
        has_url = any(kw in text for kw in ["http", "meetup.com", "eventbrite", "lu.ma"])
        has_items = "Found" in text or any(f"{i}." in text for i in range(1, 6))
        no_error = "[search failed" not in text and "[search error" not in text
        score = 0.4 * has_url + 0.4 * has_items + 0.2 * no_error
        passes = score >= 0.4
        return EvaluationOutput(
            score=score,
            test_pass=passes,
            reason=f"url={has_url} items={has_items} no_error={no_error}",
            label="pass" if passes else "fail",
        )


# ── E2E Scenarios ─────────────────────────────────────────────────────────────

SCENARIOS = [
    {
        "name":        "new-to-berlin-tech",
        "description": "Classic newcomer looking for tech community",
        "turns": [
            "I'm new to Berlin and want to find my people. I'm into tech and AI.",
            "mostly for friends, nerdy stuff. love workshops and talks.",
        ],
    },
    {
        "name":        "startup-founder",
        "description": "Startup founder seeking professional networking",
        "turns": [
            "I'm a founder looking to network with other entrepreneurs.",
            "professional networking events, not too casual.",
        ],
    },
    {
        "name":        "python-developer",
        "description": "Developer seeking skill-building community",
        "turns": [
            "I'm a Python developer and want to improve my skills.",
            "workshops and project nights with other coders",
        ],
    },
    {
        "name":        "social-newcomer",
        "description": "Newcomer seeking social/fun community",
        "turns": [
            "Just moved here. Looking for fun social events with cool people.",
            "nerdy but social. games, drinks, maybe some maker stuff.",
        ],
    },
]


def run_conversation(turns: list[str]) -> tuple[str, str, int]:
    """Return (final_phase, last_response, turn_count)."""
    from community_matcher.orchestrator.orchestrator_agent import OrchestratorAgent

    agent = OrchestratorAgent()
    last_response = ""
    count = 0

    for turn in turns:
        last_response = agent.process_turn(turn)
        count += 1
        if agent.state.phase.value == "recommending":
            break

    # Force search if still stuck
    if agent.state.phase.value not in ("recommending",):
        last_response = agent.process_turn("please find something for me now")
        count += 1

    return agent.state.phase.value, last_response, count


def run_e2e_evals():
    print("\n=== E2E Conversation Evals ===")

    phase_ev = ReachesRecommendingEvaluator(max_turns=6)
    quality_ev = RecommendationQualityEvaluator()

    passed = 0
    total = len(SCENARIOS)

    for s in SCENARIOS:
        print(f"\n  Scenario: {s['name']} — {s['description']}")
        try:
            final_phase, last_response, turns = run_conversation(s["turns"])

            phase_result = phase_ev.evaluate(
                EvaluationData(input=s["turns"][0], actual_output=(final_phase, turns))
            )
            quality_result = quality_ev.evaluate(
                EvaluationData(input=s["turns"][0], actual_output=last_response)
            )

            ok = phase_result.test_pass and quality_result.score >= 0.4
            if ok:
                passed += 1
            status = "PASS" if ok else "FAIL"

            print(f"  [{status}] Phase:   {phase_result.reason} (score={phase_result.score:.2f})")
            print(f"         Quality: {quality_result.reason} (score={quality_result.score:.2f})")
            print(f"         Response: {last_response[:150]}")

        except Exception as exc:
            print(f"  [ERROR] {s['name']}: {exc}")
            total -= 0  # count as fail but don't crash

    print(f"\n=== E2E Summary: {passed}/{total} scenarios passed ===")


def run_profile_accumulation_evals():
    """Verify multi-turn profile signals accumulate correctly."""
    print("\n=== Profile Accumulation E2E ===")

    from community_matcher.orchestrator.orchestrator_agent import OrchestratorAgent

    cases = [
        {
            "name":     "interests-from-turns",
            "turns":    ["I love AI and machine learning", "I want to meet friends and nerdy people"],
            "check_fn": lambda p: "ai" in p.interests,
            "desc":     "interests should contain 'ai'",
        },
        {
            "name":     "social-mode-extracted",
            "turns":    ["I like casual drinks and social hangouts"],
            "check_fn": lambda p: p.social_mode == "social",
            "desc":     "social_mode should be 'social'",
        },
        {
            "name":     "goals-extracted",
            "turns":    ["I want to make friends and have fun with nerdy people"],
            "check_fn": lambda p: "friends" in p.goals,
            "desc":     "goals should contain 'friends'",
        },
        {
            "name":     "multi-turn-accumulation",
            "turns":    ["I'm into python and data science", "I want to meet friends at workshops"],
            "check_fn": lambda p: "python" in p.interests and "friends" in p.goals,
            "desc":     "both python (interests) and friends (goals) should be set",
        },
    ]

    for c in cases:
        agent = OrchestratorAgent()
        for turn in c["turns"]:
            agent.process_turn(turn)
        profile = agent.state.profile
        try:
            passes = c["check_fn"](profile)
        except Exception:
            passes = False
        status = "PASS" if passes else "FAIL"
        print(f"  [{status}] {c['name']}: {c['desc']}")
        print(f"          interests={profile.interests} goals={profile.goals} social_mode={profile.social_mode!r}")


if __name__ == "__main__":
    run_profile_accumulation_evals()
    run_e2e_evals()
    print("\nE2E evals complete.")
