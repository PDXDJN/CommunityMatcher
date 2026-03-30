"""
FastAPI web server for Community Matcher.

Exposes a chat-based UI backed by the OrchestratorAgent,
with endpoints for profile inspection, community results,
and bookmarks.
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from collections import OrderedDict

import structlog
from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

log = structlog.get_logger()

from community_matcher.orchestrator.orchestrator_agent import (
    OrchestratorAgent,
    _build_search_query,
)
from community_matcher.orchestrator.session_state import SessionState, OrchestratorPhase
from community_matcher.domain.profile import UserProfile
from community_matcher.db.sessions import (
    load_session, save_session, count_sessions, delete_session,
    load_bookmarks, toggle_bookmark,
)

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

_STATIC = pathlib.Path(__file__).parent / "static"

# In-memory agent cache (agents are not serialisable — rebuilt from DB state on miss)
_agents: dict[str, tuple[OrchestratorAgent, SessionState]] = {}
_executor = ThreadPoolExecutor(max_workers=4)

# Background search jobs: job_id → {status, communities, searched_live, error, _created_at}
# Uses OrderedDict for insertion-order eviction; capped at _SEARCH_JOB_MAX entries.
_search_jobs: OrderedDict[str, dict] = OrderedDict()
_search_job_executor = ThreadPoolExecutor(max_workers=2)
_SEARCH_JOB_MAX = 100          # hard cap on dict size
_SEARCH_JOB_TTL = 3600.0       # seconds — expire completed/failed jobs after 1 hour


def _evict_search_jobs() -> None:
    """Remove expired or excess entries from _search_jobs.  Call before adding new jobs."""
    now = time.monotonic()
    stale = [
        jid for jid, job in _search_jobs.items()
        if job["status"] in ("done", "failed")
        and now - job.get("_created_at", now) > _SEARCH_JOB_TTL
    ]
    for jid in stale:
        del _search_jobs[jid]
    # If still over cap, drop oldest entries regardless of status
    while len(_search_jobs) >= _SEARCH_JOB_MAX:
        _search_jobs.popitem(last=False)


def _get_or_create_session(session_id: str) -> tuple[OrchestratorAgent, SessionState]:
    if session_id in _agents:
        return _agents[session_id]

    # Try to restore from DB
    stored = load_session(session_id)
    if stored:
        try:
            profile = UserProfile.model_validate(stored["profile"])
        except Exception:
            profile = UserProfile()
        state = SessionState(
            session_id=session_id,
            phase=OrchestratorPhase(stored["phase"]),
            profile=profile,
            conversation_history=stored["history"],
        )
        log.info("sessions.restored", session_id=session_id, phase=stored["phase"])
    else:
        state = SessionState(session_id=session_id)

    agent = OrchestratorAgent(state=state)
    _agents[session_id] = (agent, state)
    return agent, state


def _persist_session(session_id: str, state: SessionState) -> None:
    try:
        save_session(
            session_id,
            state.phase.value,
            state.profile.model_dump(),
            state.conversation_history,
        )
    except Exception as exc:
        log.warning("sessions.save_failed", session_id=session_id, error=str(exc))


# Nightly search terms derived from archetype vocabulary + interest clusters.
# Rotated across two batches so alternate nights cover different archetypes.
_SCHEDULER_TERMS_A = [
    # Tech archetypes
    "tech community Berlin", "AI meetup Berlin", "machine learning Berlin",
    "startup networking Berlin", "python developer Berlin", "data science Berlin",
    # Arts & lifestyle
    "photography Berlin community", "arts crafts workshop Berlin",
    "board games Berlin", "running club Berlin", "cycling Berlin",
]
_SCHEDULER_TERMS_B = [
    # Tech archetypes
    "maker hackspace Berlin", "gaming community Berlin", "design community Berlin",
    "social coding Berlin", "newcomer Berlin community", "cybersecurity Berlin",
    # Arts & lifestyle
    "painting drawing Berlin", "dance social Berlin", "choir singing Berlin",
    "urban sketching Berlin", "tabletop RPG Berlin", "hiking nature Berlin",
]
_SCHEDULER_TERMS_C = [
    # Broader non-tech sweep (used on day % 3 == 2)
    "pottery ceramics Berlin", "knitting sewing Berlin", "open mic Berlin",
    "salsa tango Berlin", "bouldering climbing Berlin", "book club Berlin",
    "photo walk Berlin", "volleyball basketball Berlin", "urban gardening Berlin",
    "language exchange Berlin", "expat social Berlin",
]
_SCHEDULER_SOURCES = ["meetup", "luma", "eventbrite", "mobilize", "ical", "github"]


def _run_scheduled_collection() -> None:
    """Nightly background collection job — keeps the DB fresh.

    Alternates between two term batches each night so the full archetype
    vocabulary is covered every two days without making each run too slow.
    After collection, runs the community rollup to aggregate events into
    organizer-level community rows.
    """
    import datetime
    try:
        from community_collector.orchestrator import run_collection
        from community_collector.config import CollectorConfig
        log.info("scheduler.collection_start")
        # Rotate across 3 term batches by day-of-year modulus
        day_slot = datetime.date.today().toordinal() % 3
        terms = [_SCHEDULER_TERMS_A, _SCHEDULER_TERMS_B, _SCHEDULER_TERMS_C][day_slot]
        cfg = CollectorConfig(
            search_terms=terms,
            sources_to_run=_SCHEDULER_SOURCES,
            max_results_per_source=50,
            headless=True,
        )
        run_collection(cfg)
        log.info("scheduler.collection_done", terms=terms)
    except Exception as exc:
        log.warning("scheduler.collection_failed", error=str(exc))
        return  # Skip rollup if collection failed hard

    # Post-collection rollup: collapse events → organizer-level communities
    try:
        from community_matcher.config.settings import settings
        from rollup_communities import rollup
        log.info("scheduler.rollup_start")
        stats = rollup(settings.sqlite_db_path, source_filter=None, dry_run=False)
        log.info(
            "scheduler.rollup_done",
            communities_created=stats.get("communities_created", 0),
            communities_updated=stats.get("communities_updated", 0),
            records_relinked=stats.get("records_relinked", 0),
        )
    except Exception as exc:
        log.warning("scheduler.rollup_failed", error=str(exc))


_scheduler = BackgroundScheduler(timezone="Europe/Berlin")
_scheduler.add_job(_run_scheduled_collection, "cron", hour=3, minute=0, id="nightly_collection")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure translation columns exist in the DB (idempotent migration)
    try:
        from community_collector.persistence import init_db
        from community_matcher.config.settings import settings
        init_db(settings.sqlite_db_path)
    except Exception as exc:
        log.warning("startup.db_migration_failed", error=str(exc))

    _scheduler.start()
    log.info("scheduler.started", jobs=[j.id for j in _scheduler.get_jobs()])
    yield
    _scheduler.shutdown(wait=False)
    _executor.shutdown(wait=False)


app = FastAPI(title="Community Matcher", version="1.0.0", lifespan=lifespan)


# ── Request logging middleware ─────────────────────────────────────────────────

@app.middleware("http")
async def log_requests(request: Request, call_next):
    t0 = time.perf_counter()
    log.info(
        "http.request",
        method=request.method,
        path=request.url.path,
        client=request.client.host if request.client else None,
    )
    response = await call_next(request)
    elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
    log.info(
        "http.response",
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        elapsed_ms=elapsed_ms,
    )
    return response


# ── UI ────────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def ui() -> HTMLResponse:
    return HTMLResponse((_STATIC / "index.html").read_text(encoding="utf-8"))


# ── Chat ──────────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    session_id: str
    message: str


@app.post("/chat")
async def chat(body: ChatRequest) -> dict:
    """Send one user turn to the orchestrator and receive a response."""
    agent, state = _get_or_create_session(body.session_id)
    log.info(
        "chat.turn_start",
        session_id=body.session_id,
        phase=state.phase.value,
        message_preview=body.message[:80],
    )
    t0 = time.perf_counter()
    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(_executor, agent.process_turn, body.message)
    elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
    log.info(
        "chat.turn_done",
        session_id=body.session_id,
        phase=state.phase.value,
        elapsed_ms=elapsed_ms,
    )
    _persist_session(body.session_id, state)
    return {
        "response": response,
        "phase": state.phase.value,
        "profile": state.profile.model_dump(),
    }


# ── Session / profile ─────────────────────────────────────────────────────────

@app.get("/session/{session_id}/profile")
async def get_profile(session_id: str) -> dict:
    """Return the current session phase, profile, and conversation history."""
    _, state = _get_or_create_session(session_id)
    return {
        "phase": state.phase.value,
        "profile": state.profile.model_dump(),
        "conversation_history": state.conversation_history,
    }


# ── Ranked results ───────────────────────────────────────────────────────────

@app.get("/session/{session_id}/ranked")
async def get_ranked(session_id: str) -> dict:
    """
    Return the last ranked community rows for the session (with _scores).
    Only available after at least one search has completed.
    """
    _, state = _get_or_create_session(session_id)
    return {"ranked": state.last_ranked_rows or []}


# ── Communities ───────────────────────────────────────────────────────────────

@app.get("/communities/{session_id}")
async def get_communities(session_id: str) -> dict:
    """
    Run a DB search based on the session's current profile and return
    community/event rows as structured JSON.
    """
    _, state = _get_or_create_session(session_id)
    if not state.profile.interests and not state.conversation_history:
        return {"communities": []}
    from community_matcher.agents.txt2sql_agent import txt2sql_tool

    query = _build_search_query(state)
    loop = asyncio.get_event_loop()
    try:
        raw = await loop.run_in_executor(_executor, txt2sql_tool, query)
        rows = json.loads(raw)
        if isinstance(rows, dict) and "error" in rows:
            return {"communities": [], "error": rows.get("detail", rows["error"])}
        return {"communities": rows if isinstance(rows, list) else []}
    except Exception as exc:
        return {"communities": [], "error": str(exc)}


# ── Term search ───────────────────────────────────────────────────────────────

class TermSearchRequest(BaseModel):
    session_id: str
    term: str


def _run_search_job(job_id: str, term: str, session_id: str) -> None:
    """Background worker: runs DB search + optional live collection, stores result."""
    from community_matcher.agents.txt2sql_agent import txt2sql_tool
    from community_matcher.orchestrator.orchestrator_agent import _run_live_collection

    _search_jobs[job_id]["status"] = "running"
    try:
        _, state = _get_or_create_session(session_id)
        profile = state.profile

        parts = [f"communities, groups, or events related to: {term}"]
        if profile.language_pref:
            parts.append(f"language: {', '.join(profile.language_pref)}")
        if profile.logistics.districts:
            parts.append(f"districts: {', '.join(profile.logistics.districts[:2])}")
        if profile.dealbreakers:
            parts.append(f"avoid: {', '.join(profile.dealbreakers[:2])}")
        question = "Find " + "; ".join(parts)

        def _db_query() -> list:
            try:
                raw = txt2sql_tool(question)
                rows = json.loads(raw)
                return rows if isinstance(rows, list) else []
            except Exception:
                return []

        rows = _db_query()
        searched_live = False

        if not rows:
            _run_live_collection(state, query_intents=[term])
            rows = _db_query()
            searched_live = True

        _search_jobs[job_id].update(
            status="done", communities=rows, searched_live=searched_live
        )
    except Exception as exc:
        log.warning("search_job.failed", job_id=job_id, error=str(exc))
        _search_jobs[job_id].update(status="failed", communities=[], error=str(exc))


@app.post("/communities/search-term")
async def search_by_term(body: TermSearchRequest) -> dict:
    """
    Start a background search for communities matching a free-text term.
    Returns a job_id immediately; poll GET /communities/search-term/{job_id} for results.
    """
    term = body.term.strip()
    if not term:
        return {"job_id": None, "status": "done", "communities": []}

    _evict_search_jobs()
    job_id = str(uuid.uuid4())[:8]
    _search_jobs[job_id] = {
        "status": "pending",
        "communities": [],
        "searched_live": False,
        "_created_at": time.monotonic(),
    }
    _search_job_executor.submit(_run_search_job, job_id, term, body.session_id)
    return {"job_id": job_id, "status": "pending"}


@app.get("/communities/search-term/{job_id}")
async def search_term_status(job_id: str) -> dict:
    """Poll the status of a background term search job."""
    job = _search_jobs.get(job_id)
    if not job:
        return {"status": "not_found", "communities": []}
    return job


# ── Bookmarks ─────────────────────────────────────────────────────────────────

class BookmarkRequest(BaseModel):
    session_id: str
    community_id: str


@app.post("/bookmark")
async def bookmark(body: BookmarkRequest) -> dict:
    """Toggle a bookmark for one community. Returns new bookmarked state."""
    bookmarked = toggle_bookmark(body.session_id, body.community_id)
    return {"community_id": body.community_id, "bookmarked": bookmarked}


@app.get("/bookmarks/{session_id}")
async def list_bookmarks(session_id: str) -> dict:
    """Return the set of bookmarked community IDs for a session."""
    return {"ids": list(load_bookmarks(session_id))}


# ── Map ───────────────────────────────────────────────────────────────────────

# Berlin bounding box (generous padding)
_BERLIN_LAT_MIN, _BERLIN_LAT_MAX = 52.33, 52.72
_BERLIN_LON_MIN, _BERLIN_LON_MAX = 13.08, 13.77


@app.get("/map/communities/{session_id}")
async def map_communities(session_id: str) -> dict:
    """
    Return scrape_record rows that have lat/lon coordinates within Berlin.
    Used by the map view in the UI.
    """
    from community_matcher.db.connection import execute_query
    try:
        rows = execute_query(
            "SELECT id, title, source_url, description, organizer_name, "
            "venue_name, city, cost_factor, is_online, topic_signals, tags, "
            "latitude, longitude, source "
            "FROM scrape_record "
            "WHERE latitude IS NOT NULL AND longitude IS NOT NULL "
            "  AND latitude  BETWEEN ? AND ? "
            "  AND longitude BETWEEN ? AND ? "
            "ORDER BY extraction_timestamp DESC LIMIT 500",
            params=[_BERLIN_LAT_MIN, _BERLIN_LAT_MAX,
                    _BERLIN_LON_MIN, _BERLIN_LON_MAX],
        )
    except Exception as exc:
        log.warning("map_communities.error", error=str(exc))
        return {"communities": []}
    return {"communities": rows or []}


# ── Session reset ──────────────────────────────────────────────────────────────

class ResetRequest(BaseModel):
    session_id: str


@app.post("/session/reset")
async def reset_session(body: ResetRequest) -> dict:
    """
    Wipe a session completely — profile, history, and agent — so the user
    can start a fresh conversation from scratch.
    """
    sid = body.session_id
    _agents.pop(sid, None)
    try:
        delete_session(sid)
    except Exception as exc:
        log.warning("session.reset_db_failed", session_id=sid, error=str(exc))
    log.info("session.reset", session_id=sid)
    return {"status": "ok", "session_id": sid}


# ── Profile filter removal ─────────────────────────────────────────────────────

class ProfilePatchRequest(BaseModel):
    session_id: str
    remove_interest: str | None = None
    remove_dealbreaker: str | None = None
    remove_goal: str | None = None
    clear_dealbreakers: bool = False


@app.post("/session/profile/patch")
async def patch_profile(body: ProfilePatchRequest) -> dict:
    """
    Remove a specific interest, dealbreaker, or goal from the user's profile.
    Useful for letting users fine-tune their profile without restarting.
    """
    _, state = _get_or_create_session(body.session_id)
    profile = state.profile

    if body.remove_interest and body.remove_interest in profile.interests:
        profile.interests.remove(body.remove_interest)
    if body.remove_goal and body.remove_goal in profile.goals:
        profile.goals.remove(body.remove_goal)
    if body.clear_dealbreakers:
        profile.dealbreakers.clear()
    elif body.remove_dealbreaker and body.remove_dealbreaker in profile.dealbreakers:
        profile.dealbreakers.remove(body.remove_dealbreaker)

    _persist_session(body.session_id, state)
    return {"profile": profile.model_dump()}


# ── DB stats ──────────────────────────────────────────────────────────────────

@app.get("/db/stats")
async def db_stats() -> dict:
    """Return total community/event counts from the database."""
    from community_matcher.db.connection import execute_query
    try:
        rows = execute_query("SELECT COUNT(*) AS total FROM scrape_record")
        total = rows[0]["total"] if rows else 0
    except Exception:
        total = 0
    return {"total": total}


# ── Translation backfill ──────────────────────────────────────────────────────

@app.post("/admin/backfill-translations")
async def backfill_translations(limit: int = 50) -> dict:
    """
    Translate existing scrape_record rows that have no title_en / title_de yet.
    Processes up to `limit` rows per call (default 50) to avoid timeouts.
    Safe to call repeatedly — skips already-translated rows.
    """
    from community_matcher.db.connection import execute_query, _execute_sqlite, _sqlite_default
    import sqlite3

    db_path = str(_sqlite_default())
    rows = execute_query(
        "SELECT id, title, description FROM scrape_record "
        "WHERE title_en IS NULL OR title_de IS NULL "
        f"LIMIT {min(limit, 200)}"
    )
    if not rows:
        return {"translated": 0, "message": "All rows already have translations."}

    from community_collector.translation import fill_translations
    updated = 0
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        for row in rows:
            try:
                trans = fill_translations(row["title"], row.get("description"))
                cur.execute(
                    """UPDATE scrape_record
                       SET title_en=?, description_en=?, title_de=?, description_de=?, detected_language=?
                       WHERE id=?""",
                    (
                        trans["title_en"], trans["description_en"],
                        trans["title_de"], trans["description_de"],
                        trans["detected_language"],
                        row["id"],
                    ),
                )
                updated += 1
            except Exception as exc:
                log.warning("backfill.row_failed", row_id=row["id"], error=str(exc))
        conn.commit()
    finally:
        conn.close()

    return {"translated": updated, "remaining": max(0, len(rows) - updated)}


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
@app.get("/status")
async def health() -> dict:
    return {"ok": True, "active_sessions": count_sessions()}
