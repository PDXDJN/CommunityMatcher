from __future__ import annotations
import logging
import structlog
from community_matcher.orchestrator.orchestrator_agent import OrchestratorAgent
from community_matcher.orchestrator.session_state import SessionState

structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.INFO))
log = structlog.get_logger()

BANNER = """
===========================================
  CommunityMatcher — Find Your People
===========================================
Type 'quit' or 'exit' to end the session.
-------------------------------------------
"""


def run_conversation_loop() -> None:
    """Interactive CLI conversation loop."""
    print(BANNER)

    state = SessionState()
    orchestrator = OrchestratorAgent(state=state)

    log.info("app.session_start", session_id=state.session_id)

    print("Assistant: Hello! Tell me a bit about what kind of community you're looking for.")
    print()

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not user_input:
            continue

        if user_input.lower() in ("quit", "exit", "q"):
            print("Assistant: Thanks for using CommunityMatcher. Good luck finding your people!")
            break

        response = orchestrator.process_turn(user_input)
        print(f"\nAssistant: {response}\n")
        log.info("app.turn_complete", phase=state.phase.value)
