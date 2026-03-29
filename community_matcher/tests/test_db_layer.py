import pytest
from community_matcher.db.schema_doc import SCHEMA_DOC


def test_schema_doc_contains_all_tables():
    for table in ("community", "social", "keyword", "factoid", "kw_affinity", "fc_affinity"):
        assert table in SCHEMA_DOC, f"Expected table '{table}' in SCHEMA_DOC"


def test_schema_doc_contains_affinity_columns():
    assert "aff_value" in SCHEMA_DOC
    assert "c_idx" in SCHEMA_DOC
    assert "k_idx" in SCHEMA_DOC
    assert "f_idx" in SCHEMA_DOC


def test_execute_sql_rejects_non_select():
    from community_matcher.db.connection import execute_query
    with pytest.raises((ValueError, RuntimeError)):
        # Should raise ValueError (non-SELECT) or RuntimeError (no DB configured)
        execute_query("DROP TABLE community")


def test_execute_sql_falls_back_to_sqlite(monkeypatch):
    """Without DATABASE_URL, execute_query falls back to the SQLite collector DB."""
    import community_matcher.db.connection as db_conn
    db_conn.reset_pool()
    monkeypatch.setenv("DATABASE_URL", "")

    import community_matcher.config.settings as settings_mod
    settings_mod.settings = settings_mod.Settings.from_env()

    # Should not raise — SQLite fallback is active
    rows = db_conn.execute_query("SELECT 1 AS n")
    assert rows == [{"n": 1}]

    db_conn.reset_pool()


def test_txt2sql_tool_returns_string():
    from community_matcher.agents.txt2sql_agent import txt2sql_tool
    result = txt2sql_tool("Find all Python communities")
    assert isinstance(result, str)


def test_execute_sql_tool_returns_results_from_sqlite():
    """With SQLite fallback active, the db_tool should return real rows."""
    from community_matcher.tools.db_tools import execute_sql
    import json
    import community_matcher.db.connection as db_conn
    db_conn.reset_pool()

    result = execute_sql("SELECT idx, name FROM community LIMIT 5")
    parsed = json.loads(result)
    # SQLite is populated — should be a list of rows (not an error)
    assert isinstance(parsed, list)


# Sprint 4 placeholder
@pytest.mark.skip(reason="Sprint 4: requires live PostgreSQL database")
def test_group_discovery_returns_candidates():
    pass
