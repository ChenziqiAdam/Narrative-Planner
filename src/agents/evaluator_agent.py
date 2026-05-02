from __future__ import annotations

from difflib import SequenceMatcher
from typing import Dict, List

from src.state import SessionState, TurnEvaluation, TurnRecord


class EvaluatorAgent:
    def evaluate_turn(
        self,
        state: SessionState,
        turn_record: TurnRecord,
        pre_overall_coverage: float,
        post_overall_coverage: float,
        interviewer_action: str,
    ) -> TurnEvaluation:
        coverage_gain = max(post_overall_coverage - pre_overall_coverage, 0.0)
        information_gain_score = min(coverage_gain * 4.0 + self._extraction_gain(turn_record), 1.0)
        non_redundancy_score = self._non_redundancy_score(state, turn_record)

        question_quality_score = (
            information_gain_score * 0.45
            + non_redundancy_score * 0.35
            + coverage_gain * 0.20
        )

        notes: List[str] = []
        if information_gain_score < 0.4:
            notes.append("Low information gain this turn.")
        if non_redundancy_score < 0.5:
            notes.append("Question may be too similar to recent turns.")

        return TurnEvaluation(
            turn_id=turn_record.turn_id,
            question_quality_score=round(question_quality_score, 4),
            information_gain_score=round(information_gain_score, 4),
            non_redundancy_score=round(non_redundancy_score, 4),
            emotional_alignment_score=0.0,
            coverage_gain=round(coverage_gain, 4),
            notes=notes,
        )

    def _extraction_gain(self, turn_record: TurnRecord) -> float:
        extraction = turn_record.extraction_result
        if not extraction:
            return 0.0
        graph_delta = extraction.graph_delta
        fragment_count = len(graph_delta.fragment_candidates) if graph_delta else 0
        if graph_delta and graph_delta.graph_extraction:
            entity_count = len(graph_delta.graph_extraction.entities)
            return min(entity_count * 0.15, 1.0)
        return min(fragment_count * 0.1, 1.0)

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
