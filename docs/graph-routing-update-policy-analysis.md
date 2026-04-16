# Graph Routing And Update Policy Analysis

## Question

Can graph mapping use the same low-frequency update mechanism as the dynamic elder profile?

Short answer: partially, but not directly.

The profile is a derived, stable guidance layer. It is safe to update it less often because a stale profile usually only affects style and broad planning guidance.

The graph is a working memory/control layer. It drives current event focus, missing slots, theme coverage, people coverage, and next-step decision scores. If graph updates lag too much, the planner can ask for details already provided or miss a newly introduced event.

## Current Update Logic

Current `SessionOrchestrator.process_user_response()` does this synchronously on every user answer:

1. Build `pre_graph_summary`.
2. Call `ExtractionAgent.extract()`.
3. Call `MergeEngine.merge()`.
4. Index touched events.
5. Call `GraphProjector.apply_projection()`.
6. Rebuild `theme_state`.
7. Refresh `MemoryProjector`.
8. Build `post_graph_summary`.
9. Build `generation_hints`.
10. Generate the next question.
11. Schedule turn evaluation.
12. Optionally schedule dynamic profile update.

`GraphProjector.apply_projection()` itself is deterministic and cheap. It:

- resolves a theme for each touched canonical event,
- creates or updates event nodes,
- updates theme slots,
- recomputes coverage delta.

The expensive and latency-sensitive parts are earlier: extraction and merge. Graph projection is only expensive indirectly because it currently depends on waiting for extraction and merge every turn.

## Is Current Logic Complete Enough?

It is functionally straightforward and observable, but not yet architecturally complete for a production interview loop.

Strengths:

- Simple one-turn consistency: the next question sees the latest extracted/merged graph state.
- Graph summary, memory capsule, generation hints, and debug trace are aligned in the same turn.
- Deterministic projection keeps graph as a view over canonical session state.

Gaps:

- No lightweight routing decision before extraction/merge.
- No hot-path vs cold-path split in the current implementation, even though project architecture docs recommend it.
- No explicit "skip/update/macro-planning" decision trace for graph work.
- Every answer pays extraction latency, even if the answer is a short acknowledgement, refusal, fatigue signal, or purely emotional response.
- Graph updates are all-or-nothing; there is no quick local projection for obvious slot fills versus full macro graph refresh.
- If extraction fails or is slow, the entire next question is delayed.

## Recommended Pattern

Add a lightweight `TurnRoutingPolicy` before extraction.

The policy should classify the latest user answer into one of four routes:

- `fast_reply_recent_context`: reply using recent 5 turns, memory capsule, and previous graph snapshot; do not block on extraction.
- `graph_guided_planning`: use the existing graph summary and memory capsule for macro planning, but do not update graph before replying.
- `graph_update_required`: run extraction/merge/projection before generating the next question because the answer likely contains new event/person/slot information needed immediately.
- `defer_graph_update`: return the next question first, then run extraction/merge/projection in the background so the next turn sees updated state.

This mirrors profile gating conceptually, but with stricter triggers for graph update because graph data affects immediate control decisions.

## Suggested Routing Signals

Fast reply route:

- answer length is short, e.g. under 20-30 Chinese characters or under 15 English words,
- answer is a backchannel or acknowledgement,
- answer expresses fatigue or asks to pause,
- no clear time/location/person/event/reflection markers,
- previous graph snapshot is recent enough.

Graph-guided planning route:

- low information gain for 2+ turns,
- current event has few missing slots,
- theme coverage is imbalanced,
- user seems to be drifting or fatigued,
- planner needs macro theme selection more than new extraction.

Graph update required route:

- answer contains time, location, person, relation, cause/result, strong feeling/reflection,
- likely introduces a new event,
- likely fills a missing slot for the current event,
- contains contradiction or clarification,
- current pending action was a targeted slot question and user answered concretely.

Deferred graph update route:

- answer seems useful but not needed to choose the immediate next question,
- answer is long but mostly narrative continuation,
- graph update can safely be one turn stale,
- current focus can be continued from recent transcript alone.

## Proposed Hot Path / Cold Path

Hot path should be:

1. Append raw `TurnRecord`.
2. Route the turn with cheap rules and current state.
3. If route is `fast_reply_recent_context`, generate with recent transcript + memory only.
4. If route is `graph_guided_planning`, generate with existing graph summary + memory + decision policy.
5. If route is `graph_update_required`, run extraction/merge/projection synchronously.
6. If route is `defer_graph_update`, generate first and schedule background extraction/merge/projection.

Cold path should be:

- extraction,
- merge,
- graph projection,
- memory refresh,
- profile projection,
- evaluation.

The existing dynamic profile updater is already cold-path. The graph updater can become conditionally hot-path only when the current turn provides information needed for the next question.

## Best Practice References

The design aligns with common agent/RAG orchestration patterns:

- Router pattern: classify input and dispatch to the right specialized path before doing heavier work.
- Conditional routing: route execution based on current state, tool calls, or classification output.
- Background memory processing: avoid processing every message immediately when messages arrive quickly; defer or debounce work to reduce redundant processing and token cost.
- Query/source routing: decide whether to use summarization, semantic retrieval, or multiple tools based on the query and available choices.

This repo does not need to adopt LangGraph or LlamaIndex to use these patterns. A small code-first router is enough and easier to evaluate.

External references:

- LangGraph Graph API: conditional edges route execution based on state, and conditional entry points can choose the first node when input arrives.
- LlamaIndex Routers: router modules select one or more choices from metadata, commonly choosing between summarization and semantic search paths.
- LangMem delayed background memory processing: background/debounced processing avoids redundant work, incomplete mid-conversation context, and unnecessary token use.

Project references:

- `docs/planner-multi-agent-architecture.md` already recommends a hot path / cold path split.
- `docs/planner-engineering-roadmap.md` lists extraction, merge, graph projection, memory projection, and evaluation as background work in the target architecture.
- `docs/dynamic-profile-planner-integration.md` implements a low-frequency derived-profile updater; graph routing can reuse the trigger/trace style, but should keep stricter immediate-update rules.

## Proposed State And Debug Trace

Add a structured routing decision:

```python
@dataclass
class TurnRoutingDecision:
    route: Literal[
        "fast_reply_recent_context",
        "graph_guided_planning",
        "graph_update_required",
        "defer_graph_update",
    ]
    confidence: float
    reasons: list[str]
    signals: dict[str, float | str | bool]
```

Add to debug trace:

```json
{
  "routing": {
    "route": "graph_update_required",
    "confidence": 0.82,
    "reasons": ["targeted_slot_answer", "contains_person_marker"],
    "signals": {
      "answer_length": 92,
      "has_time_marker": false,
      "has_person_marker": true,
      "targeted_slot": "people",
      "graph_staleness_turns": 0
    }
  }
}
```

## Implementation Plan

Phase 1: Add route observability without changing behavior.

- Add `TurnRoutingPolicy`.
- Compute route before extraction.
- Write route into `debug_trace.routing`.
- Still execute current synchronous extraction/merge/projection.
- Compare route predictions against actual extraction gain.

Phase 2: Enable safe fast path.

- For high-confidence `fast_reply_recent_context`, skip synchronous extraction.
- Schedule extraction/merge/projection in background.
- Generate next question from recent transcript + previous graph summary.

Phase 3: Enable deferred update.

- For `defer_graph_update`, generate first and update graph in background.
- Track `graph_update_lag`.

Phase 4: Full route experiment.

- Compare always-sync baseline vs routed graph update.
- Check latency, information gain, repeated questions, slot coverage, theme coverage, graph lag, and failed extraction recovery.

## Recommended Experiments

Sample experiment config: `docs/graph-routing-experiments/graph_routing_ablation.sample.json`.

Experiment A: Always synchronous graph update.

- Current behavior.

Experiment B: Observe-only routing.

- Same behavior as current, but logs route decisions.

Experiment C: Fast-path only.

- Skip sync update only for high-confidence low-information turns.

Experiment D: Fast-path plus deferred update.

- Defer graph update when the answer has medium information but is not needed immediately.

Metrics:

- p50/p95 turn latency,
- average information gain,
- repeated question count,
- slot targeting score,
- theme coverage,
- graph update lag,
- graph stale-read count,
- route accuracy: how often predicted low-information turns actually had no useful extraction,
- route regret: skipped/deferred turns that later caused repeated questions or missed slots.

## Recommendation

Do not make graph updates simply low-frequency like profile updates.

Instead:

- keep graph projection deterministic and incremental,
- add a routing layer before extraction,
- move graph update off the hot path only when the route is safe,
- keep macro graph summary available as a read-only snapshot for planner guidance,
- log route decisions and graph lag for evaluation.

This gives the system three useful response modes:

- recent-context fast reply,
- graph-aware macro planning,
- structure-update-first planning.
