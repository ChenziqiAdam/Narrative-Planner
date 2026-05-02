# GraphRAG Monitoring Metrics

## Current GraphRAG Status

This repository does not currently contain a single end-to-end module named `GraphRAG`.
It does contain a GraphRAG-style planner path:

- semantic event retrieval: `EventVectorStore`
- graph state and coverage: `GraphManager`, `GraphProjector`, optional Neo4j adapter
- memory context: `MemoryCapsule`
- graph-guided decision control: `PlannerDecisionPolicy` and generation hints

The monitor therefore measures whether graph + retrieval context is actually present and whether it affects planner decisions.

## Turn-Level Metrics

Every processed planner turn now adds `debug_trace.graphrag`.

### Enabled Signals

- `semantic_event_retrieval`: whether an event vector store is available
- `graph_summary`: whether graph summary context was built
- `memory_capsule`: whether memory context exists
- `decision_scoring`: whether explicit planner score components were produced

### Retrieval

- `vector_index_size`: number of indexed canonical events
- `retrieved_count`: number of retrieved event candidates
- `retrieved_event_ids`: retrieved event ids
- `top_score`: top semantic similarity score
- `active_event_hit_rate`: overlap between retrieved events and memory active events
- `focus_event_retrieved`: whether the current focus event was retrieved
- `retrieval_error`: non-empty if retrieval failed

### Graph Context

- `coverage_before`, `coverage_after`, `coverage_delta`
- `active_event_count`
- `active_people_count`
- `focus_event_id`
- `focus_missing_slot_count`
- `theme_status_counts`
- `undercovered_theme_rate`

### Grounding

- `canonical_event_count`
- `source_linkage_rate`: canonical events linked to source turns
- `average_event_completeness`
- `people_linkage_rate`

### Decision Influence

- `preferred_action`
- `preferred_focus`
- `action_score_margin`
- `focus_score_margin`
- `top_slot`
- `top_theme_id`
- `graph_recommended_theme_used`

### Quality Flags

- `retrieval_empty_with_index`
- `retrieval_error`
- `empty_graph_context`
- `low_decision_margin`
- `answer_without_grounded_event`

## Session-Level Metrics

`SessionOrchestrator.get_evaluation_state()` now returns `graphrag_metrics`.

Key metrics to watch:

- `semantic_retrieval_turn_rate`
- `average_top_similarity`
- `focus_event_retrieval_hit_rate`
- `average_graph_coverage_delta`
- `average_active_event_count`
- `decision_action_counts`
- `decision_focus_counts`
- `average_action_margin`
- `stale_or_empty_context_turns`

## Suggested Experimental Checks

1. Compare runs with event vector retrieval enabled vs disabled.
2. Compare in-memory graph vs Neo4j-backed graph if Neo4j is available.
3. Track whether high `focus_event_retrieval_hit_rate` improves missing-slot completion.
4. Track whether high `stale_or_empty_context_turns` correlates with repeated questions or low information gain.
5. For weight ablations, compare `decision_action_counts`, `top_slot`, `top_theme_id`, and `average_graph_coverage_delta`.
