from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from openai import OpenAI

from src.config import Config
from src.state import ElderProfile, GraphSummary, MemoryCapsule, TurnRecord

try:
    from json_repair import repair_json
except ImportError:  # pragma: no cover - optional dependency in some local envs
    def repair_json(text: str) -> str:
        return text


logger = logging.getLogger(__name__)


class InterviewerAgent:
    """
    统一访谈助手（Planner + Interviewer 合并版）

    将 Planner 的决策逻辑以"思维链"形式整合到 System Prompt 中，
    单次 LLM 调用完成策略分析和问题生成。
    """

    # 槽位中文映射
    SLOT_NAMES = {
        "time": "时间",
        "location": "地点",
        "people": "人物",
        "event": "事件",
        "feeling": "感受",
        "reflection": "反思",
        "cause": "起因",
        "result": "结果",
    }
    SLOT_PRIORITY = ["time", "location", "people", "event", "cause", "result", "feeling", "reflection"]

    def __init__(self):
        self.client = OpenAI(**Config.get_openai_client_kwargs())
        self.model_candidates = Config.get_model_candidates("interviewer")
        self.model = self.model_candidates[0]
        self.max_tokens = 4096 if self._is_reasoning_heavy_model() else 1024

    def generate_question(
        self,
        elder_profile: ElderProfile,
        recent_transcript: List[TurnRecord],
        memory_capsule: MemoryCapsule,
        graph_summary: GraphSummary,
        focus_event_payload: Optional[Dict[str, Any]] = None,
        generation_hints: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, str]:
        """
        生成下一个访谈问题

        单次 LLM 调用，在模型内部完成策略决策和问题生成
        """
        if not recent_transcript:
            return self._opening_response(elder_profile)

        system_prompt = self._render_system_prompt()
        user_prompt = self._build_user_prompt(
            elder_profile,
            recent_transcript,
            memory_capsule,
            graph_summary,
            focus_event_payload,
            generation_hints=generation_hints,
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

                    parsed = self._parse_response(raw_content)
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
        return self._retry_response(
            opening_turn=False,
            focus_event_payload=focus_event_payload,
            generation_hints=generation_hints,
        )

    def _render_system_prompt(self) -> str:
        """
        渲染 System Prompt

        整合 Planner 的访谈规划思维链，单次调用完成策略分析+问题生成
        """
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

### 1. 当前事件分析
- 老人刚才讲的故事完整吗？（时间、地点、人物、起因、经过、结果、感受）
- 哪些细节值得深挖？老人是否对某个细节特别有感触？
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
        memory_capsule: MemoryCapsule,
        graph_summary: GraphSummary,
        focus_event_payload: Optional[Dict[str, Any]],
        generation_hints: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        构建 User Prompt

        整合所有上下文信息，以叙事化方式呈现
        """
        prompt_stage = self._prompt_stage(recent_transcript)

        parts = []

        # 1. 受访者基本信息
        parts.append("## 受访者基本信息")
        parts.append(self._build_basic_info_text(elder_profile))

        # 2. 对话回顾
        parts.append("\n## 最近对话")
        transcript_limit = 1 if prompt_stage == "early" else 2 if prompt_stage == "mid" else 3
        for turn in recent_transcript[-transcript_limit:]:
            parts.append(f"问：{turn.interviewer_question}")
            parts.append(f"答：{turn.interviewee_answer}")
            parts.append("")

        # 3. 正在聊的事件
        if focus_event_payload:
            parts.append("## 正在聊的事件")
            summary = focus_event_payload.get("summary", "")
            if summary:
                parts.append(f"事件：{summary}")

            known = focus_event_payload.get("known_slots", {})
            if known:
                known_parts = [f"{self.SLOT_NAMES.get(k, k)}：{v}" for k, v in known.items() if v]
                if known_parts:
                    parts.append(f"已知的细节：{', '.join(known_parts)}")

            missing = focus_event_payload.get("missing_slots", [])
            if missing:
                missing_parts = [self.SLOT_NAMES.get(m, m) for m in missing]
                parts.append(f"还欠缺的细节：{', '.join(missing_parts)}")
                preferred_order = generation_hints.get("recommended_slots", []) if generation_hints else []
                prioritized_missing = self._normalize_missing_slots(missing, preferred_order=preferred_order)[:2]
                if prioritized_missing:
                    prioritized_parts = [self.SLOT_NAMES.get(m, m) for m in prioritized_missing]
                    parts.append(f"本轮优先补齐：{', '.join(prioritized_parts)}")

            unexpanded = focus_event_payload.get("unexpanded_clues", [])
            if unexpanded:
                parts.append(f"值得追问的线索：{', '.join(unexpanded[:2])}")

        # 4. 人生故事覆盖情况
        parts.append("\n## 人生故事覆盖情况")
        parts.append(self._build_coverage_summary(graph_summary))

        # 5. 待探索的话题线索
        if memory_capsule.open_loops:
            parts.append("\n## 待探索的话题线索")
            for i, loop in enumerate(memory_capsule.open_loops[:3], 1):
                parts.append(f"{i}. {loop.description}")

        # 6. 情绪观察
        emotional_note = self._build_emotional_note(memory_capsule)
        if emotional_note:
            parts.append(f"\n## 情绪观察")
            parts.append(emotional_note)

        # 7. 生成提示（用于降低重复追问）
        if generation_hints:
            parts.append("\n## 策略提示")
            low_info_streak = int(generation_hints.get("low_info_streak", 0) or 0)
            if low_info_streak >= 2:
                parts.append(
                    f"最近连续 {low_info_streak} 轮信息增益偏低。"
                    "优先换一个新切口（人物/时间/地点/主题）再问。"
                )
            recommended_theme_title = str(generation_hints.get("recommended_theme_title", "") or "")
            if recommended_theme_title:
                parts.append(f"建议切换主题：{recommended_theme_title}")
            preferred_focus = str(generation_hints.get("preferred_focus", "") or "")
            if preferred_focus:
                parts.append(f"焦点建议：{preferred_focus}")
            top_slot = ""
            for item in generation_hints.get("slot_rankings", []):
                if isinstance(item, dict) and item.get("slot"):
                    top_slot = str(item["slot"])
                    break
            if top_slot:
                parts.append(f"建议优先补槽位：{self.SLOT_NAMES.get(top_slot, top_slot)}")
            if generation_hints.get("suggest_close"):
                parts.append("覆盖率较高且连续低增益，可考虑温和收尾。")

        # 7. 任务指令
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
        """解析 LLM 响应"""
        text = raw_content.strip()

        # 提取 JSON 块
        if "```json" in text:
            text = text.split("```json", 1)[1].split("```", 1)[0].strip()
        elif "```" in text:
            text = text.split("```", 1)[1].split("```", 1)[0].strip()

        if not text:
            raise ValueError("Interviewer response was empty.")

        try:
            parsed = json.loads(repair_json(text))
        except json.JSONDecodeError:
            # 如果不是 JSON，尝试直接用文本作为问题
            return {"action": "continue", "question": text.strip().strip('"')}

        action = str(parsed.get("action", "continue")).strip() or "continue"
        question = str(parsed.get("question", "")).strip()

        if action == "end" and not question:
            question = "今天聊了很多珍贵的回忆，谢谢您愿意和我分享。"

        if not question:
            raise ValueError("Interviewer response missing question.")

        return {"action": action, "question": question}

    def _opening_response(self, elder_profile: ElderProfile) -> Dict[str, str]:
        """生成开场问题"""
        question = self._build_opening_question(elder_profile)
        return {"action": "continue", "question": question}

    def _retry_response(
        self,
        opening_turn: bool = False,
        focus_event_payload: Optional[Dict[str, Any]] = None,
        generation_hints: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, str]:
        """重试响应"""
        if opening_turn:
            question = "抱歉，我想先根据您刚才的信息整理一下，再继续向您请教，可以稍等一下吗？"
            return {"action": "continue", "question": question}

        if generation_hints and generation_hints.get("suggest_close"):
            return {
                "action": "end",
                "question": "今天和您聊到了很多珍贵的故事，真的非常感谢您愿意分享。我们先聊到这里，改天再继续好吗？",
            }
        if generation_hints and generation_hints.get("prefer_breadth_switch"):
            repeat_count = int(generation_hints.get("fallback_repeat_count", 0) or 0)
            recommended_theme_title = str(generation_hints.get("recommended_theme_title", "") or "").strip()
            breadth_questions = [
                "我们换一个轻松一点的角度聊聊吧。回头看您的人生，还有哪段经历是您一直记在心里的？",
                "我们先换个话题，不着急想刚才那件事。您人生里有没有一段让您特别自豪的时刻？",
                "没关系，我们顺着您更有感觉的部分聊。您愿意讲讲生命里一个对您影响很大的人吗？",
            ]
            if recommended_theme_title:
                breadth_questions = [
                    f"我们先换个角度，聊聊“{recommended_theme_title}”这部分吧。您最先想到的是哪件事？",
                    f"不着急回想刚才那段，我们换到“{recommended_theme_title}”这个话题。有没有一件您印象很深的事？",
                    f"我们沿着“{recommended_theme_title}”继续聊，您愿意先说一段最想分享的经历吗？",
                ]
            question = breadth_questions[repeat_count % len(breadth_questions)]
            return {
                "action": "next_phase",
                "question": question,
            }

        if focus_event_payload:
            preferred_order = generation_hints.get("recommended_slots", []) if generation_hints else []
            missing = self._normalize_missing_slots(
                focus_event_payload.get("missing_slots", []),
                preferred_order=preferred_order,
            )
            if missing:
                slot_name = missing[0]
                question_by_slot = {
                    "time": "这件事大概发生在什么时候，您还记得吗？",
                    "location": "这件事当时是在哪里发生的，您能再说说吗？",
                    "people": "当时身边还有哪些人在场，您还记得吗？",
                    "event": "当时具体发生了什么，您愿意再详细讲一点吗？",
                    "cause": "这件事最初是怎么开始的，您还有印象吗？",
                    "result": "后来事情是怎么收尾的，结果怎么样？",
                    "feeling": "那一刻您心里最强烈的感受是什么？",
                    "reflection": "回头看这件事，对您最大的影响是什么？",
                }
                return {"action": "continue", "question": question_by_slot.get(slot_name, "您愿意再讲讲这件事里的一个细节吗？")}

        question = "抱歉，我想更准确地接着您刚才的话问一句，请稍等我整理一下再继续。"
        return {"action": "continue", "question": question}

    def _normalize_missing_slots(self, missing_slots: Any, preferred_order: Optional[List[str]] = None) -> List[str]:
        if not isinstance(missing_slots, list):
            return []
        filtered = [slot for slot in missing_slots if isinstance(slot, str) and slot in self.SLOT_NAMES]
        if preferred_order:
            preferred_priority = {
                slot: index
                for index, slot in enumerate(preferred_order)
                if isinstance(slot, str) and slot in self.SLOT_NAMES
            }
            if preferred_priority:
                return sorted(filtered, key=lambda slot: preferred_priority.get(slot, len(preferred_priority) + 100))

        # 默认按固定优先级排序，优先补齐事实槽位，减少抽象追问。
        priority = {slot: index for index, slot in enumerate(self.SLOT_PRIORITY)}
        return sorted(filtered, key=lambda slot: priority.get(slot, len(self.SLOT_PRIORITY)))

    def _build_opening_question(self, elder_profile: ElderProfile) -> str:
        """构建开场问题"""
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

    def _build_coverage_summary(self, graph_summary: GraphSummary) -> str:
        """构建覆盖率的自然语言描述"""
        parts = []

        # 整体进度
        coverage_pct = int(graph_summary.overall_coverage * 100)
        parts.append(f"整体进度：约{coverage_pct}%")

        # 各主题覆盖情况
        if graph_summary.theme_coverage:
            covered = []
            uncovered = []
            for theme_id, ratio in sorted(graph_summary.theme_coverage.items()):
                if ratio > 0.5:
                    covered.append(theme_id)
                elif ratio < 0.2:
                    uncovered.append(theme_id)

            if covered:
                parts.append(f"已聊到：{', '.join(covered[:3])}")
            if uncovered:
                parts.append(f"还很少涉及：{', '.join(uncovered[:3])}")

        # 当前焦点
        if graph_summary.current_focus_theme_id:
            parts.append(f"当前话题：{graph_summary.current_focus_theme_id}")

        return "；".join(parts) if parts else "刚开始访谈"

    def _build_basic_info_text(self, elder_profile: ElderProfile) -> str:
        """构建基本信息文本"""
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

    def _build_emotional_note(self, memory_capsule: MemoryCapsule) -> str:
        """构建情感状态提示"""
        if not memory_capsule.emotional_state:
            return ""

        notes = []
        energy = memory_capsule.emotional_state.cognitive_energy
        valence = memory_capsule.emotional_state.valence

        if energy < 0.4:
            notes.append("老人精力较低，问题要简短、温和")
        elif energy > 0.7:
            notes.append("老人精力不错，可以适当深入")

        if valence < -0.3:
            notes.append("老人情绪偏负面，提问前先共情")
        elif valence > 0.3:
            notes.append("老人情绪积极，保持轻松氛围")

        return "；".join(notes) if notes else ""

    def _prompt_stage(self, recent_transcript: List[TurnRecord]) -> str:
        """判断提示阶段"""
        turn_count = len(recent_transcript)
        if turn_count <= 2:
            return "early"
        if turn_count <= 5:
            return "mid"
        return "full"

    def _is_reasoning_heavy_model(self, model_name: Optional[str] = None) -> bool:
        """判断是否为推理型模型"""
        model_name = (model_name or self.model or "").lower()
        return "thinking" in model_name or "k2.5" in model_name or "reasoning" in model_name

    def _should_fallback_model(self, error: Exception) -> bool:
        """判断是否应回退模型"""
        message = str(error).lower()
        return (
            "not found the model" in message
            or "permission denied" in message
            or "resource_not_found_error" in message
        )
