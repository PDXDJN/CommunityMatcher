"""
Session-scoped embedding cache using sentence-transformers.

Model: all-MiniLM-L6-v2 (~90 MB, downloaded once to ~/.cache/huggingface/).
Embeddings are cached in a module-level dict keyed by the text string.

Falls back gracefully: if sentence-transformers is not installed or fails to
load, all public functions return None and callers must use their fallback scorer.
"""
from __future__ import annotations
import structlog

log = structlog.get_logger()

_MODEL_NAME = "all-MiniLM-L6-v2"
_model = None  # SentenceTransformer instance, loaded lazily
_cache: dict[str, list[float]] = {}  # text → embedding vector


def _get_model():
    """Return (or lazily load) the SentenceTransformer model."""
    global _model
    if _model is not None:
        return _model
    try:
        from sentence_transformers import SentenceTransformer
        log.info("embedding_cache.loading_model", model=_MODEL_NAME)
        _model = SentenceTransformer(_MODEL_NAME)
        log.info("embedding_cache.model_ready", model=_MODEL_NAME)
        return _model
    except ImportError:
        log.warning("embedding_cache.sentence_transformers_unavailable")
        return None
    except Exception as exc:
        log.warning("embedding_cache.load_failed", error=str(exc))
        return None


def embed(text: str) -> list[float] | None:
    """
    Return the embedding vector for text. Results are cached by text string.
    Returns None if sentence-transformers is unavailable.
    """
    if not text:
        return None
    if text in _cache:
        return _cache[text]
    model = _get_model()
    if model is None:
        return None
    try:
        vector = model.encode(text, normalize_embeddings=True).tolist()
        _cache[text] = vector
        return vector
    except Exception as exc:
        log.warning("embedding_cache.encode_failed", error=str(exc))
        return None


def cosine_sim(a: list[float], b: list[float]) -> float:
    """
    Cosine similarity for two pre-normalized vectors (dot product suffices).
    Returns 0.0 if inputs are mismatched or empty.
    """
    if not a or not b or len(a) != len(b):
        return 0.0
    return sum(x * y for x, y in zip(a, b))


def clear_cache() -> None:
    """Flush the in-memory embedding cache (call between sessions if desired)."""
    _cache.clear()
