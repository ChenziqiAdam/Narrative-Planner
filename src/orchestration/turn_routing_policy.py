from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

from src.orchestration.routing_calibration import (
    CalibrationRecord,
    PersonalizedRoutingConfig,
    RoutingCalibrationBuffer,
)
from src.state import GraphSummary, SessionState, TurnRecord
from src.state.models import serialize_value


GRAPH_FAST_ROUTE = "fast_reply_recent_context"
GRAPH_GUIDED_ROUTE = "graph_guided_planning"
GRAPH_UPDATE_ROUTE = "graph_update_required"
GRAPH_DEFER_ROUTE = "defer_graph_update"


ROUTING_ROUTES = (
    GRAPH_FAST_ROUTE,
    GRAPH_GUIDED_ROUTE,
    GRAPH_UPDATE_ROUTE,
    GRAPH_DEFER_ROUTE,
)


@dataclass
class TurnRoutingDecision:
    route: str
    confidence: float
    reasons: list[str] = field(default_factory=list)
    signals: Dict[str, Any] = field(default_factory=dict)
    scores: Dict[str, float] = field(default_factory=dict)
    llm_used: bool = False
    classifier_version: str = "turn_routing_policy_v1"

    def to_dict(self) -> Dict[str, Any]:
        return serialize_value(self)


class TurnRoutingPolicy:
    """Cheap, deterministic routing before extraction/merge/graph projection.

    The policy intentionally does not call an LLM. It predicts whether the
    latest reply is safe to answer from recent context, needs macro graph
    guidance, must synchronously update structured memory, or can update later.

    Supports three-phase adaptive calibration:
    - Warm-up: returns UPDATE_ROUTE unconditionally, collects calibration data.
    - Calibrated: uses PersonalizedRoutingConfig for personalized scoring.
    """

    def __init__(
        self,
        config: Optional[PersonalizedRoutingConfig] = None,
        buffer: Optional[RoutingCalibrationBuffer] = None,
    ):
        self.config = config or PersonalizedRoutingConfig()
        self.buffer = buffer or RoutingCalibrationBuffer()

    BACKCHANNELS = {
        "嗯",
        "嗯嗯",
        "嗯是的",
        "哦",
        "噢",
        "是",
        "是的",
        "对",
        "对的",
        "好",
        "好的",
        "可以",
        "行",
        "得行",
        "没了",
        "没有了",
        "差不多",
        "还好",
        "不知道",
        "想不起来",
        "记不清了",
        "不记得了",
    }
    PAUSE_MARKERS = (
        "累",
        "休息",
        "下次",
        "改天",
        "暂停",
        "停一下",
        "不想说",
        "说不动",
        "有点困",
        "今天先",
    )
    UNCERTAIN_MARKERS = ("想不起来", "记不清", "忘了", "不记得", "不知道")
    TIME_PATTERN = re.compile(
        r"(?:18|19|20)\d{2}年?|(?:\d{1,2}岁)|小时候|年轻时|那年|当年|当时|后来|以前|解放|文革|大跃进|退休|结婚|参军|上学"
    )
    LOCATION_PATTERN = re.compile(
        r"(?:在|到|去|回|从|住在|搬到)[\u4e00-\u9fffA-Za-z0-9]{1,18}"
        r"(?:厂|村|县|市|省|学校|医院|家|车间|单位|部队|公社|镇|乡|城|岛|山|河|路|街|院)"
    )
    PERSON_MARKERS = (
        "父亲",
        "母亲",
        "爸爸",
        "妈妈",
        "爹",
        "娘",
        "丈夫",
        "老伴",
        "爱人",
        "妻子",
        "孩子",
        "儿子",
        "女儿",
        "孙子",
        "孙女",
        "哥哥",
        "姐姐",
        "弟弟",
        "妹妹",
        "老师",
        "师傅",
        "同事",
        "朋友",
        "领导",
        "邻居",
        "战友",
        "大哥",
        "二哥",
        "大姐",
        "二姐",
    )
    CAUSE_RESULT_MARKERS = (
        "因为",
        "所以",
        "结果",
        "后来",
        "于是",
        "导致",
        "影响",
        "原因",
        "就这样",
        "从那以后",
    )
    FEELING_MARKERS = (
        "觉得",
        "感觉",
        "心里",
        "难过",
        "高兴",
        "开心",
        "害怕",
        "委屈",
        "自豪",
        "遗憾",
        "后悔",
        "感恩",
        "感激",
        "苦",
        "累",
        "不容易",
        "舍不得",
    )
    REFLECTION_MARKERS = (
        "一辈子",
        "现在想",
        "回头看",
        "明白",
        "道理",
        "改变",
        "学会",
        "最重要",
        "做人",
        "价值",
        "想告诉",
        "留下",
        "看法",
        "态度",
    )
    EVENT_MARKERS = (
        "上学",
        "工作",
        "结婚",
        "参军",
        "退休",
        "生孩子",
        "调到",
        "去了",
        "进了",
        "遇到",
        "发生",
        "经历",
        "那件事",
        "第一次",
        "最难",
        "最开心",
        "最自豪",
        "有一次",
        "那时候",
        "那会儿",
    )

    def evaluate(
        self,
        state: SessionState,
        turn_record: TurnRecord,
        pre_graph_summary: Optional[GraphSummary] = None,
    ) -> TurnRoutingDecision:
        answer = (turn_record.interviewee_answer or "").strip()
        question = (turn_record.interviewer_question or "").strip()
        normalized = self._normalize_answer(answer)

        # ── Build marker sets (personalized + defaults) ──
        time_kw = self.config.personal_time_keywords
        location_kw = self.config.personal_location_keywords
        person_kw = self.config.personal_person_keywords
        feeling_kw = self.config.personal_feeling_keywords
        reflection_kw = self.config.personal_reflection_keywords
        event_kw = self.config.personal_event_keywords
        cause_result_kw = self.config.personal_cause_result_keywords

        has_time_marker = bool(self.TIME_PATTERN.search(answer)) or self._contains_any(answer, time_kw)
        has_location_marker = bool(self.LOCATION_PATTERN.search(answer)) or self._contains_any(answer, location_kw)
        has_person_marker = self._contains_any(answer, self.PERSON_MARKERS) or self._contains_any(answer, person_kw)
        has_cause_result_marker = self._contains_any(answer, self.CAUSE_RESULT_MARKERS) or self._contains_any(answer, cause_result_kw)
        has_feeling_marker = self._contains_any(answer, self.FEELING_MARKERS) or self._contains_any(answer, feeling_kw)
        has_reflection_marker = self._contains_any(answer, self.REFLECTION_MARKERS) or self._contains_any(answer, reflection_kw)
        has_event_marker = self._contains_any(answer, self.EVENT_MARKERS) or self._contains_any(answer, event_kw)
        markers = {
            "has_time_marker": has_time_marker,
            "has_location_marker": has_location_marker,
            "has_person_marker": has_person_marker,
            "has_cause_result_marker": has_cause_result_marker,
            "has_feeling_marker": has_feeling_marker,
            "has_reflection_marker": has_reflection_marker,
            "has_event_marker": has_event_marker,
        }
        marker_count = sum(1 for value in markers.values() if value)

        targeted_slot = self._infer_targeted_slot(question)
        answered_targeted_slot = self._answers_targeted_slot(targeted_slot, answer, markers)
        answer_len = len(answer)
        is_short = answer_len <= self.config.short_answer_threshold
        is_backchannel = normalized in self.BACKCHANNELS
        pause_or_fatigue = self._contains_any(answer, self.PAUSE_MARKERS)
        uncertainty = self._contains_any(answer, self.UNCERTAIN_MARKERS)

        # ── Warm-up phase: always return UPDATE, collect data for calibration ──
        if self.is_warmup(state):
            return TurnRoutingDecision(
                route=GRAPH_UPDATE_ROUTE,
                confidence=1.0,
                reasons=["warmup_phase"],
                signals={
                    "answer_length": answer_len,
                    "is_short": is_short,
                    "is_backchannel": is_backchannel,
                    "marker_count": marker_count,
                    "targeted_slot": targeted_slot,
                    "answered_targeted_slot": answered_targeted_slot,
                    "warmup_remaining": max(0, self.config.warmup_turns - state.turn_count),
                    **markers,
                },
                scores={},
                llm_used=False,
                classifier_version="warmup",
            )

        recent_low_info_streak = self._recent_low_information_streak(state)
        current_event_completeness = self._current_event_completeness(state)
        graph_staleness_turns = self._graph_staleness_turns(state, turn_record)
        overall_coverage = pre_graph_summary.overall_coverage if pre_graph_summary else 0.0
        theme_imbalance = self._theme_imbalance(pre_graph_summary)

        fast_score = (
            (0.38 if is_short else 0.0)
            + (0.42 if is_backchannel else 0.0)
            + (0.24 if pause_or_fatigue else 0.0)
            + (0.20 if marker_count == 0 else 0.0)
            + (0.10 if not targeted_slot else 0.0)
            + (0.10 if uncertainty and answer_len <= self.config.short_answer_threshold * 1.5 else 0.0)
            - min(marker_count * 0.12, 0.42)
            - (0.30 if answered_targeted_slot else 0.0)
        )
        update_score = (
            (self.config.weight_time if has_time_marker else 0.0)
            + (self.config.weight_location if has_location_marker else 0.0)
            + (self.config.weight_person if has_person_marker else 0.0)
            + (self.config.weight_event if has_event_marker else 0.0)
            + (self.config.weight_cause_result if has_cause_result_marker else 0.0)
            + (self.config.weight_feeling if has_feeling_marker else 0.0)
            + (self.config.weight_reflection if has_reflection_marker else 0.0)
            + min(answer_len / self.config.length_bonus_base, 1.0) * self.config.weight_length
            + (self.config.weight_answered_slot if answered_targeted_slot else 0.0)
            + (self.config.weight_multi_marker if marker_count >= 2 else 0.0)
            - (0.30 if is_backchannel else 0.0)
            - (0.16 if pause_or_fatigue and marker_count == 0 else 0.0)
        )
        macro_score = (
            min(recent_low_info_streak, 3) * 0.16
            + (0.20 if current_event_completeness >= 0.68 else 0.0)
            + (0.12 if theme_imbalance >= 0.45 else 0.0)
            + (0.08 if overall_coverage < 0.45 and state.turn_count >= 4 else 0.0)
            + (0.10 if marker_count == 0 and not is_short else 0.0)
            - (0.18 if update_score >= 0.52 else 0.0)
        )
        defer_score = (
            (0.16 if answer_len >= 45 else 0.0)
            + (0.18 if has_feeling_marker or has_reflection_marker else 0.0)
            + (0.12 if marker_count in {1, 2} else 0.0)
            + (0.12 if not answered_targeted_slot else 0.0)
            + (0.08 if graph_staleness_turns == 0 else 0.0)
            - (0.22 if update_score >= 0.64 else 0.0)
            - (0.18 if is_backchannel else 0.0)
        )

        scores = {
            GRAPH_FAST_ROUTE: self._clamp01(fast_score),
            GRAPH_GUIDED_ROUTE: self._clamp01(macro_score),
            GRAPH_UPDATE_ROUTE: self._clamp01(update_score),
            GRAPH_DEFER_ROUTE: self._clamp01(defer_score),
        }

        route, reasons = self._choose_route(
            scores=scores,
            marker_count=marker_count,
            is_backchannel=is_backchannel,
            pause_or_fatigue=pause_or_fatigue,
            answered_targeted_slot=answered_targeted_slot,
            recent_low_info_streak=recent_low_info_streak,
        )
        confidence = self._confidence(route, scores)
        signals = {
            "answer_length": answer_len,
            "is_short": is_short,
            "is_backchannel": is_backchannel,
            "pause_or_fatigue": pause_or_fatigue,
            "uncertainty": uncertainty,
            "marker_count": marker_count,
            "targeted_slot": targeted_slot,
            "answered_targeted_slot": answered_targeted_slot,
            "recent_low_info_streak": recent_low_info_streak,
            "current_event_completeness": round(current_event_completeness, 4),
            "graph_staleness_turns": graph_staleness_turns,
            "overall_coverage": round(overall_coverage, 4),
            "theme_imbalance": round(theme_imbalance, 4),
            **markers,
        }
        return TurnRoutingDecision(
            route=route,
            confidence=confidence,
            reasons=reasons,
            signals=signals,
            scores={key: round(value, 4) for key, value in scores.items()},
            llm_used=False,
        )

    def build_actual_outcome(
        self,
        decision: TurnRoutingDecision,
        merge_result: Any,
        extracted_events: Iterable[Any],
        pre_coverage: float,
        post_coverage: float,
        turn_record: TurnRecord,
    ) -> Dict[str, Any]:
        extracted_events = list(extracted_events or [])
        coverage_delta = post_coverage - pre_coverage
        touched_event_count = len(getattr(merge_result, "touched_event_ids", []) or [])
        touched_person_count = len(getattr(merge_result, "touched_person_ids", []) or [])
        new_event_count = len(getattr(merge_result, "new_event_ids", []) or [])
        updated_event_count = len(getattr(merge_result, "updated_event_ids", []) or [])
        new_person_count = len(getattr(merge_result, "new_person_ids", []) or [])
        extracted_event_count = len(extracted_events)
        answer_len = len((turn_record.interviewee_answer or "").strip())
        actual_update_value = (
            touched_event_count > 0
            or touched_person_count > 0
            or extracted_event_count > 0
            or coverage_delta > 0.005
        )
        high_value_update = (
            new_event_count > 0
            or updated_event_count > 0
            or new_person_count > 0
            or coverage_delta > 0.02
        )
        answer_local_low_information = (
            (
                decision.signals.get("marker_count", 0) == 0
                and (
                    decision.signals.get("is_short")
                    or decision.signals.get("is_backchannel")
                    or decision.signals.get("uncertainty")
                )
            )
            or (
                decision.signals.get("is_short")
                and decision.signals.get("uncertainty")
            )
        )
        context_carryover_merge_possible = (
            answer_local_low_information
            and extracted_event_count > 0
            and coverage_delta <= 0.005
            and new_event_count > 0
        )
        answer_local_high_value_update = high_value_update and not context_carryover_merge_possible
        low_information_actual = (
            not actual_update_value
            and coverage_delta <= 0.005
            and answer_len <= 40
        )
        predicted_skip_sync = decision.route in {GRAPH_FAST_ROUTE, GRAPH_GUIDED_ROUTE, GRAPH_DEFER_ROUTE}
        skip_would_be_safe = (not high_value_update) if predicted_skip_sync else None
        answer_local_skip_would_be_safe = (
            (not answer_local_high_value_update) if predicted_skip_sync else None
        )
        route_match_binary = (
            decision.route == GRAPH_UPDATE_ROUTE and actual_update_value
        ) or (
            decision.route != GRAPH_UPDATE_ROUTE and not high_value_update
        )
        answer_local_route_match_binary = (
            decision.route == GRAPH_UPDATE_ROUTE and answer_local_high_value_update
        ) or (
            decision.route != GRAPH_UPDATE_ROUTE and not answer_local_high_value_update
        )
        return {
            "actual_update_value": actual_update_value,
            "high_value_update": high_value_update,
            "answer_local_high_value_update": answer_local_high_value_update,
            "answer_local_low_information": answer_local_low_information,
            "context_carryover_merge_possible": context_carryover_merge_possible,
            "low_information_actual": low_information_actual,
            "coverage_delta": round(coverage_delta, 4),
            "extracted_event_count": extracted_event_count,
            "touched_event_count": touched_event_count,
            "touched_person_count": touched_person_count,
            "new_event_count": new_event_count,
            "updated_event_count": updated_event_count,
            "new_person_count": new_person_count,
            "predicted_skip_sync": predicted_skip_sync,
            "skip_would_be_safe": skip_would_be_safe,
            "answer_local_skip_would_be_safe": answer_local_skip_would_be_safe,
            "route_match_binary": route_match_binary,
            "answer_local_route_match_binary": answer_local_route_match_binary,
        }

    def _choose_route(
        self,
        scores: Dict[str, float],
        marker_count: int,
        is_backchannel: bool,
        pause_or_fatigue: bool,
        answered_targeted_slot: bool,
        recent_low_info_streak: int,
    ) -> tuple[str, list[str]]:
        reasons: list[str] = []
        if (is_backchannel or pause_or_fatigue) and scores[GRAPH_UPDATE_ROUTE] < 0.36:
            reasons.append("short_or_pause_without_structural_markers")
            return GRAPH_FAST_ROUTE, reasons

        if marker_count == 0 and scores[GRAPH_FAST_ROUTE] >= 0.55 and scores[GRAPH_UPDATE_ROUTE] < 0.25:
            reasons.append("short_reply_without_structural_markers")
            return GRAPH_FAST_ROUTE, reasons

        if answered_targeted_slot:
            reasons.append("targeted_slot_answer")
            return GRAPH_UPDATE_ROUTE, reasons

        if marker_count >= 2 and scores[GRAPH_UPDATE_ROUTE] >= 0.45:
            reasons.append("multiple_structural_markers")
            return GRAPH_UPDATE_ROUTE, reasons

        if scores[GRAPH_UPDATE_ROUTE] >= 0.58:
            reasons.append("high_predicted_information_gain")
            return GRAPH_UPDATE_ROUTE, reasons

        if scores[GRAPH_FAST_ROUTE] >= 0.68 and scores[GRAPH_UPDATE_ROUTE] < 0.42:
            reasons.append("high_confidence_low_information")
            return GRAPH_FAST_ROUTE, reasons

        if recent_low_info_streak >= 2 and scores[GRAPH_GUIDED_ROUTE] >= 0.44:
            reasons.append("macro_planning_after_low_gain_streak")
            return GRAPH_GUIDED_ROUTE, reasons

        if scores[GRAPH_DEFER_ROUTE] >= 0.42 and scores[GRAPH_UPDATE_ROUTE] < 0.58:
            reasons.append("useful_but_not_immediate")
            return GRAPH_DEFER_ROUTE, reasons

        if scores[GRAPH_GUIDED_ROUTE] >= 0.50 and scores[GRAPH_UPDATE_ROUTE] < 0.48:
            reasons.append("macro_graph_guidance_needed")
            return GRAPH_GUIDED_ROUTE, reasons

        reasons.append("conservative_default_update")
        return GRAPH_UPDATE_ROUTE, reasons

    def _confidence(self, route: str, scores: Dict[str, float]) -> float:
        top = scores.get(route, 0.0)
        runners_up = [score for key, score in scores.items() if key != route]
        margin = top - max(runners_up or [0.0])
        confidence = 0.48 + top * 0.38 + max(margin, 0.0) * 0.28
        if route == GRAPH_UPDATE_ROUTE:
            confidence = max(confidence, 0.56)
        return round(self._clamp01(confidence), 4)

    def _infer_targeted_slot(self, question: str) -> Optional[str]:
        if not question:
            return None
        slot_patterns = [
            ("time", ("什么时候", "哪年", "几年", "时间", "多大", "几岁")),
            ("location", ("哪里", "在哪", "地方", "什么地方", "厂里", "学校", "家里")),
            ("people", ("谁", "什么人", "家人", "同事", "朋友", "老师", "师傅", "孩子", "老伴")),
            ("cause", ("为什么", "原因", "怎么会", "怎么就")),
            ("result", ("后来", "结果", "最后", "之后")),
            ("feeling", ("感受", "感觉", "心里", "心情", "滋味")),
            ("reflection", ("回头看", "影响", "改变", "怎么看", "明白", "意义")),
            ("event", ("发生", "经过", "怎么回事", "讲讲", "说说", "细节")),
        ]
        for slot, patterns in slot_patterns:
            if any(pattern in question for pattern in patterns):
                return slot
        return None

    def _answers_targeted_slot(
        self,
        targeted_slot: Optional[str],
        answer: str,
        markers: Dict[str, bool],
    ) -> bool:
        if not targeted_slot:
            return False
        if targeted_slot == "time":
            return markers["has_time_marker"]
        if targeted_slot == "location":
            return markers["has_location_marker"]
        if targeted_slot == "people":
            return markers["has_person_marker"]
        if targeted_slot in {"cause", "result"}:
            return markers["has_cause_result_marker"] or len(answer) >= 28
        if targeted_slot == "feeling":
            return markers["has_feeling_marker"] or len(answer) >= 28
        if targeted_slot == "reflection":
            return markers["has_reflection_marker"] or len(answer) >= 32
        if targeted_slot == "event":
            return markers["has_event_marker"] or len(answer) >= 32
        return len(answer) >= 32

    def _recent_low_information_streak(self, state: SessionState, max_window: int = 3) -> int:
        streak = 0
        for turn in reversed(state.transcript[-max_window:]):
            debug_trace = turn.debug_trace if isinstance(turn.debug_trace, dict) else {}
            extraction = debug_trace.get("extraction", {}) or {}
            coverage = debug_trace.get("coverage", {}) or {}
            extracted_count = int(extraction.get("extracted_event_count", 0) or 0)
            coverage_delta = float(coverage.get("delta", 0.0) or 0.0)
            if extracted_count == 0 and coverage_delta <= 0.005 and len((turn.interviewee_answer or "").strip()) < 40:
                streak += 1
                continue
            break
        return streak

    def _current_event_completeness(self, state: SessionState) -> float:
        active_event_ids = state.memory_capsule.active_event_ids if state.memory_capsule else []
        if not active_event_ids:
            return 0.0
        event = state.canonical_events.get(active_event_ids[-1])
        if not event:
            return 0.0
        return float(event.completeness_score or 0.0)

    def _graph_staleness_turns(self, state: SessionState, turn_record: TurnRecord) -> int:
        last_update_turn_index = int(state.metadata.get("last_graph_update_turn_index", 0) or 0)
        if last_update_turn_index <= 0:
            return 0
        return max(0, turn_record.turn_index - last_update_turn_index)

    def _theme_imbalance(self, graph_summary: Optional[GraphSummary]) -> float:
        if not graph_summary or not graph_summary.theme_coverage:
            return 0.0
        values = list(graph_summary.theme_coverage.values())
        return max(values) - min(values) if values else 0.0

    def _normalize_answer(self, answer: str) -> str:
        return re.sub(r"[\s，。！？、,.!?…~～]+", "", answer or "")

    def _contains_any(self, text: str, markers: Iterable[str]) -> bool:
        return any(marker in text for marker in markers)

    def _clamp01(self, value: float) -> float:
        return max(0.0, min(1.0, value))

    # ── Calibration helpers ──

    def is_warmup(self, state: SessionState) -> bool:
        """Whether the session is still in the warm-up phase."""
        return state.turn_count < self.config.warmup_turns or not self.config.calibrated

    def record_markers_for_calibration(
        self,
        state: SessionState,
        turn_record: TurnRecord,
        markers_hit: Dict[str, bool],
        marker_count: int,
        targeted_slot: Optional[str],
        answered_targeted_slot: bool,
    ) -> CalibrationRecord:
        """Record marker signals during warm-up for later calibration."""
        return self.buffer.record_markers(
            turn_id=turn_record.turn_id,
            turn_index=turn_record.turn_index,
            answer=turn_record.interviewee_answer or "",
            markers_hit=markers_hit,
            marker_count=marker_count,
            targeted_slot=targeted_slot,
            answered_targeted_slot=answered_targeted_slot,
        )

    def record_outcomes_for_calibration(
        self,
        turn_id: str,
        coverage_delta: float,
        extracted_count: int,
        touched_events: int,
        new_events: int,
        new_people: int,
        extracted_events: List[Any],
    ) -> None:
        """Record actual extraction outcomes for calibration."""
        self.buffer.record_outcomes(
            turn_id=turn_id,
            coverage_delta=coverage_delta,
            extracted_count=extracted_count,
            touched_events=touched_events,
            new_events=new_events,
            new_people=new_people,
            extracted_events=extracted_events,
        )

    def should_calibrate(self, state: SessionState) -> bool:
        """Check if calibration should be triggered now."""
        if self.config.calibrated:
            turns_since = state.turn_count - self.config.last_recalibration_turn
            return turns_since >= self.config.recalibration_interval
        return self.buffer.has_enough_data(self.config.warmup_turns)
