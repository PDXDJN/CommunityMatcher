"""
TF-IDF vector search over community titles and descriptions.

Complements txt2sql and semantic_search_tool for queries where neither
keyword tags nor synonym expansion produces good results.

Strategy:
  - Builds a TF-IDF matrix over all (title + description) texts on first call.
  - Caches the index in memory; invalidated when DB row count changes.
  - Query → cosine similarity → top-k results fetched from DB by id.
  - Falls back to semantic_search_tool if scikit-learn is unavailable.

No external ML model or embedding API required — pure sklearn.
"""
from __future__ import annotations

import json
import structlog

from community_matcher.agents import tool

log = structlog.get_logger()

# In-memory index cache
_index_cache: dict = {
    "matrix": None,
    "vectorizer": None,
    "ids": [],         # scrape_record.id in matrix row order
    "db_total": -1,    # row count at build time (used to detect staleness)
}

_MAX_RESULTS = 30


def _build_index() -> bool:
    """Build TF-IDF index from the DB. Returns True on success."""
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from community_matcher.db.connection import execute_query
    except ImportError:
        return False

    try:
        rows = execute_query(
            "SELECT id, title, description FROM scrape_record "
            "WHERE title IS NOT NULL ORDER BY id"
        )
    except Exception as exc:
        log.warning("vector_search.db_read_failed", error=str(exc))
        return False

    if not rows:
        return False

    texts = [
        f"{r.get('title', '')} {r.get('description', '') or ''}".strip()
        for r in rows
    ]
    ids = [r["id"] for r in rows]

    try:
        vectorizer = TfidfVectorizer(
            analyzer="word",
            ngram_range=(1, 2),
            max_features=50_000,
            sublinear_tf=True,
            min_df=1,
        )
        matrix = vectorizer.fit_transform(texts)
    except Exception as exc:
        log.warning("vector_search.index_build_failed", error=str(exc))
        return False

    _index_cache["vectorizer"] = vectorizer
    _index_cache["matrix"] = matrix
    _index_cache["ids"] = ids
    _index_cache["db_total"] = len(rows)
    log.info("vector_search.index_built", documents=len(rows))
    return True


def _is_stale() -> bool:
    """Return True if the index needs rebuilding."""
    if _index_cache["matrix"] is None:
        return True
    try:
        from community_matcher.db.connection import execute_query
        rows = execute_query("SELECT COUNT(*) AS n FROM scrape_record")
        current = rows[0]["n"] if rows else 0
        return current != _index_cache["db_total"]
    except Exception:
        return False  # Keep cached index on DB error


@tool
def vector_search_tool(query: str) -> str:
    """
    TF-IDF semantic search over community titles and descriptions.

    Better than txt2sql for open-ended natural language queries where
    the user's phrasing doesn't map to known database tag slugs.

    Examples that work well:
      - "photography meetup"
      - "learn to code in a friendly environment"
      - "outdoor activities and hiking"
      - "creative people interested in illustration"

    Args:
        query: Natural language query describing communities of interest.

    Returns:
        JSON array of matching scrape_record rows, or JSON error object.
    """
    try:
        import numpy as np
        from sklearn.metrics.pairwise import cosine_similarity
    except ImportError:
        # scikit-learn / numpy not available — fall back to semantic search
        log.warning("vector_search.sklearn_unavailable_fallback")
        from community_matcher.agents.semantic_search_tool import semantic_search_tool
        return semantic_search_tool(query)

    from community_matcher.db.connection import execute_query, rows_to_json

    if _is_stale():
        if not _build_index():
            from community_matcher.agents.semantic_search_tool import semantic_search_tool
            return semantic_search_tool(query)

    vectorizer = _index_cache["vectorizer"]
    matrix     = _index_cache["matrix"]
    ids        = _index_cache["ids"]

    try:
        q_vec = vectorizer.transform([query])
        sims  = cosine_similarity(q_vec, matrix).flatten()
        top_indices = np.argsort(sims)[::-1][:_MAX_RESULTS]
        top_ids = [ids[i] for i in top_indices if sims[i] > 0.01]
    except Exception as exc:
        log.warning("vector_search.query_failed", error=str(exc))
        from community_matcher.agents.semantic_search_tool import semantic_search_tool
        return semantic_search_tool(query)

    if not top_ids:
        return json.dumps([])

    placeholders = ",".join("?" * len(top_ids))
    try:
        rows = execute_query(
            f"SELECT id, title, source_url, description, topic_signals, tags, "
            f"vibe_signals, audience_signals, format_signals, organizer_name, "
            f"city, cost_factor, is_online, latitude, longitude "
            f"FROM scrape_record WHERE id IN ({placeholders})",
            params=top_ids,
        )
    except Exception as exc:
        log.warning("vector_search.fetch_failed", error=str(exc))
        return json.dumps({"error": str(exc)})

    # Re-order to match similarity ranking
    id_to_row = {r["id"]: r for r in rows}
    ordered = [id_to_row[rid] for rid in top_ids if rid in id_to_row]

    log.info("vector_search.done", query=query[:80], results=len(ordered))
    return rows_to_json(ordered)
