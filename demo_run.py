"""
End-to-end demo runner for CommunityMatcher.

Drives the OrchestratorAgent directly (no web server required) through
several synthetic persona conversations. Useful for finding breaks in the
full pipeline before/after any sprint.

Usage:
    python demo_run.py              # run all personas
    python demo_run.py --persona 0  # run only the first persona
    python demo_run.py --fast       # stop after 3 turns per persona

Environment variables required (same as the web app):
    CM_LLM_BASE_URL, CM_LLM_API_KEY, CM_LLM_MODEL
    CM_SQLITE_DB_PATH  (defaults to community_collector/output/communitymatcher.db)
"""
from __future__ import annotations

import argparse
import json
import sys
import textwrap
import time
from typing import NamedTuple

import structlog

log = structlog.get_logger()


# ---------------------------------------------------------------------------
# Synthetic personas
# ---------------------------------------------------------------------------

class Persona(NamedTuple):
    name: str
    description: str
    turns: list[str]


PERSONAS: list[Persona] = [
    Persona(
        name="Hardware Tinkerer",
        description="New to Berlin, wants to tinker with hardware — tests semantic fallback",
        turns=[
            "I just moved to Berlin and want to find people who tinker with hardware and electronics.",
            "I'd love to solder things or build robots. Prefer evenings.",
            "English is fine. I hate corporate networking events.",
            "Show me what you found.",
        ],
    ),
    Persona(
        name="AI Newcomer",
        description="Looking for AI/ML community, somewhat introverted, free events preferred",
        turns=[
            "I'm new here. I work in machine learning and want to meet others in AI.",
            "I prefer smaller groups, workshops over big conferences. Free if possible.",
            "Any weekday evenings work. I'm in Mitte.",
            "Go ahead and search.",
        ],
    ),
    Persona(
        name="Social Gamer",
        description="Wants friends via board games or casual hangouts, not tech-focused",
        turns=[
            "I want to find my people in Berlin. I'm into board games and just want to make friends.",
            "Nothing too corporate or alcohol-heavy. English-speaking preferred.",
            "Any neighbourhood is fine. Weekends work best.",
            "What do you have?",
            "These look too techy. I want something more casual.",
        ],
    ),
]


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

_SEP = "─" * 70


def _print_turn(role: str, content: str) -> None:
    label = "USER" if role == "user" else "AGENT"
    prefix = f"[{label}] "
    wrapped = textwrap.fill(content, width=80, subsequent_indent=" " * len(prefix))
    print(f"{prefix}{wrapped}")


def run_persona(persona: Persona, max_turns: int | None = None) -> dict:
    """Run one persona through the orchestrator. Returns final session state."""
    from community_matcher.orchestrator.orchestrator_agent import OrchestratorAgent
    from community_matcher.orchestrator.session_state import SessionState

    print(f"\n{_SEP}")
    print(f"PERSONA: {persona.name}")
    print(f"  {persona.description}")
    print(_SEP)

    state = SessionState()
    agent = OrchestratorAgent(state=state)

    turns = persona.turns if max_turns is None else persona.turns[:max_turns]
    results: list[dict] = []
    errors: list[str] = []

    for i, message in enumerate(turns):
        print(f"\nTurn {i + 1}/{len(turns)}")
        _print_turn("user", message)

        t0 = time.perf_counter()
        try:
            response = agent.process_turn(message)
            elapsed = round((time.perf_counter() - t0) * 1000)
            _print_turn("agent", response)
            print(f"  [phase={state.phase.value}  elapsed={elapsed}ms]")
            results.append({"turn": i + 1, "elapsed_ms": elapsed, "ok": True})
        except Exception as exc:
            elapsed = round((time.perf_counter() - t0) * 1000)
            msg = f"ERROR: {exc}"
            _print_turn("agent", msg)
            print(f"  [phase={state.phase.value}  elapsed={elapsed}ms  FAILED]")
            errors.append(str(exc))
            results.append({"turn": i + 1, "elapsed_ms": elapsed, "ok": False, "error": str(exc)})

    print(f"\n--- Profile after conversation ---")
    profile_dict = state.profile.model_dump()
    for field in ("goals", "interests", "social_mode", "environment", "language_pref", "dealbreakers"):
        val = profile_dict.get(field)
        if val:
            print(f"  {field}: {val}")

    print(f"\n--- Confidence ---")
    for field, conf in (profile_dict.get("field_confidence") or {}).items():
        print(f"  {field}: {conf}")

    print(f"\n--- Candidates in session: {len(state.candidates)} ---")
    if state.last_ranked_rows:
        print(f"  Last ranked DB rows: {len(state.last_ranked_rows)}")

    summary = {
        "persona": persona.name,
        "turns_run": len(turns),
        "errors": errors,
        "final_phase": state.phase.value,
        "candidates": len(state.candidates),
        "profile": {
            k: v for k, v in profile_dict.items()
            if v and k not in ("field_confidence", "logistics", "archetype_weights")
        },
    }
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="CommunityMatcher end-to-end demo")
    parser.add_argument("--persona", type=int, default=None, help="Run only persona N (0-based)")
    parser.add_argument("--fast", action="store_true", help="Run only 3 turns per persona")
    args = parser.parse_args()

    max_turns = 3 if args.fast else None
    personas = PERSONAS if args.persona is None else [PERSONAS[args.persona]]

    all_summaries: list[dict] = []
    for persona in personas:
        summary = run_persona(persona, max_turns=max_turns)
        all_summaries.append(summary)

    print(f"\n{'=' * 70}")
    print("DEMO SUMMARY")
    print('=' * 70)
    for s in all_summaries:
        status = "PASS" if not s["errors"] else f"FAIL ({len(s['errors'])} error(s))"
        print(f"  {s['persona']:<30} phase={s['final_phase']:<15} candidates={s['candidates']:<5} {status}")
        for e in s["errors"]:
            print(f"    error: {e}")

    has_errors = any(s["errors"] for s in all_summaries)
    print()
    if has_errors:
        print("Some runs had errors — see above.")
        sys.exit(1)
    else:
        print("All personas completed without errors.")


if __name__ == "__main__":
    main()
