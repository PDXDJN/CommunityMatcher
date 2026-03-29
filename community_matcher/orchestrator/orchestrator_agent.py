from __future__ import annotations
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import structlog
from community_matcher.orchestrator.session_state import SessionState, OrchestratorPhase
from community_matcher.orchestrator.sufficiency import check_sufficiency
from community_matcher.orchestrator.question_selection import select_next_questions
from community_matcher.config.settings import settings
from community_matcher.domain.profile import FieldConfidence
from community_matcher.agents.profile_builder_agent import profile_builder_tool
from community_matcher.agents.question_planner_agent import question_planner_tool
from community_matcher.agents.archetype_agent import archetype_tool
from community_matcher.agents.search_planner_agent import search_planner_tool
from community_matcher.agents.ranking_agent import ranking_tool
from community_matcher.agents.recommendation_writer_agent import recommendation_writer_tool
from community_matcher.agents.txt2sql_agent import txt2sql_tool
from community_matcher.agents.vibe_classifier_agent import vibe_classifier_tool
from community_matcher.agents.risk_sanity_agent import risk_sanity_tool

log = structlog.get_logger()


# ── Lightweight keyword-based profile extraction (fast fallback) ──────────────

_INTEREST_KEYWORDS: dict[str, list[str]] = {
    "ai":            ["ai", "artificial intelligence", "machine learning", "llm", "gpt"],
    "python":        ["python"],
    "data_science":  ["data science", "data engineering", "analytics"],
    "startup":       ["startup", "founder", "entrepreneurship", "venture"],
    "gaming":        ["gaming", "games", "esports", "game dev"],
    "maker":         ["maker", "hardware", "arduino", "3d print", "robot"],
    "cybersecurity": ["security", "ctf", "hacking", "infosec"],
    "design":        ["design", "ux", "ui", "product design"],
    "cloud":         ["cloud", "devops", "kubernetes", "aws", "azure"],
    "blockchain":    ["blockchain", "crypto", "web3"],
    "music":         ["music", "concert", "dj"],
    "art":           ["art", "gallery", "exhibition"],
    "fitness":       ["fitness", "run", "yoga", "sport"],
    "tech":          ["nerdy", "nerd", "geek", "geeky", "tech"],
}

_GOAL_KEYWORDS: dict[str, list[str]] = {
    "friends":    ["friend", "friendship", "people", "fun", "hang out", "hang"],
    "networking": ["network", "professional", "career", "job", "connect"],
    "learning":   ["learn", "workshop", "study", "course", "skill"],
    "community":  ["community", "community building", "belong", "join"],
}

_SOCIAL_KEYWORDS: dict[str, list[str]] = {
    "workshop":   ["workshop", "hands-on", "hands on", "build"],
    "talk":       ["talk", "lecture", "presentation", "speaker"],
    "social":     ["drinks", "casual", "social", "hangout", "hang out", "fun"],
    "project":    ["project", "hack", "build", "maker night"],
    "conference": ["conference", "summit", "convention"],
}


def _extract_profile_signals(text: str, profile) -> bool:
    """Keyword scan — supplements LLM extraction. Returns True if changed.
    Fields extracted here are marked INFERRED_LOW (keyword match is less reliable)."""
    t = text.lower()
    changed = False
    for tag, kws in _INTEREST_KEYWORDS.items():
        if any(kw in t for kw in kws) and tag not in profile.interests:
            profile.interests.append(tag)
            # Only set INFERRED_LOW if no higher confidence already recorded
            if profile.field_confidence.get("interests") not in (
                FieldConfidence.EXPLICIT, FieldConfidence.INFERRED_HIGH
            ):
                profile.field_confidence["interests"] = FieldConfidence.INFERRED_LOW
            changed = True
    for goal, kws in _GOAL_KEYWORDS.items():
        if any(kw in t for kw in kws) and goal not in profile.goals:
            profile.goals.append(goal)
            if profile.field_confidence.get("goals") not in (
                FieldConfidence.EXPLICIT, FieldConfidence.INFERRED_HIGH
            ):
                profile.field_confidence["goals"] = FieldConfidence.INFERRED_LOW
            changed = True
    if profile.social_mode is None:
        for mode, kws in _SOCIAL_KEYWORDS.items():
            if any(kw in t for kw in kws):
                profile.social_mode = mode
                profile.field_confidence["social_mode"] = FieldConfidence.INFERRED_LOW
                changed = True
                break
    return changed


_LLM_CONFIDENCE_MAP = {
    "explicit": FieldConfidence.EXPLICIT,
    "inferred": FieldConfidence.INFERRED_HIGH,
}


def _apply_profile_updates(profile, updates: dict) -> None:
    """Merge LLM-extracted field updates into the profile in-place.
    Reads optional '_confidence' dict from updates and records per-field confidence."""
    llm_confidence: dict[str, str] = updates.get("_confidence", {})

    def _set_confidence(field: str) -> None:
        """Upgrade field_confidence to at least LLM-inferred level."""
        raw = llm_confidence.get(field, "inferred")
        new_conf = _LLM_CONFIDENCE_MAP.get(raw, FieldConfidence.INFERRED_HIGH)
        current = profile.field_confidence.get(field)
        # Only upgrade, never downgrade
        precedence = [FieldConfidence.UNKNOWN, FieldConfidence.INFERRED_LOW,
                      FieldConfidence.INFERRED_HIGH, FieldConfidence.EXPLICIT]
        if current is None or precedence.index(new_conf) > precedence.index(current):
            profile.field_confidence[field] = new_conf

    for key, value in updates.items():
        if key == "_confidence":
            continue
        if key == "goals" and isinstance(value, list):
            for g in value:
                if g not in profile.goals:
                    profile.goals.append(g)
            _set_confidence("goals")
        elif key == "interests" and isinstance(value, list):
            for i in value:
                if i not in profile.interests:
                    profile.interests.append(i)
            _set_confidence("interests")
        elif key == "social_mode" and value and profile.social_mode is None:
            profile.social_mode = value
            _set_confidence("social_mode")
        elif key == "environment" and value and profile.environment is None:
            profile.environment = value
            _set_confidence("environment")
        elif key == "language_pref" and isinstance(value, list):
            for lp in value:
                if lp not in profile.language_pref:
                    profile.language_pref.append(lp)
            _set_confidence("language_pref")
        elif key == "budget" and value:
            profile.budget = value
            _set_confidence("budget")
        elif key == "values" and isinstance(value, list):
            for v in value:
                if v not in profile.values:
                    profile.values.append(v)
            _set_confidence("values")
        elif key == "dealbreakers" and isinstance(value, list):
            for d in value:
                if d not in profile.dealbreakers:
                    profile.dealbreakers.append(d)
            _set_confidence("dealbreakers")
        elif key == "logistics" and isinstance(value, dict):
            if "districts" in value:
                profile.logistics.districts = value["districts"]
            if "max_travel_minutes" in value and value["max_travel_minutes"]:
                profile.logistics.max_travel_minutes = int(value["max_travel_minutes"])
            _set_confidence("logistics")


def _enrich_profile_from_turn(text: str, profile) -> None:
    """Run LLM profile_builder_tool then keyword extraction as fallback."""
    # Keyword extraction (fast, always runs)
    _extract_profile_signals(text, profile)

    # LLM extraction (richer, may fail silently)
    try:
        updates_json = _agent_call("profile_builder_tool", profile_builder_tool, text)
        updates = json.loads(updates_json)
        if updates:
            _apply_profile_updates(profile, updates)
    except Exception as exc:
        log.debug("orchestrator.profile_builder_skipped", error=str(exc))


# ── Valid DB tags ─────────────────────────────────────────────────────────────

_VALID_DB_TAGS = {
    "ai", "python", "data_science", "startup", "cloud", "cybersecurity",
    "blockchain", "maker", "design", "gaming", "social_coding",
    "language_exchange", "music", "art", "fitness", "wellness",
    "networking", "community", "tech",
    "workshop", "talk", "conference", "hackathon", "demo_night",
    "barcamp", "coworking", "social", "seminar", "meetup_event", "panel",
    "beginner_friendly", "newcomer_city", "english_friendly", "lgbtq_friendly",
    "after_work", "free", "paid", "online", "in_person", "grassroots",
    "technical", "casual", "career_oriented",
}


def _build_search_query(state: SessionState) -> str:
    """Derive a natural language DB query from session context."""
    profile = state.profile
    parts: list[str] = []

    valid_interests = [i for i in profile.interests if i in _VALID_DB_TAGS]
    if valid_interests:
        parts.append(f"topic tags (use OR between them): {', '.join(valid_interests[:4])}")

    user_turns = [t["content"] for t in state.conversation_history if t["role"] == "user"]
    if user_turns:
        parts.append(f"user said: {user_turns[0][:120]}")

    if not parts:
        return "Find tech communities and events in Berlin"

    return "Find communities or events matching: " + "; ".join(parts)


# ── Live-search fallback ─────────────────────────────────────────────────────

def _build_live_search_terms(
    state: SessionState, query_intents: list[str] | None = None
) -> list[str]:
    """Derive search terms for a live collection run from query intents + profile."""
    profile = state.profile
    terms: list[str] = list(query_intents or [])

    if len(terms) < 3:
        for interest in profile.interests[:4]:
            t = interest.replace("_", " ")
            if t not in terms:
                terms.append(t)
        for goal in profile.goals[:2]:
            if goal == "friends":
                terms.append("social community Berlin")
            elif goal == "networking":
                terms.append("networking Berlin")
            elif goal == "learning":
                terms.append("workshop Berlin")
        if profile.social_mode in ("workshop", "talk", "project"):
            t = f"{profile.social_mode} Berlin"
            if t not in terms:
                terms.append(t)

    if not terms:
        user_turns = [t["content"] for t in state.conversation_history if t["role"] == "user"]
        terms = [user_turns[0][:60]] if user_turns else ["tech community Berlin"]

    return terms[:6]


def _run_live_collection(
    state: SessionState, query_intents: list[str] | None = None
) -> str | None:
    """
    Trigger a focused live scrape when the DB has no matching results.

    Primary path: calls the collector via its MCP server (isolated subprocess,
    no Playwright event-loop conflicts with the FastAPI server).

    Fallback: direct module import (for CLI / non-server usage).

    Returns a preamble string to prepend to the recommendation output, or None on error.
    """
    terms = _build_live_search_terms(state, query_intents)
    log.info("orchestrator.live_search", terms=terms)

    # Primary: MCP client (decoupled subprocess)
    try:
        from community_matcher.tools.collector_mcp_client import live_search
        result = live_search(terms, max_results=30, print_progress=True)
        if result is not None:
            return result
        log.debug("orchestrator.mcp_live_returned_none_fallback")
    except Exception as exc:
        log.debug("orchestrator.mcp_client_unavailable", error=str(exc))

    # Fallback: direct import (CLI mode / tests)
    try:
        from community_collector.orchestrator import run_collection
        from community_collector.config import CollectorConfig

        print(
            "\n[Searching live — nothing found in local database. "
            "This may take 1-2 minutes...]\n",
            flush=True,
        )
        cfg = CollectorConfig(
            search_terms=terms,
            sources_to_run=["meetup", "luma"],
            max_results_per_source=30,
            headless=True,
            db_path=settings.sqlite_db_path,
        )
        run_collection(cfg)
        return (
            "I couldn't find much in my local database, so I did a live search — "
            "this took a few minutes but here's what I found:\n\n"
        )
    except Exception as exc:
        log.warning("orchestrator.live_search_failed", error=str(exc))
        return None


# ── Stale-result detection ────────────────────────────────────────────────────

def _rows_are_stale(rows: list[dict]) -> bool:
    """
    Return True when every result is a past one-off event (no recurring groups,
    no future events, no undated entries).  Recurring communities have no
    event_datetime_start so they are never considered stale.
    """
    from datetime import datetime, timezone

    if not rows:
        return False

    now_iso = datetime.now(timezone.utc).isoformat()
    for row in rows:
        dt = row.get("event_datetime_start")
        activity = (row.get("activity") or "").lower()
        # Recurring entries are always considered fresh
        if activity in ("weekly", "monthly", "recurring", "biweekly"):
            return False
        # Undated entries are groups/communities — not stale
        if not dt:
            return False
        # At least one future event → not stale
        if str(dt) > now_iso:
            return False

    return True  # every row is a past one-off event


# ── Feedback signal extraction ───────────────────────────────────────────────

# Maps feedback phrase fragments to profile updates.
# Each entry: (substring_to_match, field, value_or_callable)
_FEEDBACK_RULES: list[tuple[str, str, object]] = [
    # Dealbreaker additions
    ("too corporate",   "dealbreakers", "corporate"),
    ("too loud",        "dealbreakers", "loud"),
    ("too noisy",       "dealbreakers", "loud"),
    ("too much alcohol","dealbreakers", "alcohol"),
    ("alcohol",         "dealbreakers", "alcohol"),
    ("too cliquey",     "dealbreakers", "cliquey"),
    ("too political",   "dealbreakers", "political"),
    ("too expensive",   "dealbreakers", "expensive"),
    # Social mode adjustments
    ("more technical",  "social_mode",  "workshop"),
    ("more hands-on",   "social_mode",  "workshop"),
    ("more social",     "social_mode",  "social"),
    ("more casual",     "social_mode",  "social"),
    # Budget
    ("cheaper",         "budget",       "free_only"),
    ("free only",       "budget",       "free_only"),
    ("free events",     "budget",       "free_only"),
    # Language
    ("english",         "language_pref","english"),
    ("german",          "language_pref","german"),
    # Environment
    ("newcomer",        "environment",  "newcomer_friendly"),
    ("beginner",        "environment",  "newcomer_friendly"),
]

# Keywords indicating the user wants a completely new search rather than a re-rank
_RESEARCH_TRIGGERS = {"more", "search", "find", "different", "other", "again", "else",
                      "another", "new search", "try again"}


def _parse_feedback_signals(text: str, profile) -> bool:
    """
    Map feedback phrases to targeted profile updates (dealbreakers, social_mode, budget, etc.).
    Returns True if any update was applied.

    This is called in the REFINING phase to avoid re-searching when the user
    just wants to filter or adjust preferences.
    """
    t = text.lower()
    changed = False
    for phrase, field, value in _FEEDBACK_RULES:
        if phrase not in t:
            continue
        if field == "dealbreakers":
            if value not in profile.dealbreakers:
                profile.dealbreakers.append(value)
                profile.field_confidence["dealbreakers"] = FieldConfidence.EXPLICIT
                changed = True
        elif field == "social_mode":
            profile.social_mode = value
            profile.field_confidence["social_mode"] = FieldConfidence.EXPLICIT
            changed = True
        elif field == "budget":
            profile.budget = value
            profile.field_confidence["budget"] = FieldConfidence.EXPLICIT
            changed = True
        elif field == "language_pref":
            if value not in profile.language_pref:
                profile.language_pref.append(value)
                profile.field_confidence["language_pref"] = FieldConfidence.EXPLICIT
                changed = True
        elif field == "environment":
            profile.environment = value
            profile.field_confidence["environment"] = FieldConfidence.EXPLICIT
            changed = True
    return changed


def _wants_research(text: str) -> bool:
    """Return True when the user's message suggests they want a new search, not just re-ranking."""
    t = text.lower()
    return any(kw in t for kw in _RESEARCH_TRIGGERS)


# ── Full search pipeline ──────────────────────────────────────────────────────

def _agent_call(name: str, fn, *args, **kwargs):
    """Invoke an agent tool with start/end/timing logs."""
    log.info("agent.start", agent=name)
    t0 = time.perf_counter()
    try:
        result = fn(*args, **kwargs)
        elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
        log.info("agent.done", agent=name, elapsed_ms=elapsed_ms)
        return result
    except Exception as exc:
        elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
        log.warning("agent.error", agent=name, elapsed_ms=elapsed_ms, error=str(exc))
        raise


def _rerank_cached(state: SessionState) -> str:
    """
    Re-rank the cached rows from the last search against the (updated) profile.
    Used by the refinement loop when the user gives feedback rather than requesting
    a completely new search.  Returns formatted recommendation string.
    """
    rows = state.last_ranked_rows
    if not rows:
        return None  # caller should fall back to full search

    profile_json = state.profile.model_dump_json()
    log.info("orchestrator.rerank_cached", row_count=len(rows))

    # Re-classify vibe/risk for rows that don't have it yet (should be cached already)
    # Skip re-classification — classifications are already embedded in the rows.

    ranked_json = _agent_call("ranking_tool (rerank)", ranking_tool, json.dumps(rows), profile_json)
    formatted = _agent_call("recommendation_writer_tool (rerank)", recommendation_writer_tool, ranked_json)
    # Update the cache with the newly ranked order
    try:
        state.last_ranked_rows = json.loads(ranked_json)
    except Exception:
        pass
    return formatted


def _run_search_pipeline(state: SessionState) -> str:
    """
    Full pipeline: txt2sql → vibe_classifier + risk_sanity → ranking → recommendation_writer.
    Returns formatted recommendation string.
    """
    profile = state.profile
    profile_json = profile.model_dump_json()

    # Step 1: Compute archetypes + build richer search brief
    archetype_weights = {}
    try:
        archetype_weights = json.loads(_agent_call("archetype_tool", archetype_tool, profile_json))
        profile.archetype_weights = archetype_weights
        brief = json.loads(_agent_call("search_planner_tool", search_planner_tool, profile.model_dump_json()))
        query_intents = brief.get("query_intents", [])
    except Exception as exc:
        log.warning("orchestrator.archetype_error", error=str(exc))
        query_intents = []

    # Build the main search query (use top intent if available, else fallback)
    if query_intents:
        search_query = query_intents[0]
    else:
        search_query = _build_search_query(state)

    log.info("orchestrator.search_query", query=search_query)

    # Step 2: txt2sql → raw rows
    raw_json = _agent_call("txt2sql_tool", txt2sql_tool, search_query)
    try:
        rows = json.loads(raw_json)
    except Exception:
        rows = []

    if isinstance(rows, dict) and "error" in rows:
        return f"[search error: {rows.get('detail', rows['error'])}]"

    if not isinstance(rows, list):
        rows = []

    log.info("orchestrator.rows_fetched", row_count=len(rows))

    # Step 2b: Live-search fallback — no results OR only past one-off events
    live_preamble = ""
    live_search_done = False
    needs_live = len(rows) == 0 or _rows_are_stale(rows)
    if needs_live:
        if _rows_are_stale(rows):
            log.info("orchestrator.stale_results", row_count=len(rows))
        live_preamble = _run_live_collection(state, query_intents=query_intents) or ""
        live_search_done = bool(live_preamble)
        if live_preamble:
            # Re-query DB with fresh data
            raw_json2 = _agent_call("txt2sql_tool (retry)", txt2sql_tool, search_query)
            try:
                rows2 = json.loads(raw_json2)
                if isinstance(rows2, list) and len(rows2) > len(rows):
                    rows = rows2
                    log.info("orchestrator.rows_fetched_after_live", row_count=len(rows))
            except Exception:
                pass

    if not rows:
        searched = ", ".join(query_intents[:3]) if query_intents else search_query[:80]
        extra = (
            " I also did a live search but found nothing new."
            if live_search_done
            else " I searched the local database but found nothing."
        )
        suggestions = []
        if state.profile.interests:
            suggestions.append(f"a different interest area (you mentioned: {', '.join(state.profile.interests[:3])})")
        if state.profile.social_mode:
            suggestions.append(f"a different format instead of '{state.profile.social_mode}'")
        suggestions.append("broader keywords like 'tech', 'social', or 'startup'")
        sugg_str = "; or try ".join(suggestions)
        return (
            f"No communities found matching: {searched}.{extra}\n\n"
            f"You could try {sugg_str}."
        )

    # Step 3: Vibe + risk classification — run all rows in parallel
    log.info("orchestrator.classifying", row_count=len(rows))

    def _classify_row(i_row):
        i, row = i_row
        description = (row.get("title") or "") + " " + (row.get("description") or "")
        try:
            row["_vibe"] = json.loads(_agent_call(f"vibe_classifier_tool[{i}]", vibe_classifier_tool, description))
        except Exception:
            row["_vibe"] = {"newcomer_friendliness": 0.5, "vibe_alignment": 0.5}
        try:
            row["_risk"] = json.loads(_agent_call(f"risk_sanity_tool[{i}]", risk_sanity_tool, json.dumps(row)))
        except Exception:
            row["_risk"] = {"pass": True, "risk_sanity_score": 0.8}
        return i, row

    with ThreadPoolExecutor(max_workers=min(8, len(rows))) as pool:
        futures = {pool.submit(_classify_row, (i, row)): i for i, row in enumerate(rows)}
        classified = {}
        for fut in as_completed(futures):
            try:
                idx, updated_row = fut.result()
                classified[idx] = updated_row
            except Exception as exc:
                log.warning("orchestrator.classify_error", error=str(exc))
    rows = [classified.get(i, rows[i]) for i in range(len(rows))]

    # Step 3b: Quality floor — if average vibe alignment is very low and we
    # haven't already done a live search, try a fresh scrape.
    if not live_search_done:
        vibe_scores = [row.get("_vibe", {}).get("vibe_alignment", 0.5) for row in rows]
        avg_vibe = sum(vibe_scores) / len(vibe_scores) if vibe_scores else 0.5
        if avg_vibe < 0.35:
            log.info("orchestrator.low_vibe_quality", avg_vibe=round(avg_vibe, 2), row_count=len(rows))
            fresh_preamble = _run_live_collection(state, query_intents=query_intents) or ""
            if fresh_preamble:
                live_preamble = fresh_preamble
                raw_json2 = _agent_call("txt2sql_tool (quality-retry)", txt2sql_tool, search_query)
                try:
                    rows2 = json.loads(raw_json2)
                    if isinstance(rows2, list) and len(rows2) > 0:
                        rows = rows2
                        log.info("orchestrator.rows_after_quality_retry", row_count=len(rows))
                except Exception:
                    pass

    # Step 4: Rank
    ranked_json = _agent_call("ranking_tool", ranking_tool, json.dumps(rows), profile_json)

    # Cache the ranked rows on the session so the refinement loop can re-rank
    # without re-querying the database.
    try:
        state.last_ranked_rows = json.loads(ranked_json)
    except Exception:
        pass

    # Step 5: Format recommendations
    formatted = _agent_call("recommendation_writer_tool", recommendation_writer_tool, ranked_json)
    return live_preamble + formatted


# ── Orchestrator ──────────────────────────────────────────────────────────────


class OrchestratorAgent:
    """
    Top-level session controller.

    Drives the state machine manually with a full agent pipeline:
      INTAKE → QUESTIONING → SEARCHING → RECOMMENDING → REFINING
    """

    _MAX_QUESTION_TURNS = 3

    def __init__(self, state: SessionState | None = None) -> None:
        self.state = state or SessionState()
        self._question_turns = 0
        log.info("orchestrator.init", session_id=self.state.session_id)

    def process_turn(self, user_input: str) -> str:
        """Accept one user turn, update state, return assistant response."""
        self.state.add_turn("user", user_input)
        log.info("orchestrator.turn", phase=self.state.phase, input_preview=user_input[:80])

        response = self._dispatch()

        self.state.add_turn("assistant", response)
        return response

    def _dispatch(self) -> str:
        phase = self.state.phase
        if phase == OrchestratorPhase.INTAKE:
            return self._handle_intake()
        elif phase == OrchestratorPhase.QUESTIONING:
            return self._handle_questioning()
        elif phase == OrchestratorPhase.SEARCHING:
            return self._handle_searching()
        elif phase == OrchestratorPhase.AGGREGATING:
            return self._handle_aggregating()
        elif phase == OrchestratorPhase.RECOMMENDING:
            return self._handle_recommending()
        elif phase == OrchestratorPhase.REFINING:
            return self._handle_refining()
        return "[orchestrator] unknown phase"

    def _handle_intake(self) -> str:
        user_turns = [t["content"] for t in self.state.conversation_history if t["role"] == "user"]
        if user_turns:
            _enrich_profile_from_turn(user_turns[-1], self.state.profile)
        self.state.advance_phase(OrchestratorPhase.QUESTIONING)
        return self._handle_questioning()

    def _handle_questioning(self) -> str:
        user_turns = [t["content"] for t in self.state.conversation_history if t["role"] == "user"]
        if user_turns:
            _enrich_profile_from_turn(user_turns[-1], self.state.profile)

        self._question_turns += 1
        sufficiency = check_sufficiency(self.state.profile)

        if sufficiency.is_sufficient or self._question_turns >= self._MAX_QUESTION_TURNS:
            self.state.advance_phase(OrchestratorPhase.SEARCHING)
            return self._handle_searching()

        # Use question_planner_tool for smarter question selection
        try:
            profile_json = self.state.profile.model_dump_json()
            questions_json = _agent_call("question_planner_tool", question_planner_tool, profile_json)
            questions = json.loads(questions_json)
            if questions:
                return "\n".join(f"- {q}" for q in questions)
        except Exception as exc:
            log.warning("orchestrator.question_planner_fallback", error=str(exc))

        # Fallback: static question bank
        questions = select_next_questions(
            self.state.profile,
            sufficiency.missing_categories,
            settings.max_questions_per_turn,
        )
        if not questions:
            self.state.advance_phase(OrchestratorPhase.SEARCHING)
            return self._handle_searching()
        return "\n".join(f"- {q}" for q in questions)

    def _handle_searching(self) -> str:
        log.info("orchestrator.searching", profile_interests=self.state.profile.interests)
        try:
            result = _run_search_pipeline(self.state)
            self.state.advance_phase(OrchestratorPhase.RECOMMENDING)
            return result
        except Exception as exc:
            log.warning("orchestrator.search_failed", error=str(exc))
            self.state.advance_phase(OrchestratorPhase.RECOMMENDING)
            return f"[search failed: {exc}]"

    def _handle_aggregating(self) -> str:
        self.state.advance_phase(OrchestratorPhase.RECOMMENDING)
        return "[orchestrator] Aggregating results... (stub)"

    def _handle_recommending(self) -> str:
        self.state.advance_phase(OrchestratorPhase.REFINING)
        return "Type anything to refine your search, or 'quit' to exit."

    def _handle_refining(self) -> str:
        user_turns = [t["content"] for t in self.state.conversation_history if t["role"] == "user"]
        last_input = user_turns[-1] if user_turns else ""

        # Parse targeted feedback (dealbreakers, social mode, budget, etc.)
        feedback_changed = _parse_feedback_signals(last_input, self.state.profile)

        # Also run normal profile enrichment (picks up new interests/goals)
        _enrich_profile_from_turn(last_input, self.state.profile)

        # Decide: re-rank cached results or do a full new search?
        if (
            feedback_changed
            and not _wants_research(last_input)
            and self.state.last_ranked_rows
        ):
            # Feedback-only refinement — re-rank existing results, no new DB query
            log.info("orchestrator.refining_rerank", dealbreakers=self.state.profile.dealbreakers)
            result = _rerank_cached(self.state)
            if result:
                self.state.advance_phase(OrchestratorPhase.RECOMMENDING)
                return result

        # New search requested or no cached rows — run full pipeline
        self.state.advance_phase(OrchestratorPhase.SEARCHING)
        return self._handle_searching()

    def _create_strands_agent(self):
        """
        Returns a strands.Agent pre-loaded with all CommunityMatcher tools,
        or None if the Strands library is not installed.

        The explicit orchestration pipeline (process_turn → _dispatch → …) remains
        the primary execution path.  This agent instance is available for any
        LLM-driven multi-tool coordination that doesn't fit the deterministic
        pipeline — e.g. open-ended follow-up queries or tool chaining experiments.
        """
        try:
            from strands import Agent  # type: ignore
            from community_matcher.agents.profile_builder_agent import profile_builder_tool
            from community_matcher.agents.question_planner_agent import question_planner_tool
            from community_matcher.agents.archetype_agent import archetype_tool
            from community_matcher.agents.search_planner_agent import search_planner_tool
            from community_matcher.agents.txt2sql_agent import txt2sql_tool
            from community_matcher.agents.vibe_classifier_agent import vibe_classifier_tool
            from community_matcher.agents.risk_sanity_agent import risk_sanity_tool
            from community_matcher.agents.ranking_agent import ranking_tool
            from community_matcher.agents.recommendation_writer_agent import recommendation_writer_tool

            return Agent(
                tools=[
                    profile_builder_tool,
                    question_planner_tool,
                    archetype_tool,
                    search_planner_tool,
                    txt2sql_tool,
                    vibe_classifier_tool,
                    risk_sanity_tool,
                    ranking_tool,
                    recommendation_writer_tool,
                ]
            )
        except ImportError:
            log.warning("strands.not_installed", msg="strands package not found — using explicit pipeline")
            return None
