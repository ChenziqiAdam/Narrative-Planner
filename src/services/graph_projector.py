from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.core.event_node import EventNode
from src.core.graph_manager import GraphManager
from src.core.theme_node import NodeStatus
from src.state import CanonicalEvent, SessionState, ThemeState


class GraphProjector:
    def initialize_from_elder_profile(self, graph_manager: GraphManager, elder_info: Dict[str, Any]) -> None:
        background = str(elder_info.get("background", "") or "")
        keyword_theme_map = {
            "童年": ["THEME_05_CHILDHOOD_POSITIVE", "THEME_06_CHILDHOOD_NEGATIVE"],
            "家庭": ["THEME_01_LIFE_CHAPTERS", "THEME_07_ADULT_MEMORY"],
            "父母": ["THEME_01_LIFE_CHAPTERS", "THEME_05_CHILDHOOD_POSITIVE"],
            "上学": ["THEME_01_LIFE_CHAPTERS", "THEME_05_CHILDHOOD_POSITIVE"],
            "学校": ["THEME_01_LIFE_CHAPTERS", "THEME_05_CHILDHOOD_POSITIVE"],
            "工作": ["THEME_07_ADULT_MEMORY", "THEME_04_TURNING_POINT"],
            "工厂": ["THEME_07_ADULT_MEMORY", "THEME_04_TURNING_POINT"],
            "结婚": ["THEME_04_TURNING_POINT", "THEME_07_ADULT_MEMORY"],
            "老伴": ["THEME_04_TURNING_POINT", "THEME_07_ADULT_MEMORY"],
            "子女": ["THEME_01_LIFE_CHAPTERS", "THEME_07_ADULT_MEMORY"],
            "战争": ["THEME_03_LOW_POINT", "THEME_13_LIFE_CHALLENGE"],
            "文革": ["THEME_03_LOW_POINT", "THEME_13_LIFE_CHALLENGE"],
            "改革": ["THEME_04_TURNING_POINT"],
            "下乡": ["THEME_04_TURNING_POINT"],
            "迁移": ["THEME_04_TURNING_POINT"],
        }

        activated_themes = set()
        for keyword, themes in keyword_theme_map.items():
            if keyword in background:
                activated_themes.update(themes)

        for theme_id in activated_themes:
            if theme_id in graph_manager.theme_nodes:
                theme = graph_manager.theme_nodes[theme_id]
                if theme.status == NodeStatus.PENDING:
                    theme.mark_mentioned()
                    graph_manager._update_node_status(theme_id, NodeStatus.MENTIONED)

    def apply_projection(
        self,
        state: SessionState,
        graph_manager: GraphManager,
        event_ids: List[str],
    ) -> Dict[str, Any]:
        old_coverage = graph_manager.calculate_coverage().get("overall", 0.0)
        new_events = 0
        updated_events = 0
        updated_themes: List[str] = []

        for event_id in event_ids:
            event = state.canonical_events.get(event_id)
            if not event:
                continue

            theme_id = self._resolve_theme_id(graph_manager, state.current_focus_theme_id, event)
            if not theme_id:
                continue
            event.theme_id = theme_id

            event_node = self._build_event_node(event)
            if event_id in graph_manager.event_nodes:
                self._update_event_node(graph_manager.event_nodes[event_id], event)
                updated_events += 1
            else:
                if graph_manager.add_event_node(event_node, theme_id):
                    new_events += 1

            theme = graph_manager.theme_nodes.get(theme_id)
            if theme:
                self._update_theme_slots(theme, event)
                if theme_id not in updated_themes:
                    updated_themes.append(theme_id)

        new_coverage = graph_manager.calculate_coverage().get("overall", 0.0)
        return {
            "new_events": new_events,
            "updated_events": updated_events,
            "updated_themes": updated_themes,
            "coverage_change": new_coverage - old_coverage,
        }

    def build_theme_state(self, graph_manager: GraphManager) -> Dict[str, ThemeState]:
        return {
            theme_id: ThemeState(
                theme_id=theme_id,
                title=theme.title,
                status=theme.status.value,
                priority=theme.priority,
                expected_slots=list(theme.slots_filled.keys()),
                filled_slots=dict(theme.slots_filled),
                extracted_event_ids=list(theme.extracted_events),
                open_question_count=max(0, len(theme.seed_questions) - theme.current_question_index),
                completion_ratio=theme.get_completion_ratio(),
                exploration_depth=theme.exploration_depth,
            )
            for theme_id, theme in graph_manager.theme_nodes.items()
        }

    def build_graph_state(self, graph_manager: GraphManager, state: SessionState) -> Dict[str, Any]:
        state_snapshot = graph_manager.get_graph_state()
        state_snapshot["theme_nodes"] = {
            theme_id: node.to_dict()
            for theme_id, node in graph_manager.theme_nodes.items()
        }
        state_snapshot["event_nodes"] = {
            event_id: self._build_event_display_payload(state, event_id, node.to_dict())
            for event_id, node in graph_manager.event_nodes.items()
        }
        state_snapshot["people_nodes"] = {
            person_id: profile.to_dict()
            for person_id, profile in state.people_registry.items()
        }
        state_snapshot["people_count"] = len(state.people_registry)
        state_snapshot["elder_info"] = state.elder_profile.to_dict()
        state_snapshot["dynamic_profile"] = state.dynamic_profile.to_dict() if state.dynamic_profile else {}
        state_snapshot["session_id"] = state.session_id
        state_snapshot["memory_capsule"] = state.memory_capsule.to_dict() if state.memory_capsule else {}
        state_snapshot["session_metrics"] = state.session_metrics.to_dict() if state.session_metrics else {}
        state_snapshot["current_focus_theme_id"] = state.current_focus_theme_id
        state_snapshot["latest_turn_evaluation"] = (
            state.evaluation_trace[-1].to_dict() if state.evaluation_trace else {}
        )
        return state_snapshot

    def _build_event_display_payload(
        self,
        state: SessionState,
        event_id: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        canonical_event = state.canonical_events.get(event_id)
        if not canonical_event:
            return payload

        placeholder = "[missing]"
        display_slots = {
            "time": canonical_event.time or placeholder,
            "location": canonical_event.location or placeholder,
            "people": "、".join(canonical_event.people_names) if canonical_event.people_names else placeholder,
            "event": canonical_event.event or canonical_event.summary or placeholder,
            "feeling": canonical_event.feeling or placeholder,
            "reflection": canonical_event.reflection or placeholder,
            "cause": canonical_event.cause or placeholder,
            "result": canonical_event.result or placeholder,
        }
        missing_slots = [slot_name for slot_name, value in display_slots.items() if value == placeholder]
        payload["display_slots"] = display_slots
        payload["missing_slots"] = missing_slots
        payload["is_partial"] = bool(missing_slots)
        return payload

    def _build_event_node(self, event: CanonicalEvent) -> EventNode:
        return EventNode(
            event_id=event.event_id,
            theme_id=event.theme_id or "",
            title=event.title,
            description=event.summary,
            time_anchor=event.time,
            location=event.location,
            people_involved=list(event.people_names),
            slots={
                "time": event.time,
                "location": event.location,
                "people": "、".join(event.people_names) if event.people_names else None,
                "event": event.event or event.summary,
                "reflection": event.reflection or event.feeling,
            },
            emotional_score=self._estimate_emotion(event),
            information_density=event.completeness_score,
            depth_level=max(1, min(int(round(event.completeness_score * 5)), 5)),
        )

    def _update_event_node(self, event_node: EventNode, event: CanonicalEvent) -> None:
        event_node.title = event.title
        event_node.description = event.summary
        event_node.time_anchor = event.time
        event_node.location = event.location
        event_node.people_involved = list(event.people_names)
        event_node.slots.update(
            {
                "time": event.time,
                "location": event.location,
                "people": "、".join(event.people_names) if event.people_names else None,
                "event": event.event or event.summary,
                "reflection": event.reflection or event.feeling,
            }
        )
        event_node.information_density = event.completeness_score
        event_node.emotional_score = self._estimate_emotion(event)
        event_node.depth_level = max(event_node.depth_level, max(1, min(int(round(event.completeness_score * 5)), 5)))

    def _resolve_theme_id(
        self,
        graph_manager: GraphManager,
        current_focus_theme_id: Optional[str],
        event: CanonicalEvent,
    ) -> Optional[str]:
        if event.theme_id and event.theme_id in graph_manager.theme_nodes:
            return event.theme_id

        text = " ".join(
            value
            for value in [
                event.summary,
                event.feeling,
                event.reflection,
                event.location,
                event.time,
            ]
            if value
        )
        keyword_theme_map = {
            "THEME_14_HEALTH": ["医院", "生病", "住院", "手术"],
            "THEME_15_LOSS": ["去世", "离世", "不在了"],
            "THEME_16_FAILURE_REGRET": ["后悔", "遗憾", "失败"],
            "THEME_03_LOW_POINT": ["困难", "低谷", "难过", "受苦"],
            "THEME_13_LIFE_CHALLENGE": ["挑战", "坎坷", "难关", "压力"],
            "THEME_02_PEAK_EXPERIENCE": ["高兴", "开心", "自豪", "幸福"],
            "THEME_05_CHILDHOOD_POSITIVE": ["童年", "小时候", "玩", "上学"],
            "THEME_06_CHILDHOOD_NEGATIVE": ["童年", "挨打", "受苦", "家穷"],
            "THEME_07_ADULT_MEMORY": ["工作", "工厂", "上班", "结婚", "孩子"],
            "THEME_04_TURNING_POINT": ["转折", "调动", "搬家", "下乡", "离家"],
            "THEME_09_WISDOM_EVENT": ["明白了", "懂了", "教训", "看透"],
        }
        scored_candidates = []
        for theme_id, keywords in keyword_theme_map.items():
            score = sum(1 for keyword in keywords if keyword in text)
            if score > 0:
                scored_candidates.append((score, theme_id))

        if scored_candidates:
            scored_candidates.sort(reverse=True)
            return scored_candidates[0][1]
        if current_focus_theme_id:
            return current_focus_theme_id
        next_theme = graph_manager.get_next_candidate_theme()
        if next_theme:
            return next_theme.theme_id
        pending = graph_manager.get_pending_theme_nodes()
        if pending:
            return pending[0].theme_id
        return None

    def _update_theme_slots(self, theme, event: CanonicalEvent) -> bool:
        if not theme.slots_filled:
            theme.increment_depth()
            return False

        slot_sources = {
            "time": event.time,
            "location": event.location,
            "people": event.people_names,
            "person": event.people_names,
            "event": event.event or event.summary,
            "activity": event.event or event.summary,
            "chapter": event.summary,
            "before": event.cause,
            "reason": event.cause or event.reflection,
            "after": event.result,
            "impact": event.result or event.reflection,
            "feeling": event.feeling,
            "emotion": event.feeling,
            "reflection": event.reflection,
            "meaning": event.reflection,
            "significance": event.reflection,
            "coping": event.reflection or event.result,
        }

        any_updated = False
        for slot_name in list(theme.slots_filled.keys()):
            lowered = slot_name.lower()
            matched_value = None
            for key, value in slot_sources.items():
                if key in lowered and value not in (None, "", []):
                    matched_value = value
                    break
            if matched_value is not None:
                was_unfilled = not theme.slots_filled.get(slot_name, False)
                theme.update_slot(slot_name, True)
                if was_unfilled:
                    any_updated = True
        theme.increment_depth()
        return any_updated

    def _estimate_emotion(self, event: CanonicalEvent) -> float:
        text = " ".join(value for value in [event.feeling, event.reflection] if value)
        if not text:
            return 0.0
        positive_keywords = ["高兴", "开心", "幸福", "自豪", "温暖"]
        negative_keywords = ["难过", "辛苦", "遗憾", "痛苦", "压力"]
        positive_hits = sum(1 for keyword in positive_keywords if keyword in text)
        negative_hits = sum(1 for keyword in negative_keywords if keyword in text)
        if positive_hits == negative_hits:
            return 0.0
        return max(min((positive_hits - negative_hits) / 3.0, 1.0), -1.0)
