from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, ClassVar, Dict, List, Optional, Sequence, Tuple

from src.config import Config
from src.state import SessionState, ThemeState


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


@dataclass
class PlannerDecisionWeights:
    new_info_weight: float = 1.0
    missing_slot_weight: float = 1.15
    theme_coverage_weight: float = 1.0
    emotion_energy_weight: float = 0.9
    memory_stability_weight: float = 0.85
    conflict_clarification_weight: float = 1.0
    information_quality_weight: float = 0.95
    low_gain_penalty: float = 1.1
    reflection_slot_weight: float = 0.75
    factual_slot_weight: float = 1.0
    VECTOR_ORDER: ClassVar[Tuple[str, ...]] = (
        "new_info_weight",
        "missing_slot_weight",
        "theme_coverage_weight",
        "emotion_energy_weight",
        "memory_stability_weight",
        "conflict_clarification_weight",
        "information_quality_weight",
        "low_gain_penalty",
        "reflection_slot_weight",
        "factual_slot_weight",
    )

    @classmethod
    def from_config(cls, overrides: Optional[Dict[str, Any]] = None) -> "PlannerDecisionWeights":
        payload: Dict[str, Any] = {
            "new_info_weight": Config.PLANNER_NEW_INFO_WEIGHT,
            "missing_slot_weight": Config.PLANNER_MISSING_SLOT_WEIGHT,
            "theme_coverage_weight": Config.PLANNER_THEME_COVERAGE_WEIGHT,
            "emotion_energy_weight": Config.PLANNER_EMOTION_ENERGY_WEIGHT,
            "memory_stability_weight": Config.PLANNER_MEMORY_STABILITY_WEIGHT,
            "conflict_clarification_weight": Config.PLANNER_CONFLICT_CLARIFICATION_WEIGHT,
            "information_quality_weight": Config.PLANNER_INFORMATION_QUALITY_WEIGHT,
            "low_gain_penalty": Config.PLANNER_LOW_GAIN_PENALTY,
            "reflection_slot_weight": Config.PLANNER_REFLECTION_SLOT_WEIGHT,
            "factual_slot_weight": Config.PLANNER_FACTUAL_SLOT_WEIGHT,
        }
        for key, value in (overrides or {}).items():
            if key in payload and isinstance(value, (int, float)):
                payload[key] = float(value)
        return cls(**payload)

    @classmethod
    def from_vector(cls, vector: Sequence[float]) -> "PlannerDecisionWeights":
        if len(vector) != len(cls.VECTOR_ORDER):
            raise ValueError(
                f"Weight vector length must be {len(cls.VECTOR_ORDER)}, got {len(vector)}."
            )
        payload = {
            name: float(value)
            for name, value in zip(cls.VECTOR_ORDER, vector)
        }
        return cls.from_config(payload)

    @classmethod
    def from_external(cls, external: Optional[Any]) -> "PlannerDecisionWeights":
        """
        Parse external weight input.

        Supported formats:
        1) dict: {"new_info_weight": 1.2, ...}
        2) list/tuple: [1.2, 1.0, ...] in VECTOR_ORDER
        3) None: use config defaults
        """
        if external is None:
            return cls.from_config()
        if isinstance(external, dict):
            return cls.from_config(external)
        if isinstance(external, (list, tuple)):
            if not all(isinstance(item, (int, float)) for item in external):
                raise ValueError("Weight vector must contain only numeric values.")
            return cls.from_vector([float(item) for item in external])
        raise ValueError("Unsupported weight input format. Use dict or numeric vector list.")

    def to_dict(self) -> Dict[str, float]:
        return {key: round(float(value), 4) for key, value in asdict(self).items()}

    def to_vector(self) -> List[float]:
        payload = self.to_dict()
        return [float(payload[name]) for name in self.VECTOR_ORDER]


class PlannerDecisionPolicy:
    FACTUAL_SLOTS = {"time", "location", "people", "event", "cause", "result"}
    REFLECTION_SLOTS = {"feeling", "reflection"}

    def __init__(self, weights: Optional[PlannerDecisionWeights] = None):
        self.weights = weights or PlannerDecisionWeights.from_config()

    def evaluate(
        self,
        state: SessionState,
        post_overall_coverage: float,
        focus_event_payload: Optional[Dict[str, Any]],
        fallback_repeat_count: int = 0,
    ) -> Dict[str, Any]:
        low_info_streak = self._recent_low_information_streak(state)
        signals = self._compute_signals(
            state,
            post_overall_coverage=post_overall_coverage,
            focus_event_payload=focus_event_payload,
            low_info_streak=low_info_streak,
            fallback_repeat_count=fallback_repeat_count,
        )

        action_scores = self._score_actions(signals)
        preferred_action = max(action_scores, key=action_scores.get)

        focus_scores = self._score_focus(signals)
        preferred_focus = max(focus_scores, key=focus_scores.get)

        slot_rankings = self._rank_slots(focus_event_payload, signals)
        theme_rankings = self._rank_themes(state, signals)

        recommended_theme_id = theme_rankings[0]["theme_id"] if theme_rankings else None
        recommended_theme_title = theme_rankings[0]["title"] if theme_rankings else None

        return {
            "weights": self.weights.to_dict(),
            "weight_vector": self.weights.to_vector(),
            "weight_vector_order": list(self.weights.VECTOR_ORDER),
            "signals": {key: round(value, 4) for key, value in signals.items()},
            "scores": {
                "action": {key: round(value, 4) for key, value in action_scores.items()},
                "focus": {key: round(value, 4) for key, value in focus_scores.items()},
            },
            "preferred_action": preferred_action,
            "preferred_focus": preferred_focus,
            "slot_rankings": slot_rankings,
            "theme_rankings": theme_rankings,
            "recommended_theme_id": recommended_theme_id,
            "recommended_theme_title": recommended_theme_title,
            "low_info_streak": low_info_streak,
        }

    def _compute_signals(
        self,
        state: SessionState,
        post_overall_coverage: float,
        focus_event_payload: Optional[Dict[str, Any]],
        low_info_streak: int,
        fallback_repeat_count: int,
    ) -> Dict[str, float]:
        new_info_score = self._compute_new_info_score(state)
        missing_slot_score = self._compute_missing_slot_score(focus_event_payload)
        theme_undercoverage_score = self._compute_theme_undercoverage_score(state)
        emotion_energy_score = self._compute_emotion_energy_score(state)
        memory_stability_score = self._compute_memory_stability_score(state)
        conflict_score = self._compute_conflict_score(state)
        information_quality_score = self._compute_information_quality_score(state)

        low_gain_penalty_score = _clamp01(
            (low_info_streak / 3.0) * 0.8 + min(1.0, fallback_repeat_count / 3.0) * 0.2
        )

        return {
            "new_info": new_info_score,
            "missing_slot": missing_slot_score,
            "theme_undercoverage": theme_undercoverage_score,
            "emotion_energy": emotion_energy_score,
            "memory_stability": memory_stability_score,
            "conflict_clarification": conflict_score,
            "information_quality": information_quality_score,
            "low_gain_penalty": low_gain_penalty_score,
            "overall_coverage": _clamp01(post_overall_coverage),
            "person_gap": self._compute_person_gap_score(focus_event_payload),
        }

    def _score_actions(self, signals: Dict[str, float]) -> Dict[str, float]:
        w = self.weights
        continue_score = (
            w.missing_slot_weight * signals["missing_slot"]
            + w.information_quality_weight * signals["information_quality"]
            + w.memory_stability_weight * signals["memory_stability"]
            + w.new_info_weight * signals["new_info"] * 0.55
            - w.low_gain_penalty * signals["low_gain_penalty"] * 0.7
        )

        next_phase_score = (
            w.theme_coverage_weight * signals["theme_undercoverage"]
            + w.new_info_weight * signals["new_info"]
            + w.conflict_clarification_weight * signals["conflict_clarification"]
            + w.emotion_energy_weight * signals["emotion_energy"]
            + w.low_gain_penalty * signals["low_gain_penalty"]
            + w.memory_stability_weight * (1.0 - signals["memory_stability"]) * 0.6
        )

        end_score = (
            w.low_gain_penalty * signals["low_gain_penalty"] * 1.25
            + w.emotion_energy_weight * signals["emotion_energy"]
            + max(0.0, signals["overall_coverage"] - 0.65) * w.theme_coverage_weight
        )

        if signals["overall_coverage"] < 0.60:
            end_score *= 0.35
        if signals["low_gain_penalty"] < 0.45:
            end_score *= 0.5

        return {
            "continue": continue_score,
            "next_phase": next_phase_score,
            "end": end_score,
        }

    def _score_focus(self, signals: Dict[str, float]) -> Dict[str, float]:
        w = self.weights
        stay_current_event = (
            w.missing_slot_weight * signals["missing_slot"]
            + w.memory_stability_weight * signals["memory_stability"]
            + w.information_quality_weight * signals["information_quality"] * 0.5
        )
        switch_new_event = (
            w.new_info_weight * signals["new_info"]
            + w.theme_coverage_weight * signals["theme_undercoverage"] * 0.75
            + w.low_gain_penalty * signals["low_gain_penalty"] * 0.6
        )
        move_to_key_person = (
            w.missing_slot_weight * signals["person_gap"]
            + w.new_info_weight * signals["new_info"] * 0.45
            + w.theme_coverage_weight * signals["theme_undercoverage"] * 0.3
        )
        return {
            "stay_current_event": stay_current_event,
            "switch_new_event": switch_new_event,
            "move_to_key_person": move_to_key_person,
        }

    def _rank_slots(
        self,
        focus_event_payload: Optional[Dict[str, Any]],
        signals: Dict[str, float],
    ) -> List[Dict[str, Any]]:
        if not focus_event_payload:
            return []

        missing = focus_event_payload.get("missing_slots", [])
        if not isinstance(missing, list):
            return []

        base_priority = {
            "time": 1.0,
            "location": 0.95,
            "people": 1.0,
            "event": 0.9,
            "cause": 0.9,
            "result": 0.9,
            "feeling": 0.72,
            "reflection": 0.72,
        }

        rankings = []
        for slot in missing:
            if not isinstance(slot, str):
                continue
            slot_key = slot.strip()
            if slot_key not in base_priority:
                continue

            slot_weight = self.weights.factual_slot_weight
            if slot_key in self.REFLECTION_SLOTS:
                slot_weight = self.weights.reflection_slot_weight
            score = (
                base_priority[slot_key]
                * self.weights.missing_slot_weight
                * slot_weight
            )
            if slot_key in self.REFLECTION_SLOTS:
                score += self.weights.emotion_energy_weight * signals["emotion_energy"] * 0.45
                score += self.weights.information_quality_weight * signals["information_quality"] * 0.25
            else:
                score += self.weights.new_info_weight * signals["new_info"] * 0.2

            rankings.append({
                "slot": slot_key,
                "score": round(score, 4),
                "is_reflection": slot_key in self.REFLECTION_SLOTS,
            })

        rankings.sort(key=lambda item: item["score"], reverse=True)
        return rankings

    def _rank_themes(self, state: SessionState, signals: Dict[str, float]) -> List[Dict[str, Any]]:
        candidates = [
            theme for theme in state.theme_state.values()
            if theme.status in {"pending", "mentioned"}
        ]
        if not candidates:
            return []

        recent_topics = set((state.memory_capsule.recent_topics if state.memory_capsule else []) or [])
        ranked = []
        for theme in candidates:
            undercoverage = _clamp01(1.0 - float(theme.completion_ratio or 0.0))
            priority_bonus = _clamp01((6.0 - float(theme.priority or 5)) / 5.0)
            recent_penalty = 0.15 if theme.title in recent_topics else 0.0
            score = (
                self.weights.theme_coverage_weight * undercoverage
                + 0.2 * priority_bonus
                + 0.2 * self.weights.low_gain_penalty * signals["low_gain_penalty"]
                - recent_penalty
            )
            ranked.append({
                "theme_id": theme.theme_id,
                "title": theme.title,
                "score": round(score, 4),
                "undercoverage": round(undercoverage, 4),
                "completion_ratio": round(float(theme.completion_ratio or 0.0), 4),
            })

        ranked.sort(key=lambda item: item["score"], reverse=True)
        return ranked

    def _compute_new_info_score(self, state: SessionState) -> float:
        if not state.transcript:
            return 0.0
        turn = state.transcript[-1]
        extraction_result = turn.extraction_result
        if not extraction_result:
            return 0.0

        candidates = extraction_result.graph_delta.event_candidates
        candidate_score = min(1.0, len(candidates) / 2.0)

        slot_filled_values = []
        people_novelty = 0
        for event in candidates:
            filled = sum(
                1
                for value in [
                    event.time,
                    event.location,
                    event.people_names,
                    event.event,
                    event.feeling,
                    event.reflection,
                    event.cause,
                    event.result,
                ]
                if value not in (None, "", [])
            )
            slot_filled_values.append(filled / 8.0)
            people_novelty += len(event.people_names or [])

        slot_novelty = sum(slot_filled_values) / len(slot_filled_values) if slot_filled_values else 0.0
        people_score = min(1.0, people_novelty / 3.0)

        return _clamp01(candidate_score * 0.5 + slot_novelty * 0.35 + people_score * 0.15)

    def _compute_missing_slot_score(self, focus_event_payload: Optional[Dict[str, Any]]) -> float:
        if not focus_event_payload:
            return 0.0

        missing_slots = focus_event_payload.get("missing_slots", [])
        if not isinstance(missing_slots, list) or not missing_slots:
            return 0.0

        slot_weight_map = {
            "time": 1.0,
            "location": 0.95,
            "people": 1.0,
            "event": 0.9,
            "cause": 0.9,
            "result": 0.9,
            "feeling": 0.72,
            "reflection": 0.72,
        }
        total = 0.0
        for slot in missing_slots:
            if isinstance(slot, str):
                total += slot_weight_map.get(slot, 0.7)

        max_possible = max(1.0, len(missing_slots) * 1.0)
        return _clamp01(total / max_possible)

    def _compute_theme_undercoverage_score(self, state: SessionState) -> float:
        candidates = [
            theme for theme in state.theme_state.values()
            if theme.status in {"pending", "mentioned"}
        ]
        if not candidates:
            return 0.0

        sorted_candidates = sorted(candidates, key=lambda item: item.completion_ratio)
        top = sorted_candidates[:3]
        score = sum(1.0 - float(theme.completion_ratio or 0.0) for theme in top) / len(top)
        return _clamp01(score)

    def _compute_emotion_energy_score(self, state: SessionState) -> float:
        memory = state.memory_capsule
        if not memory or not memory.emotional_state:
            return 0.0

        emotional_state = memory.emotional_state
        low_energy = _clamp01(1.0 - float(emotional_state.cognitive_energy or 0.0))
        negative_valence = _clamp01(max(0.0, -float(emotional_state.valence or 0.0)))
        return _clamp01(low_energy * 0.6 + negative_valence * 0.4)

    def _compute_memory_stability_score(self, state: SessionState) -> float:
        events = list(state.canonical_events.values())
        if not events:
            return 0.0

        stable_count = 0
        for event in events:
            confidence = float(event.confidence or 0.0)
            completeness = float(event.completeness_score or 0.0)
            slot_filled = sum(
                1
                for value in [
                    event.time,
                    event.location,
                    event.people_names,
                    event.event,
                    event.feeling,
                    event.reflection,
                    event.cause,
                    event.result,
                ]
                if value not in (None, "", [])
            ) / 8.0
            if max(confidence, completeness, slot_filled) >= 0.6:
                stable_count += 1

        stable_ratio = stable_count / max(1, len(events))
        clue_count = sum(len(event.unexpanded_clues or []) for event in events)
        clue_pressure = min(1.0, clue_count / 6.0)
        return _clamp01(stable_ratio * 0.75 + (1.0 - clue_pressure) * 0.25)

    def _compute_conflict_score(self, state: SessionState) -> float:
        contradictions = len((state.memory_capsule.contradictions if state.memory_capsule else []) or [])
        conflict_loops = len([
            loop
            for loop in ((state.memory_capsule.open_loops if state.memory_capsule else []) or [])
            if loop.loop_type == "conflict"
        ])
        return _clamp01((contradictions * 0.7 + conflict_loops * 0.3) / 3.0)

    def _compute_information_quality_score(self, state: SessionState) -> float:
        if not state.transcript:
            return 0.0
        latest_turn = state.transcript[-1]
        extraction_result = latest_turn.extraction_result
        if not extraction_result:
            return _clamp01(len((latest_turn.interviewee_answer or "").strip()) / 120.0)

        candidates = extraction_result.graph_delta.event_candidates
        if not candidates:
            return _clamp01(len((latest_turn.interviewee_answer or "").strip()) / 120.0)

        quality_values = []
        for event in candidates:
            slot_density = sum(
                1
                for value in [
                    event.time,
                    event.location,
                    event.people_names,
                    event.event,
                    event.feeling,
                    event.reflection,
                    event.cause,
                    event.result,
                ]
                if value not in (None, "", [])
            ) / 8.0
            quality_values.append(
                max(float(event.confidence or 0.0), float(event.completeness_score or 0.0), slot_density)
            )
        return _clamp01(sum(quality_values) / len(quality_values))

    def _compute_person_gap_score(self, focus_event_payload: Optional[Dict[str, Any]]) -> float:
        if not focus_event_payload:
            return 0.0
        missing_slots = focus_event_payload.get("missing_slots", [])
        if not isinstance(missing_slots, list):
            return 0.0
        if "people" in missing_slots:
            return 1.0
        people_names = focus_event_payload.get("people_names", [])
        if isinstance(people_names, list) and len(people_names) <= 1:
            return 0.45
        return 0.1

    def _recent_low_information_streak(self, state: SessionState, max_window: int = 3) -> int:
        streak = 0
        for turn in reversed(state.transcript[-max_window:]):
            if self._is_low_information_turn(turn):
                streak += 1
            else:
                break
        return streak

    def _is_low_information_turn(self, turn: Any) -> bool:
        if turn.turn_evaluation and turn.turn_evaluation.information_gain_score <= 0.08:
            return True

        extracted_count = 0
        if turn.extraction_result:
            extracted_count = len(turn.extraction_result.graph_delta.event_candidates)
        coverage_delta = (
            (turn.debug_trace.get("coverage", {}) or {}).get("delta", 0.0)
            if isinstance(turn.debug_trace, dict)
            else 0.0
        )
        answer_len = len((turn.interviewee_answer or "").strip())
        return extracted_count == 0 and coverage_delta <= 0.005 and answer_len < 40


def pick_undercovered_theme(theme_state: Dict[str, ThemeState]) -> Tuple[Optional[str], Optional[str]]:
    candidates = [
        theme
        for theme in theme_state.values()
        if theme.status in {"pending", "mentioned"}
    ]
    if not candidates:
        return None, None
    ranked = sorted(candidates, key=lambda theme: (theme.completion_ratio, theme.priority))
    picked = ranked[0]
    return picked.theme_id, picked.title
