"""
GitHub adapter — discovers Berlin-based open-source community organisations.

Uses the public GitHub Search API to find repositories and organisations
tagged with Berlin + community-related topics. This surfaces real, active
tech communities that don't advertise on Meetup or Luma — hackspaces,
language user groups, coding schools, activist-tech orgs, etc.

Key facts:
  - GET https://api.github.com/search/repositories
  - No auth required (60 req/hour unauthenticated; set GITHUB_TOKEN for 5000/hr)
  - Rate-limit headers respected via Retry-After
  - Results: repo name, description, homepage URL, topics, stars, org

Unlike Meetup/Luma/iCal this adapter finds communities (orgs/repos), not
events. All records are given activity="recurring" to signal standing groups.

Environment variables (optional):
  GITHUB_TOKEN — Personal Access Token for higher rate limits (5000 req/hr)
"""
from __future__ import annotations

import asyncio
import os
import time
from typing import Optional

import httpx
from playwright.async_api import Browser  # kept for base class compat, not used

from community_collector.adapters.base import BaseSourceAdapter
from community_collector.config import CollectorConfig
from community_collector.utils.logging_utils import get_logger

log = get_logger("adapter.github")

_SEARCH_URL = "https://api.github.com/search/repositories"
_ORG_URL    = "https://api.github.com/search/users"

_PAGE_DELAY_SECONDS = 1.5   # conservative to stay within unauthenticated rate limit
_MAX_PER_PAGE       = 30

# Repo search queries — space-separated terms, GitHub API format
_BERLIN_TOPIC_QUERIES = [
    "topic:berlin community",
    "topic:berlin meetup",
    "topic:berlin hackerspace",
    "topic:berlin open-source",
    "topic:berlin maker",
]

# Org/user search queries
_BERLIN_ORG_QUERIES = [
    "berlin community type:org",
    "berlin hackerspace type:org",
    "berlin tech nonprofit type:org",
]


def _build_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "CommunityMatcher/1.0",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


class GitHubAdapter(BaseSourceAdapter):
    """
    GitHub community discovery adapter.

    Searches for Berlin-tagged repos and organisations on GitHub. Each result
    represents a standing community (not a one-off event), so records are
    tagged activity="recurring".

    The `search_term` argument augments the queries but the main signal comes
    from the pre-defined topic combinations above.
    """
    source_name = "github"

    async def collect(
        self, browser: Browser, config: CollectorConfig, search_term: str
    ) -> list[dict]:
        log.info("github.collect.start", term=search_term)
        results: list[dict] = []
        seen_urls: set[str] = set()

        headers = _build_headers()

        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            # Repo searches — use fixed topic queries (Berlin-specific by design)
            for q_template in _BERLIN_TOPIC_QUERIES:
                batch = await _search_repos(client, headers, q_template, search_term)
                for r in batch:
                    if r["url"] not in seen_urls:
                        seen_urls.add(r["url"])
                        results.append(r)
                await asyncio.sleep(_PAGE_DELAY_SECONDS)

            # Organisation searches
            for q_template in _BERLIN_ORG_QUERIES:
                batch = await _search_orgs(client, headers, q_template, search_term)
                for r in batch:
                    if r["url"] not in seen_urls:
                        seen_urls.add(r["url"])
                        results.append(r)
                await asyncio.sleep(_PAGE_DELAY_SECONDS)

        log.info("github.collect.done", term=search_term, count=len(results))
        return results


# --------------------------------------------------------------------------
# Internal helpers
# --------------------------------------------------------------------------

def _slugify(term: str) -> str:
    """Convert a search term to a GitHub query token (space-separated)."""
    return " ".join(w.lower() for w in term.split() if w)


async def _search_repos(
    client: httpx.AsyncClient,
    headers: dict,
    query: str,
    search_term: str,
) -> list[dict]:
    results: list[dict] = []
    page = 1

    while len(results) < _MAX_PER_PAGE:
        params = {
            "q":        query,
            "per_page": min(_MAX_PER_PAGE, 30),
            "page":     page,
            "sort":     "updated",
        }
        t0 = time.time()
        try:
            resp = await client.get(_SEARCH_URL, params=params, headers=headers)
        except httpx.RequestError as exc:
            log.warning("github.repos.request_error", error=str(exc))
            break

        if resp.status_code == 403:
            retry_after = int(resp.headers.get("Retry-After", 60))
            log.warning("github.rate_limited", retry_after=retry_after)
            await asyncio.sleep(retry_after)
            continue

        if resp.status_code != 200:
            log.warning("github.repos.http_error", status=resp.status_code,
                        query=query, body=resp.text[:200])
            break

        data = resp.json()
        items = data.get("items") or []
        elapsed = round(time.time() - t0, 2)
        log.info("github.repos.page", query=query[:60], page=page,
                 hits=len(items), elapsed_s=elapsed)

        for item in items:
            raw = _repo_to_raw(item, search_term)
            if raw:
                results.append(raw)

        if len(items) < 30:
            break
        page += 1

    return results


async def _search_orgs(
    client: httpx.AsyncClient,
    headers: dict,
    query: str,
    search_term: str,
) -> list[dict]:
    results: list[dict] = []
    params = {"q": query, "per_page": 30, "type": "org"}

    try:
        resp = await client.get(_ORG_URL, params=params, headers=headers)
        if resp.status_code != 200:
            return []
        data = resp.json()
        for item in (data.get("items") or []):
            raw = _org_to_raw(item, search_term)
            if raw:
                results.append(raw)
    except httpx.RequestError as exc:
        log.warning("github.orgs.request_error", error=str(exc))

    return results


def _repo_to_raw(item: dict, search_term: str) -> Optional[dict]:
    html_url  = item.get("html_url") or ""
    name      = item.get("name") or ""
    full_name = item.get("full_name") or name
    desc      = item.get("description") or ""
    homepage  = item.get("homepage") or ""
    topics    = item.get("topics") or []
    owner     = (item.get("owner") or {}).get("login") or ""
    org_url   = f"https://github.com/{owner}" if owner else html_url

    if not html_url:
        return None

    # Prefer the community homepage over the GitHub URL for source_url
    source_url = homepage.strip() if homepage and homepage.startswith("http") else html_url

    return {
        "url":             source_url,
        "canonical_url":   html_url,
        "title":           full_name.replace("/", " / ").replace("-", " ").replace("_", " ").title(),
        "description":     desc,
        "organizer":       owner,
        "community_name":  owner,
        "city":            "Berlin",
        "country":         "de",
        "is_online":       False,
        "cost_text":       "free",
        "source_record_id": str(item.get("id") or ""),
        "search_term":     search_term,
        "source":          "github",
        "activity":        "recurring",
        "tags":            [t.replace("-", "_") for t in topics],
        "raw_category":    "open_source_community",
    }


def _org_to_raw(item: dict, search_term: str) -> Optional[dict]:
    login   = item.get("login") or ""
    html_url = item.get("html_url") or f"https://github.com/{login}"
    avatar  = item.get("avatar_url") or ""

    if not login:
        return None

    return {
        "url":             html_url,
        "title":           login.replace("-", " ").replace("_", " ").title(),
        "description":     f"GitHub organisation: {login}",
        "organizer":       login,
        "community_name":  login,
        "city":            "Berlin",
        "country":         "de",
        "is_online":       False,
        "cost_text":       "free",
        "source_record_id": str(item.get("id") or ""),
        "search_term":     search_term,
        "source":          "github",
        "activity":        "recurring",
        "raw_category":    "open_source_org",
    }
