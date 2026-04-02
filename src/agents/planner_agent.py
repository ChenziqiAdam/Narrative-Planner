from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import yaml
from jinja2 import Template
from openai import OpenAI

from src.config import Config
from src.agents.prompt_formatter import PromptFormatter
from src.prompts.planner_interview_prompts import PLANNER_PROMPT_TEMPLATE
from src.state import MemoryCapsule, PlannerContext, QuestionPlan

try:
    from json_repair import repair_json
except ImportError:  # pragma: no cover - optional dependency in some local envs
    def repair_json(text: str) -> str:
        return text


logger = logging.getLogger(__name__)


class PlannerAgent:
    VALID_ACTIONS = {
        "DEEP_DIVE",
        "BREADTH_SWITCH",
        "CLARIFY",
        "SUMMARIZE",
        "PAUSE_SESSION",
        "CLOSE_INTERVIEW",
    }
    VALID_SLOTS = {"time", "location", "people", "event", "feeling", "reflection", "cause", "result"}
    VALID_TONES = {
        "EMPATHIC_SUPPORTIVE",
        "CURIOUS_INQUIRING",
        "RESPECTFUL_REVERENT",
        "CASUAL_CONVERSATIONAL",
        "PROFESSIONAL_NEUTRAL",
        "GENTLE_WARM",
        "ENCOURAGING",
    }

    def __init__(self, instruction_path: Optional[str] = None):
        self.client = OpenAI(**Config.get_openai_client_kwargs())
        self.model_candidates = Config.get_model_candidates("planner")
        self.model = self.model_candidates[0]
        self.instruction_path = instruction_path or os.path.join(Config.PROJECT_ROOT, "docs", "planner-instruction.yaml")
        self.instruction_payload = self._load_instruction_payload()
        self.max_tokens = 4096 if self._is_reasoning_heavy_model() else 1600
        self.prompt_formatter = PromptFormatter()

    def create_plan(self, context: PlannerContext) -> QuestionPlan:
        if context.turn_index == 0:
            return self._opening_plan(context)

        system_prompt = self._render_system_prompt()
        user_prompt = self._build_user_prompt(context)
        max_attempts = max(1, min(Config.MAX_RETRIES, 2))
        last_error: Optional[Exception] = None

        for model_name in self.model_candidates:
            candidate_max_tokens = 4096 if self._is_reasoning_heavy_model(model_name) else 1600
            for attempt in range(1, max_attempts + 1):
                try:
                    response = self.client.chat.completions.create(
                        model=model_name,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        max_tokens=candidate_max_tokens,
                    )
                    message = response.choices[0].message
                    raw_content = (message.content or "").strip()
                    if not raw_content:
                        reasoning_content = getattr(message, "reasoning_content", "") or ""
                        logger.warning(
                            "PlannerAgent received empty content (model=%s, finish_reason=%s, reasoning_len=%s)",
                            model_name,
                            response.choices[0].finish_reason,
                            len(reasoning_content),
                        )
                    planner_response = self._parse_response(raw_content)
                    self.model = model_name
                    self.max_tokens = candidate_max_tokens
                    return self._to_question_plan(planner_response, context)
                except Exception as exc:
                    last_error = exc
                    logger.warning(
                        "PlannerAgent model=%s attempt %s/%s failed: %s",
                        model_name,
                        attempt,
                        max_attempts,
                        exc,
                    )
                    if self._should_fallback_model(exc):
                        break

        logger.error("PlannerAgent falling back to heuristic plan: %s", last_error)
        return self._fallback_plan(context, last_error)

    def _render_system_prompt(self) -> str:
        return Template(PLANNER_PROMPT_TEMPLATE).render(
            instruction_set=json.dumps(self.instruction_payload, ensure_ascii=False, indent=2),
            timestamp=datetime.now().isoformat(),
            instruction_id=str(uuid.uuid4()),
        )

    def _build_user_prompt(self, context: PlannerContext) -> str:
        """
        构建 Planner 的用户提示词

        使用 PromptFormatter 将结构化数据转写为自然语言描述，
        使 LLM 更容易理解访谈上下文并做出决策。
        """
        prompt_stage = self._prompt_stage(context.turn_index)
        planning_note = self._planning_note(prompt_stage)

        # 使用转写格式化器生成自然语言上下文
        formatted_context = self.prompt_formatter.format_for_planner_decision(context)

        # 提取关键决策信息
        memory = context.memory_capsule or MemoryCapsule.empty()
        available_ids = {
            "theme_ids": list(context.graph_summary.theme_coverage.keys()),
            "active_event_ids": list(context.graph_summary.active_event_ids),
            "active_people_ids": list(memory.active_people_ids),
        }

        return (
            "你是老年回忆录访谈的规划模块（Planner）。\n\n"
            "【任务】\n"
            "基于访谈上下文，决定下一个最优动作。你需要：\n"
            "1. 关注受访者的情绪和精力状态\n"
            "2. 优先处理高优先级的开环线索\n"
            "3. 平衡深度追问与广度覆盖\n"
            "4. 避免重复提问\n\n"
            f"{planning_note}\n\n"
            f"{formatted_context}\n\n"
            "【可用主题ID】（必须使用这些ID，不能编造）\n"
            f"{json.dumps(available_ids, ensure_ascii=False, indent=2)}\n\n"
            "【输出要求】\n"
            "返回严格的 JSON 格式，包含 action 对象：\n"
            "{\n"
            '  "action": {\n'
            '    "primary_action": "DEEP_DIVE|BREADTH_SWITCH|CLARIFY|SUMMARIZE|PAUSE_SESSION|CLOSE_INTERVIEW",\n'
            '    "tactical_goal": {\n'
            '      "goal_type": "EXTRACT_DETAILS|EXTRACT_EMOTIONS|...",\n'
            '      "description": "简短描述"\n'
            '    },\n'
            '    "targets": {\n'
            '      "target_theme_id": "使用可用ID列表中的ID",\n'
            '      "target_event_id": "事件ID或null",\n'
            '      "target_slots": ["time", "location", ...]\n'
            '    },\n'
            '    "tone_constraint": {\n'
            '      "primary_tone": "EMPATHIC_SUPPORTIVE|...",\n'
            '      "secondary_tone": null,\n'
            '      "constraints": ["NO_LEADING_QUESTIONS", ...]\n'
            '    },\n'
            '    "strategy": {\n'
            '      "strategy_type": "OBJECT_TO_EMOTION|...",\n'
            '      "parameters": {},\n'
            '      "priority": 1\n'
            '    }\n'
            '  },\n'
            '  "_debug_snapshot": {\n'
            '    "decision_trace": ["决策理由1", "决策理由2"]\n'
            '  }\n'
            '}'
        )

    def _parse_response(self, raw_content: str) -> Dict[str, Any]:
        text = raw_content.strip()
        if "```json" in text:
            text = text.split("```json", 1)[1].split("```", 1)[0].strip()
        elif "```" in text:
            text = text.split("```", 1)[1].split("```", 1)[0].strip()

        repaired = repair_json(text)
        parsed = json.loads(repaired)
        if not isinstance(parsed, dict) or "action" not in parsed:
            raise ValueError("Planner response is missing required action payload.")
        return parsed

    def _to_question_plan(self, payload: Dict[str, Any], context: PlannerContext) -> QuestionPlan:
        memory = context.memory_capsule or MemoryCapsule.empty()
        action = payload.get("action", {}) if isinstance(payload.get("action"), dict) else {}
        targets = action.get("targets", {}) if isinstance(action.get("targets"), dict) else {}
        tactical_goal = action.get("tactical_goal", {}) if isinstance(action.get("tactical_goal"), dict) else {}
        tone_constraint = (
            action.get("tone_constraint", {})
            if isinstance(action.get("tone_constraint"), dict)
            else {}
        )
        strategy = action.get("strategy", {}) if isinstance(action.get("strategy"), dict) else {}
        debug_snapshot = (
            payload.get("_debug_snapshot", {})
            if isinstance(payload.get("_debug_snapshot"), dict)
            else {}
        )
        decision_trace = debug_snapshot.get("decision_trace", [])
        if not isinstance(decision_trace, list):
            decision_trace = [str(decision_trace)]

        allowed_theme_ids = set(context.graph_summary.theme_coverage.keys())
        allowed_event_ids = set(context.graph_summary.active_event_ids)
        allowed_event_ids.update(
            loop.source_event_id for loop in memory.open_loops if loop.source_event_id
        )
        allowed_person_ids = set(memory.active_people_ids)

        primary_action = str(action.get("primary_action", "")).strip().upper()
        if primary_action not in self.VALID_ACTIONS:
            raise ValueError(f"Invalid primary action: {primary_action}")

        target_slots = [
            slot
            for slot in targets.get("target_slots", [])
            if isinstance(slot, str) and slot in self.VALID_SLOTS
        ][:3]
        primary_tone = str(tone_constraint.get("primary_tone", "")).strip().upper()
        tone = primary_tone if primary_tone in self.VALID_TONES else self._pick_tone(memory)
        secondary_tone = tone_constraint.get("secondary_tone")
        tone_constraints = [
            item for item in tone_constraint.get("constraints", [])
            if isinstance(item, str)
        ]
        strategy_type = str(strategy.get("strategy_type", "")).strip() or self._strategy_from_slots(target_slots)
        strategy_parameters = strategy.get("parameters", {})
        if not isinstance(strategy_parameters, dict):
            strategy_parameters = {}
        strategy_priority = strategy.get("priority", 1)
        if not isinstance(strategy_priority, int):
            strategy_priority = 1

        reference_anchor = targets.get("reference_anchor") or strategy_parameters.get("anchor")
        target_theme_id = self._sanitize_identifier(targets.get("target_theme_id"), allowed_theme_ids)
        target_event_id = self._sanitize_identifier(targets.get("target_event_id"), allowed_event_ids)
        target_person_id = self._sanitize_identifier(targets.get("target_person_id"), allowed_person_ids)
        reasoning_trace = [str(item).strip() for item in decision_trace if str(item).strip()]

        instruction_set = {
            "tactical_goal": {
                "goal_type": tactical_goal.get("goal_type", "EXTRACT_DETAILS"),
                "description": tactical_goal.get("description", ""),
            },
            "targets": {
                "target_theme_id": target_theme_id,
                "target_event_id": target_event_id,
                "target_person_id": target_person_id,
                "target_slots": target_slots,
                "reference_anchor": reference_anchor,
            },
            "tone_constraint": {
                "primary_tone": tone,
                "secondary_tone": secondary_tone,
                "constraints": tone_constraints,
            },
            "strategy": {
                "strategy_type": strategy_type,
                "parameters": strategy_parameters,
                "priority": strategy_priority,
            },
        }

        return QuestionPlan(
            plan_id=f"plan_{uuid.uuid4().hex[:10]}",
            primary_action=primary_action,
            tactical_goal=str(tactical_goal.get("description", "")).strip() or "Continue the interview naturally.",
            target_theme_id=target_theme_id,
            target_event_id=target_event_id,
            target_person_id=target_person_id,
            tactical_goal_type=str(tactical_goal.get("goal_type", "EXTRACT_DETAILS")).strip() or "EXTRACT_DETAILS",
            target_slots=target_slots,
            tone=tone,
            secondary_tone=secondary_tone if isinstance(secondary_tone, str) else None,
            tone_constraints=tone_constraints,
            strategy=strategy_type,
            strategy_parameters=strategy_parameters,
            strategy_priority=strategy_priority,
            reasoning_trace=reasoning_trace or ["Planner returned no decision trace; using parsed action directly."],
            instruction_set=instruction_set,
            reference_anchor=str(reference_anchor).strip() if isinstance(reference_anchor, str) and reference_anchor.strip() else None,
            raw_planner_response=payload,
        )

    def _fallback_plan(self, context: PlannerContext, error: Optional[Exception]) -> QuestionPlan:
        memory = context.memory_capsule or MemoryCapsule.empty()
        graph_summary = context.graph_summary
        reasoning_trace: List[str] = []
        tone = self._pick_tone(memory)

        if graph_summary.overall_coverage >= 0.88 and not memory.open_loops:
            reasoning_trace.append("Planner model unavailable; coverage is already high, so closing gracefully.")
            return self._build_fallback_question_plan(
                primary_action="CLOSE_INTERVIEW",
                tactical_goal="Close the interview gracefully after the main themes are covered.",
                tactical_goal_type="FINAL_CLOSURE",
                target_theme_id=context.graph_summary.current_focus_theme_id,
                target_event_id=None,
                target_person_id=None,
                target_slots=[],
                tone=tone,
                strategy="GRACEFUL_CLOSE",
                strategy_parameters={},
                reasoning_trace=reasoning_trace,
                reference_anchor=None,
                raw_planner_response={"error": str(error) if error else "planner unavailable"},
            )

        if memory.contradictions:
            contradiction = memory.contradictions[0]
            reasoning_trace.append("Planner model unavailable; contradiction detected, so clarify before moving on.")
            return self._build_fallback_question_plan(
                primary_action="CLARIFY",
                tactical_goal=contradiction.description,
                tactical_goal_type="RESOLVE_CONFLICT",
                target_theme_id=context.graph_summary.current_focus_theme_id,
                target_event_id=contradiction.event_ids[0] if contradiction.event_ids else None,
                target_person_id=None,
                target_slots=[],
                tone="GENTLE_WARM",
                strategy="CONFLICT_RESOLUTION",
                strategy_parameters={},
                reasoning_trace=reasoning_trace,
                reference_anchor=contradiction.description,
                raw_planner_response={"error": str(error) if error else "planner unavailable"},
            )

        hottest_loop = memory.open_loops[0] if memory.open_loops else None
        if hottest_loop and self._can_deep_dive(memory):
            target_slots = self._slots_from_loop(hottest_loop)
            reasoning_trace.append(f"Planner model unavailable; follow the hottest open loop: {hottest_loop.description}")
            return self._build_fallback_question_plan(
                primary_action="DEEP_DIVE",
                tactical_goal=hottest_loop.description,
                tactical_goal_type=self._goal_type_from_slots(target_slots),
                target_theme_id=context.graph_summary.current_focus_theme_id,
                target_event_id=hottest_loop.source_event_id,
                target_person_id=None,
                target_slots=target_slots,
                tone=tone,
                strategy=self._strategy_from_slots(target_slots),
                strategy_parameters={"anchor": hottest_loop.description},
                reasoning_trace=reasoning_trace,
                reference_anchor=hottest_loop.description,
                raw_planner_response={"error": str(error) if error else "planner unavailable"},
            )

        target_theme_id = self._pick_undercovered_theme(context)
        if target_theme_id:
            reasoning_trace.append("Planner model unavailable; switching to an under-covered theme.")
            return self._build_fallback_question_plan(
                primary_action="BREADTH_SWITCH",
                tactical_goal="Move to a less-covered life theme while keeping the conversation natural.",
                tactical_goal_type="EXPLORE_THEME",
                target_theme_id=target_theme_id,
                target_event_id=None,
                target_person_id=None,
                target_slots=["event"],
                tone=tone,
                strategy="THEME_SWITCH",
                strategy_parameters={"theme_id": target_theme_id},
                reasoning_trace=reasoning_trace,
                reference_anchor=target_theme_id,
                raw_planner_response={"error": str(error) if error else "planner unavailable"},
            )

        reasoning_trace.append("Planner model unavailable; checkpoint the conversation and invite one reflective detail.")
        return self._build_fallback_question_plan(
            primary_action="SUMMARIZE",
            tactical_goal="Checkpoint the conversation and invite one more reflective memory.",
            tactical_goal_type="SYNTHESIZE_THEME",
            target_theme_id=context.graph_summary.current_focus_theme_id,
            target_event_id=None,
            target_person_id=None,
            target_slots=["reflection"],
            tone=tone,
            strategy="CHECKPOINT_SUMMARY",
            strategy_parameters={},
            reasoning_trace=reasoning_trace,
            reference_anchor=None,
            raw_planner_response={"error": str(error) if error else "planner unavailable"},
        )

    def _build_fallback_question_plan(
        self,
        primary_action: str,
        tactical_goal: str,
        tactical_goal_type: str,
        target_theme_id: Optional[str],
        target_event_id: Optional[str],
        target_person_id: Optional[str],
        target_slots: List[str],
        tone: str,
        strategy: str,
        strategy_parameters: Dict[str, Any],
        reasoning_trace: List[str],
        reference_anchor: Optional[str],
        raw_planner_response: Dict[str, Any],
    ) -> QuestionPlan:
        instruction_set = {
            "tactical_goal": {
                "goal_type": tactical_goal_type,
                "description": tactical_goal,
            },
            "targets": {
                "target_theme_id": target_theme_id,
                "target_event_id": target_event_id,
                "target_person_id": target_person_id,
                "target_slots": target_slots,
                "reference_anchor": reference_anchor,
            },
            "tone_constraint": {
                "primary_tone": tone,
                "secondary_tone": None,
                "constraints": ["NO_LEADING_QUESTIONS"],
            },
            "strategy": {
                "strategy_type": strategy,
                "parameters": strategy_parameters,
                "priority": 1,
            },
        }
        return QuestionPlan(
            plan_id=f"plan_{uuid.uuid4().hex[:10]}",
            primary_action=primary_action,
            tactical_goal=tactical_goal,
            target_theme_id=target_theme_id,
            target_event_id=target_event_id,
            target_person_id=target_person_id,
            tactical_goal_type=tactical_goal_type,
            target_slots=target_slots,
            tone=tone,
            secondary_tone=None,
            tone_constraints=["NO_LEADING_QUESTIONS"],
            strategy=strategy,
            strategy_parameters=strategy_parameters,
            strategy_priority=1,
            reasoning_trace=reasoning_trace,
            instruction_set=instruction_set,
            reference_anchor=reference_anchor,
            raw_planner_response=raw_planner_response,
        )

    def _load_instruction_payload(self) -> Dict[str, Any]:
        try:
            with open(self.instruction_path, "r", encoding="utf-8") as file:
                payload = yaml.safe_load(file) or {}
                if isinstance(payload, dict):
                    return payload
        except Exception as exc:
            logger.warning("Failed to load planner instruction YAML %s: %s", self.instruction_path, exc)
        return {}

    def _sanitize_identifier(self, value: Any, allowed_ids: set[str]) -> Optional[str]:
        if not isinstance(value, str):
            return None
        candidate = value.strip()
        if not candidate:
            return None
        return candidate if candidate in allowed_ids else None

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
        """选择覆盖率最低的主题（优先从 pending 和 mentioned 中选择）"""
        candidates = (
            context.graph_summary.pending_themes +
            context.graph_summary.mentioned_themes
        )
        if not candidates:
            return None
        # 按完成度排序，返回完成度最低的主题
        ranked = sorted(candidates, key=lambda t: t.completion_ratio)
        return ranked[0].theme_id

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

    def _goal_type_from_slots(self, target_slots: List[str]) -> str:
        if any(slot in {"reflection"} for slot in target_slots):
            return "EXTRACT_REFLECTIONS"
        if any(slot in {"feeling"} for slot in target_slots):
            return "EXTRACT_EMOTIONS"
        if any(slot in {"time", "location", "people"} for slot in target_slots):
            return "EXTRACT_DETAILS"
        return "EXTRACT_DETAILS"

    def _is_reasoning_heavy_model(self, model_name: Optional[str] = None) -> bool:
        model_name = (model_name or self.model or "").lower()
        return "thinking" in model_name or "k2.5" in model_name or "reasoning" in model_name

    def _should_fallback_model(self, error: Exception) -> bool:
        message = str(error).lower()
        return (
            "not found the model" in message
            or "permission denied" in message
            or "resource_not_found_error" in message
        )

    def _prompt_stage(self, turn_index: int) -> str:
        if turn_index <= 2:
            return "early"
        if turn_index <= 5:
            return "mid"
        return "full"

    def _planning_note(self, prompt_stage: str) -> str:
        if prompt_stage == "early":
            return (
                "This is still an early interview turn. Use progressive disclosure: stay close to the latest answer, "
                "prefer one concrete follow-up target, and avoid over-planning across too many themes."
            )
        if prompt_stage == "mid":
            return (
                "This is a middle interview turn. You may combine the latest answer with one or two broader memory or graph hints, "
                "but keep the next move anchored and natural."
            )
        return (
            "This is a later interview turn. You can use the broader session state to balance depth, coverage, and open-loop closure."
        )

    def _opening_plan(self, context: PlannerContext) -> QuestionPlan:
        target_theme_id = context.graph_summary.current_focus_theme_id
        if not target_theme_id and context.graph_summary.pending_themes:
            target_theme_id = context.graph_summary.pending_themes[0].theme_id

        background = (context.elder_profile.background_summary or "").strip()
        hometown = (context.elder_profile.hometown or "").strip()
        if background:
            reference_anchor = background[:60]
        elif hometown:
            reference_anchor = hometown
        elif context.elder_profile.birth_year:
            reference_anchor = f"{context.elder_profile.birth_year}年出生"
        else:
            reference_anchor = "人生早期经历"

        return self._build_fallback_question_plan(
            primary_action="BREADTH_SWITCH",
            tactical_goal="Open the interview with a concrete, profile-grounded starting point.",
            tactical_goal_type="EXPLORE_PERIOD",
            target_theme_id=target_theme_id,
            target_event_id=None,
            target_person_id=None,
            target_slots=["event", "time", "location"],
            tone="EMPATHIC_SUPPORTIVE",
            strategy="OPENING_ORIENTATION",
            strategy_parameters={"source": "elder_profile", "opening_turn": True},
            reasoning_trace=[
                "Opening turn: use known elder profile instead of waiting for a heavy planner inference.",
                "Ground the first question in stable profile facts so the interview can start immediately.",
            ],
            reference_anchor=reference_anchor,
            raw_planner_response={"mode": "opening_profile_bootstrap"},
        )
