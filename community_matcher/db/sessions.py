"""
SQLite-backed session store.

Persists session state (profile + conversation history + phase) so that
sessions survive server restarts. Serialises SessionState to JSON.
"""
from __future__ import annotations
import json
import sqlite3
import structlog
from pathlib import Path

log = structlog.get_logger()

_DB_PATH = Path(__file__).parent.parent.parent / "community_collector" / "output" / "sessions.db"


def _connect() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            session_id  TEXT PRIMARY KEY,
            phase       TEXT NOT NULL DEFAULT 'intake',
            profile_json TEXT NOT NULL DEFAULT '{}',
            history_json TEXT NOT NULL DEFAULT '[]',
            updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS bookmarks (
            session_id   TEXT NOT NULL,
            community_id TEXT NOT NULL,
            PRIMARY KEY (session_id, community_id)
        )
    """)
    conn.commit()
    return conn


_conn: sqlite3.Connection | None = None


def get_db() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = _connect()
        log.info("sessions.db_opened", path=str(_DB_PATH))
    return _conn


# ── Session CRUD ──────────────────────────────────────────────────────────────

def load_session(session_id: str) -> dict | None:
    """Return stored session data or None if not found."""
    row = get_db().execute(
        "SELECT phase, profile_json, history_json FROM sessions WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    if row is None:
        return None
    return {"phase": row[0], "profile": json.loads(row[1]), "history": json.loads(row[2])}


def save_session(session_id: str, phase: str, profile: dict, history: list) -> None:
    """Upsert session state."""
    get_db().execute(
        """
        INSERT INTO sessions (session_id, phase, profile_json, history_json, updated_at)
        VALUES (?, ?, ?, ?, datetime('now'))
        ON CONFLICT(session_id) DO UPDATE SET
            phase        = excluded.phase,
            profile_json = excluded.profile_json,
            history_json = excluded.history_json,
            updated_at   = excluded.updated_at
        """,
        (session_id, phase, json.dumps(profile), json.dumps(history)),
    )
    get_db().commit()


def count_sessions() -> int:
    return get_db().execute("SELECT COUNT(*) FROM sessions").fetchone()[0]


# ── Bookmark CRUD ─────────────────────────────────────────────────────────────

def load_bookmarks(session_id: str) -> set[str]:
    rows = get_db().execute(
        "SELECT community_id FROM bookmarks WHERE session_id = ?", (session_id,)
    ).fetchall()
    return {r[0] for r in rows}


def toggle_bookmark(session_id: str, community_id: str) -> bool:
    """Toggle bookmark. Returns True if now bookmarked, False if removed."""
    existing = get_db().execute(
        "SELECT 1 FROM bookmarks WHERE session_id = ? AND community_id = ?",
        (session_id, community_id),
    ).fetchone()
    if existing:
        get_db().execute(
            "DELETE FROM bookmarks WHERE session_id = ? AND community_id = ?",
            (session_id, community_id),
        )
        get_db().commit()
        return False
    get_db().execute(
        "INSERT INTO bookmarks (session_id, community_id) VALUES (?, ?)",
        (session_id, community_id),
    )
    get_db().commit()
    return True
