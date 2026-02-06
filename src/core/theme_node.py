"""
主题节点数据模型

定义 ThemeNode 类，表示 McAdams 23 个主题中的一个主题节点。
这些节点作为事件图谱中的"虚线节点"（预设大纲）。
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Any, Optional

from .node_status import NodeStatus, Domain


@dataclass
class ThemeNode:
    """
    主题节点数据模型

    表示 McAdams 23 个主题中的一个主题节点，作为事件图谱中的"虚线节点"。

    Attributes:
        theme_id: 主题ID，如 "THEME_01_LIFE_CHAPTERS"
        domain: 所属领域
        title: 主题标题
        description: 主题描述
        seed_questions: 种子问题列表
        current_question_index: 当前使用的种子问题索引
        status: 节点状态 (PENDING/MENTIONED/EXHAUSTED)
        exploration_depth: 挖掘深度 (0-5)
        slots_filled: 槽位填充情况
        extracted_events: 从该主题提取的事件ID列表
        trigger_logic: 触发条件配置
        priority: 优先级 (1-10, 1最高)
        depends_on: 依赖的其他主题ID
        created_at: 创建时间
        first_mentioned_at: 首次提及时间
        exhausted_at: 完成时间
        metadata: 元数据
    """

    # 基础标识
    theme_id: str
    domain: Domain
    title: str
    description: str

    # 种子问题
    seed_questions: List[str] = field(default_factory=list)
    current_question_index: int = 0

    # 状态管理
    status: NodeStatus = NodeStatus.PENDING

    # 挖掘追踪
    exploration_depth: int = 0
    slots_filled: Dict[str, bool] = field(default_factory=dict)
    extracted_events: List[str] = field(default_factory=list)

    # 触发逻辑
    trigger_logic: Optional[Dict[str, Any]] = None
    priority: int = 5
    depends_on: List[str] = field(default_factory=list)

    # 时间追踪
    created_at: datetime = field(default_factory=datetime.now)
    first_mentioned_at: Optional[datetime] = None
    exhausted_at: Optional[datetime] = None

    # 元数据
    metadata: Dict[str, Any] = field(default_factory=dict)

    def mark_mentioned(self) -> None:
        """标记为已提及状态"""
        if self.status == NodeStatus.PENDING:
            self.status = NodeStatus.MENTIONED
            self.first_mentioned_at = datetime.now()

    def mark_exhausted(self) -> None:
        """标记为已挖透状态"""
        self.status = NodeStatus.EXHAUSTED
        self.exhausted_at = datetime.now()

    def get_completion_ratio(self) -> float:
        """
        计算主题完成度

        Returns:
            float: 0.0 - 1.0 之间的完成度
        """
        if not self.slots_filled:
            # 如果没有定义槽位，基于深度计算
            return min(self.exploration_depth / 5.0, 1.0)

        # 检查是否有已填充的槽位
        filled_count = sum(1 for v in self.slots_filled.values() if v)
        total_count = len(self.slots_filled)

        # 如果有已填充的槽位，使用槽位填充率
        if filled_count > 0:
            return filled_count / total_count

        # 如果所有槽位都未填充，回退到使用深度计算
        return min(self.exploration_depth / 5.0, 1.0)

    def is_ready_to_explore(self, graph_state: Optional[Dict[str, 'ThemeNode']] = None) -> bool:
        """
        判断主题是否准备好被探索

        检查依赖的主题是否已完成。

        Args:
            graph_state: 图谱中所有主题的状态，用于检查依赖

        Returns:
            bool: 如果依赖满足返回 True
        """
        if not self.depends_on:
            return True

        if graph_state is None:
            return False

        return all(
            dep_id in graph_state and
            graph_state[dep_id].status == NodeStatus.EXHAUSTED
            for dep_id in self.depends_on
        )

    def get_next_seed_question(self) -> Optional[str]:
        """
        获取下一个种子问题

        Returns:
            下一个种子问题，如果没有则返回 None
        """
        if 0 <= self.current_question_index < len(self.seed_questions):
            question = self.seed_questions[self.current_question_index]
            self.current_question_index += 1
            return question
        return None

    def reset_question_index(self) -> None:
        """重置种子问题索引"""
        self.current_question_index = 0

    def has_more_questions(self) -> bool:
        """是否还有更多种子问题"""
        return self.current_question_index < len(self.seed_questions)

    def increment_depth(self) -> None:
        """增加挖掘深度"""
        self.exploration_depth = min(self.exploration_depth + 1, 5)

    def update_slot(self, slot_name: str, filled: bool = True) -> None:
        """
        更新槽位填充状态

        Args:
            slot_name: 槽位名称
            filled: 是否已填充
        """
        self.slots_filled[slot_name] = filled

    def add_extracted_event(self, event_id: str) -> None:
        """
        添加从该主题提取的事件

        Args:
            event_id: 事件ID
        """
        if event_id not in self.extracted_events:
            self.extracted_events.append(event_id)

    def to_dict(self) -> Dict[str, Any]:
        """
        序列化为字典

        Returns:
            包含节点所有关键信息的字典
        """
        return {
            "theme_id": self.theme_id,
            "domain": self.domain.value,
            "title": self.title,
            "description": self.description,
            "seed_questions": self.seed_questions,
            "status": self.status.value,
            "exploration_depth": self.exploration_depth,
            "slots_filled": self.slots_filled,
            "extracted_events_count": len(self.extracted_events),
            "priority": self.priority,
            "depends_on": self.depends_on,
            "completion_ratio": self.get_completion_ratio(),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "first_mentioned_at": self.first_mentioned_at.isoformat() if self.first_mentioned_at else None,
            "exhausted_at": self.exhausted_at.isoformat() if self.exhausted_at else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ThemeNode':
        """
        从字典创建 ThemeNode 实例

        Args:
            data: 包含节点信息的字典

        Returns:
            ThemeNode 实例
        """
        # 处理 Domain 枚举
        domain = Domain(data["domain"]) if isinstance(data.get("domain"), str) else data.get("domain")

        # 处理 NodeStatus 枚举
        status = NodeStatus(data["status"]) if isinstance(data.get("status"), str) else data.get("status", NodeStatus.PENDING)

        # 处理时间字段
        created_at = datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now()
        first_mentioned_at = datetime.fromisoformat(data["first_mentioned_at"]) if data.get("first_mentioned_at") else None
        exhausted_at = datetime.fromisoformat(data["exhausted_at"]) if data.get("exhausted_at") else None

        node = cls(
            theme_id=data["theme_id"],
            domain=domain,
            title=data["title"],
            description=data["description"],
            seed_questions=data.get("seed_questions", []),
            status=status,
            exploration_depth=data.get("exploration_depth", 0),
            slots_filled=data.get("slots_filled", {}),
            priority=data.get("priority", 5),
            depends_on=data.get("depends_on", []),
            trigger_logic=data.get("trigger_logic"),
            created_at=created_at,
            first_mentioned_at=first_mentioned_at,
            exhausted_at=exhausted_at,
            metadata=data.get("metadata", {}),
        )

        # 恢复事件列表
        extracted_events = data.get("extracted_events", [])
        if extracted_events:
            node.extracted_events = extracted_events

        return node

    def __repr__(self) -> str:
        return (f"ThemeNode(id={self.theme_id}, title={self.title}, "
                f"status={self.status.value}, completion={self.get_completion_ratio():.2f})")
