"""
Unit-level Strands Evals for CommunityMatcher.

Tests individual components in isolation:
- Profile sufficiency scoring
- Question selection logic
- txt2sql SQL generation correctness
- Profile keyword extraction

Run:
    python evals/eval_unit.py
"""
from __future__ import annotations
import sys
sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from strands_evals.types import EvaluationData, EvaluationOutput
from strands_evals.evaluators import Evaluator


# ── Custom evaluators ─────────────────────────────────────────────────────────

class SufficiencyScoreEvaluator(Evaluator):
    def __init__(self, expected: float, tolerance: float = 0.01):
        self.expected = expected
        self.tolerance = tolerance

    def evaluate(self, data: EvaluationData) -> EvaluationOutput:
        actual = float(data.actual_output)
        passes = abs(actual - self.expected) <= self.tolerance
        return EvaluationOutput(
            score=1.0 if passes else 0.0,
            test_pass=passes,
            reason=f"score={actual:.2f} (expected {self.expected:.2f})",
            label="pass" if passes else "fail",
        )


class IsSQLSelectEvaluator(Evaluator):
    def evaluate(self, data: EvaluationData) -> EvaluationOutput:
        sql = str(data.actual_output).strip()
        is_select = sql.upper().startswith("SELECT")
        has_limit = "LIMIT" in sql.upper()
        no_fence = "```" not in sql
        passes = is_select and has_limit and no_fence
        reasons = []
        if not is_select: reasons.append("not SELECT")
        if not has_limit: reasons.append("no LIMIT")
        if not no_fence: reasons.append("markdown fences")
        return EvaluationOutput(
            score=1.0 if passes else 0.0,
            test_pass=passes,
            reason="; ".join(reasons) if reasons else "valid SELECT with LIMIT",
            label="pass" if passes else "fail",
        )


class ProfileFieldEvaluator(Evaluator):
    def __init__(self, expected: list[str]):
        self.expected = expected

    def evaluate(self, data: EvaluationData) -> EvaluationOutput:
        actual = data.actual_output
        found = [e for e in self.expected if e in actual]
        score = len(found) / len(self.expected) if self.expected else 1.0
        passes = score >= 0.5
        return EvaluationOutput(
            score=score,
            test_pass=passes,
            reason=f"found={found} of expected={self.expected}",
            label="pass" if passes else "fail",
        )


# ── Tests ─────────────────────────────────────────────────────────────────────

def run_sufficiency_evals():
    print("\n=== Sufficiency Scorer Evals ===")
    from community_matcher.orchestrator.sufficiency import check_sufficiency
    from community_matcher.domain.profile import UserProfile

    # Expected scores use confidence-weighted formula (Sprint 2).
    # Profiles built without confidence metadata get 0.7 credit per field (benefit of doubt).
    # Weights: goals=0.30, interests=0.30, social_mode=0.25, logistics=0.15
    cases = [
        (UserProfile(),                                                                    0.0,   "empty-profile"),
        (UserProfile(goals=["friends"]),                                                   0.21,  "goals-only"),
        (UserProfile(goals=["friends"], interests=["ai"]),                                 0.42,  "goals-interests"),
        (UserProfile(goals=["friends"], interests=["ai"], social_mode="social"),           0.595, "three-fields"),
        (UserProfile(goals=["friends"], interests=["ai"], social_mode="social",
                     logistics={"districts": ["mitte"]}),                                  0.7,   "fully-sufficient"),
    ]

    for profile, expected_score, name in cases:
        actual = check_sufficiency(profile).score
        ev = SufficiencyScoreEvaluator(expected_score)
        result = ev.evaluate(EvaluationData(input=name, actual_output=actual))
        status = "PASS" if result.test_pass else "FAIL"
        print(f"  [{status}] {name}: {result.reason}")


def run_question_selection_evals():
    print("\n=== Question Selection Evals ===")
    from community_matcher.orchestrator.question_selection import select_next_questions
    from community_matcher.domain.profile import UserProfile

    cases = [
        (["primary_goal", "interest_cluster", "social_mode", "logistics"], 3, 3,  "all-missing-max3"),
        (["primary_goal"],                                                  3, 1,  "one-missing"),
        ([],                                                                3, 0,  "none-missing"),
        (["primary_goal", "interest_cluster", "social_mode"],               2, 2,  "max-respected"),
    ]

    for missing, max_q, expected_count, name in cases:
        questions = select_next_questions(UserProfile(), missing, max_q)
        actual = len(questions)
        passes = actual == expected_count
        status = "PASS" if passes else "FAIL"
        print(f"  [{status}] {name}: returned {actual} questions (expected {expected_count})")


def run_profile_extraction_evals():
    print("\n=== Profile Keyword Extraction Evals ===")
    from community_matcher.orchestrator.orchestrator_agent import _extract_profile_signals
    from community_matcher.domain.profile import UserProfile

    cases = [
        ("I'm really into AI and machine learning",                   ["ai"],                    "ai-interest"),
        ("mostly looking for friends and fun people to hang out with", ["friends"],               "friends-goal"),
        ("I love casual drinks and social events",                    ["social"],                 "social-mode"),
        ("nerdy tech people doing technical stuff",                   ["tech"],                   "nerdy-tech"),
        ("I want to learn Python with friends at workshops",          ["python", "friends"],      "multi-signal"),
    ]

    for text, expected, name in cases:
        profile = UserProfile()
        _extract_profile_signals(text, profile)
        all_extracted = profile.interests + profile.goals + (
            [profile.social_mode] if profile.social_mode else []
        )
        ev = ProfileFieldEvaluator(expected)
        result = ev.evaluate(EvaluationData(input=text, actual_output=all_extracted))
        status = "PASS" if result.test_pass else "FAIL"
        print(f"  [{status}] {name}: {result.reason}")


def run_sql_generation_evals():
    print("\n=== SQL Generation Evals (requires Ollama) ===")
    from community_matcher.agents.txt2sql_agent import _generate_sql

    questions = [
        ("Find AI meetups in Berlin",                "ai-meetups"),
        ("List free community events",               "free-events"),
        ("Find startup networking events",           "startup-network"),
        ("Show Python workshops",                    "python-workshops"),
        ("Find beginner-friendly events",            "newcomer-events"),
    ]

    ev = IsSQLSelectEvaluator()
    for question, name in questions:
        try:
            sql = _generate_sql(question)
            result = ev.evaluate(EvaluationData(input=question, actual_output=sql))
            status = "PASS" if result.test_pass else "FAIL"
            print(f"  [{status}] {name}: {result.reason}")
            print(f"          SQL: {sql[:100]}")
        except Exception as exc:
            print(f"  [ERROR] {name}: {exc}")


def run_field_confidence_evals():
    print("\n=== FieldConfidence Tracking Evals ===")
    from community_matcher.orchestrator.orchestrator_agent import (
        _extract_profile_signals,
        _apply_profile_updates,
    )
    from community_matcher.domain.profile import UserProfile, FieldConfidence

    # Keyword extraction should produce INFERRED_LOW
    profile = UserProfile()
    _extract_profile_signals("I love AI and machine learning", profile)
    conf = profile.field_confidence.get("interests")
    ok = conf == FieldConfidence.INFERRED_LOW
    print(f"  [{'PASS' if ok else 'FAIL'}] keyword → INFERRED_LOW: interests confidence={conf}")

    # LLM explicit extraction should produce EXPLICIT (upgrading from INFERRED_LOW)
    _apply_profile_updates(profile, {
        "goals": ["friends"],
        "_confidence": {"goals": "explicit"},
    })
    conf_goals = profile.field_confidence.get("goals")
    ok2 = conf_goals == FieldConfidence.EXPLICIT
    print(f"  [{'PASS' if ok2 else 'FAIL'}] llm explicit → EXPLICIT: goals confidence={conf_goals}")

    # LLM inferred extraction should produce INFERRED_HIGH
    profile2 = UserProfile()
    _apply_profile_updates(profile2, {
        "social_mode": "social",
        "_confidence": {"social_mode": "inferred"},
    })
    conf_sm = profile2.field_confidence.get("social_mode")
    ok3 = conf_sm == FieldConfidence.INFERRED_HIGH
    print(f"  [{'PASS' if ok3 else 'FAIL'}] llm inferred → INFERRED_HIGH: social_mode confidence={conf_sm}")

    # LLM explicit should NOT be downgraded by later keyword extraction
    profile3 = UserProfile()
    _apply_profile_updates(profile3, {
        "interests": ["startup"],
        "_confidence": {"interests": "explicit"},
    })
    _extract_profile_signals("startup founder", profile3)  # keyword fires again
    conf_after = profile3.field_confidence.get("interests")
    ok4 = conf_after == FieldConfidence.EXPLICIT  # must not downgrade
    print(f"  [{'PASS' if ok4 else 'FAIL'}] explicit not downgraded by keyword: interests={conf_after}")


def run_sufficiency_confidence_evals():
    print("\n=== Confidence-Weighted Sufficiency Evals ===")
    from community_matcher.orchestrator.sufficiency import check_sufficiency
    from community_matcher.domain.profile import UserProfile, FieldConfidence

    # Fully explicit profile → should be sufficient
    p_full = UserProfile(
        goals=["friends"], interests=["ai"], social_mode="social",
        logistics={"districts": ["mitte"]},
    )
    p_full.field_confidence = {
        "goals": FieldConfidence.EXPLICIT,
        "interests": FieldConfidence.EXPLICIT,
        "social_mode": FieldConfidence.EXPLICIT,
        "logistics": FieldConfidence.EXPLICIT,
    }
    r = check_sufficiency(p_full)
    ok = r.is_sufficient and r.score >= 0.95
    print(f"  [{'PASS' if ok else 'FAIL'}] fully-explicit sufficient: score={r.score:.2f}")

    # All INFERRED_LOW → below threshold
    p_low = UserProfile(
        goals=["friends"], interests=["ai"], social_mode="social",
        logistics={"districts": ["mitte"]},
    )
    p_low.field_confidence = {
        "goals": FieldConfidence.INFERRED_LOW,
        "interests": FieldConfidence.INFERRED_LOW,
        "social_mode": FieldConfidence.INFERRED_LOW,
        "logistics": FieldConfidence.INFERRED_LOW,
    }
    r_low = check_sufficiency(p_low)
    ok2 = not r_low.is_sufficient  # 0.5 * each → ~0.5, below 0.65 threshold
    print(f"  [{'PASS' if ok2 else 'FAIL'}] all-inferred-low insufficient: score={r_low.score:.2f}")

    # Empty profile → score 0 and not sufficient
    r_empty = check_sufficiency(UserProfile())
    ok3 = not r_empty.is_sufficient and r_empty.score == 0.0
    print(f"  [{'PASS' if ok3 else 'FAIL'}] empty profile: score={r_empty.score:.2f}")


def run_logistics_scoring_evals():
    print("\n=== District-Aware Logistics Scoring Evals ===")
    from community_matcher.agents.ranking_agent import _logistics_fit, _parse_tags

    # User wants Mitte — candidate mentions Mitte → 1.0
    score1 = _logistics_fit({"districts": ["mitte"]}, [], "Coding meetup in Mitte, Berlin")
    ok1 = score1 == 1.0
    print(f"  [{'PASS' if ok1 else 'FAIL'}] district match → 1.0: score={score1}")

    # User wants Kreuzberg — candidate in Prenzlauer Berg → 0.45
    score2 = _logistics_fit({"districts": ["kreuzberg"]}, [], "Startup night in Prenzlauer Berg")
    ok2 = score2 == 0.45
    print(f"  [{'PASS' if ok2 else 'FAIL'}] known district no-match → 0.45: score={score2}")

    # User wants Mitte — online event → 0.6
    score3 = _logistics_fit({"districts": ["mitte"]}, ["online"], "Online AI workshop")
    ok3 = score3 == 0.6
    print(f"  [{'PASS' if ok3 else 'FAIL'}] online event → 0.6: score={score3}")

    # No district preference → 0.7 neutral
    score4 = _logistics_fit({}, [], "Some event somewhere")
    ok4 = score4 == 0.7
    print(f"  [{'PASS' if ok4 else 'FAIL'}] no preference → 0.7: score={score4}")

    # User wants district — candidate has no location signal → 0.4
    score5 = _logistics_fit({"districts": ["mitte"]}, [], "Tech meetup at our office")
    ok5 = score5 == 0.4
    print(f"  [{'PASS' if ok5 else 'FAIL'}] no location signal → 0.4: score={score5}")


def run_feedback_signal_evals():
    print("\n=== Feedback Signal Parsing Evals ===")
    from community_matcher.orchestrator.orchestrator_agent import (
        _parse_feedback_signals, _wants_research,
    )
    from community_matcher.domain.profile import UserProfile

    cases = [
        ("too corporate, I hate suits",   "dealbreakers", "corporate",  True,  "corporate-dealbreaker"),
        ("it was too loud",               "dealbreakers", "loud",        True,  "loud-dealbreaker"),
        ("I want more technical events",  "social_mode",  "workshop",    True,  "technical-social-mode"),
        ("free events only please",       "budget",       "free_only",   True,  "free-budget"),
        ("I prefer english events",       "language_pref","english",     True,  "english-lang"),
        ("looks great, no changes",       None,           None,          False, "no-change"),
    ]

    for text, field, value, expected_changed, name in cases:
        profile = UserProfile()
        changed = _parse_feedback_signals(text, profile)
        if expected_changed:
            if field == "dealbreakers":
                ok = changed and value in profile.dealbreakers
            elif field == "social_mode":
                ok = changed and profile.social_mode == value
            elif field == "budget":
                ok = changed and str(profile.budget) in (value, f"BudgetSensitivity.{value.upper()}")
            elif field == "language_pref":
                ok = changed and value in profile.language_pref
            else:
                ok = changed
        else:
            ok = not changed
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")

    # _wants_research tests
    print("  --- _wants_research ---")
    assert _wants_research("find me something different") is True
    print("  [PASS] 'find me something different' → True")
    assert _wants_research("too corporate") is False
    print("  [PASS] 'too corporate' → False")


if __name__ == "__main__":
    run_sufficiency_evals()
    run_question_selection_evals()
    run_profile_extraction_evals()
    run_sql_generation_evals()
    run_field_confidence_evals()
    run_sufficiency_confidence_evals()
    run_logistics_scoring_evals()
    run_feedback_signal_evals()
    print("\nUnit evals complete.")
