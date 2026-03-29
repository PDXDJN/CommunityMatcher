# CommunityMatcher

A profile-driven community recommendation system for Berlin, built with the [AWS Strands](https://github.com/strands-agents) multi-agent framework.

You tell it what kind of people and events you're looking for. It interviews you, builds a structured preference profile, searches a curated database of Berlin communities and events, and returns ranked recommendations with explanations for why each one fits.

---

## Quick Start

```bash
# Activate virtual environment (Windows)
.venv\Scripts\activate

# Run the interactive assistant
python main.py

# Run with a synthetic demo persona
python demo_run.py --persona 1

# Populate the database (scrapes Meetup, Eventbrite, Lu.ma)
python -m community_collector.main --sources meetup,eventbrite,luma --max-results 50
```

**Environment variables** (create a `.env` in the project root):

```
CM_LLM_BASE_URL=https://api.featherless.ai/v1
CM_LLM_API_KEY=your_key_here
CM_LLM_MODEL=Qwen/Qwen3-8B
```

---

## What It Does

A user opens the app and says something like:

> "I'm new to Berlin and want to find my people."

The system then:

1. **Interviews** the user with targeted clarifying questions (at most 3 per turn)
2. **Builds** a typed preference profile — interests, goals, vibe preferences, logistics, dealbreakers
3. **Infers archetypes** — maps the profile to community styles (hacker/maker, AI/data, startup, nerdy-social, etc.)
4. **Searches** the database with natural-language queries translated to SQL
5. **Classifies** each candidate for vibe, newcomer-friendliness, corporate-ness, and alcohol centrality
6. **Ranks** candidates against the profile using a weighted scoring formula
7. **Presents** results in grouped buckets with plain-English fit explanations
8. **Refines** — user feedback like "too corporate" or "show me more" updates the profile and triggers re-ranking or a fresh search

---

## Architecture

```
User input
    │
    ▼
OrchestratorAgent          ← session controller, state machine
    │
    ├── INTAKE              extract initial signals
    ├── QUESTIONING         ask 1–3 targeted questions
    ├── SEARCHING           run full agent pipeline
    │       ├── ArchetypeAgent          map profile → community styles
    │       ├── SearchPlannerAgent      profile → query intents
    │       ├── txt2sql tool            natural language → SQL → DB rows
    │       ├── SemanticSearchTool      synonym expansion + LIKE fallback
    │       ├── VibeClassifierAgent     score atmosphere per candidate
    │       ├── RiskSanityAgent         filter dead/spammy/stale entries
    │       └── RankingAgent            weighted score per candidate
    ├── RECOMMENDING        format output
    │       └── RecommendationWriterAgent   grouped buckets + fit reasons
    └── REFINING            parse feedback, re-rank or re-search
```

The database is populated separately by the **community_collector** scraping pipeline (Meetup via GraphQL, Eventbrite and Lu.ma via Playwright).

---

## Agent Reference

### OrchestratorAgent
`community_matcher/orchestrator/orchestrator_agent.py`

The top-level session controller. Owns the state machine and drives every other agent. Receives one user turn at a time via `process_turn()` and routes it through five phases: **INTAKE → QUESTIONING → SEARCHING → RECOMMENDING → REFINING**.

In the refinement phase it distinguishes between feedback ("too corporate") — which re-ranks cached results without a new DB query — and a new search request ("find something different") — which reruns the full pipeline.

---

### ProfileBuilderAgent
`community_matcher/agents/profile_builder_agent.py`

Extracts structured `UserProfile` field updates from a single conversation turn using the LLM. Returns a partial JSON object with only the fields that can be extracted from that turn. Each field also carries a confidence level (`explicit` vs `inferred`) so the orchestrator knows how reliable the extraction was.

The orchestrator supplements this with a fast keyword scan as a parallel fallback, so profile building still works even without an LLM.

**Called:** on every user turn, during INTAKE and QUESTIONING phases.

---

### QuestionPlannerAgent
`community_matcher/agents/question_planner_agent.py`

Selects the next 1–3 highest-value clarification questions given the current profile state. Uses the LLM to weigh which missing fields matter most and to phrase questions naturally — combining related topics into a single question where possible. Falls back to a static question bank if the LLM is unavailable.

Priority order: primary goal → interest cluster → social mode → logistics → language → dealbreakers → budget.

**Called:** once per turn in the QUESTIONING phase, until profile sufficiency is reached (or after 3 turns maximum).

---

### ArchetypeAgent
`community_matcher/agents/archetype_agent.py`

Rule-based (no LLM). Maps the user's profile signals to a set of community archetype weights. Archetypes are named community styles:

| Archetype | Signals |
|---|---|
| `hacker_maker` | maker interest, project/workshop social mode |
| `ai_data` | AI/data_science interests, learning goal, talks/workshops |
| `startup_professional` | startup interest, networking goal, conferences |
| `nerdy_social` | gaming/tech interests, friends goal, social mode |
| `creative_design` | design/art/music interests, community goal |
| `wellness_fitness` | fitness/wellness interests |
| `grassroots_activist` | community goal, blockchain/cybersecurity interests |

The weights it produces feed directly into the SearchPlanner query selection and are preserved on the session profile for use in ranking.

**Called:** at the start of the search pipeline, before query planning.

---

### SearchPlannerAgent
`community_matcher/agents/search_planner_agent.py`

Rule-based (no LLM). Converts the profile and archetype weights into a `SearchBrief` — a structured object with concrete natural-language query intents for the database. Selects the top-scoring archetypes, maps them to query templates, then adds modifiers for language preference, dealbreakers, and environment constraints.

Example output for a hacker/maker profile:
```
"Find maker spaces, hackathons, project nights and technical workshops"
```

**Called:** once per search, immediately after archetype scoring.

---

### txt2sql tool
`community_matcher/agents/txt2sql_agent.py`

Sends a natural-language question to the LLM, receives a SQL `SELECT` statement, and executes it against the SQLite database. Enforces safety (SELECT-only), strips markdown fences from the model output, and infers source platform from URL when the model omits the `source` column.

Used by both the orchestrator's main pipeline and by the discovery agents.

**Called:** once per search (plus once more after a live scrape, if the DB was empty).

---

### SemanticSearchTool
`community_matcher/agents/semantic_search_tool.py`

A lightweight fallback for queries that don't map to known DB tag values — for example, "I want to tinker with hardware." Expands the query through a static synonym map (e.g. `tinker → maker`, `machine learning → ai, data_science`) then runs a free-text `LIKE` search across title and description columns. Results are merged with and deduplicated against the txt2sql results.

No external ML libraries — runs entirely against the SQLite database.

**Called:** by EventDiscoveryAgent and GroupDiscoveryAgent when txt2sql returns fewer than 3 rows.

---

### EventDiscoveryAgent
`community_matcher/agents/event_discovery_agent.py`

Queries the database for **one-off events** (talks, workshops, demo nights, hackathons) matching the search brief. Uses txt2sql as the primary path and falls back to SemanticSearchTool for open-ended queries.

**Called:** optionally, when the orchestrator needs event-specific results distinct from recurring groups.

---

### GroupDiscoveryAgent
`community_matcher/agents/group_discovery_agent.py`

Queries the database for **recurring communities and standing groups** (weekly meetups, clubs, associations). Uses txt2sql as the primary path with the same semantic fallback. Incorporates archetype labels from the search brief into its query.

**Called:** optionally, alongside EventDiscoveryAgent.

---

### VibeClassifierAgent
`community_matcher/agents/vibe_classifier_agent.py`

Scores each candidate on seven dimensions using the LLM:

| Dimension | Meaning |
|---|---|
| `newcomer_friendliness` | How welcoming to people new to the group |
| `vibe_alignment` | Positive social/nerdy vs boring/corporate feel |
| `is_casual` | Relaxed and social vs structured and formal |
| `is_technical` | Engineering/coding/maker focus |
| `is_creative` | Art/music/design focus |
| `alcohol_centrality` | How central alcohol is to the event |
| `corporate_ness` | Enterprise/investor vibe vs grassroots community |

`alcohol_centrality` and `corporate_ness` feed directly into dealbreaker filtering — if the user said "too corporate" or "too much alcohol", these scores drive which candidates get demoted.

Falls back to keyword matching when the LLM is unavailable.

**Called:** in parallel across all candidates in the search pipeline (up to 8 concurrent threads).

---

### RiskSanityAgent
`community_matcher/agents/risk_sanity_agent.py`

Rule-based filter (no LLM) that scores each candidate for trustworthiness on a 0–1 scale. Penalises: missing title, very short description, no URL, spam signals (MLM, crypto pump, "make money"), and suspiciously promotional language. Candidates scoring below 0.3 are treated as fails.

**Called:** in parallel alongside VibeClassifierAgent, one call per candidate.

---

### RankingAgent
`community_matcher/agents/ranking_agent.py`

Rule-based (no LLM). Computes a weighted `CandidateScores` vector for each classified candidate and sorts them descending by total score.

```python
total = (
    0.25 * interest_alignment    +
    0.20 * vibe_alignment        +
    0.15 * newcomer_friendliness +
    0.10 * logistics_fit         +
    0.10 * language_fit          +
    0.10 * values_fit            +
    0.05 * recurrence_strength   +
    0.05 * risk_sanity_score
)
```

Weights are configurable in `community_matcher/config/settings.py`. The per-dimension scores are preserved on each row so the RecommendationWriter can explain the match.

**Called:** once after vibe and risk classification, and again during re-ranking from cached results.

---

### RecommendationWriterAgent
`community_matcher/agents/recommendation_writer_agent.py`

Template-based (no LLM). Formats the ranked candidates into user-facing output. Groups multiple events from the same organiser or community into a single entry (e.g. "Python Meetup Berlin — 3 upcoming events"). Generates a one-line fit explanation per entry based on which score dimensions were high.

Output is divided into labeled buckets:
- **Best overall fit**
- **Best easy first step** (highest newcomer-friendliness)
- **Best recurring community** (highest recurrence_strength)
- **Also worth a look**

**Called:** once at the end of the search pipeline, and again during refinement re-ranks.

---

## Data Pipeline

The community database is populated by a separate scraping pipeline in `community_collector/`.

```
community_collector/
  main.py                   CLI entry point
  orchestrator.py           async collection pipeline
  adapters/
    meetup_adapter.py       GraphQL API — fast, rich data (~2s/term)
    eventbrite_adapter.py   Playwright browser scraping
    luma_adapter.py         Playwright browser scraping
    berlin_communities_adapter.py   Hand-curated static list of Berlin orgs
  normalization.py          Converts raw records to CommunityEventRecord
  tagging.py                Auto-tags records from keyword taxonomy
  persistence.py            Saves to SQLite + community/keyword tables
  mcp_server.py             MCP server — exposes live scrape as a tool
```

The orchestrator can trigger a live scrape via the MCP server when the database has no matching results, then re-query with fresh data.

---

## Project Structure

```
community_matcher/          Main orchestration package
  orchestrator/             OrchestratorAgent, session state, sufficiency checks
  agents/                   All Strands agent tools
  domain/                   Pydantic models (UserProfile, CandidateCommunity, etc.)
  db/                       SQLite connection layer + schema docs
  config/                   Settings and .env loading
  prompts/                  LLM prompt templates
  tests/                    pytest unit and integration tests
community_collector/        Scraping and data pipeline
  adapters/                 Per-source scrapers
  output/                   SQLite DB + per-run JSON dumps
main.py                     App entry point (interactive CLI)
demo_run.py                 Synthetic persona demo runner
```
