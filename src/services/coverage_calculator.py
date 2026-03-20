from __future__ import annotations

from statistics import mean
from typing import Dict, Iterable, List

from src.core.graph_manager import GraphManager
from src.state import GraphSummary, SessionMetrics, SessionState


class CoverageCalculator:
    SLOT_NAMES = ("time", "location", "people", "event", "reflection", "cause", "result")

    def build_graph_summary(self, state: SessionState, graph_manager: GraphManager) -> GraphSummary:
        graph_coverage = graph_manager.calculate_coverage()
        theme_coverage = {
            theme_id: theme.completion_ratio
            for theme_id, theme in state.theme_state.items()
        }
        unresolved_theme_ids = [
            theme_id
            for theme_id, theme in state.theme_state.items()
            if theme.status != "exhausted"
        ]
        return GraphSummary(
            overall_coverage=graph_coverage.get("overall", 0.0),
            theme_coverage=theme_coverage,
            slot_coverage=self._calculate_slot_coverage(state.canonical_events.values()),
            people_coverage=self._calculate_people_coverage(state),
            current_focus_theme_id=state.current_focus_theme_id,
            active_event_ids=list(state.memory_capsule.active_event_ids if state.memory_capsule else []),
            unresolved_theme_ids=unresolved_theme_ids,
        )

    def calculate_session_metrics(self, state: SessionState, graph_manager: GraphManager) -> SessionMetrics:
        slot_coverage = self._calculate_slot_coverage(state.canonical_events.values())
        theme_coverage = graph_manager.calculate_coverage().get("overall", 0.0)
        people_coverage = self._calculate_people_coverage(state)
        open_loop_closure_rate = self._closure_rate(
            getattr(state.memory_capsule, "open_loop_history_total", 0),
            getattr(state.memory_capsule, "resolved_open_loop_count", 0),
        )
        contradiction_resolution_rate = self._closure_rate(
            getattr(state.memory_capsule, "contradiction_history_total", 0),
            getattr(state.memory_capsule, "resolved_contradiction_count", 0),
        )
        average_turn_quality = self._average(
            evaluation.question_quality_score for evaluation in state.evaluation_trace
        )
        average_information_gain = self._average(
            evaluation.information_gain_score for evaluation in state.evaluation_trace
        )
        return SessionMetrics(
            overall_theme_coverage=theme_coverage,
            overall_slot_coverage=slot_coverage,
            people_coverage=people_coverage,
            open_loop_closure_rate=open_loop_closure_rate,
            contradiction_resolution_rate=contradiction_resolution_rate,
            average_turn_quality=average_turn_quality,
            average_information_gain=average_information_gain,
        )

    def _calculate_slot_coverage(self, events: Iterable) -> Dict[str, float]:
        event_list = list(events)
        if not event_list:
            return {slot: 0.0 for slot in self.SLOT_NAMES}

        coverage: Dict[str, float] = {}
        for slot in self.SLOT_NAMES:
            filled = 0
            for event in event_list:
                value = getattr(event, slot, None)
                if slot == "people":
                    value = getattr(event, "people_names", None) or getattr(event, "people_ids", None)
                if value not in (None, "", []):
                    filled += 1
            coverage[slot] = filled / len(event_list)
        return coverage

    def _calculate_people_coverage(self, state: SessionState) -> float:
        if not state.canonical_events:
            return 0.0
        events_with_people = sum(1 for event in state.canonical_events.values() if event.people_ids or event.people_names)
        unique_people_bonus = min(len(state.people_registry) / max(len(state.canonical_events), 1), 1.0)
        return min((events_with_people / len(state.canonical_events)) * 0.7 + unique_people_bonus * 0.3, 1.0)

    def _closure_rate(self, total: int, resolved: int) -> float:
        if total <= 0:
            return 1.0
        return min(max(resolved / total, 0.0), 1.0)

    def _average(self, values: Iterable[float]) -> float:
        collected: List[float] = [value for value in values]
        if not collected:
            return 0.0
        return float(mean(collected))
