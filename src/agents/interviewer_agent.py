from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

from openai import OpenAI

from src.config import Config
from src.state import ElderProfile, GraphSummary, MemoryCapsule, QuestionPlan, TurnRecord

try:
    from json_repair import repair_json
except ImportError:  # pragma: no cover - optional dependency in some local envs
    def repair_json(text: str) -> str:
        return text


logger = logging.getLogger(__name__)


class InterviewerAgent:
    ACTION_GUIDANCE = {
        "DEEP_DIVE": "Stay on the current event and ask for one more important layer of detail, feeling, or meaning.",
        "BREADTH_SWITCH": "Move naturally to a new life stage or theme without sounding abrupt.",
        "CLARIFY": "Gently resolve an ambiguity or contradiction in time, place, people, or sequence.",
        "SUMMARIZE": "Briefly checkpoint what was shared and invite one more representative detail.",
        "PAUSE_SESSION": "Land softly and avoid opening a large new thread.",
        "CLOSE_INTERVIEW": "End gracefully with a warm closing prompt instead of opening a new topic.",
    }
    SLOT_GUIDANCE = {
        "time": "when it happened",
        "location": "where it happened",
        "people": "who was there and how they were related",
        "event": "what concretely happened",
        "feeling": "what the elder felt at that moment",
        "reflection": "what it means looking back now",
        "cause": "what led to it",
        "result": "what changed afterward",
    }

    def __init__(self):
        self.client = OpenAI(**Config.get_openai_client_kwargs())
        self.model_candidates = Config.get_model_candidates("interviewer")
        self.model = self.model_candidates[0]
        self.max_tokens = 4096 if self._is_reasoning_heavy_model() else 1024
        prompt_path = os.path.join(Config.PROMPTS_DIR, "baseline_system_prompt.txt")
        with open(prompt_path, "r", encoding="utf-8") as file:
            self.system_prompt_template = file.read()

    def generate_question(
        self,
        elder_profile: ElderProfile,
        recent_transcript: List[TurnRecord],
        memory_capsule: MemoryCapsule,
        graph_summary: GraphSummary,
        plan: QuestionPlan,
        focus_event_payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, str]:
        if not recent_transcript:
            return self._opening_response(elder_profile, plan)

        system_prompt = self._render_system_prompt(elder_profile)
        user_prompt = self._build_user_prompt(
            elder_profile,
            recent_transcript,
            memory_capsule,
            graph_summary,
            plan,
            focus_event_payload,
        )
        max_attempts = max(1, min(Config.MAX_RETRIES, 2))
        last_error: Optional[Exception] = None

        for model_name in self.model_candidates:
            candidate_max_tokens = 4096 if self._is_reasoning_heavy_model(model_name) else 1024
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
                            "InterviewerAgent received empty content (model=%s, finish_reason=%s, reasoning_len=%s)",
                            model_name,
                            response.choices[0].finish_reason,
                            len(reasoning_content),
                        )
                    parsed = self._parse_response(raw_content, plan)
                    if parsed.get("question"):
                        self.model = model_name
                        self.max_tokens = candidate_max_tokens
                        return parsed
                except Exception as exc:
                    last_error = exc
                    logger.warning(
                        "InterviewerAgent model=%s attempt %s/%s failed: %s",
                        model_name,
                        attempt,
                        max_attempts,
                        exc,
                    )
                    if self._should_fallback_model(exc):
                        break

        logger.error("InterviewerAgent returning retry response: %s", last_error)
        return self._retry_response(plan, opening_turn=not recent_transcript)

    def _render_system_prompt(self, elder_profile: ElderProfile) -> str:
        basic_info = self._build_basic_info_text(elder_profile)
        replacements = [
            "{{elder_basic_info}}",
            "[用户的基本生平信息]",
            "[闁活潿鍔嶉崺娑㈡儍閸曨偆鍞ㄩ柡鍫墰閺佹捇鐛崗鍛箚闁诡厾妫?",
            "[閻劍鍩涢惃鍕唨閺堫剛鏁撻獮鍏呬繆閹棇",
        ]
        rendered = self.system_prompt_template
        for placeholder in replacements:
            rendered = rendered.replace(placeholder, basic_info)
        return rendered

    def _build_user_prompt(
        self,
        elder_profile: ElderProfile,
        recent_transcript: List[TurnRecord],
        memory_capsule: MemoryCapsule,
        graph_summary: GraphSummary,
        plan: QuestionPlan,
        focus_event_payload: Optional[Dict[str, Any]],
    ) -> str:
        prompt_stage = self._prompt_stage(recent_transcript)
        transcript_limit = 1 if prompt_stage == "early" else 2 if prompt_stage == "mid" else 3
        transcript_payload = [
            {
                "turn_index": turn.turn_index,
                "interviewer_question": turn.interviewer_question,
                "interviewee_answer": turn.interviewee_answer,
            }
            for turn in recent_transcript[-transcript_limit:]
        ]
        latest_answer = recent_transcript[-1].interviewee_answer if recent_transcript else ""
        memory_payload = self._build_memory_payload(memory_capsule, prompt_stage)
        graph_payload = self._build_graph_payload(graph_summary, prompt_stage)
        plan_payload = {
            "primary_action": plan.primary_action,
            "tactical_goal": plan.tactical_goal,
            "tactical_goal_type": plan.tactical_goal_type,
            "target_theme_id": plan.target_theme_id,
            "target_event_id": plan.target_event_id,
            "target_person_id": plan.target_person_id,
            "target_slots": plan.target_slots,
            "tone": plan.tone,
            "secondary_tone": plan.secondary_tone,
            "tone_constraints": plan.tone_constraints,
            "strategy": plan.strategy,
            "strategy_parameters": plan.strategy_parameters,
            "strategy_priority": plan.strategy_priority,
            "reference_anchor": plan.reference_anchor,
            "reasoning_trace": plan.reasoning_trace,
            "instruction_set": plan.instruction_set,
        }
        action_hint = self.ACTION_GUIDANCE.get(plan.primary_action, "Follow the planner decision faithfully.")
        slot_focus = (
            ", ".join(f"{slot} ({self.SLOT_GUIDANCE.get(slot, slot)})" for slot in plan.target_slots)
            if plan.target_slots
            else "none"
        )
        follow_up_note = self._follow_up_note(prompt_stage)
        focus_payload = self._build_focus_event_payload(focus_event_payload, prompt_stage)
        elder_profile_payload = self._build_elder_profile_payload(elder_profile, prompt_stage)

        return (
            "You are the interviewer language layer.\n"
            "Use the same interviewing style as the baseline interviewer, but you now have richer planner and memory context.\n"
            "The planner decision is the source of truth for WHAT to ask about. Your job is to turn it into one natural question.\n\n"
            "Return strict JSON with keys `action` and `question` only.\n"
            "Hard constraints:\n"
            "- Ask exactly one question.\n"
            "- Keep the question concise, natural, warm, and non-redundant.\n"
            "- Do not expose internal labels like planner, strategy, target_slots, graph, memory, or theme IDs.\n"
            "- Prefer staying close to the latest interviewee answer unless the planner explicitly requests a breadth switch.\n"
            "- If there is a focus event, use it as the main anchor for wording.\n"
            "- Respect do_not_repeat and avoid repeating nearly identical wording from recent turns.\n"
            "- If cognitive energy is low, make the question shorter and gentler.\n"
            "- If emotional valence is negative, you may add a very short validating clause before the question, but still ask only one question.\n"
            "- If the planner action is CLOSE_INTERVIEW, return action=`end` with a short warm closing prompt.\n"
            "- If the planner action is BREADTH_SWITCH, SUMMARIZE, or PAUSE_SESSION, action should usually be `next_phase`.\n"
            "- Otherwise action should usually be `continue`.\n"
            "- Use progressive disclosure: prioritize the most recent answer and the focus event before broader session state.\n\n"
            f"Planning note:\n{follow_up_note}\n\n"
            f"Prompt stage: {prompt_stage}\n\n"
            "Planner guidance summary:\n"
            f"- primary_action={plan.primary_action}: {action_hint}\n"
            f"- target_slots={slot_focus}\n"
            f"- tone={plan.tone}\n"
            f"- strategy={plan.strategy}\n"
            f"- reference_anchor={plan.reference_anchor or 'none'}\n\n"
            f"Elder profile:\n{json.dumps(elder_profile_payload, ensure_ascii=False, indent=2)}\n\n"
            f"Planner decision:\n{json.dumps(plan_payload, ensure_ascii=False, indent=2)}\n\n"
            f"Focus event payload:\n{json.dumps(focus_payload, ensure_ascii=False, indent=2)}\n\n"
            f"Memory capsule:\n{json.dumps(memory_payload, ensure_ascii=False, indent=2)}\n\n"
            f"Graph summary:\n{json.dumps(graph_payload, ensure_ascii=False, indent=2)}\n\n"
            f"Recent transcript:\n{json.dumps(transcript_payload, ensure_ascii=False, indent=2)}\n\n"
            f"Latest interviewee answer:\n{latest_answer or '(opening turn)'}"
        )

    def _parse_response(self, raw_content: str, plan: QuestionPlan) -> Dict[str, str]:
        text = raw_content.strip()
        if "```json" in text:
            text = text.split("```json", 1)[1].split("```", 1)[0].strip()
        elif "```" in text:
            text = text.split("```", 1)[1].split("```", 1)[0].strip()

        if not text:
            raise ValueError("Interviewer response was empty.")

        try:
            parsed = json.loads(repair_json(text))
        except json.JSONDecodeError:
            return {
                "action": self._map_action(plan.primary_action),
                "question": text.strip().strip('"'),
            }

        action = str(parsed.get("action", self._map_action(plan.primary_action))).strip() or "continue"
        question = str(parsed.get("question", "")).strip()
        if action == "end" and not question:
            question = "今天聊了很多珍贵的回忆，谢谢您愿意和我分享。"
        if not question:
            raise ValueError("Interviewer response missing question.")
        return {"action": action, "question": question}

    def _retry_response(self, plan: QuestionPlan, opening_turn: bool = False) -> Dict[str, str]:
        if opening_turn:
            question = "抱歉，我想先根据您刚才的信息整理一下，再继续向您请教，可以稍等一下吗？"
        elif plan.primary_action == "CLOSE_INTERVIEW":
            question = "抱歉，我想把刚才的内容整理得更准确一些，稍后再陪您收个尾。"
        else:
            question = "抱歉，我想更准确地接着您刚才的话问一句，请稍等我整理一下再继续。"
        return {
            "action": self._map_action(plan.primary_action),
            "question": question,
        }

    def _opening_response(self, elder_profile: ElderProfile, plan: QuestionPlan) -> Dict[str, str]:
        question = self._build_opening_question(elder_profile, plan)
        return {
            "action": self._map_action(plan.primary_action),
            "question": question,
        }

    def _build_opening_question(self, elder_profile: ElderProfile, plan: QuestionPlan) -> str:
        background = (elder_profile.background_summary or "").strip()
        hometown = (elder_profile.hometown or "").strip()
        birth_year = elder_profile.birth_year

        if any(keyword in background for keyword in ["工厂", "上班", "工作", "纺织", "车间"]):
            return "您刚才的经历里提到过年轻时工作那段日子。您还记得自己刚参加工作时最难忘的一幕吗？那大概是什么时候、在什么地方？"
        if any(keyword in background for keyword in ["结婚", "家庭", "孩子", "成家", "老伴"]):
            return "您的人生里一定有一段和成家有关的经历特别重要。您愿意先从那件最难忘的事讲起吗？那大概是什么时候、在哪里发生的？"
        if hometown and birth_year:
            return f"您是{birth_year}年出生的，又和{hometown}有很深的缘分。要是从最早记得的一段经历说起，您最先想到的是哪件事？"
        if birth_year:
            return f"您是{birth_year}年出生的，走过了这么长的人生路。您愿意先从一段年轻时至今还记得很清楚的经历讲起吗？"
        if background:
            return "从您的人生经历里，一定有一段故事一直留在心里。您愿意先从那件最难忘的事讲起吗？"
        return "您愿意先和我讲一段您年轻时至今还记得很清楚的具体经历吗？"

    def _map_action(self, primary_action: Optional[str]) -> str:
        action_map = {
            "DEEP_DIVE": "continue",
            "CLARIFY": "continue",
            "BREADTH_SWITCH": "next_phase",
            "SUMMARIZE": "next_phase",
            "PAUSE_SESSION": "next_phase",
            "CLOSE_INTERVIEW": "end",
        }
        return action_map.get(primary_action or "", "continue")

    def _build_basic_info_text(self, elder_profile: ElderProfile) -> str:
        parts = []
        if elder_profile.name:
            parts.append(f"姓名：{elder_profile.name}")
        if elder_profile.birth_year:
            parts.append(f"出生年份：{elder_profile.birth_year}")
        if elder_profile.hometown:
            parts.append(f"家乡：{elder_profile.hometown}")
        if elder_profile.background_summary:
            parts.append(f"背景：{elder_profile.background_summary}")
        return "；".join(parts) if parts else "一位受访老人"

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

    def _prompt_stage(self, recent_transcript: List[TurnRecord]) -> str:
        turn_count = len(recent_transcript)
        if turn_count <= 2:
            return "early"
        if turn_count <= 5:
            return "mid"
        return "full"

    def _follow_up_note(self, prompt_stage: str) -> str:
        if prompt_stage == "early":
            return (
                "This is an early follow-up turn. Stay tightly anchored to the newest answer and ask for one concrete next layer."
            )
        if prompt_stage == "mid":
            return (
                "This is a middle interview turn. Use the planner guidance plus one or two compact memory/graph hints, but keep the question natural."
            )
        return (
            "This is a later interview turn. You may use broader session context, but the final wording should still feel grounded in the active thread."
        )

    def _build_elder_profile_payload(self, elder_profile: ElderProfile, prompt_stage: str) -> Dict[str, Any]:
        payload = elder_profile.to_dict()
        stable_facts = payload.get("stable_facts", {})
        if prompt_stage == "early" and isinstance(stable_facts, dict):
            payload["stable_facts"] = {
                key: stable_facts[key]
                for key in list(stable_facts.keys())[:4]
            }
        return payload

    def _build_memory_payload(self, memory_capsule: MemoryCapsule, prompt_stage: str) -> Dict[str, Any]:
        emotional_state = (
            memory_capsule.emotional_state.to_dict()
            if memory_capsule.emotional_state
            else {}
        )
        if prompt_stage == "early":
            return {
                "current_storyline": memory_capsule.current_storyline,
                "recent_topics": memory_capsule.recent_topics[:2],
                "open_loops": [loop.to_dict() for loop in memory_capsule.open_loops[:2]],
                "do_not_repeat": memory_capsule.do_not_repeat[-2:],
                "emotional_state": emotional_state,
            }
        if prompt_stage == "mid":
            return {
                "session_summary": memory_capsule.session_summary,
                "current_storyline": memory_capsule.current_storyline,
                "recent_topics": memory_capsule.recent_topics[:3],
                "open_loops": [loop.to_dict() for loop in memory_capsule.open_loops[:4]],
                "do_not_repeat": memory_capsule.do_not_repeat[-3:],
                "emotional_state": emotional_state,
            }
        return {
            "session_summary": memory_capsule.session_summary,
            "current_storyline": memory_capsule.current_storyline,
            "recent_topics": memory_capsule.recent_topics,
            "do_not_repeat": memory_capsule.do_not_repeat[-3:],
            "open_loops": [loop.to_dict() for loop in memory_capsule.open_loops[:5]],
            "emotional_state": emotional_state,
        }

    def _build_graph_payload(self, graph_summary: GraphSummary, prompt_stage: str) -> Dict[str, Any]:
        ranked_slot_gaps = sorted(graph_summary.slot_coverage.items(), key=lambda item: item[1])
        ranked_theme_gaps = sorted(graph_summary.theme_coverage.items(), key=lambda item: item[1])
        if prompt_stage == "early":
            return {
                "overall_coverage": graph_summary.overall_coverage,
                "current_focus_theme_id": graph_summary.current_focus_theme_id,
                "top_undercovered_slots": ranked_slot_gaps[:3],
                "active_event_ids": graph_summary.active_event_ids[:3],
            }
        if prompt_stage == "mid":
            return {
                "overall_coverage": graph_summary.overall_coverage,
                "theme_coverage": dict(ranked_theme_gaps[:3]),
                "slot_coverage": dict(ranked_slot_gaps[:4]),
                "current_focus_theme_id": graph_summary.current_focus_theme_id,
                "active_event_ids": graph_summary.active_event_ids[:4],
                "unresolved_theme_ids": graph_summary.unresolved_theme_ids[:3],
            }
        return graph_summary.to_dict()

    def _build_focus_event_payload(
        self,
        focus_event_payload: Optional[Dict[str, Any]],
        prompt_stage: str,
    ) -> Dict[str, Any]:
        payload = dict(focus_event_payload or {})
        if prompt_stage == "early":
            return {
                "summary": payload.get("summary"),
                "people_names": payload.get("people_names", [])[:3],
                "missing_slots": payload.get("missing_slots", [])[:3],
                "recent_answer_span": payload.get("recent_answer_span"),
                "unexpanded_clues": payload.get("unexpanded_clues", [])[:2],
            }
        if prompt_stage == "mid":
            return {
                "summary": payload.get("summary"),
                "known_slots": payload.get("known_slots", {}),
                "missing_slots": payload.get("missing_slots", [])[:4],
                "people_names": payload.get("people_names", [])[:4],
                "recent_answer_span": payload.get("recent_answer_span"),
                "unexpanded_clues": payload.get("unexpanded_clues", [])[:3],
            }
        return payload
