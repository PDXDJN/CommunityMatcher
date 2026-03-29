from __future__ import annotations
import json
import sqlite3
import time
import structlog
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator

log = structlog.get_logger()

_pool = None

def _sqlite_default() -> Path:
    """Resolve the canonical SQLite DB path from settings (respects CM_SQLITE_DB_PATH)."""
    from community_matcher.config.settings import settings
    return Path(settings.sqlite_db_path)


def _use_postgres() -> bool:
    from community_matcher.config.settings import settings
    return bool(settings.database_url)


# ── PostgreSQL pool ────────────────────────────────────────────────────────────

def _get_pool():
    """Lazily initialise the PostgreSQL connection pool on first use."""
    global _pool
    if _pool is not None:
        return _pool

    try:
        import psycopg2
        from psycopg2 import pool as pg_pool
        from community_matcher.config.settings import settings

        if not settings.database_url:
            raise RuntimeError("DATABASE_URL is not configured")

        _pool = pg_pool.ThreadedConnectionPool(
            minconn=1,
            maxconn=10,
            dsn=settings.database_url,
        )
        log.info("db.pool_created", database_url=settings.database_url.split("@")[-1])
        return _pool

    except ImportError:
        raise RuntimeError(
            "psycopg2 is not installed. Run: pip install psycopg2-binary"
        )


@contextmanager
def get_connection() -> Generator:
    """Context manager that yields a psycopg2 connection from the pool."""
    pool = _get_pool()
    conn = pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


# ── Unified query interface ────────────────────────────────────────────────────

def execute_query(
    sql: str,
    params: tuple | None = None,
    db_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """
    Execute a SELECT query and return rows as a list of dicts.

    Routes to SQLite when DATABASE_URL is not configured (default for local dev).
    Routes to PostgreSQL when DATABASE_URL is set.

    Raises ValueError for non-SELECT statements.
    """
    normalized = sql.strip().upper()
    if not normalized.startswith("SELECT"):
        raise ValueError(
            f"Only SELECT statements are permitted via this interface. Got: {sql[:60]}"
        )

    if _use_postgres():
        return _execute_postgres(sql, params)
    return _execute_sqlite(sql, params, db_path or _sqlite_default())


def _execute_postgres(sql: str, params: tuple | None) -> list[dict[str, Any]]:
    log.info("db.pg_query_start", sql=sql, params=params)
    t0 = time.perf_counter()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            columns = [desc[0] for desc in cur.description]
            rows = [dict(zip(columns, row)) for row in cur.fetchall()]
            elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
            log.info("db.pg_query_ok", row_count=len(rows), elapsed_ms=elapsed_ms)
            return rows


def _execute_sqlite(
    sql: str, params: tuple | None, db_path: str | Path
) -> list[dict[str, Any]]:
    db_path = Path(db_path)
    if not db_path.exists():
        log.warning("db.sqlite_not_found", path=str(db_path))
        return []

    log.info("db.sqlite_query_start", sql=sql, params=params, db=str(db_path))
    t0 = time.perf_counter()
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(sql, params or ())
        rows = [dict(row) for row in cur.fetchall()]
        elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
        log.info("db.sqlite_query_ok", row_count=len(rows), elapsed_ms=elapsed_ms)
        return rows
    finally:
        conn.close()


def rows_to_json(rows: list[dict[str, Any]]) -> str:
    """Serialize query results to a JSON string (handles Decimal, date types)."""
    import decimal
    import datetime

    def default(obj):
        if isinstance(obj, decimal.Decimal):
            return float(obj)
        if isinstance(obj, (datetime.date, datetime.datetime)):
            return obj.isoformat()
        raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

    return json.dumps(rows, default=default, ensure_ascii=False)


def reset_pool() -> None:
    """Close all connections and reset the pool (used in tests)."""
    global _pool
    if _pool is not None:
        _pool.closeall()
        _pool = None
