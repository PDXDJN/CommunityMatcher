# Stand-In Prototype Spec: Web Data Collector for Community Discovery

## Goal

Build a stand-in prototype of a **web data collector** in **Python** using **Playwright**.

The prototype should collect public-facing event and community information from sites such as:

* Meetup.com
* Eventbrite
* Local community event listings
* Hacker / maker / startup / tech community sites
* Other public event/community websites that are relevant

It should be designed as part of the broader **Hackathon Community Matcher** project.

When useful, reuse components, patterns, config, or utilities from this project:

`C:\python\Event_Finder`

This is **not** intended to be a full production scraper. It is a **stand-in prototype** meant to prove the architecture, define interfaces, and demonstrate collection of structured community/event data.

---

## Core Design Decision

This web data collector should be built as a **tool-like retrieval subsystem**, not as a fully autonomous agent.

Reasoning:

* Browser automation is a deterministic capability.
* The broader orchestrator or recommendation agent should decide **when** to invoke it.
* The collector itself should focus on:

  * visiting sites
  * running searches
  * extracting event/community metadata
  * normalizing output
  * returning structured results
* Keep decision-making outside the collector where possible.

That said, the collector should be structured so it can later be wrapped by an agent.

So the architecture should be:

* **Current phase:** tool / service / library module
* **Future-ready:** callable by an orchestrator agent or MCP server

---

## Desired Outcome

The prototype should:

1. Search selected websites for communities and events.
2. Extract structured information from listings.
3. Normalize the data into a shared schema.
4. Tag results with metadata helpful for later recommendation and filtering.
5. Save the results locally in JSON for inspection.
6. Be modular enough that new source websites can be added easily.

---

## High-Level Scope

### In scope

* Python implementation
* Playwright-based browser automation
* Search and extraction from at least 2 sources initially
* Shared schema for events/communities
* Metadata tagging
* Configurable search inputs
* Logging
* Simple persistence to JSON
* Clear extension points

### Out of scope for prototype

* Full anti-bot resilience
* Account login flows
* CAPTCHA solving
* Infinite-scale scraping
* Full deduplication engine
* Distributed crawling
* Production database integration
* Continuous deployment
* Full legal/compliance workflow automation

---

## Main Use Case

A user says something like:

* “I’m new to Berlin and want to find my people.”
* “Find me tech communities.”
* “Find social coding meetups.”
* “Find startup, AI, hacker, or makerspace groups.”
* “Find events that are technical but still social.”

This collector should retrieve public event/community listings that can later be ranked by the recommendation engine.

---

## Architectural Principles

### 1. Source adapters

Each website should be implemented as its own adapter module.

Examples:

* `meetup_adapter.py`
* `eventbrite_adapter.py`
* `lu.ma_adapter.py`
* `generic_events_adapter.py`

Each adapter should implement a common interface.

### 2. Shared schema

All source-specific fields should be mapped into one normalized record model.

### 3. Config-first search behavior

Search terms, target city, categories, and limits should come from config or function parameters.

### 4. Graceful failure

If one site breaks, the rest should still run.

### 5. Light browser automation, not chaos engineering

Keep it practical. Avoid brittle overengineering. We are trying to collect usable prototype data, not audition for a black-hat opera.

---

## Proposed Project Structure

```text
Event_Finder/
├── community_collector/
│   ├── __init__.py
│   ├── main.py
│   ├── config.py
│   ├── models.py
│   ├── orchestrator.py
│   ├── tagging.py
│   ├── normalization.py
│   ├── persistence.py
│   ├── utils/
│   │   ├── __init__.py
│   │   ├── logging_utils.py
│   │   ├── text_utils.py
│   │   ├── date_utils.py
│   │   └── url_utils.py
│   ├── adapters/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── meetup_adapter.py
│   │   ├── eventbrite_adapter.py
│   │   └── generic_events_adapter.py
│   └── output/
│       ├── raw/
│       └── normalized/
├── tests/
│   ├── test_models.py
│   ├── test_tagging.py
│   ├── test_normalization.py
│   └── test_adapters_smoke.py
├── requirements.txt
└── README.md
```

---

## Functional Requirements

### FR-1: Input parameters

The system should accept the following inputs:

* `city` or `location`
* `search_terms` list
* `category_filters` list
* `date_range` optional
* `max_results_per_source`
* `headless` true/false
* `sources_to_run`

Example:

```python
{
  "location": "Berlin",
  "search_terms": ["AI", "machine learning", "hackerspace", "startup", "python", "data science"],
  "category_filters": ["tech", "maker", "startup", "community"],
  "max_results_per_source": 20,
  "headless": True,
  "sources_to_run": ["meetup", "eventbrite"]
}
```

### FR-2: Source execution

The collector should run one or more enabled source adapters.

### FR-3: Browser-driven retrieval

Each adapter should use Playwright to:

* open the source website
* navigate to search or browse pages
* search by keywords and/or location
* gather listing cards
* click into detail pages when needed
* extract relevant data

### FR-4: Normalized output

Each extracted result should be transformed into a shared record format.

### FR-5: Metadata tags

Each record should be enriched with tags inferred from title, description, venue, organizer, and source.

### FR-6: Local persistence

The tool should save:

* raw adapter output
* normalized output
* run metadata/logs

### FR-7: Duplicate tolerance

Prototype may allow duplicates, but should include a lightweight dedupe hint field, such as:

* canonical URL
* normalized title
* event start datetime
* source name

---

## Non-Functional Requirements

### NFR-1: Modular

A new website adapter should be addable with minimal changes.

### NFR-2: Readable

Claude Code should be able to understand and extend this easily.

### NFR-3: Observable

Include useful logs:

* source started
* page navigated
* search term used
* results found
* parse failures
* source completed

### NFR-4: Safe-by-default

Only collect public information visible without login.

### NFR-5: Respectful crawling

Use conservative behavior:

* modest delays where appropriate
* small page counts
* no high-rate hammering
* identify this as a prototype in comments/docs

---

## Normalized Data Model

Use either Pydantic models or dataclasses.

Recommended normalized model:

```python
from typing import List, Optional
from pydantic import BaseModel

class CommunityEventRecord(BaseModel):
    source: str
    source_record_id: Optional[str] = None
    source_url: str
    canonical_url: Optional[str] = None

    title: str
    description: Optional[str] = None
    organizer_name: Optional[str] = None
    community_name: Optional[str] = None

    event_datetime_start: Optional[str] = None
    event_datetime_end: Optional[str] = None
    timezone: Optional[str] = None

    venue_name: Optional[str] = None
    venue_address: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    is_online: Optional[bool] = None

    cost_text: Optional[str] = None
    currency: Optional[str] = None

    tags: List[str] = []
    audience_signals: List[str] = []
    format_signals: List[str] = []
    topic_signals: List[str] = []

    raw_category: Optional[str] = None
    language: Optional[str] = None

    extraction_timestamp: str
    search_term: Optional[str] = None

    raw_payload: dict = {}
```

---

## Suggested Metadata Tags

The collector should infer tags that will help downstream matching.

### Topic tags

Examples:

* `ai`
* `machine_learning`
* `python`
* `data_science`
* `cybersecurity`
* `robotics`
* `maker`
* `hardware`
* `startup`
* `founders`
* `design`
* `gaming`
* `blockchain`
* `open_source`
* `cloud`
* `devops`

### Format tags

Examples:

* `meetup_event`
* `conference`
* `hackathon`
* `workshop`
* `social`
* `talk`
* `networking`
* `demo_night`
* `coworking`
* `panel`
* `seminar`

### Audience tags

Examples:

* `beginner_friendly`
* `advanced`
* `professional`
* `student_friendly`
* `family_friendly`
* `after_work`
* `founder_focused`
* `developer_focused`
* `research_focused`

### Vibe / environment tags

Examples:

* `technical`
* `casual`
* `career_oriented`
* `community_driven`
* `social_drinking_possible`
* `structured`
* `experimental`
* `grassroots`

### Location / accessibility tags

Examples:

* `online`
* `in_person`
* `central_berlin`
* `evening_event`
* `weekend_event`
* `free`
* `paid`

---

## Adapter Interface

Define a base class or protocol.

```python
from abc import ABC, abstractmethod
from typing import List

class BaseSourceAdapter(ABC):
    source_name: str

    @abstractmethod
    async def collect(self, request: dict) -> List[dict]:
        pass
```

Each adapter should:

1. launch/open browser context
2. navigate to source
3. perform search or browse flow
4. collect listing URLs/cards
5. extract relevant fields
6. return raw source-native dictionaries

Normalization should happen outside the adapter.

---

## Meetup Adapter Expectations

Initial target behavior:

* Open Meetup
* Search by location and keyword
* Collect visible groups/events
* Extract:

  * title
  * URL
  * date/time if visible
  * organizer/group name if visible
  * venue/location if visible
  * short description/snippet
  * category/topic clues

Be pragmatic:

* The site may change.
* DOM selectors may be brittle.
* Use stable selectors where possible.
* Prefer semantic text or URL patterns over hyper-fragile CSS spaghetti.

If Meetup blocks or complicates direct scraping, the adapter should:

* fail gracefully
* log the issue
* return empty list rather than exploding dramatically like a badly written startup demo

---

## Eventbrite Adapter Expectations

Initial target behavior:

* Search for events by city + keyword
* Collect listing cards
* Extract:

  * event title
  * listing URL
  * datetime text
  * venue/location
  * organizer if visible
  * price text if visible
  * category or descriptor text

Again, keep it prototype-simple.

---

## Generic Events Adapter

Build a fallback adapter for sites that are not deeply integrated.

Possible approach:

* Use known search URLs or category pages
* Collect card-like listing blocks
* Extract common fields heuristically
* Return lower-confidence results

This adapter can be weaker than source-specific ones, but useful for expansion.

---

## Playwright Guidance

Use Playwright async API in Python.

Recommended packages:

```text
playwright
pydantic
python-dateutil
tenacity
orjson
pytest
pytest-asyncio
```

Basic patterns to use:

* explicit browser context creation
* configurable headless mode
* timeout handling
* `wait_for_selector` with sane limits
* retries for navigation only where useful
* text extraction helpers
* URL normalization

Avoid:

* giant sleep-based flows
* brittle nth-child selector chains unless absolutely necessary
* mixing scraping logic all over the codebase

---

## Orchestration Flow

Create a lightweight orchestrator module.

### Proposed flow

1. Read request/config
2. Determine enabled adapters
3. Run adapters sequentially first
4. Capture raw outputs per source
5. Normalize each raw record
6. Tag each normalized record
7. Persist outputs
8. Return combined results

Prototype can start sequentially.

Future enhancement:

* run adapters concurrently with `asyncio.gather()`
* isolate failures per adapter

---

## Output Files

Save outputs under timestamped folders.

Example:

```text
community_collector/output/
└── 2026-03-28_170500/
    ├── raw_meetup.json
    ├── raw_eventbrite.json
    ├── normalized_records.json
    ├── run_summary.json
    └── collector.log
```

### `run_summary.json` should include

* run timestamp
* input parameters
* sources executed
* records per source
* normalized total
* errors encountered
* duration

---

## Logging Requirements

Use structured logging where practical.

Log examples:

* `Starting source adapter: meetup`
* `Searching Meetup for term=python location=Berlin`
* `Found 17 listing cards on first page`
* `Failed to parse date for record X`
* `Adapter eventbrite returned 12 raw records`
* `Normalized 21 total records`

---

## Suggested Tagging Strategy

Implement a first-pass rule-based tagging layer.

### Inputs for tagging

* title
* description
* organizer_name
* community_name
* raw_category
* venue_name
* source URL

### Approach

Build keyword maps such as:

```python
TOPIC_KEYWORDS = {
    "ai": ["artificial intelligence", "ai", "llm", "genai", "machine learning"],
    "python": ["python", "pandas", "jupyter"],
    "maker": ["maker", "makerspace", "arduino", "raspberry pi", "3d printing"],
    "startup": ["startup", "founder", "venture", "pitch", "entrepreneur"]
}
```

Use these to populate:

* `tags`
* `topic_signals`
* `audience_signals`
* `format_signals`

Keep this simple now. Fancy embeddings can arrive later wearing a ridiculous cape.

---

## Reuse from `C:\python\Event_Finder`

Before writing new code, inspect the existing project for reusable elements such as:

* config patterns
* logging utilities
* common models
* path helpers
* existing search abstractions
* tagging conventions
* existing event schemas
* output folder conventions

Instruction:

* Reuse existing components where they genuinely fit.
* Do not force reuse if it creates uglier architecture.
* If reusing, clearly document what was reused and why.

---

## Implementation Phases

## Phase 1: Foundation

Build the scaffolding.

Deliverables:

* folder structure
* requirements
* config module
* base adapter interface
* normalized model
* logging setup
* persistence utilities
* main entry point

Exit criteria:

* project runs
* can execute with dummy config
* writes output folder

---

## Phase 2: Meetup adapter

Implement initial Meetup collector.

Deliverables:

* Playwright browser startup
* basic search flow
* extraction of listing cards/details
* raw JSON output
* parser helpers

Exit criteria:

* returns at least some structured records for target test searches
* failure handling works

---

## Phase 3: Eventbrite adapter

Implement second source.

Deliverables:

* Eventbrite search flow
* listing extraction
* normalization mapping

Exit criteria:

* second source working
* combined run produces multi-source output

---

## Phase 4: Normalization and tagging

Implement robust normalized mapping and inferred metadata tags.

Deliverables:

* normalization functions per source
* keyword-based metadata tagging
* run summary generation

Exit criteria:

* output records look coherent and filterable

---

## Phase 5: Hardening the prototype

Improve reliability.

Deliverables:

* retries where appropriate
* better time parsing
* URL normalization
* lightweight dedupe hints
* better error capture
* smoke tests

Exit criteria:

* collector is demoable and not embarrassingly fragile

---

## Phase 6: Future-ready packaging

Prepare it for later system integration.

Deliverables:

* callable API function
* CLI wrapper
* optional FastAPI wrapper or MCP-facing shim
* documentation for orchestrator integration

Exit criteria:

* easy for higher-level recommendation system to call

---

## CLI Requirements

Provide a simple command-line entry point.

Example:

```bash
python -m community_collector.main --location Berlin --terms "AI,python,startup" --sources meetup,eventbrite --max-results 20
```

Expected behavior:

* runs enabled adapters
* saves outputs
* prints summary to console

---

## Main Entry Point Behavior

`main.py` should:

1. parse CLI args
2. build request object
3. invoke orchestrator
4. print:

   * sources run
   * number of raw records per source
   * number of normalized records
   * output folder path
   * any source-level errors

---

## Testing Expectations

Include at least lightweight tests.

### Unit tests

* model validation
* tagging logic
* normalization logic
* text/date helper functions

### Smoke tests

* adapter can initialize
* adapter returns list
* orchestrator handles one adapter failing

Do not try to fully replay live sites in unit tests.
That path leads to brittle sadness.

---

## Error Handling Expectations

Handle these cleanly:

* site unavailable
* selector not found
* timeout
* partial extraction
* missing fields
* invalid dates
* navigation redirect

Rules:

* log the error
* keep the run alive if possible
* preserve partial useful data

---

## Data Quality Expectations

For each record, try to capture these fields in priority order:

### Must-have

* source
* source_url
* title
* extraction_timestamp

### Strongly preferred

* datetime or datetime text
* location or venue
* description/snippet
* organizer/community name

### Nice-to-have

* price
* tags
* language
* online vs in-person

---

## Future Expansion Hooks

Design so the following can be added later:

* additional adapters
* concurrency
* rotating proxies if ever needed
* LLM-assisted metadata extraction
* embedding-based topic inference
* event deduplication and entity resolution
* ranking/scoring integration
* MCP server wrapper
* scheduled collection
* database storage

---

## MCP Positioning

There does not need to be a separate “Playwright MCP” for this prototype.

Recommended approach:

* build this first as a normal Python module/service
* define a clean callable interface
* later expose it via MCP if the broader orchestrator benefits from that

In other words:

* **Playwright = browser automation layer**
* **collector = retrieval tool/service**
* **MCP = optional wrapper layer later**

Do not overcomplicate the first version by building protocol wrappers before the collector itself works.
Classic trap. Very fashionable. Still a trap.

---

## Suggested Public Interface

Aim for something like:

```python
async def collect_community_data(request: dict) -> list[CommunityEventRecord]:
    ...
```

And optionally:

```python
def run_collection(request: dict) -> dict:
    """Sync wrapper that returns summary + records + output paths."""
```

---

## Code Quality Expectations

* Use type hints throughout
* Keep functions small and clear
* Separate extraction from normalization
* Separate normalization from tagging
* Use docstrings on public functions/classes
* Avoid giant god-files full of tangled browser logic

---

## Deliverables Expected from Claude Code

Claude Code should produce:

1. Python package scaffolding
2. Requirements file
3. Base adapter interface
4. At least two source adapters
5. Normalized model definitions
6. Tagging module
7. Persistence module
8. CLI entry point
9. README with run instructions
10. Basic tests

---

## Definition of Done for Prototype

The prototype is complete when:

* it runs locally in Python
* it uses Playwright successfully
* it searches at least 2 relevant websites
* it returns structured normalized records
* it writes JSON output to disk
* it includes inferred metadata tags
* it fails gracefully when a source breaks
* its code structure is clean enough for future integration into the community matcher system

---

## Final Instruction to Claude Code

Build this as a **clean, modular prototype**, not a disposable script.

Bias toward:

* maintainability
* readability
* extensibility
* pragmatic Playwright automation

Do not bias toward:

* premature distributed architecture
* over-agentification
* unnecessary abstraction layers
* cleverness for its own sake

The goal is to create a working **stand-in community/event data collector** that can later be plugged into a larger recommendation or orchestrator system.

A sturdy prototype beats a beautiful mess. Every time.
