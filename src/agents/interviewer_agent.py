from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from openai import OpenAI

from src.config import Config
from src.state import ElderProfile, TurnRecord
from src.services.graph_rag_decision_context import GraphRAGDecisionContext

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
    ) -> Dict[str, str]:
        """Generate next question using GraphRAG decision context."""
        if not recent_transcript:
            return self._opening_response(elder_profile)

        system_prompt = self._render_system_prompt()
        user_prompt = self._build_user_prompt(
            elder_profile, recent_transcript, decision_ctx
        )

        max_attempts = max(1, min(Config.MAX_RETRIES, 2))

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
                            "InterviewerAgent received empty content (model=%s, reasoning_len=%s)",
                            model_name, len(reasoning_content),
                        )
                        continue

                    parsed = self._parse_response(raw_content)
                    if parsed.get("question"):
                        self.model = model_name
                        self.max_tokens = candidate_max_tokens
                        return parsed
                except Exception as exc:
                    logger.warning(
                        "InterviewerAgent model=%s attempt %s/%s failed: %s",
                        model_name, attempt, max_attempts, exc,
                    )
                    if self._should_fallback_model(exc):
                        break

        logger.error("InterviewerAgent returning fallback response")
        return {
            "action": "continue",
            "question": "您能再跟我多说说那个时候的事情吗？",
        }

    def _render_system_prompt(self) -> str:
        return """你是一位充满好奇心、善于倾听的传记访谈者，正在陪一位老人重温他/她的人生旅程。

你的目标不是"收集信息"，而是帮老人讲述一个完整、有温度的生命故事。让老人感到被理解、被珍视。

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

**3. 重要人物** —— 生命中影响深远的人
   - 家人、恩师、挚友、对手

**4. 价值观与信仰** —— 人生的指南针
   - 经历了这么多，老人最看重什么？

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

4. **一次只问一件事** —— 问题清晰、聚焦，不堆叠多个问题

5. **隐藏技术细节** —— 永远不提"图谱"、"节点"、"槽位"、"覆盖率"等概念

---

## 【访谈规划思维链】

在生成下一个问题之前，请先基于以下维度进行分析：

### 1. 当前叙事分析
- 老人刚才讲的故事完整吗？（时间、地点、人物、起因、经过、结果、感受）
- 哪些细节值得深挖？老人是否对某个细节特别有感触？
- 图谱中有哪些可追问的方向？
- **策略方向**：
  * 如果信息缺失且需要确认 → 封闭式确认
  * 如果老人流露出情感 → 开放式追问感受
  * 如果故事还有延伸空间 → 开放式引导继续

### 2. 情绪状态判断
- 老人的精力如何？（低 → 简短温和；高 → 可适当深入）
- 情绪是积极、中性还是消极？（消极 → **先真诚共情，再问问题**）
- 是否表现出话题疲劳？（是 → 考虑广度跳转）

### 3. 策略决策（三选一）

**路径 A：深度挖掘 (Deep Dive)**
- 适用：当前故事有温度但还不完整，老人愿意聊
- 方法（结合具体场景，不要照搬例句）：
  * 由事及人 —— 从事件延伸到人物性格和关系
  * 由物及情 —— 用具体的物品、场景触发情感记忆
  * 追问感受 —— 关注情绪变化和内心活动
  * 挖掘反思 —— 问"回头看"的意义，而非当时的事实

**路径 B：广度跳转 (Breadth Switch)**
- 适用：当前故事已足够完整，或老人出现疲劳
- 跳转方法（按优先级，结合场景选择）：
  * 情感/人物路径 —— 抓住情绪线索，连接到其他人生时刻
  * 地理/时间路径 —— 顺着时空线索自然过渡
  * 时代背景路径 —— 用历史事件作为切入点
  * 回溯之前的话题 —— 捡起之前放下的线索

**路径 C：温和澄清 (Clarify)**
- 适用：发现时间、地点或人物关系有矛盾/模糊
- 方法：用温和的封闭式问题确认，不给压力
  * 例："是1968年吗？" "您说的那位是张师傅还是李师傅？"

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
  "action": "continue|next_phase|end",
  "question": "你的访谈问题"
}
```

- `action=continue`：继续深入当前话题
- `action=next_phase`：切换到新话题或总结过渡
- `action=end`：结束访谈

**重要**：
- question 字段只能包含**一个问题**
- 问感受时用**开放式问题**，问确认时用**封闭式问题**
- 语气自然、温暖、好奇，像老朋友聊天一样"""

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

        # 2. Recent dialogue
        parts.append("\n## 最近对话")
        limit = 1 if prompt_stage == "early" else 2 if prompt_stage == "mid" else 3
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

        # 7. Emotional observation
        if ctx.emotional_state:
            parts.append("\n## 情绪观察")
            parts.append(self._build_emotional_note(ctx.emotional_state))

        # 8. Strategy hints
        parts.append("\n## 策略提示")
        if ctx.low_info_streak >= 2:
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
        parts.append("基于以上上下文，先进行【访谈规划思维链】分析，然后生成下一个问题。")
        parts.append("")
        parts.append("记住：")
        parts.append("1. 问题要自然、温暖、像聊天")
        parts.append("2. 不要暴露任何技术概念")
        parts.append("3. 如果老人情绪低落，先共情再提问")
        parts.append("4. 如果老人疲劳，切换到轻松话题")
        parts.append("")
        parts.append("返回严格 JSON 格式：")
        parts.append('{\'action\': \'continue|next_phase|end\', \'question\': \'你的问题\'}')

        return "\n".join(parts)

    def _parse_response(self, raw_content: str) -> Dict[str, str]:
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
            return {"action": "continue", "question": text.strip().strip('"')}

        action = str(parsed.get("action", "continue")).strip() or "continue"
        question = str(parsed.get("question", "")).strip()

        if action == "end" and not question:
            question = "今天聊了很多珍贵的回忆，谢谢您愿意和我分享。"

        if not question:
            raise ValueError("Interviewer response missing question.")

        return {"action": action, "question": question}

    def _opening_response(self, elder_profile: ElderProfile) -> Dict[str, str]:
        question = self._build_opening_question(elder_profile)
        return {"action": "continue", "question": question}

    def _build_opening_question(self, elder_profile: ElderProfile) -> str:
        background = (elder_profile.background_summary or "").strip()
        hometown = (elder_profile.hometown or "").strip()
        birth_year = elder_profile.birth_year
        name = elder_profile.name or "您"

        if any(keyword in background for keyword in ["工厂", "上班", "工作", "纺织", "车间"]):
            return f"{name}，从您的人生经历里，年轻时工作那段日子一定很值得一提。您还记得自己刚参加工作时最难忘的一幕吗？"

        if any(keyword in background for keyword in ["结婚", "家庭", "孩子", "成家", "老伴"]):
            return f"{name}，您的人生里一定有一段和成家有关的经历特别重要。您愿意先从那件最难忘的事讲起吗？"

        if hometown and birth_year:
            return f"{name}，您是{birth_year}年出生的，又和{hometown}有很深的缘分。要是从最早记得的一段经历说起，您最先想到的是哪件事？"

        if birth_year:
            return f"{name}，您是{birth_year}年出生的，走过了这么长的人生路。您愿意先从一段年轻时至今还记得很清楚的经历讲起吗？"

        if background:
            return f"{name}，从您的人生经历里，一定有一段故事一直留在心里。您愿意先从那件最难忘的事讲起吗？"

        return f"{name}，您愿意先和我讲一段您年轻时至今还记得很清楚的具体经历吗？"

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

    def _build_emotional_note(self, emotional_state) -> str:
        if not emotional_state:
            return ""
        lines = []
        energy = emotional_state.cognitive_energy
        valence = emotional_state.valence
        if energy < 0.35:
            lines.append("老人可能有些疲惫了，回答较短。")
        elif energy > 0.7:
            lines.append("老人精力充沛，表达很活跃。")
        if valence < -0.3:
            lines.append("情绪偏消极，注意温柔引导。")
        elif valence > 0.3:
            lines.append("情绪比较积极，可以深入聊。")
        if emotional_state.evidence:
            lines.append(f"依据：{'、'.join(emotional_state.evidence[:2])}")
        return "\n".join(lines)

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
