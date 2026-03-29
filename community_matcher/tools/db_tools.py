from __future__ import annotations
from community_matcher.agents import tool
from community_matcher.db.schema_doc import SCHEMA_DOC


@tool
def get_db_schema() -> str:
    """
    Returns the complete database schema documentation as a string.

    Use this before generating SQL so you understand the available tables
    and columns. Returns a human-readable schema with common query patterns.

    Returns:
        Schema documentation string.
    """
    return SCHEMA_DOC


@tool
def execute_sql(sql: str) -> str:
    """
    Executes a read-only SQL SELECT statement against the community database
    and returns the results as a JSON array.

    Only SELECT statements are permitted. Do not include semicolons or
    multiple statements. Keep result sets under 100 rows by using LIMIT.

    Args:
        sql: A valid PostgreSQL SELECT statement.

    Returns:
        JSON array of result rows, or a JSON error object if execution fails.
    """
    from community_matcher.db.connection import execute_query, rows_to_json
    import json

    try:
        rows = execute_query(sql)
        return rows_to_json(rows)
    except ValueError as e:
        return json.dumps({"error": "forbidden", "detail": str(e)})
    except Exception as e:
        return json.dumps({"error": "query_failed", "detail": str(e)})
