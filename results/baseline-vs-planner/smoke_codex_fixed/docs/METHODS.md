# Baseline vs Planner Experiment Methods

## Purpose
This experiment compares the control-group `baseline` interviewer against the GraphRAG-enabled `planner` interviewer under the same automated interview conditions.

## Default Design
- Agents: `baseline`, `planner`
- Runs per agent: 1
- Turns per run: 1
- Interview mode: AI interviewee through the same `/api/<agent>/auto?single_turn=1` route used by the 9999 compare UI
- Graph reset: once before the experiment, preserving Topic nodes, when Neo4j is enabled
- Planner tools enabled: False
- Model override: `moonshot-v1-8k`

## Per-Run Artifacts
Each run directory contains:
- `transcript.md`: readable full dialogue
- `turns.jsonl`: raw SSE events for each turn
- `run.json`: complete run payload
- `metrics.json`: extracted comparable metrics
- `score.json`: deterministic and optional LLM scorer output
- `planner_report.json` and `graph_state.json`: planner-only GraphRAG reports

## Comparable Metrics
- completed_turns and completion_rate
- avg_question_quality
- avg_information_gain
- avg_non_redundancy
- low_gain_ratio
- final_coverage
- action_continue_ratio / action_next_phase_ratio / action_end_ratio
- avg_interviewer_ms

Planner additionally records GraphRAG observability:
- retrieval_nonempty_rate
- avg_ranked_entities
- avg_context_chars
- total_new_entities
- total_updated_entities
- total_relationships_written
- total_extracted_events

## Deterministic Score
The common deterministic score intentionally does not require GraphRAG-specific fields, so baseline and planner are judged on the same output-quality surface:

`score = 0.28*question_quality + 0.24*information_gain + 0.20*non_redundancy + 0.18*coverage + 0.10*completion`

Planner GraphRAG metrics are reported separately as `graph_observability_score`, and are not folded into the common score by default.

## Optional Scoring Agent
When `--use-llm-scorer` is set, `ConversationScorerAgent` scores the transcript on narrative coherence, emotional depth, question effectiveness, non-redundancy, topic coverage quality, and overall quality. Final score becomes:

`overall = (1 - llm_weight) * deterministic_score + llm_weight * llm_overall`

If the scorer agent fails, the script falls back to deterministic score and records `llm_score = null`.

## Stability Penalty
For each agent:

`mean_minus_variance_penalty = mean(overall_score) - variance_penalty_weight * population_variance(overall_score)`

This favors agents that are both high-performing and stable across independent runs.
