"""
Language detection and translation for community/event records.

At collection time: detect title+description language, then produce both
EN and DE versions using the Featherless AI LLM. Results are stored in the
scrape_record table so the UI can toggle between languages without extra
API calls.

Language detection is heuristic (no external library required):
  - Common German function words trigger a DE classification
  - Everything else is treated as EN

Translation is done in a single LLM call: title and description together
to preserve context. Falls back gracefully if the LLM is unavailable.
"""
from __future__ import annotations

import json
import os
import re
import requests
import logging

log = logging.getLogger(__name__)

# Common German function words for heuristic detection.
# Short corpus check — enough for titles + short descriptions.
_DE_WORDS = frozenset([
    # Conjunctions / prepositions (unambiguous German)
    "und", "oder", "mit", "für", "auf", "bei", "zum", "zur",
    "nach", "über", "unter", "durch", "ohne", "gegen",
    # Articles / determiners
    "die", "der", "das", "ein", "eine", "einer", "eines", "einem", "einen",
    # Pronouns
    "wir", "ihr", "uns", "unser", "euer",
    # Verbs
    "ist", "sind", "wird", "werden", "haben", "hat", "hatte", "werden",
    "bitte", "kommt", "findet", "statt",
    # Event-domain German words (not borrowed English)
    "veranstaltung", "treffen", "vortrag", "abend",
    "monatlich", "wöchentlich", "kostenlos", "kostenfreie",
    "anmeldung", "teilnahme", "einladung", "thema",
    "jeden", "nächste", "diesen", "diesmal",
])

_LLM_BASE_URL = (
    os.getenv("CM_LLM_BASE_URL")
    or os.getenv("FEATHERLESS_BASE_URL", "https://api.featherless.ai/v1")
)
_LLM_API_KEY = (
    os.getenv("CM_LLM_API_KEY")
    or os.getenv("FEATHERLESS_API", "")
)
_LLM_MODEL = os.getenv("CM_LLM_MODEL", "Qwen/Qwen3-8B")

_TRANSLATE_SYSTEM = """\
You are a precise translator. The user will give you a JSON object with fields
"title" and "description". Translate both fields into the requested target
language (English or German). Keep proper nouns, URLs, and event names as-is.
Respond ONLY with a valid JSON object with the same two keys, no markdown fences,
no commentary. If a field is null or empty, return it as null."""


def detect_language(text: str) -> str:
    """Return 'de' if text appears to be German, 'en' otherwise."""
    if not text:
        return "en"
    tokens = re.findall(r"\b\w+\b", text.lower())
    if not tokens:
        return "en"
    de_count = sum(1 for t in tokens if t in _DE_WORDS)
    ratio = de_count / len(tokens)
    return "de" if ratio > 0.06 else "en"


def _llm_translate(title: str | None, description: str | None, target_lang: str) -> tuple[str | None, str | None]:
    """
    Call the LLM to translate title+description to target_lang ("en" or "de").
    Returns (translated_title, translated_description).
    Falls back to (title, description) on any error.
    """
    if not _LLM_API_KEY:
        return title, description

    payload_text = json.dumps({"title": title, "description": description}, ensure_ascii=False)
    lang_label = "English" if target_lang == "en" else "German"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {_LLM_API_KEY}",
    }
    body = {
        "model": _LLM_MODEL,
        "messages": [
            {"role": "system", "content": _TRANSLATE_SYSTEM},
            {"role": "user", "content": f"Translate to {lang_label}:\n{payload_text}"},
        ],
        "temperature": 0.0,
    }
    try:
        url = f"{_LLM_BASE_URL.rstrip('/')}/chat/completions"
        resp = requests.post(url, json=body, headers=headers, timeout=(10, 60))
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"].strip()
        # Strip Qwen3 <think> blocks
        raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
        # Strip markdown fences
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw).strip()
        parsed = json.loads(raw)
        return parsed.get("title") or title, parsed.get("description") or description
    except Exception as exc:
        log.debug("translation.failed target=%s error=%s", target_lang, exc)
        return title, description


def fill_translations(
    title: str | None,
    description: str | None,
) -> dict[str, str | None]:
    """
    Detect language, translate to the other language.
    Returns dict with keys: title_en, description_en, title_de, description_de.
    """
    corpus = f"{title or ''} {description or ''}".strip()
    detected = detect_language(corpus)

    if detected == "de":
        title_de = title
        desc_de = description
        title_en, desc_en = _llm_translate(title, description, "en")
    else:
        title_en = title
        desc_en = description
        title_de, desc_de = _llm_translate(title, description, "de")

    return {
        "title_en":       title_en,
        "description_en": desc_en,
        "title_de":       title_de,
        "description_de": desc_de,
        "detected_language": detected,
    }
