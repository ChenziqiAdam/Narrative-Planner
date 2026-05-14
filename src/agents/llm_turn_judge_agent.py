from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

from openai import OpenAI

from src.config import Config

try:
    from json_repair import repair_json
except ImportError:  # pragma: no cover
    def repair_json(text: str) -> str:
        return text


logger = logging.getLogger(__name__)


class LLMTurnJudgeAgent:
    """LLM-as-a-judge scorer for one interviewer question in context."""

    DIMENSION_SPECS: Dict[str, Dict[str, Any]] = {
        "trajectory_guidance": {
            "weight": 0.25,
            "label": "叙事导向与推进",
            "rubric": (
                "只评估这个问题在整场回忆录访谈中的导向功能：是否把对话推进到更清楚的人生阶段、"
                "关键事件、人物关系、转折或反思；是否避免停留在礼貌寒暄、泛泛感想或无目的延展。"
                "如果本轮有 interview_goal_or_intent，应评估问题是否真正落实该意图；若无显式意图，"
                "按回忆录访谈的长期目标评估。不要因为语气温柔或单句开放就加高分。"
            ),
        },
        "evidence_responsiveness": {
            "weight": 0.20,
            "label": "证据承接与定位",
            "rubric": (
                "只评估问题是否抓住受访者刚给出的具体证据、人物、地点、事件、情绪或未闭合线索。"
                "必须查看 previous_turns_for_continuity 和 recent_dialogue_context，尤其上一轮问答。"
                "高分问题应针对清楚线索发问；低分问题会忽视刚出现的关键信息、机械换题、重复受访者已说内容，"
                "或只用“这些经历/那个时候”这类空泛指代。"
            ),
        },
        "depth_breadth_control": {
            "weight": 0.20,
            "label": "深挖与换题控制",
            "rubric": (
                "只评估问题是否选择了合适的推进策略：该深挖时补事件经过、原因、结果、人物关系或反思；"
                "该拓宽时自然转向新人生阶段或主题；避免在同一浅层主题上反复绕圈。"
                "如果问题只是“再讲讲/还有吗/哪些影响”而没有明确要补的叙事缺口，应扣分。"
            ),
        },
        "information_gain_design": {
            "weight": 0.20,
            "label": "信息增益设计",
            "rubric": (
                "只评估问题是否被设计成能获得新的、可用的回忆录材料：时间、地点、人物、行动顺序、"
                "因果、结果、冲突、关系变化、时代背景或个人反思。高分问题应让回答更具体、更可写；"
                "泛泛询问意义、品质、影响，或容易得到重复/套话回答，应扣分。"
            ),
        },
        "rapport_and_load": {
            "weight": 0.15,
            "label": "关系维护与认知负荷",
            "rubric": (
                "只评估提问是否尊重、温和、清楚且负担适中。高分问题应一次聚焦一个主问题，"
                "情绪上能承接受访者状态；低分问题会堆叠多个问题、过度引导答案、空泛赞美过多、"
                "或在敏感内容上显得生硬。"
            ),
        },
    }
    DIMENSION_KEYS = tuple(DIMENSION_SPECS.keys())

    def __init__(self, model: Optional[str] = None):
        client_kwargs = Config.get_openai_client_kwargs()
        client_kwargs.setdefault("timeout", Config.REQUEST_TIMEOUT)
        self.client = OpenAI(**client_kwargs)
        self.model = model or Config.LLM_TURN_JUDGE_MODEL_NAME

    def judge_turn(
        self,
        *,
        dialogue_context: List[Dict[str, str]],
        interviewer_question: str,
        interviewee_answer: str,
        interviewer_action: str = "continue",
        interview_goal: str = "",
        mode: str = "",
        deterministic_evaluation: Optional[Dict[str, Any]] = None,
        debug_trace: Optional[Dict[str, Any]] = None,
        **legacy_kwargs: Any,
    ) -> Dict[str, Any]:
        effective_goal = interview_goal or str(legacy_kwargs.get("legacy_goal", "") or "")
        base_payload = self._base_payload(
            dialogue_context=dialogue_context,
            interviewer_question=interviewer_question,
            interviewee_answer=interviewee_answer,
            interviewer_action=interviewer_action,
            interview_goal=effective_goal,
            deterministic_evaluation=deterministic_evaluation,
            debug_trace=debug_trace,
        )

        dimensions: Dict[str, float] = {}
        dimension_reasons: Dict[str, str] = {}
        suggestions: List[str] = []
        errors: Dict[str, str] = {}

        max_workers = min(len(self.DIMENSION_KEYS), 5)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(self._judge_dimension, dimension_key, base_payload): dimension_key
                for dimension_key in self.DIMENSION_KEYS
            }
            for future in as_completed(futures):
                dimension_key = futures[future]
                try:
                    result = future.result()
                    dimensions[dimension_key] = result["score"]
                    dimension_reasons[dimension_key] = result["reason"]
                    suggestions.extend(result.get("suggestions", []))
                except Exception as exc:
                    logger.warning("LLM turn judge dimension failed (%s): %s", dimension_key, exc)
                    dimensions[dimension_key] = 0.0
                    dimension_reasons[dimension_key] = f"{dimension_key} 评分失败"
                    errors[dimension_key] = str(exc)

        question_score = self._weighted_score(dimensions)
        return {
            "status": "completed",
            "question_score": question_score,
            "reason": self._summary_reason(dimension_reasons, dimensions),
            "dimensions": dimensions,
            "dimension_reasons": dimension_reasons,
            "suggestions": self._dedupe(suggestions)[:3],
            "model": self.model,
            "error": json.dumps(errors, ensure_ascii=False) if errors else None,
        }

    def safe_judge_turn(self, **kwargs) -> Dict[str, Any]:
        try:
            return self.judge_turn(**kwargs)
        except Exception as exc:  # pragma: no cover - external service boundary
            logger.warning("LLM turn judge failed: %s", exc)
            return {
                "status": "failed",
                "question_score": None,
                "reason": "",
                "dimensions": {},
                "suggestions": [],
                "model": self.model,
                "error": str(exc),
            }

    def _judge_dimension(self, dimension_key: str, base_payload: Dict[str, Any]) -> Dict[str, Any]:
        spec = self.DIMENSION_SPECS[dimension_key]
        user_payload = {
            **base_payload,
            "dimension_to_score": dimension_key,
            "dimension_label": spec["label"],
            "dimension_rubric": spec["rubric"],
            "output_schema": {
                "reason": "string, 60字以内，只解释该维度",
                "score": "float 0-1，只评该维度",
                "suggestions": ["string, 最多2条，只针对该维度"],
            },
        }
        raw = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": self._dimension_system_prompt(dimension_key)},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ],
            temperature=0.0,
            max_tokens=700,
        ).choices[0].message.content or ""
        return self._parse_dimension(raw)

    def _parse_dimension(self, text: str) -> Dict[str, Any]:
        payload = (text or "").strip()
        if "```json" in payload:
            payload = payload.split("```json", 1)[1].split("```", 1)[0].strip()
        elif "```" in payload:
            payload = payload.split("```", 1)[1].split("```", 1)[0].strip()

        parsed = json.loads(repair_json(payload))
        if not isinstance(parsed, dict):
            raise ValueError("LLM turn judge returned non-dict JSON.")

        return {
            "score": self._clip01(parsed.get("score", 0.0)),
            "reason": str(parsed.get("reason", "") or "").strip()[:240],
            "suggestions": [
                str(item).strip()
                for item in parsed.get("suggestions", [])
                if str(item).strip()
            ][:3],
        }

    def _base_payload(
        self,
        *,
        dialogue_context: List[Dict[str, str]],
        interviewer_question: str,
        interviewee_answer: str,
        interviewer_action: str,
        interview_goal: str,
        deterministic_evaluation: Optional[Dict[str, Any]],
        debug_trace: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        previous_turns = self._previous_full_turns(dialogue_context)
        return {
            "task": "评估本轮访谈者提问质量。注意：本次调用只评分一个维度，不要综合其他维度。",
            "interview_goal_or_intent": interview_goal or "无显式访谈目标；请按回忆录访谈通用目标评估。",
            "interviewer_action": interviewer_action,
            "recent_dialogue_context": dialogue_context[-8:],
            "previous_turns_for_continuity": previous_turns[-3:],
            "has_previous_turn_for_continuity": bool(previous_turns),
            "session_progress_for_strategy": {
                "prior_turn_count": len(previous_turns),
                "recent_interviewer_questions": [
                    turn["interviewer_question"] for turn in previous_turns[-4:]
                ],
                "recent_interviewee_answers": [
                    turn["interviewee_answer"] for turn in previous_turns[-4:]
                ],
            },
            "current_turn": {
                "interviewer_question": interviewer_question,
                "interviewee_answer_after_question": interviewee_answer,
            },
            "deterministic_evaluation_reference_only": deterministic_evaluation or {},
            "decision_context_reference_only": self._compact_debug_trace(debug_trace or {}),
        }

    @staticmethod
    def _previous_full_turns(dialogue_context: List[Dict[str, str]]) -> List[Dict[str, str]]:
        turns: List[Dict[str, str]] = []
        pending_question: Optional[str] = None
        for item in dialogue_context:
            role = item.get("role")
            text = item.get("text", "")
            if role == "interviewer":
                pending_question = text
            elif role == "interviewee" and pending_question is not None:
                turns.append(
                    {
                        "interviewer_question": pending_question,
                        "interviewee_answer": text,
                    }
                )
                pending_question = None
        return turns

    def _weighted_score(self, dimensions: Dict[str, float]) -> float:
        total = 0.0
        weight_sum = 0.0
        for key, spec in self.DIMENSION_SPECS.items():
            weight = float(spec["weight"])
            total += self._clip01(dimensions.get(key, 0.0)) * weight
            weight_sum += weight
        return round(total / max(weight_sum, 1e-9), 4)

    def _summary_reason(self, reasons: Dict[str, str], dimensions: Dict[str, float]) -> str:
        ordered = sorted(dimensions.items(), key=lambda item: item[1])
        low_key = ordered[0][0] if ordered else ""
        high_key = ordered[-1][0] if ordered else ""
        snippets = []
        if high_key:
            snippets.append(f"强项：{self.DIMENSION_SPECS[high_key]['label']} {dimensions[high_key]:.2f}")
        if low_key and low_key != high_key:
            snippets.append(f"短板：{self.DIMENSION_SPECS[low_key]['label']} {dimensions[low_key]:.2f}")
        return "；".join(snippets)[:240]

    @staticmethod
    def _dedupe(items: List[str]) -> List[str]:
        seen = set()
        result: List[str] = []
        for item in items:
            if item in seen:
                continue
            seen.add(item)
            result.append(item)
        return result

    @staticmethod
    def _clip01(value: Any) -> float:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            numeric = 0.0
        return max(0.0, min(1.0, numeric))

    @staticmethod
    def _compact_debug_trace(debug_trace: Dict[str, Any]) -> Dict[str, Any]:
        planning = debug_trace.get("planning", {}) if isinstance(debug_trace, dict) else {}
        if not isinstance(planning, dict):
            planning = {}
        return {
            "planning": {
                "next_action": planning.get("next_action"),
                "selected_action": planning.get("selected_action"),
                "stage": planning.get("stage"),
                "focus": planning.get("focus"),
                "selected_slot_or_angle": planning.get("selected_slot_or_angle"),
                "missing_dimensions": planning.get("missing_dimensions"),
                "question_intent": planning.get("question_intent"),
            }
        }

    @staticmethod
    def _dimension_system_prompt(dimension_key: str) -> str:
        return f"""你是一个专业、严格但公平的“回忆录访谈策略评测专家”。你的任务是评估【访谈者刚提出的问题】的一个单独维度：{dimension_key}。

为了避免光环效应，你必须只评价本次指定维度，不要综合其他维度，不要给总分。

如果指定维度是 evidence_responsiveness：
- 必须查看 previous_turns_for_continuity；若存在上一轮问答，至少以上一轮为主要依据判断承接是否自然。
- 如果 has_previous_turn_for_continuity=false，说明这是开场或缺少上一轮，此时不要臆造上下文，只按开场是否自然给中性到较高分。

如果指定维度涉及导向、深挖、信息增益或策略推进：
- 必须结合 session_progress_for_strategy、recent_dialogue_context、interview_goal_or_intent 和 current_turn 判断。
- 高分不是“问题听起来礼貌开放”，而是“这个问题在当前访谈阶段能让叙事更完整、更有结构、更可写”。
- 对泛泛的称赞、泛泛的影响/品质追问、重复“再讲讲”、没有明确叙事缺口的换题，要从策略功能上扣分。

评分量表：
- 0.90-1.00：优秀。准确抓住当前叙事机会，推进清楚，能显著补足事件/人物/阶段/反思。
- 0.75-0.89：良好。方向合理，有一定策略功能，但还可更精准地补缺口或控制节奏。
- 0.55-0.74：一般。能维持对话，但导向偏泛，主要依靠开放性和礼貌感，新增材料不稳定。
- 0.30-0.54：较差。重复、空泛、换题/深挖时机不佳，或没有回应关键线索。
- 0.00-0.29：严重失效。跑题、冒犯、幻觉、压迫式追问，或明显破坏访谈推进。

注意：
- 不要因为受访者回答很长就自动给高分；要判断问题本身是否有导向设计。
- 不要因为问题温柔、开放、自然承接就自动给 0.85。若它没有清楚推进叙事或补足缺口，通常不应超过 0.74。
- 不要奖励一次问很多问题。多问合一、压力过大、像审讯或填表，应扣分。
- 你不知道也不需要知道问题来自哪个系统或实验组。不要猜测来源，不要在 reason 中出现任何系统名、组别名或实现名。
- 必须只输出合法 JSON，不要输出 Markdown 或额外解释。

输出格式：
{{
  "reason": "60字以内，只解释该维度",
  "score": 0.0,
  "suggestions": ["最多2条，只针对该维度"]
}}
"""
