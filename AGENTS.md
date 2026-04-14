# AGENTS.md

## Project mission
This repository contains a Planner system for conversational interviewing.
The current research goal is to study how information weights affect Planner decisions.

## Research objective
Treat this as a decision-control problem, not a prompt-only tuning problem.
Focus on making Planner behavior configurable, measurable, and experimentally testable.

The key question is:
Which information types most influence the Planner’s next-step decision, and how do different weights affect:
- action choice (`continue`, `next_phase`, `end`)
- focus choice (stay on current event vs switch to new event vs move to key person)
- slot choice (time, location, people, cause/result, feeling/reflection)
- theme choice (which undercovered theme to move to)

## Information weight dimensions
Implement support for configurable weights for:
- new_info_weight
- missing_slot_weight
- theme_coverage_weight
- emotion_energy_weight
- memory_stability_weight
- conflict_clarification_weight
- information_quality_weight
- low_gain_penalty
- reflection_slot_weight

## Preferred implementation style
- Do not hardcode decision logic into prompt text only.
- Prefer configurable scoring in planner/orchestrator/generation_hints.
- Keep existing architecture and naming conventions unless there is a strong reason to refactor.
- Add instrumentation and evaluation hooks whenever decision logic changes.
- Preserve backward compatibility when possible.

## Expected engineering workflow
Before editing:
1. Read the research framework file and the Planner decision code.
2. Identify where action, focus, slot, and theme decisions are made.
3. Find existing config, scoring, hints, or planner state structures that can host weights.

During implementation:
1. Introduce configurable weight fields.
2. Refactor decision logic into explicit score components.
3. Log intermediate scores for debugging and evaluation.
4. Add or update tests.
5. Add experiment configs or scripts for ablation studies.

## Validation requirements
Always do all that apply:
- run unit tests
- run integration tests
- run lint/typecheck if present
- report exactly what passed, failed, or was not available

## Research deliverables
Every completed task should end with:
1. changed files
2. what decision logic changed
3. what assumptions were made
4. what experiments were added or proposed
5. what metrics should be checked
6. remaining risks or open questions

## Output style
Do not stop at high-level suggestions.
Default to implementing concrete code changes, tests, and experiment scaffolding.
Only ask for clarification when truly blocked by missing repository context.