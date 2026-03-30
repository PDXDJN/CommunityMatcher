"""
txt2sql tool — translates natural language questions to SQL and runs them
against the community SQLite database (or PostgreSQL in production).

Uses the Featherless AI API (OpenAI-compatible) for SQL generation.
The tool is a simple two-step: generate SQL → execute SQL → return JSON.

Configuration (env vars, all optional):
  CM_LLM_BASE_URL  — base URL of the OpenAI-compatible API
                     default: https://api.featherless.ai/v1
  CM_LLM_API_KEY   — bearer token / API key
  CM_LLM_MODEL     — model ID to use
                     default: Qwen/Qwen3-8B
"""
from __future__ import annotations
import json
import os
import re
import structlog
from community_matcher.agents import tool
from community_matcher.db.schema_doc import SCHEMA_DOC

# Ensure .env files are loaded before reading env vars below.
import community_matcher.config.settings  # noqa: F401  (side-effect: load_dotenv)

log = structlog.get_logger()

_LLM_BASE_URL = os.getenv("CM_LLM_BASE_URL", "https://api.featherless.ai/v1")
# Accept CM_LLM_API_KEY (canonical) or FEATHERLESS_API (legacy .env name)
_LLM_API_KEY  = os.getenv("CM_LLM_API_KEY") or os.getenv("FEATHERLESS_API", "")
_LLM_MODEL    = os.getenv("CM_LLM_MODEL",     "Qwen/Qwen3-8B")

_SQL_GEN_PROMPT = f"""\
You are a SQLite query expert for the CommunityMatcher database.

{SCHEMA_DOC}

Rules:
- Generate ONLY a single SQLite SELECT statement. No explanation, no markdown, no backticks.
- Always include LIMIT (default 20, max 50).
- Use LIKE (not ILIKE — this is SQLite) for text matching.
- For tag searches use LIKE '%"tagname"%' since tags are stored as JSON arrays in TEXT columns.
- ALWAYS use OR (never AND) when combining multiple topic/tag conditions — AND returns too few results.
- Prefer scrape_record for rich data (title, description, tags, source_url).
- ALWAYS include these columns in every SELECT from scrape_record: source, source_url, title, description, tags, title_en, description_en, title_de, description_de, detected_language.
- Only filter on column names and tag values that exist in the schema above.
- Do NOT invent tag values — only use tags listed in the schema (ai, python, startup, tech, etc.).
- Output only the raw SQL statement on a single line.
"""


def _llm_post(path: str, payload: dict) -> dict:
    """POST to the configured OpenAI-compatible LLM endpoint."""
    import requests

    headers = {"Content-Type": "application/json"}
    if _LLM_API_KEY:
        headers["Authorization"] = f"Bearer {_LLM_API_KEY}"

    url = f"{_LLM_BASE_URL.rstrip('/')}{path}"
    resp = requests.post(url, json=payload, headers=headers, timeout=(10, 120))
    resp.raise_for_status()
    return resp.json()


def _generate_sql(question: str, previous_sql: str | None = None, error_hint: str | None = None) -> str:
    """Ask the LLM to generate a SQL SELECT for the given question.

    When called on a retry, previous_sql and error_hint are included so the
    model can self-correct (fewer filters, OR instead of AND, etc.).
    """
    user_content = f"Question: {question}\n\nSQL:"
    if previous_sql and error_hint:
        user_content = (
            f"Question: {question}\n\n"
            f"Previous attempt returned 0 results:\n{previous_sql}\n\n"
            f"Hint: {error_hint}\n"
            f"Write a relaxed version that returns more results. SQL:"
        )

    payload = {
        "model": _LLM_MODEL,
        "messages": [
            {"role": "system", "content": _SQL_GEN_PROMPT},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.0,
    }
    data = _llm_post("/chat/completions", payload)
    raw = data["choices"][0]["message"]["content"].strip()

    # Strip markdown code fences and trailing semicolons
    raw = re.sub(r"^```(?:sql)?\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\s*```$", "", raw)
    sql = raw.strip().rstrip(";")

    # Safety: reject anything that isn't a SELECT
    if not sql.upper().startswith("SELECT"):
        raise ValueError(f"Model generated a non-SELECT statement: {sql[:80]}")

    log.info("txt2sql.sql_generated", sql=sql, is_retry=bool(previous_sql))
    return sql


def _infer_source(url: str) -> str:
    """Infer source platform from a URL string."""
    u = (url or "").lower()
    if "meetup.com" in u:
        return "meetup"
    if "eventbrite" in u:
        return "eventbrite"
    if "lu.ma" in u or "luma" in u:
        return "luma"
    return "unknown"


def _fill_missing_source(rows: list[dict]) -> None:
    """
    Ensure every row has a 'source' field.
    When the LLM-generated SQL omits the source column, infer it from source_url.
    Mutates rows in-place.
    """
    for row in rows:
        if not row.get("source"):
            row["source"] = _infer_source(row.get("source_url", ""))


_RETRY_HINTS = [
    (
        "Use OR between all topic/tag conditions instead of AND. "
        "Remove any date or location filters. "
        "Search topic_signals, tags, and title with OR."
    ),
    (
        "Make the query as broad as possible: search only the title column with a single "
        "LIKE '%tech%' or similar very general term and return up to 50 rows."
    ),
]


@tool
def txt2sql_tool(question: str) -> str:
    """
    Translates a natural language question into SQL, executes it against the
    community database, and returns results as a JSON array.

    Use this to search for communities, events, and meetups stored in the
    database. The database was populated by scraping Meetup, Eventbrite, and
    Lu.ma for Berlin events. Examples:
      - "Find tech meetups related to Python or AI"
      - "Which communities are free and newcomer-friendly?"
      - "List startup networking events"
      - "Find workshops about data science"

    Args:
        question: Natural language question about the community database.

    Returns:
        JSON array of matching rows, or a JSON error object.
    """
    from community_matcher.db.connection import execute_query, rows_to_json

    last_sql: str | None = None
    last_exc: Exception | None = None

    # Up to 1 initial attempt + 2 retries (total 3 tries)
    for attempt, hint in enumerate([None] + _RETRY_HINTS):
        try:
            sql = _generate_sql(question, previous_sql=last_sql, error_hint=hint)
            rows = execute_query(sql)
            _fill_missing_source(rows)

            if rows or attempt == len(_RETRY_HINTS):
                # Return results (even if empty on final attempt)
                result = rows_to_json(rows)
                log.info(
                    "txt2sql.done",
                    question=question[:80],
                    row_count=len(rows),
                    attempt=attempt,
                )
                return result

            # Empty result — retry with relaxed query
            log.info(
                "txt2sql.empty_retry",
                question=question[:80],
                attempt=attempt,
                sql_preview=sql[:120],
            )
            last_sql = sql

        except Exception as exc:
            last_exc = exc
            last_sql = None
            log.warning(
                "txt2sql.attempt_failed",
                question=question[:80],
                attempt=attempt,
                error=str(exc),
            )

    # All attempts failed
    detail = str(last_exc) if last_exc else "all attempts returned empty"
    log.warning("txt2sql.error", question=question[:80], error=detail)
    return json.dumps({"error": "txt2sql_failed", "detail": detail})


# ── Tag-based fallback (no LLM required) ────────────────────────────────────

_REQUIRED_COLUMNS = (
    "source, source_url, title, description, tags, "
    "topic_signals, audience_signals, format_signals, vibe_signals, "
    "activity, cost_factor, organizer_name, community_name, "
    "event_datetime_start, detected_language, title_en, description_en, "
    "title_de, description_de"
)


def tag_search(
    tags: list[str],
    *,
    audience_tags: list[str] | None = None,
    format_tags: list[str] | None = None,
    vibe_tags: list[str] | None = None,
    free_only: bool = False,
    limit: int = 30,
) -> list[dict]:
    """
    Direct SQL search using the signal columns — no LLM involved.

    Builds a broad OR query across topic_signals, tags, title and optional
    audience/format/vibe signals.  Used as a reliable fallback when txt2sql
    returns empty results or the LLM is unavailable.

    Args:
        tags: Interest/topic tags to search for (e.g. ["ai", "python"]).
        audience_tags: Optional audience constraints (e.g. ["beginner_friendly"]).
        format_tags: Optional format constraints (e.g. ["workshop"]).
        vibe_tags: Optional vibe constraints (e.g. ["technical"]).
        free_only: If True, restrict to cost_factor = 0.
        limit: Max rows to return.

    Returns:
        List of row dicts.
    """
    from community_matcher.db.connection import execute_query

    conditions: list[str] = []
    params: list[str] = []

    # Topic / tag matching (broad OR)
    topic_parts: list[str] = []
    for tag in tags:
        safe = tag.replace("'", "''")
        topic_parts += [
            f'topic_signals LIKE \'%"{safe}"%\'',
            f'tags LIKE \'%"{safe}"%\'',
            f"title LIKE '%{safe}%'",
        ]
    if topic_parts:
        conditions.append(f"({' OR '.join(topic_parts)})")

    # Audience signals (OR between them)
    if audience_tags:
        aud_parts = [f'audience_signals LIKE \'%"{t.replace(chr(39), chr(39)*2)}"%\'' for t in audience_tags]
        conditions.append(f"({' OR '.join(aud_parts)})")

    # Format signals (OR)
    if format_tags:
        fmt_parts = [f'format_signals LIKE \'%"{t.replace(chr(39), chr(39)*2)}"%\'' for t in format_tags]
        conditions.append(f"({' OR '.join(fmt_parts)})")

    # Vibe signals (OR)
    if vibe_tags:
        vibe_parts = [f'vibe_signals LIKE \'%"{t.replace(chr(39), chr(39)*2)}"%\'' for t in vibe_tags]
        conditions.append(f"({' OR '.join(vibe_parts)})")

    if free_only:
        conditions.append("(cost_factor = 0 OR cost_text LIKE '%free%' OR cost_text LIKE '%kostenlos%')")

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    sql = f"SELECT {_REQUIRED_COLUMNS} FROM scrape_record {where} LIMIT {int(limit)}"

    try:
        rows = execute_query(sql)
        _fill_missing_source(rows)
        log.info("tag_search.done", tags=tags, row_count=len(rows))
        return rows
    except Exception as exc:
        log.warning("tag_search.error", tags=tags, error=str(exc))
        return []
