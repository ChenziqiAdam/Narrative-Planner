from __future__ import annotations

import json
import os
from typing import Dict, List, Optional

from openai import OpenAI

from src.config import Config
from src.state import ElderProfile, GraphSummary, MemoryCapsule, QuestionPlan, TurnRecord


class InterviewerAgent:
    ACTION_GUIDANCE = {
        "DEEP_DIVE": "Stay on the current event and ask for one more layer of detail, feeling, or reflection.",
        "BREADTH_SWITCH": "Move naturally to a new life stage or theme without sounding abrupt.",
        "CLARIFY": "Gently resolve an ambiguity or contradiction in time, place, people, or sequence.",
        "SUMMARIZE": "Briefly checkpoint what was shared and invite one more representative detail.",
        "PAUSE_SESSION": "Land softly and avoid opening a large new thread.",
        "CLOSE_INTERVIEW": "End gracefully with a warm closing prompt instead of opening a new topic.",
    }
    TONE_GUIDANCE = {
        "EMPATHIC_SUPPORTIVE": "Warm, validating, and emotionally supportive.",
        "CURIOUS_INQUIRING": "Curious and engaged, but still respectful and non-leading.",
        "RESPECTFUL_REVERENT": "Respectful, calm, and honoring the elder's experience.",
        "CASUAL_CONVERSATIONAL": "Natural and relaxed, like a gentle conversation.",
        "PROFESSIONAL_NEUTRAL": "Clear, neutral, and unobtrusive.",
        "GENTLE_WARM": "Short, soft, and low-pressure, especially when energy is low.",
        "ENCOURAGING": "Lightly encouraging without pushing too hard.",
    }
    STRATEGY_GUIDANCE = {
        "OBJECT_TO_EMOTION": "Anchor on a concrete moment first, then invite feeling or meaning.",
        "TIMELINE_SLOT_FILL": "Prefer filling missing time, place, or people slots.",
        "PERSON_CONTEXT_FILL": "Clarify who was involved and what their relationship was.",
        "DETAIL_EXPANSION": "Expand the most important concrete detail from the current thread.",
        "THEME_SWITCH": "Transition cleanly into a less-covered but related life theme.",
        "CHECKPOINT_SUMMARY": "Use a brief summary to bridge into one reflective follow-up.",
        "CONFLICT_RESOLUTION": "Politely verify inconsistent details instead of assuming.",
        "GRACEFUL_CLOSE": "Close warmly and help the elder leave the conversation with dignity.",
        "OPENING_ORIENTATION": "Open broad enough for storytelling, but specific enough to get a concrete memory.",
    }
    SLOT_GUIDANCE = {
        "time": "when it happened",
        "location": "where it happened",
        "people": "who was there and their relationship to the elder",
        "event": "what concretely happened",
        "feeling": "what the elder felt at that moment",
        "reflection": "what it means looking back now",
        "cause": "what led to it",
        "result": "what changed afterward",
    }

    def __init__(self):
        self.client = OpenAI(**Config.get_openai_client_kwargs())
        self.model = Config.MODEL_NAME
        prompt_path = os.path.join(Config.PROMPTS_DIR, "interviewer_system_prompt.md")
        with open(prompt_path, "r", encoding="utf-8") as file:
            self.system_prompt_template = file.read()

    def generate_question(
        self,
        elder_profile: ElderProfile,
        recent_transcript: List[TurnRecord],
        memory_capsule: MemoryCapsule,
        graph_summary: GraphSummary,
        plan: QuestionPlan,
    ) -> Dict[str, str]:
        if plan.candidate_questions:
            return self._fallback_response(plan)

        system_prompt = self._render_system_prompt(elder_profile)
        user_prompt = self._build_user_prompt(recent_transcript, memory_capsule, graph_summary, plan)

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=1024,
            )
            raw_content = (response.choices[0].message.content or "").strip()
            parsed = self._parse_response(raw_content)
            if parsed.get("question") or parsed.get("action") == "end":
                return parsed
        except Exception:
            pass

        return self._fallback_response(plan)

    def _render_system_prompt(self, elder_profile: ElderProfile) -> str:
        basic_info = self._build_basic_info_text(elder_profile)
        replacements = [
            "{{elder_basic_info}}",
            "[鐢ㄦ埛鐨勫熀鏈敓骞充俊鎭痌",
            "[閻劍鍩涢惃鍕唨閺堫剛鏁撻獮鍏呬繆閹棇",
        ]
        rendered = self.system_prompt_template
        for placeholder in replacements:
            rendered = rendered.replace(placeholder, basic_info)
        return rendered

    def _build_user_prompt(
        self,
        recent_transcript: List[TurnRecord],
        memory_capsule: MemoryCapsule,
        graph_summary: GraphSummary,
        plan: QuestionPlan,
    ) -> str:
        transcript_text = "\n".join(
            f"Q: {turn.interviewer_question}\nA: {turn.interviewee_answer}"
            for turn in recent_transcript[-3:]
        ) or "(no completed turns yet)"

        plan_payload = {
            "primary_action": plan.primary_action,
            "tactical_goal": plan.tactical_goal,
            "target_theme_id": plan.target_theme_id,
            "target_event_id": plan.target_event_id,
            "target_person_id": plan.target_person_id,
            "target_slots": plan.target_slots,
            "tone": plan.tone,
            "strategy": plan.strategy,
            "reasoning_trace": plan.reasoning_trace,
            "candidate_questions": plan.candidate_questions,
        }
        memory_payload = {
            "session_summary": memory_capsule.session_summary,
            "current_storyline": memory_capsule.current_storyline,
            "recent_topics": memory_capsule.recent_topics,
            "do_not_repeat": memory_capsule.do_not_repeat,
            "open_loops": [loop.description for loop in memory_capsule.open_loops[:5]],
            "emotional_state": memory_capsule.emotional_state.to_dict() if memory_capsule.emotional_state else {},
        }
        graph_payload = graph_summary.to_dict()

        action_hint = self.ACTION_GUIDANCE.get(plan.primary_action, "Follow the planner decision faithfully.")
        tone_hint = self.TONE_GUIDANCE.get(plan.tone, "Keep the tone natural and respectful.")
        strategy_hint = self.STRATEGY_GUIDANCE.get(plan.strategy, "Turn the plan into one natural question.")
        slot_focus = (
            ", ".join(f"{slot} ({self.SLOT_GUIDANCE.get(slot, slot)})" for slot in plan.target_slots)
            if plan.target_slots
            else "none"
        )

        return (
            "You are only the language surface layer for the interviewer.\n"
            "Do not redesign the strategy. The planner decision is the source of truth.\n"
            "Use memory, graph summary, and transcript only to phrase the next question naturally.\n\n"
            "Return strict JSON with keys `action` and `question` only.\n"
            "Hard constraints:\n"
            "- Ask exactly one question.\n"
            "- Keep the question concise, natural, warm, and non-redundant.\n"
            "- Do not ask multiple sub-questions in one turn.\n"
            "- Do not expose internal labels like DEEP_DIVE, target_slots, strategy, or theme IDs.\n"
            "- Respect `do_not_repeat` and avoid repeating nearly identical wording from recent turns.\n"
            "- If cognitive energy is low, make the question shorter and gentler.\n"
            "- If emotional valence is negative, you may add a brief validating clause before the question, but still ask only one question.\n"
            "- If the planner action is CLOSE_INTERVIEW, return action=`end` and provide a short closing prompt.\n"
            "- If the planner action is BREADTH_SWITCH, SUMMARIZE, or PAUSE_SESSION, action should usually be `next_phase`.\n"
            "- Otherwise action should usually be `continue`.\n\n"
            "Planner semantics:\n"
            f"- primary_action={plan.primary_action}: {action_hint}\n"
            f"- tone={plan.tone}: {tone_hint}\n"
            f"- strategy={plan.strategy}: {strategy_hint}\n"
            f"- target_slots={slot_focus}\n\n"
            "When target slots are present, prefer filling the most important one or two slots naturally instead of asking for everything at once.\n"
            "If there is a contradiction or ambiguity, ask for clarification rather than assuming.\n"
            "If the plan already provides candidate questions, treat them as preferred phrasing direction.\n\n"
            f"Planner decision:\n{json.dumps(plan_payload, ensure_ascii=False, indent=2)}\n\n"
            f"Memory capsule:\n{json.dumps(memory_payload, ensure_ascii=False, indent=2)}\n\n"
            f"Graph summary:\n{json.dumps(graph_payload, ensure_ascii=False, indent=2)}\n\n"
            f"Recent transcript:\n{transcript_text}"
        )

    def _parse_response(self, raw_content: str) -> Dict[str, str]:
        text = raw_content.strip()
        if "```json" in text:
            text = text.split("```json", 1)[1].split("```", 1)[0].strip()
        elif "```" in text:
            text = text.split("```", 1)[1].split("```", 1)[0].strip()

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return self._fallback_response(None, fallback_question=text)

        action = str(parsed.get("action", "continue")).strip() or "continue"
        question = str(parsed.get("question", "")).strip()
        if action == "end" and not question:
            question = "今天我们聊了很多珍贵的经历。最后，您最希望别人记住您人生中的哪一点？"
        return {"action": action, "question": question}

    def _fallback_response(
        self,
        plan: Optional[QuestionPlan],
        fallback_question: Optional[str] = None,
    ) -> Dict[str, str]:
        if fallback_question:
            return {
                "action": self._map_action(plan.primary_action if plan else None),
                "question": fallback_question,
            }
        if plan and plan.candidate_questions:
            return {
                "action": self._map_action(plan.primary_action),
                "question": plan.candidate_questions[0],
            }
        return {
            "action": "continue",
            "question": "您愿意把刚才那段经历再多讲一点吗？",
        }

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
