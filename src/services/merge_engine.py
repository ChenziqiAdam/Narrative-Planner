from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Iterable, List, Optional

from src.core.interfaces import ExtractedEvent
from src.services.relation_lexicon import infer_relation_code, is_self_reference
from src.state import CanonicalEvent, PersonProfile, SessionState


@dataclass
class MergeResult:
    new_event_ids: List[str] = field(default_factory=list)
    updated_event_ids: List[str] = field(default_factory=list)
    touched_event_ids: List[str] = field(default_factory=list)
    new_person_ids: List[str] = field(default_factory=list)
    touched_person_ids: List[str] = field(default_factory=list)
    theme_hints: List[str] = field(default_factory=list)


class MergeEngine:
    def __init__(self, similarity_threshold: float = 0.72):
        self.similarity_threshold = similarity_threshold

    def merge(
        self,
        state: SessionState,
        extracted_events: List[ExtractedEvent],
        turn_id: str,
    ) -> MergeResult:
        result = MergeResult()

        for extracted in extracted_events:
            if extracted.theme_id:
                result.theme_hints.append(extracted.theme_id)

            person_ids, new_person_ids = self._upsert_people(state, extracted, turn_id)
            result.new_person_ids.extend(
                person_id for person_id in new_person_ids if person_id not in result.new_person_ids
            )
            result.touched_person_ids.extend(
                person_id for person_id in person_ids if person_id not in result.touched_person_ids
            )

            matched_event = self._find_match(state, extracted)
            if matched_event:
                self._update_event(matched_event, extracted, person_ids, turn_id)
                matched_event.merge_status = "updated"
                result.updated_event_ids.append(matched_event.event_id)
                if matched_event.event_id not in result.touched_event_ids:
                    result.touched_event_ids.append(matched_event.event_id)
                self._link_people(state, person_ids, matched_event.event_id)
                continue

            canonical_event = self._create_event(extracted, person_ids, turn_id)
            state.canonical_events[canonical_event.event_id] = canonical_event
            result.new_event_ids.append(canonical_event.event_id)
            result.touched_event_ids.append(canonical_event.event_id)
            self._link_people(state, person_ids, canonical_event.event_id)

        return result

    def _find_match(
        self,
        state: SessionState,
        extracted: ExtractedEvent,
    ) -> Optional[CanonicalEvent]:
        if extracted.is_update and extracted.updated_event_id:
            return state.canonical_events.get(extracted.updated_event_id)

        best_match: Optional[CanonicalEvent] = None
        best_score = 0.0
        for event in state.canonical_events.values():
            score = self._event_similarity(event, extracted)
            if score > best_score:
                best_match = event
                best_score = score

        if best_score >= self.similarity_threshold:
            return best_match
        return None

    def _event_similarity(
        self,
        existing: CanonicalEvent,
        extracted: ExtractedEvent,
    ) -> float:
        candidate_text = extracted.slots.event or ""
        if not candidate_text:
            return 0.0

        summary_score = SequenceMatcher(None, existing.summary or "", candidate_text).ratio()

        time_score = 0.0
        if existing.time and extracted.slots.time:
            time_score = (
                1.0
                if existing.time == extracted.slots.time
                else SequenceMatcher(None, existing.time, extracted.slots.time).ratio() * 0.6
            )

        location_score = 0.0
        if existing.location and extracted.slots.location:
            location_score = (
                1.0
                if existing.location == extracted.slots.location
                else SequenceMatcher(None, existing.location, extracted.slots.location).ratio() * 0.5
            )

        extracted_people = {
            self._normalize_key(name)
            for name in extracted.slots.people or []
            if not is_self_reference(str(name))
        }
        existing_people = {self._normalize_key(name) for name in existing.people_names}
        people_score = 0.0
        if extracted_people and existing_people:
            overlap = len(extracted_people & existing_people)
            people_score = overlap / max(len(extracted_people | existing_people), 1)

        return (summary_score * 0.65) + (time_score * 0.15) + (location_score * 0.1) + (people_score * 0.1)

    def _create_event(
        self,
        extracted: ExtractedEvent,
        person_ids: List[str],
        turn_id: str,
    ) -> CanonicalEvent:
        summary = extracted.slots.event or "Untitled event"
        people_names = self._filtered_people_names(extracted)

        return CanonicalEvent(
            event_id=extracted.event_id or f"evt_{uuid.uuid4().hex[:12]}",
            title=summary[:24],
            summary=summary,
            time=extracted.slots.time,
            location=extracted.slots.location,
            people_ids=person_ids,
            people_names=people_names,
            event=extracted.slots.event,
            feeling=extracted.slots.feeling,
            reflection=extracted.slots.reflection,
            cause=extracted.slots.cause,
            result=extracted.slots.result,
            unexpanded_clues=self._normalize_clues(extracted.slots.unexpanded_clues),
            theme_id=extracted.theme_id,
            source_turn_ids=[turn_id],
            completeness_score=self._completeness_score(extracted, people_names),
            confidence=extracted.confidence,
            merge_status="new",
        )

    def _update_event(
        self,
        event: CanonicalEvent,
        extracted: ExtractedEvent,
        person_ids: List[str],
        turn_id: str,
    ) -> None:
        event.summary = event.summary or extracted.slots.event or event.title
        event.title = (event.title or extracted.slots.event or event.event_id)[:24]
        event.time = event.time or extracted.slots.time
        event.location = event.location or extracted.slots.location
        event.event = event.event or extracted.slots.event
        event.feeling = event.feeling or extracted.slots.feeling
        event.reflection = event.reflection or extracted.slots.reflection
        event.cause = event.cause or extracted.slots.cause
        event.result = event.result or extracted.slots.result
        if extracted.theme_id and not event.theme_id:
            event.theme_id = extracted.theme_id

        for person_name in self._filtered_people_names(extracted):
            if person_name not in event.people_names:
                event.people_names.append(person_name)

        for person_id in person_ids:
            if person_id not in event.people_ids:
                event.people_ids.append(person_id)

        for clue in self._normalize_clues(extracted.slots.unexpanded_clues):
            if clue not in event.unexpanded_clues:
                event.unexpanded_clues.append(clue)

        if turn_id not in event.source_turn_ids:
            event.source_turn_ids.append(turn_id)

        event.completeness_score = max(
            event.completeness_score,
            self._completeness_score(extracted, self._filtered_people_names(extracted)),
        )
        event.confidence = max(event.confidence, extracted.confidence)

    def _upsert_people(
        self,
        state: SessionState,
        extracted: ExtractedEvent,
        turn_id: str,
    ) -> tuple[List[str], List[str]]:
        person_ids: List[str] = []
        new_person_ids: List[str] = []

        for raw_name in extracted.slots.people or []:
            display_name = str(raw_name).strip()
            if not display_name or is_self_reference(display_name):
                continue

            normalized = self._normalize_key(display_name)
            existing_id = self._find_person_id(state.people_registry.values(), normalized)
            if existing_id:
                person = state.people_registry[existing_id]
                if display_name not in person.aliases and display_name != person.display_name:
                    person.aliases.append(display_name)
                person_ids.append(existing_id)
                continue

            person_id = f"person_{uuid.uuid4().hex[:10]}"
            state.people_registry[person_id] = PersonProfile(
                person_id=person_id,
                display_name=display_name,
                relation_to_elder=infer_relation_code(display_name),
                summary=f"Mentioned in turn {turn_id}.",
            )
            person_ids.append(person_id)
            new_person_ids.append(person_id)

        return person_ids, new_person_ids

    def _find_person_id(
        self,
        people: Iterable[PersonProfile],
        normalized_name: str,
    ) -> Optional[str]:
        for person in people:
            candidates = [person.display_name, *person.aliases]
            if normalized_name in {self._normalize_key(candidate) for candidate in candidates}:
                return person.person_id
        return None

    def _link_people(
        self,
        state: SessionState,
        person_ids: List[str],
        event_id: str,
    ) -> None:
        for person_id in person_ids:
            person = state.people_registry.get(person_id)
            if person and event_id not in person.related_event_ids:
                person.related_event_ids.append(event_id)

    def _filtered_people_names(self, extracted: ExtractedEvent) -> List[str]:
        return [
            str(name).strip()
            for name in extracted.slots.people or []
            if str(name).strip() and not is_self_reference(str(name))
        ]

    def _normalize_clues(self, raw_clues: Optional[str]) -> List[str]:
        if not raw_clues:
            return []
        normalized = str(raw_clues).replace("；", ";")
        parts = [item.strip() for item in normalized.split(";")]
        return [item for item in parts if item]

    def _normalize_key(self, value: str) -> str:
        return value.strip().lower().replace(" ", "")

    def _completeness_score(
        self,
        extracted: ExtractedEvent,
        filtered_people: Optional[List[str]] = None,
    ) -> float:
        slots = extracted.slots
        people_value = filtered_people if filtered_people is not None else list(slots.people or [])
        checks = [
            slots.time,
            slots.location,
            people_value,
            slots.event,
            slots.feeling,
            slots.reflection,
            slots.cause,
            slots.result,
        ]
        filled = sum(1 for value in checks if value not in (None, "", []))
        return min(filled / len(checks), 1.0)
