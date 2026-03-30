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
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

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
    load_session, save_session, count_sessions,
    load_bookmarks, toggle_bookmark,
)

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

_STATIC = pathlib.Path(__file__).parent / "static"

# In-memory agent cache (agents are not serialisable — rebuilt from DB state on miss)
_agents: dict[str, tuple[OrchestratorAgent, SessionState]] = {}
_executor = ThreadPoolExecutor(max_workers=4)


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
    "tech community Berlin", "AI meetup Berlin", "machine learning Berlin",
    "startup networking Berlin", "python developer Berlin", "data science Berlin",
]
_SCHEDULER_TERMS_B = [
    "maker hackspace Berlin", "gaming community Berlin", "design community Berlin",
    "social coding Berlin", "newcomer Berlin community", "cybersecurity Berlin",
]
_SCHEDULER_SOURCES = ["meetup", "luma", "mobilize", "ical", "github"]


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
        # Alternate batches by day-of-year parity
        day_parity = datetime.date.today().toordinal() % 2
        terms = _SCHEDULER_TERMS_A if day_parity == 0 else _SCHEDULER_TERMS_B
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
