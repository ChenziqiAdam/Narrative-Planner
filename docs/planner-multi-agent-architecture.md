# Planner Multi-Agent Architecture Draft

Status: draft v0.1

## 1. Goals

This document proposes a production-oriented architecture for the interview simulator that supports:

- `baseline` and `planner` modes under the same simulation framework
- turn-level question quality evaluation
- session-level coverage and outcome evaluation
- dynamic graph updates for `theme`, `event`, and `people`
- a lightweight memory layer for planning and question generation
- low latency by separating critical-path logic from background enrichment

## 2. Core Design Principles

### 2.1 One source of truth, multiple views

Do not maintain an independent "memory system" and "graph system" with separate truths.

Use one canonical session state, then project it into:

- `graph view`: theme coverage, event structure, people relations, open slots
- `memory view`: compact narrative summary for planning and questioning
- `evaluation view`: turn scores, coverage snapshots, strategy traces

### 2.2 Logical agents are not equal to physical model calls

We should split responsibilities by role, but not force each role to become a separate LLM request.

Recommended split:

- Logical agents:
  - `PlannerAgent`
  - `InterviewerAgent`
  - `ExtractionAgent`
  - `EvaluatorAgent`
- Code services:
  - `SessionStateStore`
  - `MergeEngine`
  - `GraphProjector`
  - `MemoryProjector`
  - `CoverageCalculator`
  - `Orchestrator`

Production best practice:

- keep only `1-2` synchronous model calls on the user-facing path
- move extraction, merging, graph projection, and evaluation off the critical path when possible
- prefer code for deterministic transforms and metrics

### 2.3 Hot path vs cold path

- `hot path`: what must be ready before the next question is returned
- `cold path`: enrichment that can land after the question is returned

Recommended:

- hot path reads the latest committed `memory capsule + graph summary`
- cold path performs extraction, event merge, people merge, graph update, and evaluation

This means planner reads a slightly stale but stable snapshot, usually lagging by at most one turn.

## 3. Recommended Multi-Agent Collaboration

## 3.1 Agent Responsibilities

### A. PlannerAgent

Purpose:

- decide the next interview action
- choose between depth, breadth, clarify, summarize, pause, close
- produce a compact question plan instead of directly writing long natural language

Inputs:

- `PlannerContext`
- current turn transcript
- `memory capsule`
- `graph summary`
- previous evaluation hints

Outputs:

- `QuestionPlan`

### B. InterviewerAgent

Purpose:

- transform `QuestionPlan` into the actual natural-language next question
- control tone, granularity, and phrasing

Inputs:

- `QuestionPlan`
- hot context
- recent transcript

Outputs:

- `InterviewerTurn`

### C. ExtractionAgent

Purpose:

- extract structured event candidates from the latest answer
- return three layers in one output:
  - metadata
  - memory delta
  - graph delta

Inputs:

- current turn
- recent context
- candidate existing events or summaries

Outputs:

- `ExtractionResult`

### D. EvaluatorAgent

Purpose:

- score question quality for each turn
- score overall session performance
- generate fair comparison signals for baseline vs planner

Inputs:

- question
- answer
- pre-turn state
- post-turn state
- selected strategy

Outputs:

- `TurnEvaluation`
- `SessionEvaluation`

## 3.2 Code-First Services

### MergeEngine

Purpose:

- merge extracted candidates into canonical events
- decide create/update/attach/open-loop
- merge people mentions into stable person identities

This should be mostly code, with optional LLM fallback only for borderline cases.

### GraphProjector

Purpose:

- write canonical state into `ThemeNode`, `EventNode`, `PeopleNode`
- update theme status and coverage

### MemoryProjector

Purpose:

- create a compact planning-facing summary
- maintain stable person facts, recent storyline, unresolved clues, contradictions, emotional state

### CoverageCalculator

Purpose:

- compute slot coverage
- compute theme coverage
- compute people coverage
- compute open-loop closure rate

## 4. End-to-End Turn Flow

## 4.1 Recommended Runtime Flow

When the interviewee answers:

1. Persist raw turn into transcript.
2. Load latest committed `SessionState`.
3. Build `PlannerContext` from:
   - recent transcript
   - `memory capsule`
   - `graph summary`
   - previous evaluation hints
4. `PlannerAgent` outputs `QuestionPlan`.
5. `InterviewerAgent` generates the actual next question.
6. Return question to UI immediately.
7. In background, `ExtractionAgent` processes the latest answer.
8. `MergeEngine` reconciles extracted items with canonical events and people.
9. `GraphProjector` updates graph nodes and coverage.
10. `MemoryProjector` updates the memory capsule.
11. `EvaluatorAgent` scores the turn and appends evaluation trace.
12. Next turn uses the newly committed state.

## 4.2 Why this flow is preferred

- planner gets a global view without blocking on graph extraction every turn
- extraction can be slow without harming response latency
- evaluation does not slow down user-facing interaction
- baseline and planner can share the same evaluator and simulator infrastructure

## 5. Recommended Call Topology

## 5.1 Best-practice topology

### Option A: Most practical

- synchronous calls:
  - `Planner + Interviewer` as one LLM call
- asynchronous calls:
  - `ExtractionAgent`
  - `EvaluatorAgent`

Total:

- `1` sync LLM call per turn
- `2` async LLM calls per turn

### Option B: Easier to debug

- synchronous calls:
  - `PlannerAgent`
  - `InterviewerAgent`
- asynchronous calls:
  - `ExtractionAgent`
  - `EvaluatorAgent`

Total:

- `2` sync LLM calls per turn
- `2` async LLM calls per turn

### Option C: Current project direction

The current compare-mode planner path is effectively:

- sync extraction
- sync baseline interviewer

This is not ideal because:

- graph does not actually steer question generation
- extraction blocks the next question
- planner is not a true strategy layer yet

## 6. Unified Session State

```python
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional


ActionType = Literal[
    "DEEP_DIVE",
    "BREADTH_SWITCH",
    "CLARIFY",
    "SUMMARIZE",
    "PAUSE_SESSION",
    "CLOSE_INTERVIEW",
]


@dataclass
class SessionState:
    session_id: str
    mode: Literal["baseline", "planner"]
    created_at: datetime
    updated_at: datetime

    elder_profile: "ElderProfile"
    transcript: List["TurnRecord"] = field(default_factory=list)

    canonical_events: Dict[str, "CanonicalEvent"] = field(default_factory=dict)
    people_registry: Dict[str, "PersonProfile"] = field(default_factory=dict)
    theme_state: Dict[str, "ThemeState"] = field(default_factory=dict)

    memory_capsule: "MemoryCapsule" | None = None
    evaluation_trace: List["TurnEvaluation"] = field(default_factory=list)
    session_metrics: "SessionMetrics" | None = None

    current_focus_theme_id: Optional[str] = None
    pending_jobs: List["BackgroundJobStatus"] = field(default_factory=list)
```

## 7. Data Structure Draft

## 7.1 Transcript Layer

```python
@dataclass
class TurnRecord:
    turn_id: str
    turn_index: int
    timestamp: datetime

    interviewer_question: str
    interviewee_answer: str

    planner_plan: "QuestionPlan | None" = None
    extraction_result: "ExtractionResult | None" = None
    turn_evaluation: "TurnEvaluation | None" = None
```

## 7.2 Stable Elder Profile

```python
@dataclass
class ElderProfile:
    name: Optional[str] = None
    birth_year: Optional[int] = None
    age: Optional[int] = None
    hometown: Optional[str] = None
    background_summary: Optional[str] = None

    stable_facts: Dict[str, Any] = field(default_factory=dict)
```

## 7.3 Memory Capsule

This is not a second truth source. It is a compact read model for planner and interviewer.

```python
@dataclass
class MemoryCapsule:
    session_summary: str
    current_storyline: str
    active_event_ids: List[str] = field(default_factory=list)
    active_people_ids: List[str] = field(default_factory=list)
    open_loops: List["OpenLoop"] = field(default_factory=list)
    contradictions: List["ContradictionNote"] = field(default_factory=list)
    emotional_state: "EmotionalState | None" = None
    recent_topics: List[str] = field(default_factory=list)
    do_not_repeat: List[str] = field(default_factory=list)
```

```python
@dataclass
class OpenLoop:
    loop_id: str
    source_event_id: Optional[str]
    loop_type: Literal["missing_slot", "unexpanded_clue", "conflict", "person_gap"]
    description: str
    priority: float
```

```python
@dataclass
class ContradictionNote:
    note_id: str
    event_ids: List[str]
    description: str
    severity: Literal["low", "medium", "high"]
```

```python
@dataclass
class EmotionalState:
    emotional_energy: float
    cognitive_energy: float
    valence: float
    confidence: float
    evidence: List[str] = field(default_factory=list)
```

## 7.4 Canonical Event Layer

```python
@dataclass
class CanonicalEvent:
    event_id: str
    title: str
    summary: str

    time: Optional[str] = None
    location: Optional[str] = None
    people_ids: List[str] = field(default_factory=list)
    event: Optional[str] = None
    feeling: Optional[str] = None
    reflection: Optional[str] = None
    cause: Optional[str] = None
    result: Optional[str] = None
    unexpanded_clues: List[str] = field(default_factory=list)

    theme_id: Optional[str] = None
    source_turn_ids: List[str] = field(default_factory=list)

    completeness_score: float = 0.0
    confidence: float = 0.0
    merge_status: Literal["new", "updated", "merged", "uncertain"] = "new"
```

## 7.5 Person Layer

```python
@dataclass
class PersonProfile:
    person_id: str
    display_name: str
    aliases: List[str] = field(default_factory=list)
    relation_to_elder: Optional[str] = None
    summary: Optional[str] = None
    related_event_ids: List[str] = field(default_factory=list)
    stable_attributes: Dict[str, Any] = field(default_factory=dict)
```

## 7.6 Theme Layer

```python
@dataclass
class ThemeState:
    theme_id: str
    title: str
    status: Literal["pending", "mentioned", "exhausted"]
    priority: int

    expected_slots: List[str] = field(default_factory=list)
    filled_slots: Dict[str, bool] = field(default_factory=dict)
    extracted_event_ids: List[str] = field(default_factory=list)
    open_question_count: int = 0

    completion_ratio: float = 0.0
    exploration_depth: int = 0
```

## 7.7 Planner Input and Output

```python
@dataclass
class PlannerContext:
    session_id: str
    turn_index: int
    elder_profile: ElderProfile
    recent_transcript: List[TurnRecord]
    graph_summary: "GraphSummary"
    memory_capsule: MemoryCapsule
    last_turn_evaluation: "TurnEvaluation | None"
```

```python
@dataclass
class GraphSummary:
    overall_coverage: float
    theme_coverage: Dict[str, float]
    slot_coverage: Dict[str, float]
    people_coverage: float
    current_focus_theme_id: Optional[str]
    active_event_ids: List[str] = field(default_factory=list)
    unresolved_theme_ids: List[str] = field(default_factory=list)
```

```python
@dataclass
class QuestionPlan:
    plan_id: str
    primary_action: ActionType
    tactical_goal: str
    target_theme_id: Optional[str]
    target_event_id: Optional[str]
    target_person_id: Optional[str]
    target_slots: List[str] = field(default_factory=list)
    tone: str = "EMPATHIC_SUPPORTIVE"
    strategy: str = "OBJECT_TO_EMOTION"
    reasoning_trace: List[str] = field(default_factory=list)
    candidate_questions: List[str] = field(default_factory=list)
```

## 7.8 Extraction Output

One extraction call should produce all three layers.

```python
@dataclass
class ExtractionResult:
    turn_id: str
    metadata: "ExtractionMetadata"
    memory_delta: "MemoryDelta"
    graph_delta: "GraphDelta"
```

```python
@dataclass
class ExtractionMetadata:
    extractor_version: str
    confidence: float
    source_spans: List[str] = field(default_factory=list)
    is_incremental_update: bool = False
    matched_event_id: Optional[str] = None
```

```python
@dataclass
class MemoryDelta:
    summary_updates: List[str] = field(default_factory=list)
    new_open_loops: List[OpenLoop] = field(default_factory=list)
    contradiction_notes: List[ContradictionNote] = field(default_factory=list)
    emotional_state_update: EmotionalState | None = None
```

```python
@dataclass
class GraphDelta:
    event_candidates: List[CanonicalEvent] = field(default_factory=list)
    people_candidates: List[PersonProfile] = field(default_factory=list)
    theme_hints: List[str] = field(default_factory=list)
```

## 7.9 Evaluation Layer

```python
@dataclass
class TurnEvaluation:
    turn_id: str
    question_quality_score: float
    information_gain_score: float
    non_redundancy_score: float
    slot_targeting_score: float
    emotional_alignment_score: float
    planner_alignment_score: float
    notes: List[str] = field(default_factory=list)
```

```python
@dataclass
class SessionMetrics:
    overall_theme_coverage: float
    overall_slot_coverage: Dict[str, float]
    people_coverage: float
    open_loop_closure_rate: float
    contradiction_resolution_rate: float
    average_turn_quality: float
    average_information_gain: float
```

## 8. What Belongs to Graph vs Memory

### Graph should answer

- which themes are under-covered
- which events exist
- which slots are missing
- which people are involved
- which clues remain unexpanded
- which relations exist across events and people

### Memory should answer

- who this elder is in one compact summary
- what we are currently talking about
- what was just asked
- what should not be repeated
- what emotional tone the next question should use
- which unresolved clues are most salient right now

Short rule:

- graph = structured global world model
- memory = compact planner-facing narrative state

## 9. Merge Strategy Best Practice

## 9.1 Event merge

Recommended pipeline:

1. deterministic filter:
   - same time window
   - overlapping people
   - similar location
2. semantic similarity:
   - event summary embedding or text similarity
3. optional LLM adjudication only when score is uncertain

Outputs:

- `create_new_event`
- `update_existing_event`
- `attach_as_related_event`
- `leave_unresolved_for_review`

## 9.2 People merge

Use code-first alias normalization:

- pronoun or kinship normalization
- relation dictionary
- alias mapping
- fallback LLM resolution for ambiguous mentions

## 10. Evaluation Design

## 10.1 Turn-Level Evaluation

For each question, evaluate:

- relevance to current context
- information gain
- non-redundancy
- whether it targets missing slots
- whether it follows planner strategy
- whether the tone matches user state

## 10.2 Session-Level Evaluation

At the end of the session, evaluate:

- theme coverage
- slot coverage
- people coverage
- ratio of high-value events collected
- unresolved clue closure rate
- contradiction resolution rate
- average turn quality

Important:

Do not use only `overall_coverage` as the final score.

Recommended final score should be a weighted combination of:

- `35%` theme coverage
- `25%` slot coverage
- `15%` people coverage
- `15%` average turn quality
- `10%` open-loop closure and contradiction handling

## 11. Fair Baseline vs Planner Comparison

To compare fairly:

- both modes must use the same interviewee simulator
- both modes must use the same extractor and evaluator
- both modes must share the same state schema
- the only real difference should be whether `PlannerContext` is used to steer the next question

Recommended experiment setup:

- `baseline`: interviewer reads transcript only
- `planner`: interviewer reads `QuestionPlan + transcript + memory capsule + graph summary`
- both are scored by the same evaluator

## 12. Suggested Module Layout

```text
src/
  orchestration/
    session_orchestrator.py
    state_store.py
    background_jobs.py

  agents/
    planner_agent.py
    interviewer_agent.py
    extraction_agent.py
    evaluator_agent.py
    interviewee_agent.py

  state/
    models.py
    session_state.py
    planner_context.py
    evaluation_models.py

  services/
    merge_engine.py
    graph_projector.py
    memory_projector.py
    coverage_calculator.py
    summarizer.py

  adapters/
    llm_client.py
    websocket_broadcaster.py
    persistence.py
```

## 13. Migration Path

### Phase 1

- keep current compare UI
- introduce `SessionState`
- keep current graph manager
- add `MemoryCapsule`
- add evaluator off the critical path

### Phase 2

- make planner produce `QuestionPlan`
- let interviewer read planner output
- stop using pure baseline generation in planner mode

### Phase 3

- move event extraction fully async in compare mode
- wire merge engine into canonical events
- add people projector

### Phase 4

- fuse planner + interviewer if latency is still too high
- keep evaluator and extractor async

## 14. Immediate Refactoring Targets in Current Codebase

- use `StreamingInterviewEngine` as the long-term orchestration direction, not `PlannerInterviewAgent` wrapper
- stop making planner mode call baseline question generation directly
- pass `existing_events` into extraction prompts
- actually wire `find_similar_event` and `extract_incremental`
- add `PeopleNode` write path instead of returning empty `people_nodes`
- ensure theme matching does not rely on fields that are missing from `ThemeNode`

## 15. Recommended Next Artifact

The next concrete implementation artifact should be a code-level schema file, for example:

- `src/state/models.py`

It should define:

- `SessionState`
- `TurnRecord`
- `QuestionPlan`
- `ExtractionResult`
- `MemoryCapsule`
- `TurnEvaluation`

That file becomes the contract between compare mode, planner mode, graph updates, and evaluation jobs.
