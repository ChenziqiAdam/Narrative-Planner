"""
动态事件图谱 - 核心接口定义

本模块定义了动态事件图谱系统的核心接口和数据结构。
遵循接口隔离原则，便于后续扩展和替换实现。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, AsyncIterator, Callable
from datetime import datetime
from enum import Enum


class NodeStatus(Enum):
    """节点状态枚举"""
    PENDING = "pending"      # 预设待触达（虚线节点）
    MENTIONED = "mentioned"  # 已提及未展开（虚线节点）
    EXHAUSTED = "exhausted"  # 已挖透（实线节点）


class ExtractionStrategy(Enum):
    """事件提取策略"""
    EVERY_TURN = "every_turn"      # 每轮都提取
    ADAPTIVE = "adaptive"          # 自适应（根据队列情况）
    EVERY_N_TURNS = "every_n_turns" # 每N轮提取一次


@dataclass
class EventSlots:
    """
    事件6核心槽位 + 3扩展槽位

    核心槽位：时间、地点、人物、事件、感受、未展开线索
    扩展槽位：起因、结果、反思
    """
    # 核心槽位（6层）
    time: Optional[str] = None           # 时间（如：1960年春天、我8岁那年）
    location: Optional[str] = None       # 地点（如：成都纺织厂、老家院子）
    people: Optional[List[str]] = None   # 涉及人物（如：["母亲", "王师傅"]）
    event: Optional[str] = None          # 事件描述（必填）
    feeling: Optional[str] = None        # 感受（如：很难过、特别自豪）
    unexpanded_clues: Optional[str] = None  # 未展开线索（如：老王具体如何帮忙的细节）

    # 扩展槽位
    cause: Optional[str] = None          # 起因
    result: Optional[str] = None         # 结果
    reflection: Optional[str] = None     # 反思

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（排除None值）"""
        return {k: v for k, v in self.__dict__.items() if v is not None}

    @property
    def core_filled(self) -> int:
        """核心槽位已填充数量"""
        core_fields = [self.time, self.location, self.people, self.event, self.feeling, self.unexpanded_clues]
        return sum(1 for f in core_fields if f is not None and f != [])

    @property
    def core_completion_rate(self) -> float:
        """核心槽位完成率"""
        return self.core_filled / 6.0


@dataclass
class ExtractedEvent:
    """提取的事件数据"""
    event_id: str
    extracted_at: datetime
    slots: EventSlots

    # 元数据
    confidence: float = 0.0                # 提取置信度 0-1
    theme_id: Optional[str] = None         # 关联的McAdams主题
    source_turns: List[str] = field(default_factory=list)  # 来源轮次ID

    # 增量更新相关
    is_update: bool = False                # 是否是对已有事件的更新
    updated_event_id: Optional[str] = None # 如更新，填写原事件ID

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "event_id": self.event_id,
            "extracted_at": self.extracted_at.isoformat(),
            "slots": self.slots.to_dict(),
            "confidence": self.confidence,
            "theme_id": self.theme_id,
            "source_turns": self.source_turns,
            "is_update": self.is_update,
            "updated_event_id": self.updated_event_id
        }


@dataclass
class DialogueTurn:
    """单轮对话记录"""
    # 必需字段（无默认值）
    turn_id: str
    session_id: str
    timestamp: datetime
    interviewer_question: str
    interviewer_action: str  # continue|next_phase|end
    interviewee_raw_reply: str

    # 可选字段（有默认值）
    interviewer_intent: Optional[str] = None
    interviewee_emotion: Optional[str] = None
    interviewee_memories_referenced: List[str] = field(default_factory=list)
    extracted_events: List[ExtractedEvent] = field(default_factory=list)

    def __post_init__(self):
        """确保列表字段有默认值"""
        if self.interviewee_memories_referenced is None:
            self.interviewee_memories_referenced = []
        if self.extracted_events is None:
            self.extracted_events = []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "session_id": self.session_id,
            "timestamp": self.timestamp.isoformat(),
            "interviewer": {
                "question": self.interviewer_question,
                "action": self.interviewer_action,
                "intent": self.interviewer_intent
            },
            "interviewee": {
                "raw_reply": self.interviewee_raw_reply,
                "emotion": self.interviewee_emotion,
                "memories_referenced": self.interviewee_memories_referenced
            },
            "extracted_events": [e.to_dict() for e in self.extracted_events]
        }


@dataclass
class GraphUpdateEvent:
    """图谱更新事件基类"""
    update_type: str
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "update_type": self.update_type,
            "timestamp": self.timestamp.isoformat()
        }


@dataclass
class EventAddedUpdate(GraphUpdateEvent):
    """新事件添加更新"""
    event: ExtractedEvent = field(default=None)  # type: ignore
    theme_id: Optional[str] = None

    def __post_init__(self):
        self.update_type = "event_added"
        if self.event is None:
            raise ValueError("event is required")

    def to_dict(self) -> Dict[str, Any]:
        base = super().to_dict()
        base["event"] = self.event.to_dict()
        base["theme_id"] = self.theme_id
        return base


@dataclass
class EventUpdatedUpdate(GraphUpdateEvent):
    """事件更新"""
    event_id: str = ""
    updated_slots: Dict[str, Any] = field(default_factory=dict)
    new_confidence: float = 0.0

    def __post_init__(self):
        self.update_type = "event_updated"
        if not self.event_id:
            raise ValueError("event_id is required")

    def to_dict(self) -> Dict[str, Any]:
        base = super().to_dict()
        base["event_id"] = self.event_id
        base["updated_slots"] = self.updated_slots
        base["new_confidence"] = self.new_confidence
        return base


@dataclass
class ThemeStatusUpdate(GraphUpdateEvent):
    """主题状态变更"""
    theme_id: str = ""
    old_status: NodeStatus = field(default=None)  # type: ignore
    new_status: NodeStatus = field(default=None)  # type: ignore

    def __post_init__(self):
        self.update_type = "theme_status_changed"
        if not self.theme_id:
            raise ValueError("theme_id is required")
        if self.old_status is None or self.new_status is None:
            raise ValueError("old_status and new_status are required")

    def to_dict(self) -> Dict[str, Any]:
        base = super().to_dict()
        base["theme_id"] = self.theme_id
        base["old_status"] = self.old_status.value
        base["new_status"] = self.new_status.value
        return base


# ==================== 抽象接口 ====================

class IEventExtractor(ABC):
    """
    事件提取器接口

    负责从对话内容中提取结构化事件。
    实现类可以是基于LLM的提取器、规则提取器等。
    """

    @abstractmethod
    async def extract_from_turn(
        self,
        turn: DialogueTurn,
        conversation_context: List[DialogueTurn]
    ) -> List[ExtractedEvent]:
        """
        从单轮对话中提取事件

        Args:
            turn: 当前对话轮次
            conversation_context: 最近N轮对话上下文

        Returns:
            提取到的事件列表（可能为空）
        """
        pass

    @abstractmethod
    async def extract_incremental(
        self,
        new_turn: DialogueTurn,
        existing_event: ExtractedEvent,
        conversation_context: List[DialogueTurn]
    ) -> Optional[EventSlots]:
        """
        对已有事件进行增量更新

        当新对话可能补充已有事件信息时使用。

        Args:
            new_turn: 新的对话轮次
            existing_event: 已有的事件
            conversation_context: 对话上下文

        Returns:
            更新的槽位，如果没有更新则返回None
        """
        pass

    @abstractmethod
    async def find_similar_event(
        self,
        candidate: ExtractedEvent,
        existing_events: List[ExtractedEvent]
    ) -> Optional[ExtractedEvent]:
        """
        查找相似事件（用于去重）

        Args:
            candidate: 候选事件
            existing_events: 已有事件列表

        Returns:
            最相似的事件（如果相似度超过阈值），否则None
        """
        pass


class IGraphBroadcaster(ABC):
    """
    图谱状态广播器接口

    负责将图谱状态变更广播给所有连接的客户端。
    实现类可以是WebSocket广播器、SSE广播器等。
    """

    @abstractmethod
    async def connect(self, session_id: str, client_id: str) -> None:
        """客户端连接"""
        pass

    @abstractmethod
    async def disconnect(self, session_id: str, client_id: str) -> None:
        """客户端断开"""
        pass

    @abstractmethod
    async def broadcast_event_added(
        self,
        session_id: str,
        event: ExtractedEvent,
        theme_id: Optional[str] = None
    ) -> None:
        """广播新事件添加"""
        pass

    @abstractmethod
    async def broadcast_event_updated(
        self,
        session_id: str,
        event_id: str,
        updated_slots: Dict[str, Any]
    ) -> None:
        """广播事件更新"""
        pass

    @abstractmethod
    async def broadcast_theme_status_changed(
        self,
        session_id: str,
        theme_id: str,
        old_status: NodeStatus,
        new_status: NodeStatus
    ) -> None:
        """广播主题状态变更"""
        pass

    @abstractmethod
    async def broadcast_to_session(
        self,
        session_id: str,
        message: Dict[str, Any]
    ) -> int:
        """
        广播消息到指定会话的所有客户端

        Returns:
            成功发送的客户端数量
        """
        pass


class IInterviewEngine(ABC):
    """
    访谈引擎接口

    负责管理对话流程、协调事件提取和图谱更新。
    """

    @abstractmethod
    async def initialize_session(
        self,
        session_id: str,
        basic_info: str
    ) -> str:
        """
        初始化访谈会话

        Returns:
            开场问题
        """
        pass

    @abstractmethod
    async def process_user_message(
        self,
        session_id: str,
        message: str
    ) -> AsyncIterator[str]:
        """
        处理用户消息并流式返回响应

        Yields:
            响应token流
        """
        pass

    @abstractmethod
    async def get_current_graph_state(self, session_id: str) -> Dict[str, Any]:
        """获取当前图谱状态"""
        pass

    @abstractmethod
    async def save_checkpoint(self, session_id: str) -> bool:
        """保存断点"""
        pass


class IEventStorage(ABC):
    """
    事件存储接口

    负责事件的持久化存储。
    """

    @abstractmethod
    async def save_event(self, session_id: str, event: ExtractedEvent) -> bool:
        """保存事件"""
        pass

    @abstractmethod
    async def get_events(self, session_id: str) -> List[ExtractedEvent]:
        """获取会话的所有事件"""
        pass

    @abstractmethod
    async def update_event(
        self,
        session_id: str,
        event_id: str,
        slots_update: Dict[str, Any]
    ) -> bool:
        """更新事件"""
        pass
