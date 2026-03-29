# CLAUDE.md

## Environment

- Python 3.12+ required
- Virtual environment at `.venv/` — activate before running anything
- Dependencies managed via `pyproject.toml`
- AWS Strands Multi-agent framework: https://github.com/strands-agents

## Commands

```bash
# Activate virtual environment (Windows)
.venv\Scripts\activate

# Run the application
python main.py

# Install dependencies (after adding to pyproject.toml)
pip install -e .
```

# Community Matcher Orchestrator

## Purpose

This document is the master overview for a Python implementation of a **Community Finder / Recommendation Orchestrator** using the **AWS Strands** framework. The orchestrator's job is to interview the user, build a structured profile, determine whether enough information has been collected, dispatch downstream discovery agents, aggregate results, rank them against user preferences, and support iterative refinement.

This repo should be implemented so Claude Code can consume the design **one markdown file at a time**. This file is the top-level plan and program structure. Later files should each cover a single bounded concern.

---

## Product Goal

A user says something like:

> I am new to Berlin and want to find my people.

The system should:

1. ask proactive, high-value clarifying questions,
2. build a structured preference profile,
3. infer likely community archetypes,
4. dispatch targeted discovery agents,
5. rank communities, groups, meetups, and events,
6. explain why the results fit,
7. refine recommendations based on feedback.

This is **not** a plain keyword event search. It is a profile-driven matching system.

---

## Design Principles

### 1. Ask before searching

The orchestrator should avoid jumping directly into search when the request is underspecified.

### 2. Use structured state

The system should maintain a typed profile object, not rely on free-form chat history alone.

### 3. Minimize user fatigue

Ask only the next 1 to 3 highest-value questions instead of dumping a giant questionnaire.

### 4. Separate orchestration from retrieval

The orchestrator should coordinate agents rather than doing all work itself.

### 5. Explain the match

Recommendations should say why they fit, not just list results.

### 6. Support refinement

User feedback such as “too corporate” or “too noisy” should update the profile and trigger re-ranking or fresh search.

### 7. Preserve guardrails

The system should use preference matching, not creepy or discriminatory profiling.

---

## Why AWS Strands

AWS Strands is a good fit because we need:

* explicit multi-agent coordination,
* bounded agent responsibilities,
* reusable tool-enabled agents,
* orchestration logic with structured handoffs,
* a clear path for later expansion into production infrastructure.

The Strands implementation should keep the orchestrator as the top-level controller and delegate specialized work to narrower agents.

---

## Proposed Agent Topology

### Top-Level Agent

* **OrchestratorAgent**

  * Owns session flow
  * Builds and updates the user profile
  * Chooses next-best questions
  * Checks profile sufficiency
  * Creates discovery plans
  * Dispatches downstream agents
  * Aggregates and ranks results
  * Handles refinement loops

### Supporting Agents

* **ProfileBuilderAgent**

  * Extracts structured profile updates from conversation turns
  * Maintains confidence scores
  * Suggests missing high-value fields

* **QuestionPlannerAgent**

  * Chooses the next 1 to 3 clarification questions
  * Optimizes for information gain and user patience

* **CommunityArchetypeAgent**

  * Maps profile signals to archetype weights
  * Example archetypes: hacker/maker, AI/data, startup/professional, nerdy-social, family-friendly nerd, queer-inclusive geek, grassroots activist-tech

* **SearchPlannerAgent**

  * Converts profile + archetypes into query plans for downstream search tools or source-specific retrievers

* **EventDiscoveryAgent**

  * Searches for events and one-off activities

* **GroupDiscoveryAgent**

  * Searches for recurring communities, standing groups, associations, clubs, and regular meetups

* **VibeClassifierAgent**

  * Reads candidate descriptions and classifies newcomer-friendliness, corporate-ness, alcohol centrality, energy, cliquishness, family-friendliness, etc.

* **RiskSanityAgent**

  * Filters dead groups, spammy events, stale listings, suspicious communities, extremist signals, obvious bad fits

* **RankingAgent**

  * Scores and orders candidates against the structured profile

* **RecommendationWriterAgent**

  * Produces user-facing recommendation buckets and fit explanations

---

## System Workflow

### Phase A: Intake

Input is a free-form user request.

Example:

* “I am new to Berlin and want a very techy group.”

The orchestrator initializes a session profile and extracts obvious signals.

### Phase B: Discovery Questions

The orchestrator asks the fewest high-value questions needed to clarify:

* user goal,
* interest cluster,
* desired social mode,
* environment preference,
* logistics,
* language,
* dealbreakers.

### Phase C: Sufficiency Check

Once minimum profile sufficiency is reached, the orchestrator stops asking and starts planning search.

### Phase D: Search Dispatch

The orchestrator creates task briefs and sends them to discovery agents.

### Phase E: Aggregation and Classification

Candidate results are normalized, deduplicated, vibe-classified, sanity-checked, and scored.

### Phase F: Recommendation Output

Results are presented in explanatory buckets such as:

* Best overall fit
* Best easy first step
* Best recurring community
* Stretch option
* Avoid if you dislike X

### Phase G: Refinement

User feedback updates the profile and triggers re-ranking or re-search.

---

## Core Domain Model

The project should use a typed Python domain model. The exact implementation will be specified in a later markdown file, but the core shape should include:

### UserProfile

Holds:

* user goals,
* interests,
* social preferences,
* environment preferences,
* language preferences,
* logistics,
* budget,
* values / boundaries,
* dealbreakers,
* inferred archetype weights,
* confidence scores.

### ProfileFieldConfidence

Tracks whether a field is:

* explicit,
* inferred-high-confidence,
* inferred-low-confidence,
* unknown.

### CandidateCommunity

Normalized representation of an event, group, venue, or recurring social node.

### CandidateScores

Per-dimension scoring:

* interest alignment,
* vibe alignment,
* newcomer friendliness,
* logistics fit,
* language fit,
* values fit,
* recurrence strength,
* risk/sanity score.

### SearchBrief

Structured handoff from orchestrator to downstream agents.

### RecommendationBundle

Final grouped output presented to the user.

---

## Minimum Viable Fields for Search Readiness

The orchestrator should begin search when all required categories are present.

### Required

* primary goal
* at least one strong interest cluster
* at least one social/vibe preference
* minimum logistics info

### Optional but usually valuable

* language preference
* dealbreakers
* budget sensitivity
* values / ideological intensity tolerance

The orchestrator should not keep interrogating the user once these are known well enough.

---

## Example User Profile Categories

The implementation should support fields like:

* friendship vs networking vs dating-adjacent intent
* hacker/maker vs AI/data vs startup vs nerdy-social preference
* workshops vs talks vs project nights vs drinks vs games
* newcomer-friendly vs deep regular community
* adult-space tolerance vs family-friendly preference
* alcohol comfort
* noise tolerance
* English vs German vs mixed
* preferred districts
* max travel time
* days / times available
* recurrence preference
* hard no’s such as too corporate, too loud, too political, too cliquey, too alcohol-centered

---

## Example Match Dimensions

The ranking model should combine several interpretable dimensions.

Suggested initial weighting:

```python
match_score = (
    0.25 * interest_alignment +
    0.20 * vibe_alignment +
    0.15 * newcomer_friendliness +
    0.10 * logistics_fit +
    0.10 * language_fit +
    0.10 * values_fit +
    0.05 * recurrence_strength +
    0.05 * safety_reputation
)
```

These weights should be configurable.

---

## Python Implementation Strategy

The codebase should be organized into clean modules.

### Suggested repo shape

```text
community_matcher/
  app.py
  config/
    settings.py
  domain/
    profile.py
    candidates.py
    scoring.py
    briefs.py
  orchestrator/
    orchestrator_agent.py
    session_state.py
    sufficiency.py
    question_selection.py
  agents/
    profile_builder_agent.py
    question_planner_agent.py
    archetype_agent.py
    search_planner_agent.py
    event_discovery_agent.py
    group_discovery_agent.py
    vibe_classifier_agent.py
    risk_sanity_agent.py
    ranking_agent.py
    recommendation_writer_agent.py
  tools/
    search_tools.py
    location_tools.py
    normalization_tools.py
  prompts/
    orchestrator_prompts.py
    profiling_prompts.py
    ranking_prompts.py
  tests/
    test_profile_builder.py
    test_sufficiency.py
    test_question_selection.py
    test_ranking.py
    test_end_to_end_intake.py
  docs/
    00_overview_and_sprint_plan.md
    01_domain_model.md
    02_orchestrator_flow.md
    03_question_strategy.md
    04_strands_agent_design.md
    05_search_and_ranking.md
    06_python_skeleton.md
    07_test_plan.md
```

---

## Sprint Plan

The project should be delivered in bounded sprint phases so Claude Code can implement safely and incrementally.

# Sprint 0 — Foundations and Skeleton

## Goal

Create the project structure, domain stubs, configuration layout, and a no-op orchestration path.

## Deliverables

* repo scaffolding
* Python package structure
* dependency file
* Strands app bootstrap
* stub agents and interfaces
* typed domain placeholders
* session state object
* basic README

## Acceptance Criteria

* project runs locally
* imports resolve cleanly
* orchestrator can accept a mock user request and return a placeholder response
* tests run successfully even if most are scaffolds

---

# Sprint 1 — Profile Model and Intake State

## Goal

Implement the typed `UserProfile`, profile confidence tracking, profile update logic, and intake session state.

## Deliverables

* concrete domain models
* profile merge/update rules
* confidence metadata
* support for explicit vs inferred fields
* session persistence for a single conversation

## Acceptance Criteria

* a conversation turn can update the profile deterministically
* profile state serializes to JSON cleanly
* unit tests cover merge behavior and confidence propagation

---

# Sprint 2 — Question Strategy and Sufficiency Logic

## Goal

Teach the orchestrator to decide what to ask next and when to stop asking.

## Deliverables

* question bank
* adaptive question selection strategy
* sufficiency rubric
* logic for next-best-question planning

## Acceptance Criteria

* given partial profiles, the system selects sensible next questions
* the orchestrator asks at most 1 to 3 questions per turn
* the orchestrator transitions to search planning once sufficient profile data exists

---

# Sprint 3 — Archetypes and Search Planning

## Goal

Infer community archetypes and turn them into structured search briefs.

## Deliverables

* archetype scoring logic
* search brief model
* translation from profile → query strategy
* support for multiple candidate query families

## Acceptance Criteria

* the system generates a search brief with profile summary, archetypes, constraints, and query intents
* search briefs are deterministic enough for testing

---

# Sprint 4 — Discovery Agents and Candidate Normalization

## Goal

Implement event/group retrieval interfaces and normalize results.

## Deliverables

* event discovery agent contract
* group discovery agent contract
* candidate normalization pipeline
* deduplication rules

## Acceptance Criteria

* multiple candidate sources can be merged into a common format
* duplicate events / groups are collapsed cleanly
* normalized candidates can be passed into later scoring stages

---

# Sprint 5 — Vibe Classification, Risk Checks, and Ranking

## Goal

Score candidates according to the user profile and filter bad results.

## Deliverables

* vibe classification schema
* risk/sanity checks
* weighted ranking logic
* explanation fragments for score contributors

## Acceptance Criteria

* candidate ranking is explainable and testable
* obvious bad fits are demoted or removed
* per-dimension scores are preserved for later explanation

---

# Sprint 6 — Recommendation Writing and Refinement Loop

## Goal

Produce polished recommendation bundles and support post-result feedback.

## Deliverables

* recommendation bundle formatter
* fit explanations
* follow-up refinement prompts
* profile updates from recommendation feedback

## Acceptance Criteria

* results are grouped into meaningful buckets
* explanations reference the profile accurately
* feedback such as “too corporate” changes later rankings

---

# Sprint 7 — Hardening, Evaluation, and Demo Readiness

## Goal

Make the system robust enough for a demo or pilot.

## Deliverables

* end-to-end evaluation flows
* synthetic user scenarios
* edge-case handling
* observability and logging
* polished developer docs

## Acceptance Criteria

* demo flows work reliably for several user archetypes
* logs make orchestration decisions inspectable
* failures degrade gracefully instead of collapsing into nonsense

---

## Suggested Markdown Breakdown for Claude Code

Each markdown file should be narrow and implementation-oriented.

1. **00_overview_and_sprint_plan.md**

   * overall architecture
   * sprint plan
   * repo structure

2. **01_domain_model.md**

   * Pydantic/dataclass models
   * field definitions
   * confidence tracking
   * JSON examples

3. **02_orchestrator_flow.md**

   * state machine
   * session transitions
   * control flow pseudocode

4. **03_question_strategy.md**

   * question bank
   * question selection heuristics
   * sufficiency scoring rules

5. **04_strands_agent_design.md**

   * agent responsibilities
   * Strands wiring
   * tool contracts and handoff payloads

6. **05_search_and_ranking.md**

   * search brief design
   * candidate normalization
   * ranking and explanation logic

7. **06_python_skeleton.md**

   * starter code skeletons
   * module-level pseudocode
   * interface definitions

8. **07_test_plan.md**

   * unit tests
   * scenario tests
   * evaluation cases

---

## Initial Technical Assumptions

* language: Python 3.11+
* orchestration: AWS Strands
* modeling: Pydantic or dataclasses
* tests: pytest
* logging: structured logging
* persistence for MVP: in-memory session state, optional JSON snapshotting
* external search providers: abstracted behind tool interfaces so the retrieval layer can be swapped later

---

## Key Risks

### 1. Over-questioning users

Mitigation: hard cap per turn, sufficiency threshold, information-gain-based selection.

### 2. Weak vibe inference

Mitigation: keep vibe classifications probabilistic and explainable; allow user correction.

### 3. Retrieval quality variance

Mitigation: normalize candidates, use multiple discovery paths, re-rank aggressively.

### 4. Creepy or sensitive profiling

Mitigation: ask for atmosphere preferences, not protected-attribute inference.

### 5. Agent sprawl

Mitigation: keep a strong orchestrator contract and tightly bounded agent responsibilities.

---

## Definition of Done for MVP

The MVP is done when:

* a user can describe the type of people and events they want,
* the orchestrator asks intelligent clarifying questions,
* a structured profile is built incrementally,
* the orchestrator knows when it has enough information,
* a search brief is generated,
* candidate communities are ranked against the profile,
* recommendations are returned with reasons,
* user feedback can refine the next round.

---

## Next File To Create

The next markdown file should be:

**01_domain_model.md**

It should define the complete Python domain model for:

* `UserProfile`
* nested preference classes
* `FieldConfidence`
* `SearchBrief`
* `CandidateCommunity`
* `CandidateScore`
* `RecommendationBundle`

It should include concrete field definitions, types, defaults, validation notes, and example JSON payloads.
