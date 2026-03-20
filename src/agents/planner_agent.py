from __future__ import annotations

import uuid
from typing import List, Optional

from src.state import MemoryCapsule, PlannerContext, QuestionPlan


class PlannerAgent:
    THEME_LABELS = {
        "THEME_01_LIFE_CHAPTERS": "人生早期的重要阶段",
        "THEME_02_PEAK_EXPERIENCE": "人生中的高光时刻",
        "THEME_03_LOW_POINT": "人生中的低谷经历",
        "THEME_04_TURNING_POINT": "人生转折点",
        "THEME_05_CHILDHOOD_POSITIVE": "童年里快乐的回忆",
        "THEME_06_CHILDHOOD_NEGATIVE": "童年里艰难的经历",
        "THEME_07_ADULT_MEMORY": "成年后印象深刻的经历",
        "THEME_13_LIFE_CHALLENGE": "人生中最难的挑战",
        "THEME_14_HEALTH": "和健康相关的重要经历",
        "THEME_15_LOSS": "重要的失落经历",
        "THEME_16_FAILURE_REGRET": "失败或遗憾的经历",
    }

    def create_plan(self, context: PlannerContext) -> QuestionPlan:
        memory = context.memory_capsule or MemoryCapsule.empty()
        turn_index = context.turn_index
        graph_summary = context.graph_summary

        reasoning_trace: List[str] = []
        tone = self._pick_tone(memory)

        if turn_index == 0:
            target_theme_id = graph_summary.unresolved_theme_ids[0] if graph_summary.unresolved_theme_ids else None
            reasoning_trace.append("Opening turn: start with a broad, welcoming question.")
            return QuestionPlan(
                plan_id=f"plan_{uuid.uuid4().hex[:10]}",
                primary_action="BREADTH_SWITCH",
                tactical_goal="Open the interview and orient around the elder's early life or main timeline.",
                target_theme_id=target_theme_id,
                target_event_id=None,
                target_person_id=None,
                target_slots=[],
                tone=tone,
                strategy="OPENING_ORIENTATION",
                reasoning_trace=reasoning_trace,
                candidate_questions=self._opening_candidates(context, target_theme_id),
            )

        if graph_summary.overall_coverage >= 0.88 and not memory.open_loops:
            reasoning_trace.append("Coverage is high and no major open loops remain.")
            return QuestionPlan(
                plan_id=f"plan_{uuid.uuid4().hex[:10]}",
                primary_action="CLOSE_INTERVIEW",
                tactical_goal="Close the interview gracefully after confirming major life themes are covered.",
                target_theme_id=context.graph_summary.current_focus_theme_id,
                target_event_id=None,
                target_person_id=None,
                target_slots=[],
                tone=tone,
                strategy="GRACEFUL_CLOSE",
                reasoning_trace=reasoning_trace,
                candidate_questions=["今天聊了很多珍贵的回忆。最后，您最希望后人记住您人生中的哪一部分？"],
            )

        if memory.contradictions:
            contradiction = memory.contradictions[0]
            reasoning_trace.append("A contradiction was detected and should be clarified before moving on.")
            return QuestionPlan(
                plan_id=f"plan_{uuid.uuid4().hex[:10]}",
                primary_action="CLARIFY",
                tactical_goal=contradiction.description,
                target_theme_id=context.graph_summary.current_focus_theme_id,
                target_event_id=contradiction.event_ids[0] if contradiction.event_ids else None,
                target_person_id=None,
                target_slots=[],
                tone="GENTLE_WARM",
                strategy="CONFLICT_RESOLUTION",
                reasoning_trace=reasoning_trace,
                candidate_questions=["我想确认一下刚才那段经历的时间或地点，您愿意再帮我理一理吗？"],
            )

        hottest_loop = memory.open_loops[0] if memory.open_loops else None
        if hottest_loop and self._can_deep_dive(memory):
            target_slots = self._slots_from_loop(hottest_loop)
            reasoning_trace.append(f"Open loop selected: {hottest_loop.description}")
            return QuestionPlan(
                plan_id=f"plan_{uuid.uuid4().hex[:10]}",
                primary_action="DEEP_DIVE",
                tactical_goal=hottest_loop.description,
                target_theme_id=context.graph_summary.current_focus_theme_id,
                target_event_id=hottest_loop.source_event_id,
                target_person_id=None,
                target_slots=target_slots,
                tone=tone,
                strategy=self._strategy_from_slots(target_slots),
                reasoning_trace=reasoning_trace,
                candidate_questions=self._follow_up_candidates(hottest_loop.description, target_slots),
            )

        target_theme_id = self._pick_undercovered_theme(context)
        if target_theme_id:
            reasoning_trace.append(f"Switching breadth to an under-covered theme: {target_theme_id}")
            return QuestionPlan(
                plan_id=f"plan_{uuid.uuid4().hex[:10]}",
                primary_action="BREADTH_SWITCH",
                tactical_goal="Move to a less-covered life theme while keeping the conversation natural.",
                target_theme_id=target_theme_id,
                target_event_id=None,
                target_person_id=None,
                target_slots=[],
                tone=tone,
                strategy="THEME_SWITCH",
                reasoning_trace=reasoning_trace,
                candidate_questions=self._theme_switch_candidates(context, target_theme_id),
            )

        reasoning_trace.append("No urgent open loop found; summarize to checkpoint and invite one more detail.")
        return QuestionPlan(
            plan_id=f"plan_{uuid.uuid4().hex[:10]}",
            primary_action="SUMMARIZE",
            tactical_goal="Checkpoint the conversation and invite one more reflective memory.",
            target_theme_id=context.graph_summary.current_focus_theme_id,
            target_event_id=None,
            target_person_id=None,
            target_slots=["reflection"],
            tone=tone,
            strategy="CHECKPOINT_SUMMARY",
            reasoning_trace=reasoning_trace,
            candidate_questions=["回头看刚才聊到的这些经历，哪一段最能代表那个阶段的您？"],
        )

    def _pick_tone(self, memory: MemoryCapsule) -> str:
        emotional_state = memory.emotional_state
        if not emotional_state:
            return "EMPATHIC_SUPPORTIVE"
        if emotional_state.cognitive_energy < 0.4:
            return "GENTLE_WARM"
        if emotional_state.valence < -0.2:
            return "EMPATHIC_SUPPORTIVE"
        if emotional_state.valence > 0.2:
            return "CURIOUS_INQUIRING"
        return "EMPATHIC_SUPPORTIVE"

    def _can_deep_dive(self, memory: MemoryCapsule) -> bool:
        emotional_state = memory.emotional_state
        if not emotional_state:
            return True
        return emotional_state.cognitive_energy >= 0.35

    def _pick_undercovered_theme(self, context: PlannerContext) -> Optional[str]:
        unresolved = context.graph_summary.unresolved_theme_ids
        if not unresolved:
            return None
        ranked = sorted(
            unresolved,
            key=lambda theme_id: context.graph_summary.theme_coverage.get(theme_id, 0.0),
        )
        return ranked[0]

    def _slots_from_loop(self, loop) -> List[str]:
        if loop.loop_type == "unexpanded_clue":
            return ["event", "reflection"]
        if loop.loop_type == "person_gap":
            return ["people"]
        description = loop.description.lower()
        candidates = []
        for slot_name in ["time", "location", "people", "reflection", "feeling", "cause", "result"]:
            if slot_name in description:
                candidates.append(slot_name)
        return candidates or ["event"]

    def _strategy_from_slots(self, target_slots: List[str]) -> str:
        if any(slot in {"reflection", "feeling"} for slot in target_slots):
            return "OBJECT_TO_EMOTION"
        if any(slot in {"time", "location"} for slot in target_slots):
            return "TIMELINE_SLOT_FILL"
        if "people" in target_slots:
            return "PERSON_CONTEXT_FILL"
        return "DETAIL_EXPANSION"

    def _opening_candidates(self, context: PlannerContext, target_theme_id: Optional[str]) -> List[str]:
        background = (context.elder_profile.background_summary or "").lower()
        if any(keyword in background for keyword in ["工厂", "工作", "上班", "career", "work"]):
            return ["您还记得自己第一次参加工作时的情景吗？能从那一天讲起，也说说大概是什么时候、在哪里吗？"]
        if any(keyword in background for keyword in ["结婚", "家庭", "孩子", "老伴"]):
            return ["您还记得自己成家前后最重要的一件事吗？愿意从那件具体的事讲起，也说说当时是什么时候、在哪里吗？"]
        if target_theme_id and target_theme_id in context.graph_summary.theme_coverage:
            return ["您能先讲一件发生在年轻时候、至今记得最清楚的具体事情吗？最好说说大概是什么时候、在哪里发生的。"]
        return ["您能先讲一件对您很重要、而且记得最清楚的具体事情吗？最好说说大概是什么时候、在哪里发生的。"]

    def _follow_up_candidates(self, description: str, target_slots: List[str]) -> List[str]:
        slot_templates = {
            "time": "这件事大概发生在什么时候，您还记得吗？",
            "location": "当时是在哪里发生的，周围是什么样子？",
            "people": "当时还有哪些人和您在一起，他们和您是什么关系？",
            "reflection": "现在回头看这件事，您觉得它对您意味着什么？",
            "feeling": "那一刻您心里最强烈的感受是什么？",
            "cause": "这件事是怎么开始的，背后有什么原因吗？",
            "result": "后来事情是怎么发展的，对您带来了什么变化？",
            "event": "您愿意把这件事再展开讲讲，尤其是最关键的细节吗？",
        }
        questions = [slot_templates[slot] for slot in target_slots if slot in slot_templates]
        if not questions:
            questions.append(f"关于“{description}”，您愿意再多讲一点细节吗？")
        return questions[:3]

    def _theme_switch_candidates(self, context: PlannerContext, target_theme_id: str) -> List[str]:
        theme_title = self.THEME_LABELS.get(target_theme_id, "那段重要经历")
        return [f"我们换到您人生的另一段重要经历上。关于{theme_title}，您能讲一件记得最清楚的具体事情吗？最好说说它大概是什么时候、在哪里发生的。"]
