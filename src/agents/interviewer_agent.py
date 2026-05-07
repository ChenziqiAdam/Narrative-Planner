from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from openai import OpenAI

from src.config import Config
from src.services.llm_retry import is_transient_llm_error, sleep_before_retry
from src.state import ElderProfile, TurnRecord
from src.services.graph_rag_decision_context import GraphRAGDecisionContext
from src.tools.planner_tools import (
    PlannerToolSystem,
    get_planner_tool_callables,
    get_planner_tool_schemas,
)

try:
    from json_repair import repair_json
except ImportError:  # pragma: no cover - optional dependency
    def repair_json(text: str) -> str:
        return text


logger = logging.getLogger(__name__)


class InterviewerAgent:
    """GraphRAG 访谈助手 — 基于图谱决策上下文生成访谈问题。"""

    def __init__(self):
        self.client = OpenAI(**Config.get_openai_client_kwargs())
        self.model_candidates = Config.get_model_candidates("interviewer")
        self.model = self.model_candidates[0]
        self.max_tokens = 4096 if self._is_reasoning_heavy_model() else 1024

    def generate_question(
        self,
        elder_profile: ElderProfile,
        recent_transcript: List[TurnRecord],
        decision_ctx: GraphRAGDecisionContext,
        planner_tool_system: Optional[PlannerToolSystem] = None,
    ) -> Dict[str, Any]:
        """Generate next question using GraphRAG decision context."""
        if not recent_transcript:
            return self._opening_response(elder_profile)

        system_prompt = self._render_system_prompt()
        user_prompt = self._build_user_prompt(
            elder_profile, recent_transcript, decision_ctx
        )
        tool_schemas: List[Dict[str, Any]] = []
        tool_callables: Dict[str, Any] = {}
        if Config.PLANNER_TOOLS_ENABLED:
            tool_system = planner_tool_system or PlannerToolSystem(
                elder_profile,
                recent_transcript,
                decision_ctx,
            )
            tool_schemas = get_planner_tool_schemas(
                include_graph_tools=tool_system.has_graph_tools
            )
            tool_callables = get_planner_tool_callables(tool_system)

        max_attempts = max(1, min(Config.MAX_RETRIES, 2))

        for model_name in self.model_candidates:
            candidate_max_tokens = 4096 if self._is_reasoning_heavy_model(model_name) else 1024
            for attempt in range(1, max_attempts + 1):
                try:
                    message, tool_trace = self._create_completion_with_optional_tools(
                        model_name=model_name,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        max_tokens=candidate_max_tokens,
                        tools=tool_schemas,
                        tool_callables=tool_callables,
                    )
                    raw_content = (message.content or "").strip()

                    if not raw_content:
                        reasoning_content = getattr(message, "reasoning_content", "") or ""
                        logger.warning(
                            "InterviewerAgent received empty content (model=%s, reasoning_len=%s)",
                            model_name, len(reasoning_content),
                        )
                        continue

                    parsed = self._parse_response(raw_content)
                    if parsed.get("question"):
                        if tool_trace:
                            parsed["tool_trace"] = tool_trace
                        self.model = model_name
                        self.max_tokens = candidate_max_tokens
                        return parsed
                except Exception as exc:
                    logger.warning(
                        "InterviewerAgent model=%s attempt %s/%s failed: %s",
                        model_name, attempt, max_attempts, exc,
                    )
                    if is_transient_llm_error(exc):
                        if attempt < max_attempts:
                            sleep_before_retry(exc, attempt)
                            continue
                        break
                    if self._should_fallback_model(exc):
                        break

        logger.error("InterviewerAgent returning fallback response")
        return {
            "action": "continue",
            "question": "您能再跟我多说说那个时候的事情吗？",
            "planner_plan": self._fallback_planner_plan(
                "continue",
                "LLM 生成失败，降级为温和追问当前经历。",
            ),
        }

    def _render_system_prompt(self) -> str:
        return """你是一位充满好奇心、善于倾听的传记访谈者，正在陪一位老人重温他/她的人生旅程。
你的目标不是"收集信息"，而是引导老人讲述一个完整、有温度的生命故事，覆盖他人生的主要阶段，如童年、求学、工作、家庭、重要转折点、起伏等。让老人感到被理解、被珍视。

---

## 【访谈覆盖主题】（供参考，不必一次问完）

根据《人生故事访谈》(Life Story Interview) 规程，一个好的回忆录应覆盖以下维度：

**1. 人生篇章** —— 帮助老人划分人生阶段，建立时间骨架
   - 例："如果人生是一本书，各个章节的标题会是什么？"

**2. 关键场景**（深度挖掘重点）
   - 高光时刻：最自豪、最快乐的经历
   - 低谷时刻：最困难、最具挑战的经历
   - 转折点：改变人生方向的关键决定
   - 童年记忆：早期对性格形成有影响的事
   - 智慧时刻：展现洞察力的经历
   - 温情时刻：最难忘的亲情、友情、爱情

**3. 重要人物** —— 生命中影响深远的人
   - 家人、恩师、挚友、对手

**4. 价值观与信仰** —— 人生的指南针
   - 经历了这么多，老人的最信仰什么、看重什么？

**5. 未来展望** —— 对剩余生命的期待
   - 还有什么心愿？想留下什么话？

---

## 【行为准则】

1. **先回应，后提问** —— 不要干巴巴地接着问，先对老人的分享做出真诚的情感回应
   - 好的回应："听起来那真的不容易"、"我能感觉到您当时的兴奋"
   - 避免：机械地"嗯嗯"后立刻转入下一个问题

2. **好奇多于礼貌** —— 像老朋友聊天一样自然，不要过分客套
   - 好的："后来呢？我特别想知道..."
   - 避免："不好意思打扰一下，请问您能否..."

3. **问题类型灵活选择**
   - **问事实/确认信息** → 多用**封闭式问题**（是/否、具体数字）
     * 例："是1968年吗？" "当时厂里大概多少人？"
   - **问感受/故事** → 多用**开放式问题**
     * 例："那时候您心里是什么感觉？" "能给我讲讲当时的情景吗？"

4. **抓住一个切入点提问** —— 把老人意犹未尽或者到嘴边没说出来的话延展出去。问题清晰、聚焦，不堆叠多个问题但可以交叉确认或核实必要的信息

5. **隐藏技术细节** —— 永远不提"图谱"、"节点"、"槽位"、"覆盖率"等概念

---

## 【内部 Planner 工作流】

在生成下一个问题之前，请在内部按以下流程分析。不要输出完整分析过程，只输出结构化 planner_plan 摘要和最终问题。

### 1. 语义理解
- 判断老人刚才主要讲的是人生阶段、具体事件、人物关系、地点、价值观，还是情绪表达。
- 判断当前叙事焦点是否清楚，是否存在突然跳题的风险。

### 2. 访谈阶段判断
- 前 5-10 轮优先建立粗粒度人生脉络：人生阶段、大事节点、关键人物、自我评价、价值观。
- 如果仍处于人生脉络梳理阶段，不要因为背景或回答中出现"工作/工厂/家庭/地点"等词就立刻深挖单个主题。

### 3. 当前事件完整度判断
- 评估当前叙事是否具备：时间、地点、人物、经过、原因、结果、感受、反思。
- 识别 missing_dimensions 和 weak_dimensions，优先作为切入点深挖。
- 事件不完整还要结合主题覆盖和关联性判断事件是否重要、值得深挖。

### 4. 情绪与精力判断
- 判断情绪能量、认知负担、是否需要先共情承接。
- 如果老人疲惫、消极或回答变短，问题要更轻、更短、更温和。

### 5. 图谱和主题判断
- 参考主题覆盖、当前焦点、相关人物/地点、待探索线索和跨会话开放线索。
- 切换主题时必须自然承接，不要为了覆盖率突然跳走。

### 6. 候选动作比较
在内部比较以下动作，并给出 0-1 的相对分数：
- continue_life_overview：继续人生脉络梳理
- deep_dive_event：深挖当前事件
- clarify：澄清含糊或冲突
- confirm_summary：总结确认当前理解
- switch_theme：切换主题
- move_to_person：转向关键人物
- move_to_period：转向人生阶段
- gentle_reflection：引导自我评价/反思
- end：结束

### 4. 判停与结束判断
- 童年、青年、中年、晚年是否都有涉及？
- 是否有足够的高光、低谷、转折点故事？
- 老人是否表现出结束访谈的意愿？
- 如满足 → 优雅结束，表达感谢

---

## 【输出要求】

返回严格的 JSON 格式：

```json
{
  "planner_plan": {
    "stage": "life_overview|event_deepening|theme_expansion|reflection|closing",
    "selected_action": "continue_life_overview|deep_dive_event|clarify|confirm_summary|switch_theme|move_to_person|move_to_period|gentle_reflection|end",
    "focus": {"type": "life_period|event|person|location|theme|reflection", "label": "简短中文焦点"},
    "event_completeness": {
      "score": 0.0,
      "missing_dimensions": ["time", "location", "people", "sequence", "cause", "result", "feeling", "reflection"],
      "reason_summary": "一句话说明，不要写完整思维链"
    },
    "emotion_signal": {
      "energy": 0.5,
      "valence": "positive|neutral|negative",
      "support_needed": false
    },
    "candidate_actions": [
      {"action": "continue_life_overview", "score": 0.8, "reason_summary": "一句话理由"},
      {"action": "deep_dive_event", "score": 0.4, "reason_summary": "一句话理由"}
    ],
    "selected_slot_or_angle": "life_timeline|time|location|people|sequence|cause|result|feeling|reflection|theme|person",
    "tone": "respectful_warm|curious_gentle|empathetic_supportive|light_conversational",
    "question_intent": "一句话说明下一问意图"
  },
  "action": "continue|next_phase|end",
  "question": "你的访谈问题"
}
```

- `action=continue`：继续深入当前话题
- `action=next_phase`：切换到新话题或总结过渡
- `action=end`：结束访谈
- `planner_plan` 只用于调试和记录，不要包含完整推理链，只写简短决策摘要

**重要**：
- question 字段只能包含**一个问题**
- 问感受时用**开放式问题**，问确认时用**封闭式问题**
- 语气自然、温暖、好奇，像老朋友聊天一样

## 【工具调用】

如果你需要更多证据，可以调用工具查询主题覆盖、当前焦点、事件完整度、相关上下文或开放线索。
工具只提供证据，不替你决定动作。不要为了调用工具而调用工具；如果上下文已经足够，可以直接输出 JSON。"""

    def _build_user_prompt(
        self,
        elder_profile: ElderProfile,
        recent_transcript: List[TurnRecord],
        ctx: GraphRAGDecisionContext,
    ) -> str:
        """Build user prompt from GraphRAGDecisionContext."""
        prompt_stage = self._prompt_stage(recent_transcript)
        parts: List[str] = []

        # 1. Basic info
        parts.append("## 受访者基本信息")
        parts.append(self._build_basic_info_text(elder_profile))

        # 1.5 Dynamic profile (long-term memory)
        if ctx.dynamic_profile_hint:
            self._append_dynamic_profile(parts, ctx.dynamic_profile_hint)

        # 2. Recent dialogue
        parts.append("\n## 最近对话")
        limit = 3 if prompt_stage == "early" else 4 if prompt_stage == "mid" else 5
        for turn in recent_transcript[-limit:]:
            parts.append(f"问：{turn.interviewer_question}")
            parts.append(f"答：{turn.interviewee_answer}")
            parts.append("")

        # 3. Focus narrative
        if ctx.focus_rich_text:
            parts.append("## 正在聊的经历")
            parts.append(ctx.focus_rich_text)
            if ctx.connected_people:
                parts.append(f"相关人物：{', '.join(ctx.connected_people[:4])}")
            if ctx.connected_locations:
                parts.append(f"相关地点：{', '.join(ctx.connected_locations[:3])}")
            if ctx.emotional_thread:
                parts.append(f"情感线索：{ctx.emotional_thread}")

        # 4. Coverage (from graph)
        parts.append("\n## 人生故事覆盖情况")
        parts.append(f"整体叙事丰富度：{ctx.overall_coverage:.0%}")
        if ctx.coverage_by_theme:
            covered = [tid for tid, c in ctx.coverage_by_theme.items() if c >= 0.5]
            sparse = ctx.undercovered_themes[:5]
            if covered:
                parts.append(f"已有较丰富内容的主题：{len(covered)} 个")
            if sparse:
                parts.append(f"还很少涉及的方向：{len(sparse)} 个")
        if ctx.current_focus_theme_id:
            parts.append(f"当前焦点方向：{ctx.current_focus_theme_id}")

        # 5. Explorable angles
        if ctx.explorable_angles:
            parts.append("\n## 待探索的话题线索")
            for i, angle in enumerate(ctx.explorable_angles[:4], 1):
                parts.append(f"{i}. {angle}")

        # 6. Narrative memory context (from hybrid retriever)
        if ctx.graph_rag_context:
            parts.append("\n## 叙事记忆脉络")
            parts.append(ctx.graph_rag_context)

        # 7. Strategy hints
        parts.append("\n## 策略提示")
        if ctx.low_info_streak >= 3:
            parts.append(
                f"最近连续 {ctx.low_info_streak} 轮信息增益偏低。"
                "优先换一个新切口（人物/时间/地点/主题）再问。"
            )
        if ctx.cross_session_summary:
            parts.append(f"\n## 跨会话历史")
            parts.append(ctx.cross_session_summary)
        if ctx.cross_session_open_loops:
            parts.append("之前访谈中尚未展开的线索：")
            for loop in ctx.cross_session_open_loops[:3]:
                parts.append(f"- {loop}")

        # Task instruction
        parts.append("\n## 你的任务")
        parts.append("基于以上上下文，在内部完成 Planner 工作流分析，然后生成下一个问题。不要输出完整分析过程。")
        parts.append("")
        parts.append("记住：")
        parts.append("1. 问题要自然、温暖、像聊天")
        parts.append("2. 不要暴露任何技术概念")
        parts.append("3. 如果老人情绪低落，先共情再提问")
        parts.append("4. 如果老人疲劳，切换到轻松话题")
        parts.append("5. 前几轮不要因为背景里出现某个职业、地点或亲属就立刻深挖；先让老人自己铺开人生脉络")
        parts.append("")
        parts.append("返回严格 JSON 格式，必须包含 planner_plan、action、question 三个顶层字段：")
        parts.append(
            "{"
            "'planner_plan': {"
            "'stage': 'life_overview|event_deepening|theme_expansion|reflection|closing', "
            "'selected_action': 'continue_life_overview|deep_dive_event|clarify|confirm_summary|switch_theme|move_to_person|move_to_period|gentle_reflection|end', "
            "'focus': {'type': 'life_period|event|person|location|theme|reflection', 'label': '简短中文焦点'}, "
            "'event_completeness': {'score': 0.0, 'missing_dimensions': [], 'reason_summary': '一句话说明'}, "
            "'emotion_signal': {'energy': 0.5, 'valence': 'positive|neutral|negative', 'support_needed': false}, "
            "'candidate_actions': [{'action': 'continue_life_overview', 'score': 0.8, 'reason_summary': '一句话理由'}], "
            "'selected_slot_or_angle': 'life_timeline|time|location|people|sequence|cause|result|feeling|reflection|theme|person', "
            "'tone': 'respectful_warm|curious_gentle|empathetic_supportive|light_conversational', "
            "'question_intent': '一句话说明下一问意图'"
            "}, "
            "'action': 'continue|next_phase|end', "
            "'question': '你的问题'"
            "}"
        )

        return "\n".join(parts)

    def _create_completion_with_optional_tools(
        self,
        *,
        model_name: str,
        messages: List[Dict[str, Any]],
        max_tokens: int,
        tools: List[Dict[str, Any]],
        tool_callables: Dict[str, Any],
        allow_tool_fallback: bool = True,
    ):
        if not tools:
            response = self.client.chat.completions.create(
                model=model_name,
                messages=messages,
                max_tokens=max_tokens,
            )
            return response.choices[0].message, []

        working_messages = list(messages)
        tool_trace: List[Dict[str, Any]] = []
        max_rounds = max(0, int(Config.PLANNER_MAX_TOOL_ROUNDS))
        max_tools_per_round = max(1, int(Config.PLANNER_MAX_TOOLS_PER_ROUND))

        for round_index in range(max_rounds + 1):
            try:
                response = self.client.chat.completions.create(
                    model=model_name,
                    messages=working_messages,
                    max_tokens=max_tokens,
                    tools=tools,
                    tool_choice="auto",
                )
            except Exception as exc:
                if allow_tool_fallback and self._should_disable_tools_for_error(exc):
                    logger.warning("Planner tools unsupported by model/API; retrying without tools: %s", exc)
                    return self._create_completion_with_optional_tools(
                        model_name=model_name,
                        messages=messages,
                        max_tokens=max_tokens,
                        tools=[],
                        tool_callables={},
                        allow_tool_fallback=False,
                    )
                raise

            message = response.choices[0].message
            tool_calls = list(getattr(message, "tool_calls", None) or [])
            if not tool_calls:
                return message, tool_trace

            if round_index >= max_rounds:
                logger.warning("Planner tool loop exhausted before final answer")
                return message, tool_trace

            selected_calls = tool_calls[:max_tools_per_round]
            working_messages.append(
                {
                    "role": "assistant",
                    "content": message.content,
                    "tool_calls": [
                        {
                            "id": tool_call.id,
                            "type": "function",
                            "function": {
                                "name": tool_call.function.name,
                                "arguments": tool_call.function.arguments,
                            },
                        }
                        for tool_call in selected_calls
                    ],
                }
            )

            for tool_call in selected_calls:
                fn_name = tool_call.function.name
                fn_args = self._parse_tool_arguments(tool_call.function.arguments or "{}")
                fn = tool_callables.get(fn_name)
                if fn is None:
                    result: Any = {"error": f"unknown planner tool: {fn_name}"}
                else:
                    try:
                        result = fn(**fn_args)
                    except Exception as exc:
                        logger.debug("Planner tool %s failed", fn_name, exc_info=True)
                        result = {"error": str(exc)}

                tool_trace.append(
                    {
                        "round": round_index + 1,
                        "tool": fn_name,
                        "args": fn_args,
                        "result": result,
                    }
                )
                working_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )

        raise RuntimeError("Planner tool loop ended unexpectedly.")

    def _parse_tool_arguments(self, raw: str) -> Dict[str, Any]:
        try:
            repaired = repair_json(raw)
            parsed = json.loads(repaired)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            logger.debug("Failed to parse planner tool arguments: %s", raw, exc_info=True)
        return {}

    def _should_disable_tools_for_error(self, error: Exception) -> bool:
        message = str(error).lower()
        return (
            "tool" in message
            and (
                "unsupported" in message
                or "not supported" in message
                or "unrecognized" in message
                or "unknown parameter" in message
                or "tool_choice" in message
            )
        )

    def _parse_response(self, raw_content: str) -> Dict[str, Any]:
        text = raw_content.strip()
        if "```json" in text:
            text = text.split("```json", 1)[1].split("```", 1)[0].strip()
        elif "```" in text:
            text = text.split("```", 1)[1].split("```", 1)[0].strip()

        if not text:
            raise ValueError("Interviewer response was empty.")

        try:
            parsed = json.loads(repair_json(text))
        except (json.JSONDecodeError, TypeError, ValueError):
            question = text.strip().strip('"')
            return {
                "action": "continue",
                "question": question,
                "planner_plan": self._fallback_planner_plan(
                    "continue",
                    "模型未返回 JSON，按自然文本问题降级处理。",
                ),
            }
        if not isinstance(parsed, dict):
            question = str(parsed).strip()
            return {
                "action": "continue",
                "question": question,
                "planner_plan": self._fallback_planner_plan(
                    "continue",
                    "模型返回了非对象 JSON，按自然文本问题降级处理。",
                ),
            }

        planner_plan = parsed.get("planner_plan")
        if not isinstance(planner_plan, dict):
            planner_plan = {}

        action = str(parsed.get("action", "")).strip()
        if not action:
            action = self._infer_top_level_action(planner_plan)
        if action not in {"continue", "next_phase", "end"}:
            action = "continue"
        question = str(parsed.get("question", "")).strip()

        if action == "end" and not question:
            question = "今天聊了很多珍贵的回忆，谢谢您愿意和我分享。"

        if not question:
            raise ValueError("Interviewer response missing question.")

        planner_plan = self._normalize_planner_plan(planner_plan, action)
        return {"action": action, "question": question, "planner_plan": planner_plan}

    def _opening_response(self, elder_profile: ElderProfile) -> Dict[str, Any]:
        question = self._build_opening_question(elder_profile)
        return {
            "action": "continue",
            "question": question,
            "planner_plan": self._opening_planner_plan(elder_profile),
        }

    def _opening_planner_plan(self, elder_profile: ElderProfile) -> Dict[str, Any]:
        focus_label = "早年经历"
        if elder_profile.hometown:
            focus_label = f"{elder_profile.hometown}的早年记忆"
        return {
            "stage": "life_overview",
            "selected_action": "continue_life_overview",
            "focus": {"type": "life_period", "label": focus_label},
            "event_completeness": {
                "score": 0.0,
                "missing_dimensions": [
                    "time",
                    "location",
                    "people",
                    "sequence",
                    "feeling",
                    "reflection",
                ],
                "reason_summary": "访谈刚开始，尚未形成具体事件。",
            },
            "emotion_signal": {
                "energy": 0.5,
                "valence": "neutral",
                "support_needed": False,
            },
            "candidate_actions": [
                {
                    "action": "continue_life_overview",
                    "score": 0.9,
                    "reason_summary": "开场阶段应先帮助老人铺开人生脉络。",
                },
                {
                    "action": "deep_dive_event",
                    "score": 0.2,
                    "reason_summary": "尚无明确事件，不适合立即深挖。",
                },
            ],
            "selected_slot_or_angle": "life_timeline",
            "tone": "respectful_warm",
            "question_intent": "邀请老人从最早、最清楚的记忆开始讲述。",
        }

    def _fallback_planner_plan(self, action: str, reason_summary: str) -> Dict[str, Any]:
        selected_action = "end" if action == "end" else "switch_theme" if action == "next_phase" else "deep_dive_event"
        return {
            "stage": "event_deepening",
            "selected_action": selected_action,
            "focus": {"type": "event", "label": "当前经历"},
            "event_completeness": {
                "score": 0.0,
                "missing_dimensions": [],
                "reason_summary": reason_summary,
            },
            "emotion_signal": {
                "energy": 0.5,
                "valence": "neutral",
                "support_needed": False,
            },
            "candidate_actions": [
                {
                    "action": selected_action,
                    "score": 1.0,
                    "reason_summary": reason_summary,
                }
            ],
            "selected_slot_or_angle": "theme",
            "tone": "respectful_warm",
            "question_intent": reason_summary,
        }

    def _normalize_planner_plan(self, planner_plan: Dict[str, Any], action: str) -> Dict[str, Any]:
        if not planner_plan:
            return self._fallback_planner_plan(action, "模型未提供 planner_plan，按顶层 action 记录。")

        normalized = dict(planner_plan)
        normalized.setdefault("stage", "event_deepening")
        normalized.setdefault("selected_action", self._infer_selected_action(action))
        focus = normalized.get("focus")
        if not isinstance(focus, dict):
            normalized["focus"] = {"type": "event", "label": str(focus or "当前经历")}

        completeness = normalized.get("event_completeness")
        if not isinstance(completeness, dict):
            completeness = {}
        score = completeness.get("score", 0.0)
        try:
            score = max(0.0, min(float(score), 1.0))
        except (TypeError, ValueError):
            score = 0.0
        missing = completeness.get("missing_dimensions", [])
        if not isinstance(missing, list):
            missing = []
        normalized["event_completeness"] = {
            "score": score,
            "missing_dimensions": [str(item) for item in missing[:8]],
            "reason_summary": str(completeness.get("reason_summary", "") or "")[:160],
        }

        emotion = normalized.get("emotion_signal")
        if not isinstance(emotion, dict):
            emotion = {}
        energy = emotion.get("energy", 0.5)
        try:
            energy = max(0.0, min(float(energy), 1.0))
        except (TypeError, ValueError):
            energy = 0.5
        normalized["emotion_signal"] = {
            "energy": energy,
            "valence": str(emotion.get("valence", "neutral") or "neutral"),
            "support_needed": bool(emotion.get("support_needed", False)),
        }

        candidates = normalized.get("candidate_actions")
        if not isinstance(candidates, list) or not candidates:
            candidates = [
                {
                    "action": normalized["selected_action"],
                    "score": 1.0,
                    "reason_summary": "模型只给出了最终动作。",
                }
            ]
        normalized["candidate_actions"] = [
            self._normalize_candidate_action(item)
            for item in candidates[:4]
            if isinstance(item, dict)
        ] or [
            {
                "action": normalized["selected_action"],
                "score": 1.0,
                "reason_summary": "模型只给出了最终动作。",
            }
        ]
        normalized.setdefault("selected_slot_or_angle", "theme")
        normalized.setdefault("tone", "respectful_warm")
        normalized.setdefault("question_intent", "继续推进访谈。")
        return normalized

    def _normalize_candidate_action(self, item: Dict[str, Any]) -> Dict[str, Any]:
        score = item.get("score", 0.0)
        try:
            score = max(0.0, min(float(score), 1.0))
        except (TypeError, ValueError):
            score = 0.0
        return {
            "action": str(item.get("action", "") or ""),
            "score": score,
            "reason_summary": str(item.get("reason_summary", "") or "")[:160],
        }

    def _infer_top_level_action(self, planner_plan: Dict[str, Any]) -> str:
        selected_action = str(planner_plan.get("selected_action", "") or "")
        if selected_action == "end":
            return "end"
        if selected_action in {"switch_theme", "move_to_period", "confirm_summary"}:
            return "next_phase"
        return "continue"

    def _infer_selected_action(self, action: str) -> str:
        if action == "end":
            return "end"
        if action == "next_phase":
            return "switch_theme"
        return "deep_dive_event"

    def _build_opening_question(self, elder_profile: ElderProfile) -> str:
        background = (elder_profile.background_summary or "").strip()
        hometown = (elder_profile.hometown or "").strip()
        birth_year = elder_profile.birth_year
        address = self._safe_opening_address(elder_profile)

        if hometown and birth_year:
            return (
                f"{address}，您是{birth_year}年出生的，又和{hometown}有很深的缘分。"
                "如果从人生最早的一段清楚记忆说起，您最先想到的是哪里、什么人，或者哪一幕场景？"
            )

        if birth_year:
            return (
                f"{address}，您是{birth_year}年出生的，走过了这么长的人生路。"
                "您愿意先从一段现在还记得很清楚的早年经历讲起吗？"
            )

        if hometown:
            return (
                f"{address}，您和{hometown}有很深的缘分。"
                "要是从最早的家乡记忆聊起，您脑海里先浮现的是哪一幕？"
            )

        if background:
            return (
                f"{address}，从您的这些人生经历里，一定有些画面一直留在心里。"
                "您愿意先从一段最早、最清楚的记忆慢慢讲起吗？"
            )

        return f"{address}，您愿意先和我讲一段现在还记得很清楚的早年经历吗？"

    @staticmethod
    def _safe_opening_address(elder_profile: ElderProfile) -> str:
        name = (elder_profile.name or "").strip()
        if not name:
            return "奶奶"
        if name.endswith(("奶奶", "爷爷", "阿姨", "叔叔", "老师")):
            return name
        if len(name) <= 4:
            return f"{name}奶奶"
        return "奶奶"

    @staticmethod
    def _append_dynamic_profile(parts: List[str], hint: Dict[str, Any]) -> None:
        section_labels = {
            "core_identity_and_personality": "核心身份与性格",
            "current_life_status": "当前生活状况",
            "family_situation": "家庭情况",
            "life_views_and_attitudes": "人生观与态度",
        }
        sections = hint.get("sections", {})
        if not sections:
            return
        parts.append("\n## 已了解的受访者特点（动态画像）")
        for section_key, fields in sections.items():
            label = section_labels.get(section_key, section_key)
            lines = []
            for fname, fdata in fields.items():
                val = fdata.get("value")
                if not val:
                    continue
                display = ", ".join(val) if isinstance(val, list) else str(val)
                lines.append(f"- {fname}: {display}")
            if lines:
                parts.append(f"**{label}**：")
                parts.extend(lines)
        guidance = hint.get("planner_guidance", [])
        if guidance:
            parts.append("\n**画像引导建议**：")
            for g in guidance:
                parts.append(f"- {g}")

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

    def _prompt_stage(self, recent_transcript: List[TurnRecord]) -> str:
        turn_count = len(recent_transcript)
        if turn_count <= 2:
            return "early"
        if turn_count <= 5:
            return "mid"
        return "full"

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
