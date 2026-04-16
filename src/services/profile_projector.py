from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

from src.services.relation_lexicon import get_relation_group
from src.state import (
    DynamicElderProfile,
    DynamicProfileField,
    ElderProfile,
    PersonProfile,
    SessionState,
    TurnRecord,
)


class ProfileProjector:
    """
    Builds a low-frequency dynamic elder profile from merged planner memory.

    The initial ElderProfile remains the input truth. This projector maintains a
    derived planning profile that can be refreshed asynchronously after merge.
    """

    SCHEMA: Dict[str, Tuple[str, ...]] = {
        "core_identity_and_personality": (
            "identity_background",
            "knowledge_level",
            "life_overview",
            "personality_traits",
            "speaking_style",
            "common_expressions",
        ),
        "current_life_status": (
            "daily_habits_preferences",
            "interests_hobbies_social",
            "health_status_current_concerns",
        ),
        "family_situation": (
            "marital_status",
            "parents_children",
            "siblings",
            "grandchildren",
            "other_relatives",
        ),
        "life_views_and_attitudes": (
            "life_attitude_philosophy",
            "society_interpersonal_relationships",
            "core_values",
        ),
    }

    PARENT_CHILD_CODES = {"mother", "father", "parent", "child", "grandparent"}
    SIBLING_CODES = {"sibling"}
    GRANDCHILD_CODES = {"grandchild"}
    SPOUSE_CODES = {"spouse"}

    HEALTH_KEYWORDS = (
        "hospital",
        "illness",
        "surgery",
        "medicine",
        "pain",
        "blood pressure",
        "diabetes",
        "cancer",
        "doctor",
        "nurse",
        "住院",
        "生病",
        "手术",
        "吃药",
        "疼",
        "血压",
        "糖尿病",
        "医生",
    )
    INTEREST_KEYWORDS = (
        "sing",
        "dance",
        "cards",
        "mahjong",
        "walk",
        "volunteer",
        "garden",
        "read",
        "唱歌",
        "跳舞",
        "打牌",
        "麻将",
        "散步",
        "志愿",
        "种菜",
        "读书",
    )
    VALUE_KEYWORDS = {
        "family": ("family", "children", "parents", "home", "家庭", "孩子", "父母", "家里"),
        "diligence": ("work hard", "hardship", "endure", "辛苦", "吃苦", "勤快", "努力"),
        "gratitude": ("grateful", "thanks", "感恩", "感谢", "知足"),
        "responsibility": ("responsibility", "duty", "责任", "担当", "照顾"),
        "independence": ("independent", "self-reliant", "独立", "靠自己", "自立"),
    }

    def build_initial_profile(self, state: SessionState) -> DynamicElderProfile:
        profile = DynamicElderProfile(updated_at=datetime.now())
        self._ensure_schema(profile)
        self._seed_from_elder_profile(profile, state.elder_profile)
        profile.profile_quality = self._compute_profile_quality(profile)
        profile.planner_guidance = self._build_planner_guidance(profile, state)
        return profile

    def should_update(
        self,
        state: SessionState,
        merge_result: Any,
        turn_record: TurnRecord,
        min_turns_between_updates: int = 3,
        max_turns_between_updates: int = 5,
    ) -> Tuple[bool, str]:
        if state.dynamic_profile is None:
            return True, "profile_missing"

        last_turn_index = int(state.metadata.get("dynamic_profile_last_turn_index", 0) or 0)
        turns_since_update = max(0, turn_record.turn_index - last_turn_index)

        significant_reason = self._detect_significant_trigger(state, merge_result)
        if significant_reason:
            return True, significant_reason

        if turns_since_update >= max_turns_between_updates:
            return True, "max_turn_window"

        touched_event_ids = list(getattr(merge_result, "touched_event_ids", []) or [])
        if turns_since_update >= min_turns_between_updates and touched_event_ids:
            return True, "summary_turn_window"

        return False, "below_update_threshold"

    def update_profile(
        self,
        state: SessionState,
        turn_record: TurnRecord,
        merge_result: Any,
        reason: str,
    ) -> DynamicElderProfile:
        profile = state.dynamic_profile or self.build_initial_profile(state)
        self._ensure_schema(profile)
        self._seed_from_elder_profile(profile, state.elder_profile)

        touched_event_ids = list(getattr(merge_result, "touched_event_ids", []) or [])
        touched_events = [
            event for event_id in touched_event_ids
            if (event := state.canonical_events.get(event_id)) is not None
        ]

        self._project_events(profile, turn_record, touched_events)
        self._project_people(profile, turn_record, state.people_registry.values())
        self._project_latest_answer(profile, turn_record)

        profile.update_count += 1
        profile.last_updated_turn_id = turn_record.turn_id
        profile.last_update_reason = reason
        profile.updated_at = datetime.now()
        profile.profile_quality = self._compute_profile_quality(profile)
        profile.planner_guidance = self._build_planner_guidance(profile, state)
        return profile

    def _detect_significant_trigger(self, state: SessionState, merge_result: Any) -> Optional[str]:
        new_person_ids = list(getattr(merge_result, "new_person_ids", []) or [])
        if len(new_person_ids) >= 2:
            return "multiple_new_people"

        for event_id in list(getattr(merge_result, "touched_event_ids", []) or []):
            event = state.canonical_events.get(event_id)
            if not event:
                continue
            if event.completeness_score >= 0.65 and event.confidence >= 0.65:
                return "major_event_completed"
            if event.reflection and len(event.reflection.strip()) >= 12:
                return "high_value_reflection"
            if event.result and event.cause and event.people_names:
                return "causal_event_completed"
        return None

    def _ensure_schema(self, profile: DynamicElderProfile) -> None:
        for section_name, field_names in self.SCHEMA.items():
            section = getattr(profile, section_name)
            for field_name in field_names:
                section.setdefault(field_name, DynamicProfileField())

    def _seed_from_elder_profile(self, profile: DynamicElderProfile, elder_profile: ElderProfile) -> None:
        identity_parts = []
        if elder_profile.name:
            identity_parts.append(f"name={elder_profile.name}")
        if elder_profile.birth_year:
            identity_parts.append(f"birth_year={elder_profile.birth_year}")
        if elder_profile.age:
            identity_parts.append(f"age={elder_profile.age}")
        if elder_profile.hometown:
            identity_parts.append(f"hometown={elder_profile.hometown}")
        if elder_profile.background_summary:
            identity_parts.append(f"background={elder_profile.background_summary}")

        if identity_parts:
            self._upsert_field(
                profile.core_identity_and_personality,
                "identity_background",
                "; ".join(identity_parts),
                confidence=0.9,
            )

        if elder_profile.background_summary:
            self._upsert_field(
                profile.core_identity_and_personality,
                "life_overview",
                [elder_profile.background_summary],
                confidence=0.75,
                append=True,
            )

        stable = elder_profile.stable_facts or {}
        for key in ("education", "knowledge_level", "occupation", "work", "profession"):
            if stable.get(key):
                self._upsert_field(
                    profile.core_identity_and_personality,
                    "knowledge_level",
                    f"{key}: {stable[key]}",
                    confidence=0.65,
                )
                break

    def _project_events(
        self,
        profile: DynamicElderProfile,
        turn_record: TurnRecord,
        events: Iterable[Any],
    ) -> None:
        event_summaries = []
        reflections = []
        feeling_texts = []
        event_ids = []
        health_notes = []
        interest_notes = []

        for event in events:
            event_ids.append(event.event_id)
            text_parts = [
                event.summary,
                event.time,
                event.location,
                " ".join(event.people_names or []),
                event.cause,
                event.result,
                event.feeling,
                event.reflection,
            ]
            text = " ".join(str(part) for part in text_parts if part)
            if event.summary:
                event_summaries.append(self._compact_text(event.summary, 80))
            if event.reflection:
                reflections.append(self._compact_text(event.reflection, 80))
            if event.feeling:
                feeling_texts.append(self._compact_text(event.feeling, 40))
            if self._contains_any(text, self.HEALTH_KEYWORDS):
                health_notes.append(self._compact_text(text, 90))
            if self._contains_any(text, self.INTEREST_KEYWORDS):
                interest_notes.append(self._compact_text(text, 90))

        if event_summaries:
            self._upsert_field(
                profile.core_identity_and_personality,
                "life_overview",
                event_summaries,
                confidence=0.65,
                turn_id=turn_record.turn_id,
                event_ids=event_ids,
                append=True,
            )

        if reflections:
            self._upsert_field(
                profile.life_views_and_attitudes,
                "life_attitude_philosophy",
                reflections,
                confidence=0.7,
                turn_id=turn_record.turn_id,
                event_ids=event_ids,
                append=True,
            )
            values = self._derive_values_from_text(" ".join(reflections))
            if values:
                self._upsert_field(
                    profile.life_views_and_attitudes,
                    "core_values",
                    values,
                    confidence=0.55,
                    turn_id=turn_record.turn_id,
                    event_ids=event_ids,
                    append=True,
                )

        traits = self._derive_traits_from_text(" ".join(feeling_texts + reflections))
        if traits:
            self._upsert_field(
                profile.core_identity_and_personality,
                "personality_traits",
                traits,
                confidence=0.5,
                turn_id=turn_record.turn_id,
                event_ids=event_ids,
                append=True,
            )

        if health_notes:
            self._upsert_field(
                profile.current_life_status,
                "health_status_current_concerns",
                health_notes,
                confidence=0.55,
                turn_id=turn_record.turn_id,
                event_ids=event_ids,
                append=True,
            )

        if interest_notes:
            self._upsert_field(
                profile.current_life_status,
                "interests_hobbies_social",
                interest_notes,
                confidence=0.55,
                turn_id=turn_record.turn_id,
                event_ids=event_ids,
                append=True,
            )

    def _project_people(
        self,
        profile: DynamicElderProfile,
        turn_record: TurnRecord,
        people: Iterable[PersonProfile],
    ) -> None:
        marital = []
        parents_children = []
        siblings = []
        grandchildren = []
        other_relatives = []
        social_people = []

        for person in people:
            relation = person.relation_to_elder or ""
            label = person.display_name
            group = get_relation_group(relation or label)
            payload = self._person_note(person)

            if relation in self.SPOUSE_CODES:
                marital.append(payload)
            elif relation in self.PARENT_CHILD_CODES:
                parents_children.append(payload)
            elif relation in self.SIBLING_CODES:
                siblings.append(payload)
            elif relation in self.GRANDCHILD_CODES:
                grandchildren.append(payload)
            elif group == "family":
                other_relatives.append(payload)
            elif group in {"friend", "work"}:
                social_people.append(payload)

        if marital:
            self._upsert_field(
                profile.family_situation,
                "marital_status",
                marital,
                confidence=0.65,
                turn_id=turn_record.turn_id,
                append=True,
            )
        if parents_children:
            self._upsert_field(
                profile.family_situation,
                "parents_children",
                parents_children,
                confidence=0.65,
                turn_id=turn_record.turn_id,
                append=True,
            )
        if siblings:
            self._upsert_field(
                profile.family_situation,
                "siblings",
                siblings,
                confidence=0.65,
                turn_id=turn_record.turn_id,
                append=True,
            )
        if grandchildren:
            self._upsert_field(
                profile.family_situation,
                "grandchildren",
                grandchildren,
                confidence=0.65,
                turn_id=turn_record.turn_id,
                append=True,
            )
        if other_relatives:
            self._upsert_field(
                profile.family_situation,
                "other_relatives",
                other_relatives,
                confidence=0.55,
                turn_id=turn_record.turn_id,
                append=True,
            )
        if social_people:
            self._upsert_field(
                profile.life_views_and_attitudes,
                "society_interpersonal_relationships",
                social_people,
                confidence=0.45,
                turn_id=turn_record.turn_id,
                append=True,
            )

    def _project_latest_answer(self, profile: DynamicElderProfile, turn_record: TurnRecord) -> None:
        answer = (turn_record.interviewee_answer or "").strip()
        if not answer:
            return

        speaking_style = self._infer_speaking_style(answer)
        self._upsert_field(
            profile.core_identity_and_personality,
            "speaking_style",
            speaking_style,
            confidence=0.45,
            turn_id=turn_record.turn_id,
        )

        common_expressions = self._extract_common_expressions(answer)
        if common_expressions:
            self._upsert_field(
                profile.core_identity_and_personality,
                "common_expressions",
                common_expressions,
                confidence=0.35,
                turn_id=turn_record.turn_id,
                append=True,
            )

        if self._contains_any(answer, self.HEALTH_KEYWORDS):
            self._upsert_field(
                profile.current_life_status,
                "health_status_current_concerns",
                [self._compact_text(answer, 90)],
                confidence=0.45,
                turn_id=turn_record.turn_id,
                append=True,
            )

        if self._contains_any(answer, self.INTEREST_KEYWORDS):
            self._upsert_field(
                profile.current_life_status,
                "interests_hobbies_social",
                [self._compact_text(answer, 90)],
                confidence=0.45,
                turn_id=turn_record.turn_id,
                append=True,
            )

    def _upsert_field(
        self,
        section: Dict[str, DynamicProfileField],
        field_name: str,
        value: Any,
        confidence: float,
        turn_id: Optional[str] = None,
        event_ids: Optional[List[str]] = None,
        append: bool = False,
    ) -> None:
        field = section.setdefault(field_name, DynamicProfileField())
        normalized_value = self._normalize_value(value)
        if normalized_value in (None, "", []):
            return

        if append:
            existing_items = self._as_list(field.value)
            new_items = self._as_list(normalized_value)
            merged = self._merge_unique(existing_items, new_items, limit=8)
            field.value = merged
        elif field.value in (None, "", []) or confidence >= field.confidence:
            field.value = normalized_value

        field.confidence = round(max(float(field.confidence or 0.0), float(confidence)), 3)
        if turn_id and turn_id not in field.evidence_turn_ids:
            field.evidence_turn_ids.append(turn_id)
        for event_id in event_ids or []:
            if event_id and event_id not in field.evidence_event_ids:
                field.evidence_event_ids.append(event_id)
        field.updated_at = datetime.now()

    def _compute_profile_quality(self, profile: DynamicElderProfile) -> Dict[str, float]:
        payload: Dict[str, float] = {}
        section_scores = []
        for section_name, field_names in self.SCHEMA.items():
            section = getattr(profile, section_name)
            filled = sum(1 for field_name in field_names if section.get(field_name) and section[field_name].value not in (None, "", []))
            score = filled / max(1, len(field_names))
            payload[section_name] = round(score, 4)
            section_scores.append(score)
        payload["overall"] = round(sum(section_scores) / max(1, len(section_scores)), 4)
        return payload

    def _build_planner_guidance(self, profile: DynamicElderProfile, state: SessionState) -> List[str]:
        guidance = []

        family_score = profile.profile_quality.get("family_situation", 0.0)
        if family_score < 0.35:
            guidance.append("Family profile is still thin; when the story naturally allows it, ask about spouse, children, siblings, or grandchildren.")

        current_life_score = profile.profile_quality.get("current_life_status", 0.0)
        if current_life_score < 0.35 and state.turn_count >= 3:
            guidance.append("Current-life profile is undercovered; consider a gentle bridge to daily routines, hobbies, social activity, or health concerns.")

        values_field = profile.life_views_and_attitudes.get("core_values")
        if values_field and values_field.value:
            guidance.append(f"Known values to connect with: {', '.join(self._as_list(values_field.value)[:3])}.")

        speaking_style = profile.core_identity_and_personality.get("speaking_style")
        if speaking_style and isinstance(speaking_style.value, str):
            guidance.append(f"Adapt question shape to speaking style: {speaking_style.value}.")

        if not guidance:
            guidance.append("Dynamic profile is sparse; prioritize concrete events before making broad personality inferences.")

        return guidance[:4]

    def _person_note(self, person: PersonProfile) -> str:
        relation = person.relation_to_elder or "unknown_relation"
        event_count = len(person.related_event_ids or [])
        if event_count:
            return f"{person.display_name} ({relation}, linked_events={event_count})"
        return f"{person.display_name} ({relation})"

    def _infer_speaking_style(self, answer: str) -> str:
        length = len(answer)
        if length < 40:
            return "brief replies; use short, concrete prompts and avoid stacking multiple questions"
        if length > 180:
            return "story-rich replies; allow narrative space, then follow up on one concrete detail"
        if "?" in answer or "？" in answer:
            return "interactive replies; acknowledge uncertainty and clarify gently"
        return "moderate detail; one focused follow-up works best"

    def _extract_common_expressions(self, answer: str) -> List[str]:
        parts = [
            part.strip()
            for part in re.split(r"[。！？!?；;\n]+", answer)
            if 4 <= len(part.strip()) <= 22
        ]
        return self._merge_unique([], parts, limit=3)

    def _derive_traits_from_text(self, text: str) -> List[str]:
        traits = []
        lowered = text.lower()
        if self._contains_any(lowered, ("hardship", "辛苦", "困难", "吃苦", "不容易")):
            traits.append("resilient")
        if self._contains_any(lowered, ("proud", "自豪", "骄傲")):
            traits.append("pride in contribution")
        if self._contains_any(lowered, ("regret", "遗憾", "后悔")):
            traits.append("reflective about regret")
        if self._contains_any(lowered, ("thank", "感恩", "感谢", "知足")):
            traits.append("grateful")
        return traits

    def _derive_values_from_text(self, text: str) -> List[str]:
        lowered = text.lower()
        values = []
        for value_name, keywords in self.VALUE_KEYWORDS.items():
            if self._contains_any(lowered, keywords):
                values.append(value_name)
        return values

    def _contains_any(self, text: str, keywords: Iterable[str]) -> bool:
        lowered = (text or "").lower()
        return any(keyword and keyword.lower() in lowered for keyword in keywords)

    def _compact_text(self, value: str, limit: int) -> str:
        text = " ".join(str(value).split())
        return text[:limit]

    def _normalize_value(self, value: Any) -> Any:
        if isinstance(value, str):
            return self._compact_text(value, 240)
        if isinstance(value, list):
            return [self._compact_text(item, 160) for item in value if str(item).strip()]
        return value

    def _as_list(self, value: Any) -> List[str]:
        if value in (None, "", []):
            return []
        if isinstance(value, list):
            return [str(item) for item in value if str(item).strip()]
        return [str(value)]

    def _merge_unique(self, existing: List[str], new_items: List[str], limit: int) -> List[str]:
        merged = []
        seen = set()
        for item in [*existing, *new_items]:
            normalized = str(item).strip()
            key = normalized.lower()
            if normalized and key not in seen:
                seen.add(key)
                merged.append(normalized)
        return merged[-limit:]
