from __future__ import annotations

from difflib import SequenceMatcher
from typing import Dict, List

from src.state import PlannerContext, SessionState, TurnEvaluation, TurnRecord


class EvaluatorAgent:
    def evaluate_turn(
        self,
        state: SessionState,
        turn_record: TurnRecord,
        pre_overall_coverage: float,
        post_overall_coverage: float,
        interviewer_action: str,
    ) -> TurnEvaluation:
        plan = turn_record.planner_plan
        targeted_slots = list(plan.target_slots if plan else [])
        coverage_gain = max(post_overall_coverage - pre_overall_coverage, 0.0)
        information_gain_score = min(coverage_gain * 4.0 + self._event_gain(turn_record), 1.0)
        non_redundancy_score = self._non_redundancy_score(state, turn_record)
        slot_targeting_score = self._slot_targeting_score(turn_record, targeted_slots)
        emotional_alignment_score = self._emotional_alignment_score(state, plan.tone if plan else "EMPATHIC_SUPPORTIVE")
        planner_alignment_score = self._planner_alignment_score(plan.primary_action if plan else None, interviewer_action)

        question_quality_score = (
            information_gain_score * 0.30
            + non_redundancy_score * 0.25
            + slot_targeting_score * 0.20
            + emotional_alignment_score * 0.15
            + planner_alignment_score * 0.10
        )

        notes: List[str] = []
        if information_gain_score < 0.4:
            notes.append("Low information gain this turn.")
        if non_redundancy_score < 0.5:
            notes.append("Question may be too similar to recent turns.")
        if targeted_slots and slot_targeting_score < 0.5:
            notes.append("Targeted slots were not effectively advanced.")

        return TurnEvaluation(
            turn_id=turn_record.turn_id,
            question_quality_score=round(question_quality_score, 4),
            information_gain_score=round(information_gain_score, 4),
            non_redundancy_score=round(non_redundancy_score, 4),
            slot_targeting_score=round(slot_targeting_score, 4),
            emotional_alignment_score=round(emotional_alignment_score, 4),
            planner_alignment_score=round(planner_alignment_score, 4),
            coverage_gain=round(coverage_gain, 4),
            targeted_slots=targeted_slots,
            notes=notes,
        )

    def _event_gain(self, turn_record: TurnRecord) -> float:
        extraction = turn_record.extraction_result
        if not extraction:
            return 0.0
        candidates = extraction.graph_delta.event_candidates
        if not candidates:
            return 0.0
        average_completeness = sum(event.completeness_score for event in candidates) / len(candidates)
        return min((len(candidates) * 0.15) + average_completeness * 0.5, 1.0)

    def _non_redundancy_score(self, state: SessionState, turn_record: TurnRecord) -> float:
        question = turn_record.interviewer_question or ""
        recent_questions = [turn.interviewer_question for turn in state.recent_transcript(3)[:-1]]
        if not recent_questions:
            return 1.0
        max_similarity = max(
            SequenceMatcher(None, question, previous_question).ratio()
            for previous_question in recent_questions
        )
        return max(0.0, min(1.0, 1.0 - max_similarity))

    def _slot_targeting_score(self, turn_record: TurnRecord, targeted_slots: List[str]) -> float:
        if not targeted_slots:
            return 0.7
        extraction = turn_record.extraction_result
        if not extraction or not extraction.graph_delta.event_candidates:
            return 0.0

        hit_count = 0
        for slot_name in targeted_slots:
            if any(self._slot_has_value(event, slot_name) for event in extraction.graph_delta.event_candidates):
                hit_count += 1
        return hit_count / max(len(targeted_slots), 1)

    def _slot_has_value(self, event, slot_name: str) -> bool:
        if slot_name == "people":
            return bool(event.people_ids or event.people_names)
        return getattr(event, slot_name, None) not in (None, "", [])

    def _emotional_alignment_score(self, state: SessionState, tone: str) -> float:
        emotional_state = state.memory_capsule.emotional_state if state.memory_capsule else None
        if not emotional_state:
            return 0.7

        if emotional_state.cognitive_energy < 0.4:
            return 1.0 if tone == "GENTLE_WARM" else 0.6
        if emotional_state.valence < -0.2:
            return 1.0 if tone == "EMPATHIC_SUPPORTIVE" else 0.55
        if emotional_state.valence > 0.2:
            return 1.0 if tone == "CURIOUS_INQUIRING" else 0.7
        return 0.85 if tone in {"EMPATHIC_SUPPORTIVE", "CURIOUS_INQUIRING"} else 0.7

    def _planner_alignment_score(self, primary_action: str | None, interviewer_action: str) -> float:
        if not primary_action:
            return 0.7
        mapped = {
            "DEEP_DIVE": "continue",
            "CLARIFY": "continue",
            "BREADTH_SWITCH": "next_phase",
            "SUMMARIZE": "next_phase",
            "PAUSE_SESSION": "next_phase",
            "CLOSE_INTERVIEW": "end",
        }
        return 1.0 if mapped.get(primary_action) == interviewer_action else 0.55
