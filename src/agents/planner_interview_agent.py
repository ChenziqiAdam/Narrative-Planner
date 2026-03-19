#!/usr/bin/env python3
"""
PlannerInterviewAgent - 带事件提取和图谱管理的访谈Agent

该Agent结合了Baseline的对话能力和Planner的事件提取、图谱管理功能。
用于与BaselineAgent进行对比测试。
"""

import os
import sys
import json
import logging
import asyncio
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Any

# 添加项目根目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.config import Config
from src.agents.baseline_agent import BaselineAgent
from src.core.event_extractor import EventExtractor
from src.core.graph_manager import GraphManager
from src.core.event_node import EventNode
from src.core.theme_node import NodeStatus
from openai import OpenAI

# 设置日志
logger = logging.getLogger(__name__)


class PlannerInterviewAgent:
    """
    带事件提取和图谱管理的访谈Agent

    结合Baseline对话能力 + Planner事件提取和图谱管理
    """

    def __init__(self, session_id: str = None):
        """
        初始化 Planner Interview Agent

        Args:
            session_id: 会话 ID，用于日志和结果保存
        """
        self.session_id = session_id or datetime.now().strftime("%Y%m%d_%H%M%S")

        # 基础对话能力（复用BaselineAgent）
        self.baseline_agent = BaselineAgent(session_id)

        # 事件提取器
        self.event_extractor = EventExtractor()

        # 图谱管理器
        self.graph_manager = GraphManager()

        # 对话历史（用于事件提取上下文）
        self.conversation_history: List[Dict[str, str]] = []

        # 当前轮次计数
        self.turn_count = 0

        # 老人信息
        self.elder_info: Dict[str, Any] = {}

        logger.info(f"PlannerInterviewAgent 初始化完成 (Session: {self.session_id})")

    def initialize_conversation(self, elder_info: Dict[str, Any]):
        """
        初始化对话和图谱

        Args:
            elder_info: 老人信息字典，包含name, birth_year, hometown, background等
        """
        self.elder_info = elder_info

        # 构建基本信息文本（用于BaselineAgent）
        basic_info_text = self._build_basic_info_text(elder_info)

        # 初始化Baseline对话
        self.baseline_agent.initialize_conversation(basic_info_text)

        # 构建初始图谱（基于老人背景信息预填充一些主题）
        self._initialize_graph_from_elder_info(elder_info)

        # 添加系统消息到历史
        self.conversation_history.append({
            "role": "system",
            "content": f"开始访谈 - 受访者: {elder_info.get('name', '未知')}"
        })

        logger.info(f"对话已初始化，老人信息: {elder_info.get('name', '未知')}")

    def _build_basic_info_text(self, elder_info: Dict[str, Any]) -> str:
        """构建老人信息文本"""
        parts = []
        if elder_info.get('name'):
            parts.append(f"姓名：{elder_info['name']}")
        if elder_info.get('birth_year'):
            parts.append(f"出生于{elder_info['birth_year']}年")
        if elder_info.get('hometown'):
            parts.append(f"家乡：{elder_info['hometown']}")
        if elder_info.get('background'):
            parts.append(f"背景：{elder_info['background']}")

        return "，".join(parts) if parts else "一位老人"

    def _initialize_graph_from_elder_info(self, elder_info: Dict[str, Any]):
        """基于老人信息初始化图谱状态"""
        # 解析背景信息，尝试激活相关主题
        background = elder_info.get('background', '')

        # 简单的关键词匹配来预激活主题
        keyword_theme_map = {
            '童年': ['THEME_05_CHILDHOOD_POSITIVE', 'THEME_06_CHILDHOOD_NEGATIVE'],
            '家庭': ['THEME_01_LIFE_CHAPTERS', 'THEME_07_ADULT_MEMORY'],
            '父母': ['THEME_01_LIFE_CHAPTERS', 'THEME_05_CHILDHOOD_POSITIVE'],
            '上学': ['THEME_01_LIFE_CHAPTERS', 'THEME_05_CHILDHOOD_POSITIVE'],
            '学校': ['THEME_01_LIFE_CHAPTERS', 'THEME_05_CHILDHOOD_POSITIVE'],
            '老师': ['THEME_05_CHILDHOOD_POSITIVE'],
            '同学': ['THEME_05_CHILDHOOD_POSITIVE'],
            '工作': ['THEME_07_ADULT_MEMORY', 'THEME_04_TURNING_POINT'],
            '工厂': ['THEME_07_ADULT_MEMORY', 'THEME_04_TURNING_POINT'],
            '上班': ['THEME_07_ADULT_MEMORY'],
            '结婚': ['THEME_04_TURNING_POINT', 'THEME_07_ADULT_MEMORY'],
            '老伴': ['THEME_04_TURNING_POINT', 'THEME_07_ADULT_MEMORY'],
            '子女': ['THEME_01_LIFE_CHAPTERS', 'THEME_07_ADULT_MEMORY'],
            '儿子': ['THEME_01_LIFE_CHAPTERS'],
            '女儿': ['THEME_01_LIFE_CHAPTERS'],
            '战争': ['THEME_03_LOW_POINT', 'THEME_13_LIFE_CHALLENGE'],
            '文革': ['THEME_03_LOW_POINT', 'THEME_13_LIFE_CHALLENGE'],
            '改革': ['THEME_04_TURNING_POINT'],
            '下乡': ['THEME_04_TURNING_POINT'],
            '北大荒': ['THEME_04_TURNING_POINT'],
            '迁移': ['THEME_04_TURNING_POINT'],
        }

        activated_themes = set()
        for keyword, themes in keyword_theme_map.items():
            if keyword in background:
                activated_themes.update(themes)

        # 将匹配到的主题标记为已提及（MENTIONED）
        for theme_id in activated_themes:
            if theme_id in self.graph_manager.theme_nodes:
                theme = self.graph_manager.theme_nodes[theme_id]
                if theme.status == NodeStatus.PENDING:
                    theme.mark_mentioned()
                    self.graph_manager._update_node_status(theme_id, NodeStatus.MENTIONED)
                    logger.debug(f"预激活主题: {theme_id}")

    async def get_next_question(self, user_response: str = None) -> Dict[str, Any]:
        """
        获取下一个问题，同时执行事件提取和图谱更新

        Args:
            user_response: 用户回复（如果是第一轮则为None）

        Returns:
            包含问题、动作、提取的事件、图谱状态的字典
        """
        result = {
            "question": "",
            "action": "continue",  # continue/next_phase/end
            "extracted_events": [],
            "graph_changes": {},
            "current_graph_state": None,
            "turn_count": self.turn_count
        }

        # 1. 如果有用户回复，先进行事件提取
        extracted_events = []
        if user_response:
            self.turn_count += 1

            # 添加到对话历史
            if self.conversation_history:
                last_q = self.conversation_history[-1].get('content', '') if self.conversation_history else ''
                self.conversation_history.append({"role": "user", "content": user_response})

            # 构建当前轮次用于事件提取
            from src.core.interfaces import DialogueTurn
            current_turn = DialogueTurn(
                turn_id=str(self.turn_count),
                session_id=self.session_id,
                timestamp=datetime.now(),
                interviewer_question=self.conversation_history[-2]['content'] if len(self.conversation_history) >= 2 else '',
                interviewer_action="continue",
                interviewee_raw_reply=user_response,
                extracted_events=[]
            )

            # 获取上下文（最近3轮）
            context = []
            for i in range(max(0, len(self.conversation_history) - 4), len(self.conversation_history) - 1):
                if i > 0 and i < len(self.conversation_history):
                    turn = DialogueTurn(
                        turn_id=str(i),
                        session_id=self.session_id,
                        timestamp=datetime.now(),
                        interviewer_question=self.conversation_history[i-1].get('content', '') if i > 0 else '',
                        interviewer_action="continue",
                        interviewee_raw_reply=self.conversation_history[i].get('content', ''),
                        extracted_events=[]
                    )
                    context.append(turn)

            # 执行事件提取
            try:
                extracted_events = await self.event_extractor.extract_from_turn(
                    current_turn, context
                )
                result["extracted_events"] = [
                    {
                        "event_id": e.event_id,
                        "slots": e.slots.to_dict() if hasattr(e.slots, 'to_dict') else e.slots,
                        "confidence": e.confidence,
                        "theme_id": e.theme_id
                    }
                    for e in extracted_events
                ]
                logger.info(f"从第{self.turn_count}轮提取到 {len(extracted_events)} 个事件")
            except Exception as e:
                logger.error(f"事件提取失败: {e}")

            # 2. 更新图谱
            graph_changes = self._update_graph_with_events(extracted_events)
            result["graph_changes"] = graph_changes

        # 3. 获取Baseline的下一个问题
        question = self.baseline_agent.get_next_question(user_response)

        # 解析问题中的action（如果包含JSON格式）
        try:
            # 尝试从问题中提取action
            if isinstance(question, str) and '"action"' in question:
                # 可能是JSON格式，尝试解析
                cleaned = question.strip()
                if cleaned.startswith('{') and cleaned.endswith('}'):
                    q_data = json.loads(cleaned)
                    result["question"] = q_data.get("question", question)
                    result["action"] = q_data.get("action", "continue")
                else:
                    result["question"] = question
            else:
                result["question"] = question
        except json.JSONDecodeError:
            result["question"] = question

        # 4. 获取当前图谱状态
        result["current_graph_state"] = self.get_graph_state()

        # 添加到对话历史
        self.conversation_history.append({"role": "assistant", "content": result["question"]})

        # 5. 检查是否应该结束（基于图谱覆盖率和轮次）
        coverage = self.graph_manager.calculate_coverage()
        if coverage.get("overall", 0) > 0.8 or self.turn_count >= 50:
            result["action"] = "end"

        return result

    def _update_graph_with_events(self, events: List[Any]) -> Dict[str, Any]:
        """
        使用提取的事件更新图谱

        Returns:
            图谱变更摘要
        """
        changes = {
            "new_events": 0,
            "updated_themes": [],
            "coverage_change": 0.0
        }

        old_coverage = self.graph_manager.calculate_coverage().get("overall", 0)

        for event in events:
            try:
                slots = self._event_slots_to_dict(event)
                theme_id = self._resolve_theme_id(event, slots)

                if not theme_id:
                    logger.warning(
                        "Skipping extracted event %s because no graph theme could be resolved",
                        getattr(event, "event_id", "unknown"),
                    )
                    continue

                event_description = self._stringify_slot_value(slots.get("event"))
                event_title = self._build_event_title(event, slots)

                event_node = EventNode(
                    event_id=event.event_id,
                    theme_id=theme_id,
                    title=event_title,
                    description=event_description or event_title,
                    time_anchor=self._stringify_slot_value(slots.get("time")),
                    location=self._stringify_slot_value(slots.get("location")),
                    people_involved=self._normalize_people(slots.get("people")),
                    slots=slots,
                    emotional_score=self._estimate_emotional_score(slots),
                    information_density=self._estimate_information_density(slots),
                    depth_level=1,
                )

                success = self.graph_manager.add_event_node(event_node, theme_id)
                if success:
                    changes["new_events"] += 1
                    if theme_id not in changes["updated_themes"]:
                        changes["updated_themes"].append(theme_id)
                else:
                    logger.warning(
                        "Graph manager rejected extracted event %s for theme %s",
                        event.event_id,
                        theme_id,
                    )
            except Exception:
                logger.exception(
                    "Failed to add extracted event %s into graph",
                    getattr(event, "event_id", "unknown"),
                )

        # 计算覆盖率变化
        new_coverage = self.graph_manager.calculate_coverage().get("overall", 0)
        changes["coverage_change"] = new_coverage - old_coverage

        return changes

    def _event_slots_to_dict(self, event: Any) -> Dict[str, Any]:
        """Normalize EventSlots / dict payloads into a plain dict."""
        raw_slots = getattr(event, "slots", {}) or {}
        if hasattr(raw_slots, "to_dict"):
            raw_slots = raw_slots.to_dict()
        elif not isinstance(raw_slots, dict):
            raw_slots = {}

        normalized = {}
        for key, value in raw_slots.items():
            if value in (None, "", [], {}):
                continue
            normalized[key] = value
        return normalized

    def _resolve_theme_id(self, event: Any, slots: Dict[str, Any]) -> Optional[str]:
        """Resolve generic/legacy theme hints to an existing graph theme."""
        hinted_theme = getattr(event, "theme_id", None)

        if hinted_theme in self.graph_manager.theme_nodes:
            return hinted_theme

        for candidate in self._theme_hint_candidates(hinted_theme, slots):
            if candidate in self.graph_manager.theme_nodes:
                return candidate

        matched_theme = self._match_event_to_theme(event, slots)
        if matched_theme and matched_theme in self.graph_manager.theme_nodes:
            return matched_theme

        mentioned = self.graph_manager.get_mentioned_theme_nodes()
        if mentioned:
            return mentioned[0].theme_id

        next_theme = self.graph_manager.get_next_candidate_theme()
        if next_theme:
            return next_theme.theme_id

        pending = self.graph_manager.get_pending_theme_nodes()
        if pending:
            return pending[0].theme_id

        return None

    def _theme_hint_candidates(self, theme_hint: Optional[str], slots: Dict[str, Any]) -> List[str]:
        """Map generic or legacy theme hints to current THEME_* identifiers."""
        if not theme_hint:
            return []

        normalized_hint = str(theme_hint).strip().lower()
        event_text = " ".join(
            filter(
                None,
                [
                    self._stringify_slot_value(slots.get("event")),
                    self._stringify_slot_value(slots.get("feeling")),
                    self._stringify_slot_value(slots.get("reflection")),
                ],
            )
        )
        negative_hint = any(word in event_text for word in ["难受", "困难", "吃苦", "悲伤", "失败", "遗憾", "低谷"])

        alias_map = {
            "childhood": ["THEME_06_CHILDHOOD_NEGATIVE" if negative_hint else "THEME_05_CHILDHOOD_POSITIVE"],
            "childhood_positive": ["THEME_05_CHILDHOOD_POSITIVE"],
            "childhood_negative": ["THEME_06_CHILDHOOD_NEGATIVE"],
            "family": ["THEME_01_LIFE_CHAPTERS", "THEME_07_ADULT_MEMORY"],
            "parent": ["THEME_05_CHILDHOOD_POSITIVE", "THEME_01_LIFE_CHAPTERS"],
            "school": ["THEME_05_CHILDHOOD_POSITIVE", "THEME_01_LIFE_CHAPTERS"],
            "education": ["THEME_05_CHILDHOOD_POSITIVE", "THEME_01_LIFE_CHAPTERS"],
            "career": ["THEME_07_ADULT_MEMORY", "THEME_04_TURNING_POINT"],
            "work": ["THEME_07_ADULT_MEMORY", "THEME_04_TURNING_POINT"],
            "marriage": ["THEME_04_TURNING_POINT", "THEME_07_ADULT_MEMORY"],
            "relationship": ["THEME_07_ADULT_MEMORY"],
            "children": ["THEME_01_LIFE_CHAPTERS", "THEME_07_ADULT_MEMORY"],
            "war": ["THEME_03_LOW_POINT", "THEME_13_LIFE_CHALLENGE"],
            "migration": ["THEME_04_TURNING_POINT", "THEME_07_ADULT_MEMORY"],
            "health": ["THEME_14_HEALTH"],
            "loss": ["THEME_15_LOSS"],
            "regret": ["THEME_16_FAILURE_REGRET"],
            "failure": ["THEME_16_FAILURE_REGRET"],
            "peak": ["THEME_02_PEAK_EXPERIENCE"],
            "low_point": ["THEME_03_LOW_POINT"],
            "turning_point": ["THEME_04_TURNING_POINT"],
            "adult_memory": ["THEME_07_ADULT_MEMORY"],
            "wisdom": ["THEME_09_WISDOM_EVENT"],
            "childhood_family": ["THEME_05_CHILDHOOD_POSITIVE", "THEME_06_CHILDHOOD_NEGATIVE"],
            "childhood_play": ["THEME_05_CHILDHOOD_POSITIVE"],
            "family_origin": ["THEME_01_LIFE_CHAPTERS"],
            "parent_relationship": ["THEME_05_CHILDHOOD_POSITIVE", "THEME_06_CHILDHOOD_NEGATIVE"],
            "sibling_relationship": ["THEME_05_CHILDHOOD_POSITIVE"],
            "school_education": ["THEME_05_CHILDHOOD_POSITIVE", "THEME_01_LIFE_CHAPTERS"],
            "academic_experience": ["THEME_05_CHILDHOOD_POSITIVE", "THEME_07_ADULT_MEMORY"],
            "work_career": ["THEME_07_ADULT_MEMORY", "THEME_04_TURNING_POINT"],
            "career_transition": ["THEME_04_TURNING_POINT", "THEME_07_ADULT_MEMORY"],
            "marriage_meeting": ["THEME_04_TURNING_POINT", "THEME_07_ADULT_MEMORY"],
            "marriage_life": ["THEME_07_ADULT_MEMORY"],
            "children_upbringing": ["THEME_01_LIFE_CHAPTERS", "THEME_07_ADULT_MEMORY"],
            "parent_child_relationship": ["THEME_01_LIFE_CHAPTERS"],
            "war_experience": ["THEME_03_LOW_POINT", "THEME_13_LIFE_CHALLENGE"],
            "cultural_revolution": ["THEME_03_LOW_POINT", "THEME_13_LIFE_CHALLENGE"],
            "reform_opening": ["THEME_04_TURNING_POINT"],
        }

        if normalized_hint in alias_map:
            return alias_map[normalized_hint]

        compact_hint = normalized_hint.replace("-", "_").replace(" ", "_")
        return alias_map.get(compact_hint, [])

    def _build_event_title(self, event: Any, slots: Dict[str, Any]) -> str:
        """Build a concise fallback title for an extracted event."""
        summary = self._stringify_slot_value(slots.get("event")) or ""
        if summary:
            return summary[:24]
        return getattr(event, "event_id", "event")

    def _stringify_slot_value(self, value: Any) -> Optional[str]:
        """Convert slot values into compact text."""
        if value in (None, "", [], {}):
            return None
        if isinstance(value, list):
            parts = [str(item).strip() for item in value if str(item).strip()]
            return "、".join(parts) if parts else None
        text = str(value).strip()
        return text or None

    def _normalize_people(self, people_value: Any) -> List[str]:
        """Normalize people fields to a list of names."""
        if not people_value:
            return []
        if isinstance(people_value, list):
            return [str(item).strip() for item in people_value if str(item).strip()]

        text = str(people_value).strip()
        if not text:
            return []

        for separator in ["，", "、", ",", "/", ";", "和"]:
            if separator in text:
                return [part.strip() for part in text.split(separator) if part.strip()]
        return [text]

    def _estimate_information_density(self, slots: Dict[str, Any]) -> float:
        """Estimate density from how many meaningful slots were filled."""
        if not slots:
            return 0.0
        filled_count = sum(1 for value in slots.values() if value not in (None, "", [], {}))
        return min(filled_count / 6.0, 1.0)

    def _estimate_emotional_score(self, slots: Dict[str, Any]) -> float:
        """Very lightweight sentiment estimation for event nodes."""
        feeling_text = " ".join(
            filter(
                None,
                [
                    self._stringify_slot_value(slots.get("feeling")),
                    self._stringify_slot_value(slots.get("reflection")),
                ],
            )
        )
        if not feeling_text:
            return 0.0

        positive_keywords = ["高兴", "开心", "激动", "自豪", "满足", "幸福"]
        negative_keywords = ["难受", "伤心", "困难", "辛苦", "失望", "压力", "遗憾", "害怕"]

        positive_hits = sum(1 for word in positive_keywords if word in feeling_text)
        negative_hits = sum(1 for word in negative_keywords if word in feeling_text)

        if positive_hits == negative_hits:
            return 0.0
        return max(min((positive_hits - negative_hits) / 3.0, 1.0), -1.0)

    def _match_event_to_theme(self, event: Any, slots: Optional[Dict[str, Any]] = None) -> Optional[str]:
        """根据事件内容匹配最合适的主题"""
        slots = slots or self._event_slots_to_dict(event)
        event_text = " ".join(
            filter(
                None,
                [
                    self._stringify_slot_value(slots.get("event")),
                    self._stringify_slot_value(slots.get("time")),
                    self._stringify_slot_value(slots.get("location")),
                    self._stringify_slot_value(slots.get("people")),
                    self._stringify_slot_value(slots.get("feeling")),
                    self._stringify_slot_value(slots.get("reflection")),
                ],
            )
        )

        keyword_theme_map = {
            "THEME_14_HEALTH": ["医院", "生病", "住院", "手术"],
            "THEME_15_LOSS": ["去世", "离世", "走了", "不在了"],
            "THEME_16_FAILURE_REGRET": ["后悔", "遗憾", "失败", "没做好"],
            "THEME_03_LOW_POINT": ["困难", "受苦", "挨饿", "难受", "低谷"],
            "THEME_13_LIFE_CHALLENGE": ["挑战", "坎坷", "难关", "压力"],
            "THEME_02_PEAK_EXPERIENCE": ["最高兴", "最开心", "自豪", "喜悦", "幸福"],
            "THEME_05_CHILDHOOD_POSITIVE": ["童年", "小时候", "父母", "玩耍", "上学"],
            "THEME_06_CHILDHOOD_NEGATIVE": ["童年", "小时候", "挨打", "受苦", "家穷"],
            "THEME_07_ADULT_MEMORY": ["工作", "工厂", "上班", "师傅", "同事", "结婚", "老伴", "孩子"],
            "THEME_04_TURNING_POINT": ["结婚", "调动", "搬家", "下乡", "北大荒", "转折", "离家"],
            "THEME_09_WISDOM_EVENT": ["明白了", "懂了", "教训", "看透"],
        }

        scored_candidates = []
        for theme_id, keywords in keyword_theme_map.items():
            score = sum(1 for keyword in keywords if keyword in event_text)
            if score > 0:
                scored_candidates.append((score, theme_id))

        if scored_candidates:
            scored_candidates.sort(reverse=True)
            return scored_candidates[0][1]

        # 默认返回第一个待探索的主题
        pending = self.graph_manager.get_pending_theme_nodes()
        if pending:
            return pending[0].theme_id

        return None

    def get_graph_state(self) -> Dict[str, Any]:
        """获取当前图谱状态（用于前端展示）"""
        state = self.graph_manager.get_graph_state()
        elder_info = dict(self.elder_info or {})
        if elder_info.get("birth_year") and not elder_info.get("age"):
            try:
                elder_info["age"] = datetime.now().year - int(elder_info["birth_year"])
            except (TypeError, ValueError):
                pass

        # 添加详细信息
        state["theme_nodes"] = {
            theme_id: node.to_dict()
            for theme_id, node in self.graph_manager.theme_nodes.items()
        }

        state["event_nodes"] = {
            event_id: node.to_dict()
            for event_id, node in self.graph_manager.event_nodes.items()
        }

        state["people_nodes"] = {}
        state["people_count"] = 0
        state["elder_info"] = elder_info
        state["session_id"] = self.session_id

        return state

    def get_conversation_history(self) -> List[Dict[str, str]]:
        """获取对话历史"""
        return self.conversation_history.copy()

    def save_conversation(self) -> str:
        """保存对话记录和图谱状态"""
        results_dir = "results/conversations"
        os.makedirs(results_dir, exist_ok=True)

        # 保存对话
        output_file = os.path.join(results_dir, f"planner_{self.session_id}.txt")
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(f"=== Planner Interview - Session {self.session_id} ===\n\n")
            for msg in self.conversation_history:
                role_label = {"system": "系统", "user": "受访者", "assistant": "访谈者"}.get(msg['role'], msg['role'])
                f.write(f"[{role_label}]: {msg['content']}\n\n")

        # 保存图谱状态
        self.graph_manager.save_checkpoint(self.session_id)

        logger.info(f"对话记录已保存到: {output_file}")
        return output_file


# 同步包装器（用于Flask同步上下文）
class PlannerInterviewAgentSync:
    """PlannerInterviewAgent的同步包装器，便于在Flask中使用"""

    def __init__(self, session_id: str = None):
        self.async_agent = PlannerInterviewAgent(session_id)
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

    def initialize_conversation(self, elder_info: Dict[str, Any]):
        """同步初始化"""
        self.async_agent.initialize_conversation(elder_info)

    def get_next_question(self, user_response: str = None) -> Dict[str, Any]:
        """同步获取下一个问题"""
        return self.loop.run_until_complete(
            self.async_agent.get_next_question(user_response)
        )

    def get_graph_state(self) -> Dict[str, Any]:
        """同步获取图谱状态"""
        return self.async_agent.get_graph_state()

    def save_conversation(self) -> str:
        """同步保存对话"""
        return self.async_agent.save_conversation()

    def close(self):
        """关闭事件循环"""
        self.loop.close()


if __name__ == "__main__":
    # 测试代码
    agent = PlannerInterviewAgentSync()

    elder_info = {
        "name": "王淑芬",
        "birth_year": 1942,
        "hometown": "四川成都",
        "background": "出生于1942年，四川成都人，曾是纺织厂工人，经历过文革和改革开放，育有三个子女"
    }

    agent.initialize_conversation(elder_info)

    # 第一轮
    result = agent.get_next_question()
    print(f"访谈者: {result['question']}")

    # 模拟回复
    result = agent.get_next_question("我小时候家里很穷，父母都是工人...")
    print(f"\n提取到 {len(result['extracted_events'])} 个事件")
    print(f"当前覆盖率: {result['current_graph_state']['coverage_metrics']['overall_coverage']:.2%}")
