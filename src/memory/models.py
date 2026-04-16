# 增强的节点数据模型 - 支持详细属性
# 为每种实体类型定义具体的属性结构

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import List, Dict, Any, Optional
import uuid


# ========================================
# 基础节点模型
# ========================================

@dataclass
class EnhancedGraphNode:
    """增强的图节点 - 包含丰富的细节信息"""
    
    id: str
    type: str  # Event, Person, Location, Emotion, Time_Period, Topic, Object, etc.
    name: str
    description: str
    
    # ====== 核心元数据 ======
    confidence: float = 0.8  # 信息置信度 (0-1)
    source_type: str = "extraction"  # extraction, manual_input, inference
    source_interview_id: str = ""
    source_turn: int = 0
    
    # ====== 时间戳 ======
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    first_mentioned: str = field(default_factory=lambda: datetime.now().isoformat())
    last_updated: str = field(default_factory=lambda: datetime.now().isoformat())
    
    # ====== 使用统计 ======
    mention_count: int = 1  # 被提及次数
    reference_count: int = 0  # 被引用次数
    
    # ====== 通用属性 ======
    tags: List[str] = field(default_factory=list)  # 标签集合
    attributes: Dict[str, Any] = field(default_factory=dict)  # 扩展属性
    
    # ====== 链接和元数据 ======
    parent_entity_id: Optional[str] = None  # 父实体（如果适用）
    related_entity_ids: List[str] = field(default_factory=list)  # 相关实体
    
    # ====== 质量指标 ======
    is_conflicted: bool = False  # 是否存在冲突信息
    conflict_notes: str = ""  # 冲突说明
    is_verified: bool = False  # 是否已验证
    verification_notes: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)


# ========================================
# 特定实体类型的详细模型
# ========================================

@dataclass
class EventNode(EnhancedGraphNode):
    """事件节点 - 包含完整的时间、地点、参与者数据"""
    
    type: str = field(default="Event", init=False)
    
    # ====== 事件专属属性 ======
    event_category: str = ""  # childhood, career, family, education etc.
    
    # 时间信息
    time_frame: str = ""  # "1960-1966", "1980s", "December 1995" etc.
    time_precision: str = "approximate"  # exact, approximate, range, decade
    duration: Optional[str] = None  # "2 years", "one day" etc.
    
    # 地点信息
    locations: List[str] = field(default_factory=list)  # 相关地点ID列表
    primary_location: str = ""  # 主要发生地
    
    # 参与者
    participants: List[str] = field(default_factory=list)  # 人物ID列表
    primary_actor: str = ""  # 主要参与者
    
    # 情感和意义
    emotional_tone: List[str] = field(default_factory=list)  # joy, sadness, nostalgia等
    significance_level: str = "medium"  # low, medium, high, critical
    significance_reason: str = ""  # 为什么重要
    
    # 细节信息
    detailed_description: str = ""  # 更详细的叙述
    key_details: Dict[str, Any] = field(default_factory=dict)  # {detail_name: detail_value}
    
    # 事件关系
    is_elaboration_of: Optional[str] = None  # 是对某个事件的补充
    has_elaborations: List[str] = field(default_factory=list)  # 有哪些补充
    contradicts: List[str] = field(default_factory=list)  # 与哪些事件矛盾
    
    # 上下文
    trigger_event: Optional[str] = None  # 触发这个事件的原因
    consequence_events: List[str] = field(default_factory=list)  # 导致的后果事件


@dataclass
class PersonNode(EnhancedGraphNode):
    """人物节点 - 包含人物特征、关系(network)、角色信息"""
    
    type: str = field(default="Person", init=False)
    
    # ====== 基本信息 ======
    gender: Optional[str] = None  # male, female, unknown
    age_mentioned: Optional[str] = None  # "around 70", "70s" etc.
    age_at_event: Optional[Dict[str, int]] = None  # {event_id: age}
    
    # ====== 角色和关系 ======
    role_in_story: str = ""  # friend, family, colleague, stranger等
    relationship_to_elder: str = ""  # 与受访者的关系描述
    relationship_duration: Optional[str] = None  # "childhood friend", "worked together for 10 years"
    
    # ====== 性格特征 ======
    traits: List[str] = field(default_factory=list)  # kind, hardworking, intelligent等
    role_characteristics: Dict[str, str] = field(default_factory=dict)  # {characteristic: description}
    
    # ====== 人物关系网络 ======
    knows_people: List[str] = field(default_factory=list)  # 认识的人物ID
    family_relations: Dict[str, List[str]] = field(default_factory=dict)  # {relation_type: [person_ids]}
    professional_relations: Dict[str, List[str]] = field(default_factory=dict)  # {relation_type: [person_ids]}
    social_connections: Dict[str, Any] = field(default_factory=dict)  # 其他社交連結
    
    # ====== 人物历史 ======
    locations_lived: List[str] = field(default_factory=list)  # 住过的地方
    occupations: List[str] = field(default_factory=list)  # 职业（可能有多个）
    education_level: Optional[str] = None  # 教育程度
    
    # ====== 故事片段 ======
    memorable_stories: List[Dict[str, str]] = field(default_factory=list)  # [{title, brief_description}]
    key_quotes: List[Dict[str, str]] = field(default_factory=list)  # [{quote, context}]
    
    # ====== 联系和现况 ======
    current_status: Optional[str] = None  # alive, deceased, unknown
    last_contact: Optional[str] = None  # "5 years ago", "still in touch" etc.
    contact_info_type: Optional[str] = None  # phone, address, social_media等
    
    # ====== 提及情况 ======
    first_mentioned_in_turn: int = 0  # 首次提及的轮次
    mention_sentiment: str = "neutral"  # positive, negative, mixed, neutral


@dataclass  
class LocationNode(EnhancedGraphNode):
    """地点节点 - 包含地理、文化、时间层面的信息"""
    
    type: str = field(default="Location", init=False)
    
    # ====== 地理信息 ======
    location_type: str = ""  # province, city, town, village, building, room等
    country: str = ""  # 国家
    administrative_division: Optional[str] = None  # 行政区划 (如果适用)
    coordinates: Optional[Dict[str, float]] = None  # {latitude, longitude}
    
    # ====== 时间层面 ======
    time_periods_lived: List[str] = field(default_factory=list)  # 长者在这里生活的时期
    era_descriptions: List[str] = field(default_factory=list)  # "during 1960s", "war time"等
    
    # ====== 特征和意义 ======
    characteristics: List[str] = field(default_factory=list)  # rural, urban, poor, developed等
    cultural_significance: str = ""  # 文化意义
    emotional_significance: str = ""  # 情感意义 (nostalgia, hardship等)
    
    # ====== 地点内容 ======
    landmark_features: Dict[str, str] = field(default_factory=dict)  # {feature_name: description}
    notable_places: List[str] = field(default_factory=list)  # 著名地点（这个地方里的小地点）
    community_members: List[str] = field(default_factory=list)  # 认识的该地居民
    
    # ====== 生活经历 ======
    life_events_here: List[str] = field(default_factory=list)  # 在这里发生的事件ID
    daily_activities: List[str] = field(default_factory=list)  # 日常活动描述
    hardships_or_joys: List[Dict[str, str]] = field(default_factory=list)  # [{type: "hardship/joy", description}]
    
    # ====== 往来 ======
    frequency_of_visits: str = ""  # "daily", "weekly", "occasionally"等
    last_visit: Optional[str] = None  # "10 years ago", "never left"等
    still_connected: bool = False  # 现在是否还与这个地方有联系


@dataclass
class EmotionNode(EnhancedGraphNode):
    """情感节点 - 包含情感的具体表现、强度、持续时间"""
    
    type: str = field(default="Emotion", init=False)
    
    # ====== 情感分类 ======
    emotion_category: str = ""  # joy, sadness, love, regret, nostalgia, gratitude等
    emotion_subcategory: Optional[str] = None  # 更细致的分类
    valence: str = "neutral"  # positive, negative, neutral
    
    # ====== 强度和时间 ======
    intensity: float = 0.5  # 强度 (0-1)
    persistence: str = "temporary"  # temporary, persistent, cyclical
    duration_description: str = ""  # "throughout the period", "occasional"
    
    # ====== 触发和表现 ======
    triggered_by: List[str] = field(default_factory=list)  # 触发这个情感的实体ID
    present_in_events: List[str] = field(default_factory=list)  # 在哪些事件中表现
    manifest_behaviors: List[str] = field(default_factory=list)  # 表现行为 ("cried", "laughed"等)
    
    # ====== 变化 ======
    emotion_arc: Optional[str] = None  # 情感弧线描述
    evolution_description: str = ""  # 随时间的变化
    related_emotions: List[str] = field(default_factory=list)  # 相关情感ID
    contrasting_emotions: List[str] = field(default_factory=list)  # 对比情感ID


@dataclass
class TopicNode(EnhancedGraphNode):
    """话题/主题节点 - 访谈中反复出现的主题"""
    
    type: str = field(default="Topic", init=False)
    
    # ====== 话题分类 ======
    topic_category: str = ""  # education, family, work, relationships, culture等
    topic_priority: str = "medium"  # high, medium, low
    
    # ====== 核心观点 ======
    core_message: str = ""  # 这个话题的核心信息
    key_beliefs: List[str] = field(default_factory=list)  # 相关的信念
    values_expressed: List[str] = field(default_factory=list)  # 表达的价值观
    
    # ====== 频率和覆盖 ======
    frequency_across_interviews: int = 0  # 在多少场访谈中出现
    times_mentioned: int = 1  # 总共被提及多少次
    turns_mentioned: List[int] = field(default_factory=list)  # 在哪些轮次提及
    
    # ====== 关联 ======
    related_events: List[str] = field(default_factory=list)  # 支撑这个话题的事件
    related_people: List[str] = field(default_factory=list)  # 相关的人物
    related_locations: List[str] = field(default_factory=list)  # 相关的地点
    related_emotions: List[str] = field(default_factory=list)  # 相关的情感
    related_topics: List[str] = field(default_factory=list)  # 相关的话题
    
    # ====== 深度洞察 ======
    underlying_themes: List[str] = field(default_factory=list)  # 潜在主题
    impact_or_influence: str = ""  # 这个话题的影响
    evolution_of_perspective: str = ""  # 观点的演变


@dataclass
class InsightNode(EnhancedGraphNode):
    """洞察/模式节点 - AI提取的高级发现"""
    
    type: str = field(default="Insight", init=False)
    
    # ====== 洞察分类 ======
    insight_type: str = ""  # pattern, contradiction, elaboration, theme, value, behavior等
    insight_category: str = ""  # behavioral, emotional, relational, temporal等
    
    # ====== 核心内容 ======
    title: str = ""  # 洞察标题
    detailed_description: str = ""  # 详细解释
    evidence_level: str = "medium"  # weak, medium, strong
    inference_chain: List[str] = field(default_factory=list)  # 推理链条
    
    # ====== 支持证据 ======
    supporting_events: List[str] = field(default_factory=list)  # 支持的事件ID
    supporting_quotes: List[Dict[str, str]] = field(default_factory=list)  # [{quote, turn_number}]
    contradicting_examples: List[str] = field(default_factory=list)  # 矛盾例子
    
    # ====== 验证 ======
    confidence_score: float = 0.7  # 置信度
    validation_status: str = "unverified"  # unverified, pending, confirmed, rejected
    validator_notes: str = ""  # 验证者笔记
    
    # ====== 影响 ======
    significance: str = "medium"  # low, medium, high
    implications: List[str] = field(default_factory=list)  # 含义
    relevant_for_future_questions: bool = False  # 对后续提问是否相关


# ========================================
# 辅助函数
# ========================================

def create_event_node(
    name: str,
    description: str,
    category: str = "",
    locations: List[str] = None,
    participants: List[str] = None,
    emotional_tone: List[str] = None,
    **kwargs
) -> EventNode:
    """快速创建事件节点"""
    
    return EventNode(
        id=f"evt_{uuid.uuid4().hex[:8]}",
        name=name,
        description=description,
        event_category=category,
        locations=locations or [],
        participants=participants or [],
        emotional_tone=emotional_tone or [],
        source_interview_id=kwargs.get("interview_id", ""),
        source_turn=kwargs.get("turn", 0),
        **{k: v for k, v in kwargs.items() if k not in ["interview_id", "turn"]}
    )


def create_person_node(
    name: str,
    description: str,
    role: str = "",
    relationship: str = "",
    traits: List[str] = None,
    **kwargs
) -> PersonNode:
    """快速创建人物节点"""
    
    return PersonNode(
        id=f"person_{uuid.uuid4().hex[:8]}",
        name=name,
        description=description,
        role_in_story=role,
        relationship_to_elder=relationship,
        traits=traits or [],
        source_interview_id=kwargs.get("interview_id", ""),
        source_turn=kwargs.get("turn", 0),
        **{k: v for k, v in kwargs.items() if k not in ["interview_id", "turn"]}
    )


def create_location_node(
    name: str,
    description: str,
    location_type: str = "",
    characteristics: List[str] = None,
    **kwargs
) -> LocationNode:
    """快速创建地点节点"""
    
    return LocationNode(
        id=f"loc_{uuid.uuid4().hex[:8]}",
        name=name,
        description=description,
        location_type=location_type,
        characteristics=characteristics or [],
        source_interview_id=kwargs.get("interview_id", ""),
        source_turn=kwargs.get("turn", 0),
        **{k: v for k, v in kwargs.items() if k not in ["interview_id", "turn"]}
    )


# ========================================
# 示例：如何使用丰富的节点模型
# ========================================

def example_rich_node_creation():
    """演示如何创建信息丰富的节点"""
    
    # 创建一个详细的事件节点
    event = EventNode(
        id="evt_childhood_001",
        name="山东河边的童年记忆",
        description="长者回忆在山东河边与朋友玩耍的时光",
        event_category="childhood",
        time_frame="1950-1955",
        time_precision="approximate",
        primary_location="loc_shandong",
        locations=["loc_shandong", "loc_river"],
        participants=["person_xiaoming", "elder_subject"],
        primary_actor="person_xiaoming",
        emotional_tone=["nostalgia", "joy", "fondness"],
        significance_level="high",
        significance_reason="塑造了长者对友谊和自由的理解",
        key_details={
            "frequency": "经常去",
            "activities": ["swimming", "playing", "talking"],
            "conditions": "穷困但快乐"
        },
        detailed_description="""
        那时候我们家很穷，但小明和我经常一起去河边玩。
        我们会游泳、捉鱼、讲故事。虽然物质条件差，
        但那时的友谊和快乐没有金钱能买到。
        """,
        mention_count=3,  # 被提及3次
        is_verified=True,
        confidence=0.95
    )
    
    # 创建一个详细的人物节点
    person = PersonNode(
        id="person_xiaoming",
        name="小明",
        description="长者的童年好友，后来一起去了北京工作",
        role_in_story="childhood_friend_and_colleague",
        relationship_to_elder="lifelong friend",
        relationship_duration="60+ years",
        gender="male",
        traits=["intelligent", "kind-hearted", "ambitious"],
        knows_people=["person_zhangsan"],  # 长者的ID
        professional_relations={
            "colleague": ["person_company_director"],
            "coworker": ["person_colleague_1", "person_colleague_2"]
        },
        occupations=["engineer", "project_manager"],
        current_status="alive",
        last_contact="still in touch",
        memorable_stories=[
            {
                "title": "河边的故事",
                "brief": "在河边遇险，小明救了我"
            }
        ]
    )
    
    # 创建一个详细的地点节点
    location = LocationNode(
        id="loc_shandong",
        name="山东",
        description="长者的故乡，充满美好的童年记忆",
        location_type="province",
        country="China",
        administrative_division="Shandong",
        era_descriptions=["1950s rural China", "pre-industrial era"],
        characteristics=["rural", "poor", "tight-knit community"],
        cultural_significance="agricultural heartland of northern China",
        emotional_significance="nostalgia and longing for simplicity",
        life_events_here=[
            "evt_childhood_001",
            "evt_education",
            "evt_family_life"
        ],
        daily_activities=[
            "farming with father",
            "school attendance",
            "playing by the river"
        ],
        frequency_of_visits="rarely (moved away in 1966)",
        still_connected=True,
        hardships_or_joys=[
            {"type": "hardship", "description": "extreme poverty"},
            {"type": "hardship", "description": "limited education opportunities"},
            {"type": "joy", "description": "strong community bonds"},
            {"type": "joy", "description": "natural beauty"}
        ]
    )
    
    return event, person, location


if __name__ == "__main__":
    print("增强的图节点数据模型演示\n")
    
    event, person, location = example_rich_node_creation()
    
    print("事件节点示例:")
    print(f"  {event.name}")
    print(f"  类别: {event.event_category}")
    print(f"  情感: {event.emotional_tone}")
    print(f"  重要程度: {event.significance_level}\n")
    
    print("人物节点示例:")
    print(f"  {person.name}")
    print(f"  角色: {person.role_in_story}")
    print(f"  特征: {person.traits}")
    print(f"  提及次数: {person.mention_count}\n")
    
    print("地点节点示例:")
    print(f"  {location.name}")
    print(f"  类型: {location.location_type}")
    print(f"  特征: {location.characteristics}")
    print(f"  感情意义: {location.emotional_significance}")
