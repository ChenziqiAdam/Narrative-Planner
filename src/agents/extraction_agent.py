from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import List

from src.core.event_extractor import EventExtractor
from src.core.interfaces import DialogueTurn, EventSlots, ExtractedEvent
from src.state import (
    CanonicalEvent,
    EmotionalState,
    ExtractionMetadata,
    ExtractionResult,
    GraphDelta,
    MemoryDelta,
    SessionState,
    TurnRecord,
)


class ExtractionAgent:
    def __init__(self, extractor: EventExtractor | None = None):
        self.extractor = extractor or EventExtractor()

    async def extract(
        self,
        state: SessionState,
        turn_record: TurnRecord,
    ) -> tuple[List[ExtractedEvent], ExtractionResult]:
        current_turn = DialogueTurn(
            turn_id=turn_record.turn_id,
            session_id=state.session_id,
            timestamp=turn_record.timestamp,
            interviewer_question=turn_record.interviewer_question,
            interviewer_action=state.pending_action or "continue",
            interviewee_raw_reply=turn_record.interviewee_answer,
            extracted_events=[],
        )
        context = [
            DialogueTurn(
                turn_id=previous.turn_id,
                session_id=state.session_id,
                timestamp=previous.timestamp,
                interviewer_question=previous.interviewer_question,
                interviewer_action="continue",
                interviewee_raw_reply=previous.interviewee_answer,
                extracted_events=[],
            )
            for previous in state.recent_transcript(3)
        ]
        existing_events = [event.to_dict() for event in state.canonical_events.values()]
        extracted_events = await self.extractor.extract_with_existing_events(
            current_turn,
            context,
            existing_events,
        )
        debug_trace = self.extractor.consume_debug_trace(turn_record.turn_id)
        if not extracted_events:
            fallback_event = self._build_fallback_partial_event(turn_record)
            if fallback_event:
                extracted_events = [fallback_event]
                debug_trace = {
                    **debug_trace,
                    "fallback_reason": debug_trace.get("fallback_reason", "fallback_partial_event"),
                }

        extraction_result = self._build_extraction_result(turn_record, extracted_events, debug_trace)
        return extracted_events, extraction_result

    def _build_extraction_result(
        self,
        turn_record: TurnRecord,
        extracted_events: List[ExtractedEvent],
        debug_trace: dict,
    ) -> ExtractionResult:
        candidate_events = [self._build_candidate_event(event, turn_record.turn_id) for event in extracted_events]
        metadata = ExtractionMetadata(
            extractor_version="event_extractor_v2",
            confidence=(
                sum(event.confidence for event in extracted_events) / len(extracted_events)
                if extracted_events
                else 0.0
            ),
            source_spans=[turn_record.interviewee_answer[:120]] if turn_record.interviewee_answer else [],
            is_incremental_update=any(event.is_update for event in extracted_events),
            matched_event_id=next((event.updated_event_id for event in extracted_events if event.updated_event_id), None),
        )
        emotional_state_update = self._estimate_emotional_state(turn_record.interviewee_answer)
        memory_delta = MemoryDelta(
            summary_updates=[candidate.summary for candidate in candidate_events if candidate.summary],
            emotional_state_update=emotional_state_update,
        )
        graph_delta = GraphDelta(
            event_candidates=candidate_events,
            theme_hints=[event.theme_id for event in extracted_events if event.theme_id],
        )
        return ExtractionResult(
            turn_id=turn_record.turn_id,
            metadata=metadata,
            memory_delta=memory_delta,
            graph_delta=graph_delta,
            debug_trace=debug_trace or {},
        )

    def _build_candidate_event(self, event: ExtractedEvent, turn_id: str) -> CanonicalEvent:
        raw_clues = str(event.slots.unexpanded_clues or "").replace(";", ",").replace("，", ",")
        clues = [item.strip() for item in raw_clues.split(",") if item.strip()]
        return CanonicalEvent(
            event_id=event.event_id,
            title=(event.slots.event or "Untitled event")[:24],
            summary=event.slots.event or "Untitled event",
            time=event.slots.time,
            location=event.slots.location,
            people_names=list(event.slots.people or []),
            event=event.slots.event,
            feeling=event.slots.feeling,
            reflection=event.slots.reflection,
            cause=event.slots.cause,
            result=event.slots.result,
            unexpanded_clues=clues,
            theme_id=event.theme_id,
            source_turn_ids=[turn_id],
            completeness_score=self._completeness_score(event),
            confidence=event.confidence,
            merge_status="uncertain" if event.is_update else "new",
        )

    def _build_fallback_partial_event(self, turn_record: TurnRecord) -> ExtractedEvent | None:
        answer = (turn_record.interviewee_answer or "").strip()
        if not self._looks_like_event(answer):
            return None

        time_hint = self._extract_time_hint(answer)
        location_hint = self._extract_location_hint(answer)
        people = self._extract_people(answer)
        summary = self._summarize_event(answer)
        theme_hint = self._infer_theme_hint(answer)
        feeling_hint = self._extract_feeling_hint(answer)

        confidence = 0.25
        if time_hint:
            confidence += 0.1
        if location_hint:
            confidence += 0.1
        if people:
            confidence += 0.05

        return ExtractedEvent(
            event_id=f"evt_{uuid.uuid4().hex[:12]}",
            extracted_at=datetime.now(),
            slots=EventSlots(
                time=time_hint,
                location=location_hint,
                people=people or None,
                event=summary,
                feeling=feeling_hint,
                unexpanded_clues="Some core dimensions are still missing and should be filled in later turns.",
                cause=None,
                result=None,
                reflection=None,
            ),
            confidence=min(confidence, 0.55),
            theme_id=theme_hint,
            source_turns=[turn_record.turn_id],
            is_update=False,
            updated_event_id=None,
        )

    def _completeness_score(self, extracted: ExtractedEvent) -> float:
        checks = [
            extracted.slots.time,
            extracted.slots.location,
            extracted.slots.people,
            extracted.slots.event,
            extracted.slots.feeling,
            extracted.slots.reflection,
            extracted.slots.cause,
            extracted.slots.result,
        ]
        filled = sum(1 for value in checks if value not in (None, "", []))
        return min(filled / len(checks), 1.0)

    def _estimate_emotional_state(self, answer: str) -> EmotionalState:
        positive_keywords = ["开心", "高兴", "幸福", "自豪", "喜欢", "温暖", "快乐"]
        negative_keywords = ["难过", "伤心", "遗憾", "辛苦", "困难", "痛苦", "压抑"]
        pos_hits = sum(1 for word in positive_keywords if word in answer)
        neg_hits = sum(1 for word in negative_keywords if word in answer)
        valence = 0.0 if pos_hits == neg_hits else max(min((pos_hits - neg_hits) / 3.0, 1.0), -1.0)
        return EmotionalState(
            emotional_energy=min(max(len(answer) / 180.0, 0.2), 1.0),
            cognitive_energy=min(max(len(answer) / 140.0, 0.25), 1.0),
            valence=valence,
            confidence=0.6,
            evidence=[answer[:80]] if answer else [],
        )

    def _looks_like_event(self, answer: str) -> bool:
        if len(answer) < 25:
            return False
        if re.search(r"(?:19|20)\d{2}", answer):
            return True
        event_markers = [
            "年", "月", "当时", "后来", "第一次", "那天", "那年", "小时候", "进了", "去了", "结婚", "工作",
        ]
        return any(marker in answer for marker in event_markers)

    def _extract_time_hint(self, answer: str) -> str | None:
        patterns = [
            r"(?:19|20)\d{2}年(?:\d{1,2}月)?",
            r"(?:19|20)\d{2}",
            r"\d{1,2}岁(?:那年)?",
            r"小时候",
            r"年轻时候",
            r"后来",
            r"当时",
        ]
        for pattern in patterns:
            match = re.search(pattern, answer)
            if match:
                return match.group(0)
        return None

    def _extract_location_hint(self, answer: str) -> str | None:
        patterns = [
            r"在([^，。；]{2,18}(?:厂|学校|车间|村|县|城|站|家))",
            r"进了([^，。；]{2,18}(?:厂|学校|车间))",
        ]
        for pattern in patterns:
            match = re.search(pattern, answer)
            if match:
                return match.group(1)
        return None

    def _extract_people(self, answer: str) -> List[str]:
        people = []
        relation_keywords = ["父亲", "母亲", "爸爸", "妈妈", "老师", "师傅", "朋友", "同事", "老伴", "儿子", "女儿"]
        if "我" in answer:
            people.append("我")
        for keyword in relation_keywords:
            if keyword in answer and keyword not in people:
                people.append(keyword)
        return people

    def _summarize_event(self, answer: str) -> str:
        first_sentence = re.split(r"[。！？!?.]", answer)[0].strip()
        if first_sentence:
            return first_sentence[:80]
        return answer[:80]

    def _infer_theme_hint(self, answer: str) -> str | None:
        theme_keywords = {
            "career": ["工作", "工厂", "上班", "车间", "师傅"],
            "migration": ["离开", "去了", "搬家", "下乡"],
            "marriage": ["结婚", "对象", "爱人", "老伴"],
            "family": ["父亲", "母亲", "孩子", "家庭"],
            "childhood": ["小时候", "童年", "上学"],
        }
        for theme_hint, keywords in theme_keywords.items():
            if any(keyword in answer for keyword in keywords):
                return theme_hint
        return None

    def _extract_feeling_hint(self, answer: str) -> str | None:
        feeling_keywords = ["紧张", "兴奋", "害怕", "高兴", "难过", "自豪", "辛苦"]
        found = [keyword for keyword in feeling_keywords if keyword in answer]
        if found:
            return "、".join(found[:2])
        return None

    async def close(self) -> None:
        await self.extractor.stop()
