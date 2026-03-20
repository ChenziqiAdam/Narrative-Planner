from __future__ import annotations

from itertools import combinations
from typing import Dict, List

from src.state import (
    ContradictionNote,
    EmotionalState,
    MemoryCapsule,
    OpenLoop,
    SessionState,
)


class MemoryProjector:
    def build_initial_capsule(self, state: SessionState) -> MemoryCapsule:
        summary_parts = []
        profile = state.elder_profile
        if profile.name:
            summary_parts.append(profile.name)
        if profile.birth_year:
            summary_parts.append(f"born in {profile.birth_year}")
        if profile.hometown:
            summary_parts.append(f"from {profile.hometown}")
        if profile.background_summary:
            summary_parts.append(profile.background_summary)

        summary = ", ".join(summary_parts) if summary_parts else "Interview session initialized."
        return MemoryCapsule(
            session_summary=summary,
            current_storyline="Opening the conversation.",
            emotional_state=EmotionalState(confidence=0.4, evidence=["No completed turns yet."]),
        )

    def refresh(self, state: SessionState) -> MemoryCapsule:
        previous = state.memory_capsule or MemoryCapsule.empty()
        open_loops = self._collect_open_loops(state)
        contradictions = self._collect_contradictions(state)
        recent_topics = self._recent_topics(state)
        active_event_ids = self._active_event_ids(state)
        active_people_ids = self._active_people_ids(state, active_event_ids)
        emotional_state = self._infer_emotional_state(state)

        previous_loop_ids = {loop.loop_id for loop in previous.open_loops}
        current_loop_ids = {loop.loop_id for loop in open_loops}
        previous_contradiction_ids = {note.note_id for note in previous.contradictions}
        current_contradiction_ids = {note.note_id for note in contradictions}

        return MemoryCapsule(
            session_summary=self._build_session_summary(state),
            current_storyline=self._build_current_storyline(state, active_event_ids),
            active_event_ids=active_event_ids,
            active_people_ids=active_people_ids,
            open_loops=open_loops,
            contradictions=contradictions,
            emotional_state=emotional_state,
            recent_topics=recent_topics,
            do_not_repeat=[turn.interviewer_question for turn in state.recent_transcript(3)],
            open_loop_history_total=previous.open_loop_history_total + len(current_loop_ids - previous_loop_ids),
            resolved_open_loop_count=previous.resolved_open_loop_count + len(previous_loop_ids - current_loop_ids),
            contradiction_history_total=previous.contradiction_history_total + len(current_contradiction_ids - previous_contradiction_ids),
            resolved_contradiction_count=previous.resolved_contradiction_count + len(previous_contradiction_ids - current_contradiction_ids),
        )

    def _build_session_summary(self, state: SessionState) -> str:
        profile = state.elder_profile
        summary_parts = []
        if profile.name:
            summary_parts.append(profile.name)
        if profile.hometown:
            summary_parts.append(f"from {profile.hometown}")
        if profile.background_summary:
            summary_parts.append(profile.background_summary)

        recent_events = list(state.canonical_events.values())[-2:]
        if recent_events:
            event_summary = " | ".join(event.summary for event in recent_events if event.summary)
            summary_parts.append(f"Recent events: {event_summary}")

        if not summary_parts:
            return "Interview session in progress."
        return ". ".join(summary_parts)

    def _build_current_storyline(self, state: SessionState, active_event_ids: List[str]) -> str:
        if active_event_ids:
            event = state.canonical_events.get(active_event_ids[-1])
            if event:
                return f"Currently exploring: {event.summary}"
        if state.current_focus_theme_id and state.current_focus_theme_id in state.theme_state:
            theme = state.theme_state[state.current_focus_theme_id]
            return f"Currently exploring theme: {theme.title}"
        return "Expanding the interview timeline."

    def _active_event_ids(self, state: SessionState) -> List[str]:
        recent_turn_ids = [turn.turn_id for turn in state.recent_transcript(2)]
        active = [
            event.event_id
            for event in state.canonical_events.values()
            if any(turn_id in event.source_turn_ids for turn_id in recent_turn_ids)
        ]
        if active:
            return active[-3:]
        return list(state.canonical_events.keys())[-2:]

    def _active_people_ids(self, state: SessionState, active_event_ids: List[str]) -> List[str]:
        person_ids: List[str] = []
        for event_id in active_event_ids:
            event = state.canonical_events.get(event_id)
            if not event:
                continue
            for person_id in event.people_ids:
                if person_id not in person_ids:
                    person_ids.append(person_id)
        return person_ids[:5]

    def _collect_open_loops(self, state: SessionState) -> List[OpenLoop]:
        open_loops: List[OpenLoop] = []
        slot_priority = {
            "time": 0.9,
            "location": 0.8,
            "people": 0.8,
            "reflection": 0.85,
            "feeling": 0.75,
            "cause": 0.7,
            "result": 0.7,
        }

        for event in state.canonical_events.values():
            slot_values: Dict[str, object] = {
                "time": event.time,
                "location": event.location,
                "people": event.people_names,
                "reflection": event.reflection,
                "feeling": event.feeling,
                "cause": event.cause,
                "result": event.result,
            }
            for slot_name, priority in slot_priority.items():
                value = slot_values.get(slot_name)
                if value in (None, "", []):
                    open_loops.append(
                        OpenLoop(
                            loop_id=f"{event.event_id}:{slot_name}",
                            source_event_id=event.event_id,
                            loop_type="missing_slot" if slot_name != "people" else "person_gap",
                            description=f"Missing {slot_name} detail for event '{event.title}'.",
                            priority=priority,
                        )
                    )
            for index, clue in enumerate(event.unexpanded_clues):
                open_loops.append(
                    OpenLoop(
                        loop_id=f"{event.event_id}:clue:{index}",
                        source_event_id=event.event_id,
                        loop_type="unexpanded_clue",
                        description=clue,
                        priority=0.95,
                    )
                )

        open_loops.sort(key=lambda item: item.priority, reverse=True)
        return open_loops[:8]

    def _collect_contradictions(self, state: SessionState) -> List[ContradictionNote]:
        contradictions: List[ContradictionNote] = []
        events = list(state.canonical_events.values())
        for left, right in combinations(events, 2):
            if left.summary != right.summary:
                continue

            if left.time and right.time and left.time != right.time:
                contradictions.append(
                    ContradictionNote(
                        note_id=f"conflict:{left.event_id}:{right.event_id}:time",
                        event_ids=[left.event_id, right.event_id],
                        description=f"Event time conflict between '{left.title}' and '{right.title}'.",
                        severity="medium",
                    )
                )
            if left.location and right.location and left.location != right.location:
                contradictions.append(
                    ContradictionNote(
                        note_id=f"conflict:{left.event_id}:{right.event_id}:location",
                        event_ids=[left.event_id, right.event_id],
                        description=f"Event location conflict between '{left.title}' and '{right.title}'.",
                        severity="medium",
                    )
                )
        return contradictions[:5]

    def _recent_topics(self, state: SessionState) -> List[str]:
        topics: List[str] = []
        for event in list(state.canonical_events.values())[-3:]:
            if event.title and event.title not in topics:
                topics.append(event.title)
        if state.current_focus_theme_id and state.current_focus_theme_id in state.theme_state:
            theme_title = state.theme_state[state.current_focus_theme_id].title
            if theme_title not in topics:
                topics.append(theme_title)
        return topics[:5]

    def _infer_emotional_state(self, state: SessionState) -> EmotionalState:
        if not state.transcript:
            return EmotionalState(confidence=0.4, evidence=["No completed turns yet."])

        latest_turn = state.transcript[-1]
        answer = latest_turn.interviewee_answer or ""
        evidence = []
        valence = self._estimate_valence(answer)
        emotional_energy = min(max(len(answer) / 180.0, 0.2), 1.0)
        cognitive_energy = min(max(len(answer) / 140.0, 0.25), 1.0)

        if latest_turn.extraction_result:
            for candidate in latest_turn.extraction_result.graph_delta.event_candidates:
                if candidate.feeling:
                    evidence.append(candidate.feeling)
                if candidate.reflection:
                    evidence.append(candidate.reflection)

        if not evidence:
            evidence.append(answer[:80] if answer else "Short reply.")

        return EmotionalState(
            emotional_energy=round(emotional_energy, 3),
            cognitive_energy=round(cognitive_energy, 3),
            valence=round(valence, 3),
            confidence=0.65,
            evidence=evidence[:4],
        )

    def _estimate_valence(self, text: str) -> float:
        positive_keywords = ["开心", "高兴", "幸福", "自豪", "喜欢", "温暖", "快乐"]
        negative_keywords = ["难过", "伤心", "遗憾", "辛苦", "困难", "痛苦", "压抑"]
        pos_hits = sum(1 for word in positive_keywords if word in text)
        neg_hits = sum(1 for word in negative_keywords if word in text)
        if pos_hits == neg_hits == 0:
            return 0.0
        return max(min((pos_hits - neg_hits) / 3.0, 1.0), -1.0)
