# Dynamic Elder Profile Planner Integration

## Goal

Add a low-frequency dynamic elder profile after extraction merge so the planner can use gradually stabilized user understanding, without turning every utterance into a permanent profile fact.

The profile is a derived planning state. It does not replace the initial `ElderProfile`; the initial profile remains input truth, while `DynamicElderProfile` summarizes evidence discovered during the interview.

## Profile Schema

The implemented schema follows four groups:

- Core identity and personality: identity background, knowledge level, life overview, personality traits, speaking style, common expressions.
- Current life status: daily habits/preferences, interests/hobbies/social activity, health status/current concerns.
- Family situation: marital status, parents/children, siblings, grandchildren, other relatives.
- Life views and attitudes: life attitude/philosophy, society/interpersonal relationships, core values.

Each field stores:

- `value`
- `confidence`
- `evidence_turn_ids`
- `evidence_event_ids`
- `updated_at`

This makes profile guidance measurable and debuggable rather than prompt-only.

## Integration Point

Current orchestrator flow:

1. Extract events from the user response.
2. Merge extracted events into canonical memory.
3. Apply graph projection and refresh memory capsule.
4. Decide whether dynamic profile update should run.
5. Build generation hints and generate the next question using the previous stable profile.
6. Save state.
7. If triggered, run dynamic profile update asynchronously in a background thread.

This means the next question is not blocked by profile summarization. The refreshed profile becomes available to subsequent planning turns.

## Update Frequency And Triggers

Profile updates are intentionally low-frequency.

Config fields:

- `ENABLE_DYNAMIC_PROFILE_UPDATE`, default `true`
- `DYNAMIC_PROFILE_MIN_TURNS_BETWEEN_UPDATES`, default `3`
- `DYNAMIC_PROFILE_MAX_TURNS_BETWEEN_UPDATES`, default `5`
- `PROFILE_GUIDANCE_MAX_NOTES`, default `4`

Trigger reasons:

- `major_event_completed`: touched event has high completeness and confidence.
- `high_value_reflection`: touched event includes a substantial reflection.
- `causal_event_completed`: event has cause, result, and people.
- `multiple_new_people`: one turn introduces multiple people.
- `summary_turn_window`: at least the minimum turn window elapsed and merged events changed.
- `max_turn_window`: maximum turn window elapsed, forcing a consolidation pass.

Non-triggered turns are recorded as `below_update_threshold`.

## Planner Guidance Path

The profile is injected through `generation_hints`, not hardcoded as planner prompt logic:

- `generation_hints.dynamic_profile`
- `generation_hints.profile_guidance`
- `turn.debug_trace.planning.dynamic_profile_quality`
- `turn.debug_trace.planning.profile_guidance`
- `turn.debug_trace.profile_update`

`InterviewerAgent` renders a compact `Dynamic elder profile` section from those hints. The prompt receives evidence-backed facts and planning notes, while the decision/debug layer retains traceable profile quality and trigger reasons.

## Current Implementation Boundaries

The first implementation uses a deterministic `ProfileProjector`. It reads merged canonical events, people registry, reflections, and recent answer style. This avoids a new LLM dependency in tests and keeps the profile updater replaceable.

A future LLM-backed updater can reuse the same state schema and scheduling trigger. It should produce the same field structure and confidence/evidence metadata.

## Evaluation Metrics

Check these metrics when comparing runs:

- `dynamic_profile.profile_quality.overall`
- per-section profile coverage
- update count and update reasons
- action distribution: `continue`, `next_phase`, `end`
- focus distribution: current event vs new event vs key person
- slot targeting score
- theme coverage gain
- repeated question count
- average information gain
- average turn quality
- family/current-life/value coverage in generated questions

## Proposed Ablations

1. Disabled dynamic profile: `ENABLE_DYNAMIC_PROFILE_UPDATE=false`.
2. Conservative update: min/max window `4/6`, major-event triggers still enabled.
3. Default update: min/max window `3/5`.
4. Fast update: min/max window `2/3`.

Primary hypothesis: default or conservative updates should improve family/value/current-life coverage and reduce repeated questions without causing profile overfitting or excessive topic switching.
