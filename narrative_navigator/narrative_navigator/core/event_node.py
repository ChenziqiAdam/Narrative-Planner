"""
事件节点数据模型

定义 EventNode 类，表示从对话中提取的具体事件。
事件节点关联到某个 ThemeNode，是实际收集到的内容。
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Any, Optional
import uuid


@dataclass
class EventNode:
    """
    事件节点数据模型

    表示从对话中提取的具体事件，关联到某个 ThemeNode。

    Attributes:
        event_id: 事件唯一ID
        theme_id: 关联的主题ID
        title: 事件标题
        description: 事件详细描述
        time_anchor: 时间锚点（如"1992年冬天"）
        location: 地点
        people_involved: 涉及的人物列表
        slots: 槽位（叙事完整度）
        emotional_score: 情绪能量 (-1.0 到 1.0)
        information_density: 信息密度 (0.0 到 1.0)
        depth_level: 挖掘深度等级 (0-5)
        related_events: 关联的事件ID列表
        created_at: 创建时间
    """

    # 基础标识
    event_id: str
    theme_id: str

    # 事件内容
    title: str
    description: str

    # 时间与地点
    time_anchor: Optional[str] = None
    location: Optional[str] = None

    # 人物
    people_involved: List[str] = field(default_factory=list)

    # 槽位（叙事完整度）
    # 预定义槽位：time, location, people, cause, result, emotion, reflection
    slots: Dict[str, Optional[str]] = field(default_factory=dict)

    # 情感与分析
    emotional_score: float = 0.0     # 情绪能量 (-1.0 到 1.0)
    information_density: float = 0.0  # 信息密度 (0.0 到 1.0)

    # 状态
    depth_level: int = 0              # 挖掘深度等级 (0-5)

    # 关联
    related_events: List[str] = field(default_factory=list)

    # 时间
    created_at: datetime = field(default_factory=datetime.now)

    def __post_init__(self):
        """初始化后处理"""
        if not self.event_id:
            self.event_id = f"evt_{uuid.uuid4().hex[:12]}"

        # 初始化槽位
        if not self.slots:
            self.slots = {
                "time": None,
                "location": None,
                "people": None,
                "cause": None,
                "result": None,
                "emotion": None,
                "reflection": None,
            }

    def get_slot_completion_ratio(self) -> float:
        """
        计算槽位填充率

        Returns:
            float: 0.0 - 1.0 之间的槽位填充率
        """
        if not self.slots:
            return 0.0

        filled = sum(1 for v in self.slots.values() if v)
        return filled / len(self.slots)

    def update_slot(self, slot_name: str, value: Any) -> None:
        """
        更新槽位值

        Args:
            slot_name: 槽位名称
            value: 槽位值
        """
        if slot_name in self.slots:
            self.slots[slot_name] = str(value) if value is not None else None
        else:
            self.slots[slot_name] = str(value) if value is not None else None

    def add_person(self, person_name: str) -> None:
        """
        添加涉及的人物

        Args:
            person_name: 人物姓名
        """
        if person_name and person_name not in self.people_involved:
            self.people_involved.append(person_name)

    def increment_depth(self) -> None:
        """增加挖掘深度"""
        self.depth_level = min(self.depth_level + 1, 5)

    def is_exhausted(self) -> bool:
        """
        判断事件是否已挖透

        Returns:
            bool: 如果深度>=4且槽位填充率>=0.8返回True
        """
        return self.depth_level >= 4 or self.get_slot_completion_ratio() >= 0.8

    def add_related_event(self, event_id: str) -> None:
        """
        添加关联事件

        Args:
            event_id: 关联事件的ID
        """
        if event_id not in self.related_events:
            self.related_events.append(event_id)

    def to_dict(self) -> Dict[str, Any]:
        """
        序列化为字典

        Returns:
            包含事件所有关键信息的字典
        """
        return {
            "event_id": self.event_id,
            "theme_id": self.theme_id,
            "title": self.title,
            "description": self.description,
            "time_anchor": self.time_anchor,
            "location": self.location,
            "people_involved": self.people_involved,
            "slots": self.slots,
            "emotional_score": self.emotional_score,
            "information_density": self.information_density,
            "depth_level": self.depth_level,
            "slot_completion_ratio": self.get_slot_completion_ratio(),
            "related_events": self.related_events,
            "is_exhausted": self.is_exhausted(),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'EventNode':
        """
        从字典创建 EventNode 实例

        Args:
            data: 包含事件信息的字典

        Returns:
            EventNode 实例
        """
        created_at = datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now()

        return cls(
            event_id=data["event_id"],
            theme_id=data["theme_id"],
            title=data["title"],
            description=data["description"],
            time_anchor=data.get("time_anchor"),
            location=data.get("location"),
            people_involved=data.get("people_involved", []),
            slots=data.get("slots", {}),
            emotional_score=data.get("emotional_score", 0.0),
            information_density=data.get("information_density", 0.0),
            depth_level=data.get("depth_level", 0),
            related_events=data.get("related_events", []),
            created_at=created_at,
        )

    def __repr__(self) -> str:
        return (f"EventNode(id={self.event_id}, title={self.title}, "
                f"depth={self.depth_level}, completion={self.get_slot_completion_ratio():.2f})")
