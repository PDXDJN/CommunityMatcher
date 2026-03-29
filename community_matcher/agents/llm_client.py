"""
Shared LLM client for all CommunityMatcher agents.

Configuration via env vars (all optional):
  CM_LLM_BASE_URL  — OpenAI-compatible base URL (default: https://api.featherless.ai/v1)
  CM_LLM_API_KEY   — bearer token
  CM_LLM_MODEL     — model ID (default: Qwen/Qwen3-8B)
"""
from __future__ import annotations
import os
import re
import requests
import structlog

log = structlog.get_logger()

_LLM_BASE_URL = os.getenv("CM_LLM_BASE_URL", "https://api.featherless.ai/v1")
_LLM_API_KEY  = os.getenv("CM_LLM_API_KEY",  "")
_LLM_MODEL    = os.getenv("CM_LLM_MODEL",     "Qwen/Qwen3-8B")


def _strip_thinking(text: str) -> str:
    """Remove Qwen3 <think>…</think> reasoning blocks from output."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def llm_chat(
    system_prompt: str,
    user_message: str,
    temperature: float = 0.0,
    timeout: tuple[int, int] = (10, 60),
) -> str:
    """
    Call the configured LLM and return the assistant content as a plain string.
    Strips Qwen3 <think> blocks automatically.
    Raises requests.HTTPError on non-2xx responses.
    """
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if _LLM_API_KEY:
        headers["Authorization"] = f"Bearer {_LLM_API_KEY}"

    payload = {
        "model": _LLM_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_message},
        ],
        "temperature": temperature,
    }

    url = f"{_LLM_BASE_URL.rstrip('/')}/chat/completions"
    log.debug("llm_client.request", model=_LLM_MODEL, url=url)

    resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
    resp.raise_for_status()

    raw = resp.json()["choices"][0]["message"]["content"].strip()
    return _strip_thinking(raw)


def llm_json(
    system_prompt: str,
    user_message: str,
    temperature: float = 0.0,
) -> str:
    """
    Like llm_chat but also strips markdown code fences (```json … ```).
    Returns the raw JSON string (not parsed). Caller must json.loads() it.
    """
    raw = llm_chat(system_prompt, user_message, temperature=temperature)
    # Strip markdown fences
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\s*```$", "", raw)
    return raw.strip()
