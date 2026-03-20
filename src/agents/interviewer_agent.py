from __future__ import annotations

import json
import os
from typing import Dict, List, Optional

from openai import OpenAI

from src.config import Config
from src.state import ElderProfile, GraphSummary, MemoryCapsule, QuestionPlan, TurnRecord


class InterviewerAgent:
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
            "[用户的基本生平信息]",
            "[鐢ㄦ埛鐨勫熀鏈敓骞充俊鎭痌",
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

        return (
            "Use the planner decision below to write the next natural interview question in Chinese.\n"
            "Return strict JSON with keys `action` and `question` only.\n"
            "Rules:\n"
            "- Ask exactly one question.\n"
            "- Keep it natural, warm, and non-redundant.\n"
            "- If the planner action is CLOSE_INTERVIEW, return action=`end` and provide a short closing question or prompt.\n"
            "- If the planner action is BREADTH_SWITCH or SUMMARIZE, action should usually be `next_phase`.\n"
            "- Otherwise action should usually be `continue`.\n\n"
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
            question = "今天我们聊了很多宝贵的经历。最后，您最希望别人记住您人生中的哪一点？"
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
