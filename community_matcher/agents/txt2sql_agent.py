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

log = structlog.get_logger()

_LLM_BASE_URL = os.getenv("CM_LLM_BASE_URL", "https://api.featherless.ai/v1")
_LLM_API_KEY  = os.getenv("CM_LLM_API_KEY",  "")
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


def _generate_sql(question: str) -> str:
    """Ask the LLM to generate a SQL SELECT for the given question."""
    payload = {
        "model": _LLM_MODEL,
        "messages": [
            {"role": "system", "content": _SQL_GEN_PROMPT},
            {"role": "user", "content": f"Question: {question}\n\nSQL:"},
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

    log.info("txt2sql.sql_generated", sql=sql)
    return sql


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

    try:
        sql = _generate_sql(question)
        rows = execute_query(sql)
        result = rows_to_json(rows)
        log.info("txt2sql.done", question=question[:80], row_count=len(rows))
        return result
    except Exception as exc:
        log.warning("txt2sql.error", question=question[:80], error=str(exc))
        return json.dumps({"error": "txt2sql_failed", "detail": str(exc)})
