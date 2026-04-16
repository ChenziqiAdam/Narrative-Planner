# GraphMemoryManager - 同步版本
# 使用官方同步 Neo4j 驱动，无异步复杂度

import json
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import asdict

from . import models
from .neo4j_driver_sync import Neo4jGraphDriver
from .vector_storage import VectorStore, create_vector_store


class EnhancedGraphMemoryManager:
    """
    增强的图记忆管理器，支持丰富的节点属性和 Neo4j 后端
    
    特点：
    - 同步 API（无事件循环问题）
    - 丰富的节点模型
    - 自动数据清理和序列化
    - 本地缓存和 Neo4j 后端双重支持
    """
    
    def __init__(
        self,
        neo4j_uri: str = "bolt://localhost:7687",
        neo4j_user: str = "neo4j",
        neo4j_password: str = "capstone2024",
        max_cache_size: int = 1000,
        vector_store: Optional[VectorStore] = None,
        enable_vector_dedup: bool = True
    ):
        """初始化记忆管理器
        
        Args:
            neo4j_uri: Neo4j连接URI
            neo4j_user: Neo4j用户名
            neo4j_password: Neo4j密码
            max_cache_size: 本地缓存大小
            vector_store: VectorStore实例（为None则自动创建）
            enable_vector_dedup: 是否启用向量去重功能
        """
        
        self.driver = Neo4jGraphDriver(
            uri=neo4j_uri,
            username=neo4j_user,
            password=neo4j_password
        )
        
        # 初始化向量存储（用于去重）
        self.vector_store = vector_store or create_vector_store("auto")
        self.enable_vector_dedup = enable_vector_dedup
        
        self.max_cache_size = max_cache_size
        self.node_cache: Dict[str, Any] = {}
        self._initialized = False
    
    def initialize_sync(self) -> bool:
        """同步初始化连接"""
        try:
            self.driver.connect()
            self.driver.initialize_schema()
            self._initialized = True
            print("✓ Neo4j 连接已同步初始化")
            return True
        except Exception as e:
            print(f"初始化失败: {e}")
            self._initialized = False
            return False
    
    def close(self):
        """关闭连接"""
        self.driver.close()
    
    def _sanitize_node_dict(self, node_dict: Dict[str, Any]) -> Dict[str, Any]:
        """清理节点字典，确保所有值都能被 Neo4j 序列化"""
        
        sanitized = {}
        
        for key, value in node_dict.items():
            if value is None:
                sanitized[key] = None
            elif isinstance(value, (str, int, float, bool)):
                # 基本类型，直接保留
                sanitized[key] = value
            elif isinstance(value, (list, tuple)):
                try:
                    # 列表中的基本类型可以保留
                    if all(isinstance(x, (str, int, float, bool, type(None))) for x in value):
                        sanitized[key] = list(value)
                    else:
                        # 包含复杂对象，序列化为 JSON 字符串
                        sanitized[f"{key}_json"] = json.dumps(value, default=str)
                except:
                    sanitized[f"{key}_json"] = json.dumps(value, default=str)
            elif isinstance(value, dict):
                try:
                    sanitized[key] = json.dumps(value)
                except:
                    sanitized[f"{key}_json"] = json.dumps(value, default=str)
            elif isinstance(value, datetime):
                sanitized[key] = value.isoformat()
            else:
                # 其他类型序列化为 JSON
                try:
                    sanitized[f"{key}_json"] = json.dumps(value, default=str)
                except:
                    sanitized[f"{key}_str"] = str(value)
        
        return sanitized
    
    # ===== 节点创建 =====
    
    def create_event_node(
        self,
        name: str,
        description: str,
        category: str = "general",
        locations: List[str] = None,
        participants: List[str] = None,
        emotional_tone: List[str] = None,
        time_frame: str = "",
        significance_level: str = "medium",
        interview_id: str = "",
        turn: int = 0,
        **extra_attributes
    ) -> models.EventNode:
        """创建并存储事件节点，并自动创建相关子节点和双向关系
        
        关键逻辑：
        1. 首先创建 Event 节点（临时使用名字列表）
        2. 为每个 participants/locations/emotional_tone 创建子节点
        3. 收集子节点的 ID，更新 Event 节点的对应字段
        4. 为每个子节点更新 related_entity_ids（反向链接到 Event）
        5. 最后更新 Event 节点到数据库
        """
        
        # 过滤并只传递 EventNode 支持的字段
        event_fields = {
            'time_precision', 'duration', 'primary_location', 'primary_actor',
            'detailed_description', 'key_details', 'is_elaboration_of', 'has_elaborations',
            'contradicts', 'trigger_event', 'consequence_events', 'significance_reason',
            'tags', 'attributes', 'parent_entity_id', 'related_entity_ids'
        }
        filtered_attrs = {k: v for k, v in extra_attributes.items() if k in event_fields}
        
        # 创建事件节点实例
        event = models.EventNode(
            id=f"evt_{uuid.uuid4().hex[:8]}",
            name=name,
            description=description,
            event_category=category,
            locations=[],  # 初始为空，稍后填充 ID
            participants=[],  # 初始为空，稍后填充 ID
            emotional_tone=[],  # 初始为空，稍后填充 ID
            time_frame=time_frame,
            significance_level=significance_level,
            source_interview_id=interview_id,
            source_turn=turn,
            confidence=0.8,
            **filtered_attrs
        )
        
        print(f"[MANAGER] Creating event: {event.name} (ID: {event.id})")
        
        # 步骤1：初始化存储
        node_dict = asdict(event)
        node_dict = self._sanitize_node_dict(node_dict)
        
        if self.driver:
            self.driver.insert_node(node_dict)
        
        # 步骤2：处理参与者
        created_person_ids = []
        if participants:
            print(f"[MANAGER] Creating {len(participants)} participant nodes...")
            for participant_name in participants:
                if participant_name and participant_name.strip():
                    # 创建 Person 节点，提供更详细的 description
                    person = self.create_person_node(
                        name=participant_name,
                        description=f"Participant in: [{event.name}]. {description[:100] if description else 'N/A'}",
                        role_in_story="participant",
                        interview_id=interview_id,
                        turn=turn,
                        related_entity_ids=[event.id]  # 立即建立反向链接
                    )
                    created_person_ids.append(person.id)
                    
                    # 创建 Event --INVOLVES--> Person 关系
                    if self.driver:
                        self.driver.insert_edge(
                            source_id=event.id,
                            target_id=person.id,
                            relation_type="INVOLVES",
                            properties={"role": "participant"}
                        )
                    print(f"[MANAGER]   ✓ Created INVOLVES: {event.id} -> {person.id}")
        
        # 步骤3：处理位置
        created_location_ids = []
        if locations:
            print(f"[MANAGER] Creating {len(locations)} location nodes...")
            for location_name in locations:
                if location_name and location_name.strip():
                    # 创建 Location 节点
                    location = self.create_location_node(
                        name=location_name,
                        description=f"Location where: [{event.name}] occurred. {description[:100] if description else 'N/A'}",
                        location_type="event_location",
                        related_entity_ids=[event.id]  # 立即建立反向链接
                    )
                    created_location_ids.append(location.id)
                    
                    # 创建 Event --OCCURS_AT--> Location 关系
                    if self.driver:
                        self.driver.insert_edge(
                            source_id=event.id,
                            target_id=location.id,
                            relation_type="OCCURS_AT",
                            properties={"role": "primary_location"}
                        )
                    print(f"[MANAGER]   ✓ Created OCCURS_AT: {event.id} -> {location.id}")
        
        # 步骤4：处理情感
        created_emotion_ids = []
        if emotional_tone:
            print(f"[MANAGER] Creating {len(emotional_tone)} emotion nodes...")
            for emotion_name in emotional_tone:
                if emotion_name and emotion_name.strip():
                    # 创建 Emotion 节点
                    emotion = self.create_emotion_node(
                        name=emotion_name,
                        description=f"Emotional context in: [{event.name}]. {description[:100] if description else 'N/A'}",
                        emotion_category=emotion_name,
                        intensity=0.7,
                        triggered_by=[event.id],  # 情感由该事件触发
                        interview_id=interview_id,
                        related_entity_ids=[event.id]  # 立即建立反向链接
                    )
                    created_emotion_ids.append(emotion.id)
                    
                    # 创建 Event --HAS_EMOTIONAL_TONE--> Emotion 关系
                    if self.driver:
                        self.driver.insert_edge(
                            source_id=event.id,
                            target_id=emotion.id,
                            relation_type="HAS_EMOTIONAL_TONE",
                            properties={"intensity": "medium"}
                        )
                    print(f"[MANAGER]   ✓ Created HAS_EMOTIONAL_TONE: {event.id} -> {emotion.id}")
        
        # 步骤5：更新 Event 节点的 ID 列表
        event.participants = created_person_ids
        event.locations = created_location_ids
        event.emotional_tone = created_emotion_ids
        event.related_entity_ids = created_person_ids + created_location_ids + created_emotion_ids
        
        # 步骤6：将更新后的 Event 节点再次保存到数据库
        node_dict = asdict(event)
        node_dict = self._sanitize_node_dict(node_dict)
        
        if self.driver:
            self.driver.insert_node(node_dict)  # MERGE 会更新现有节点
        
        # 缓存
        self.node_cache[event.id] = event
        print(f"[MANAGER] ✓ Event created with {len(created_person_ids)} participants, "
              f"{len(created_location_ids)} locations, {len(created_emotion_ids)} emotions")
        
        return event
    
    def create_person_node(
        self,
        name: str,
        description: str,
        role: str = "",
        relationship: str = "",
        traits: List[str] = None,
        interview_id: str = "",
        turn: int = 0,
        **extra_attributes
    ) -> models.PersonNode:
        """创建人物节点"""
        
        # 过滤并只传递 PersonNode 支持的字段
        person_fields = {
            'gender', 'age_mentioned', 'age_at_event', 'relationship_duration',
            'role_characteristics', 'knows_people', 'family_relations', 'professional_relations',
            'social_connections', 'locations_lived', 'occupations', 'education_level',
            'memorable_stories', 'key_quotes', 'current_status', 'last_contact',
            'contact_info_type', 'first_mentioned_in_turn', 'mention_sentiment',
            'tags', 'attributes', 'parent_entity_id', 'related_entity_ids'
        }
        filtered_attrs = {k: v for k, v in extra_attributes.items() if k in person_fields}
        
        # 确保 description 是有意义的内容，而不是模板字符串
        if not description or description.startswith("Participant in"):
            description = f"{name}: 人物信息待补充"
        
        person = models.PersonNode(
            id=f"person_{uuid.uuid4().hex[:8]}",
            name=name,
            description=description,
            role_in_story=role or "其他",
            relationship_to_elder=relationship,
            traits=traits or [],
            source_interview_id=interview_id,
            source_turn=turn,
            confidence=0.8,
            **filtered_attrs
        )
        
        node_dict = asdict(person)
        node_dict = self._sanitize_node_dict(node_dict)
        
        print(f"[MANAGER] Creating person: {person.name} (ID: {person.id})")
        
        if self.driver:
            self.driver.insert_node(node_dict)
        
        self.node_cache[person.id] = person
        return person
    
    def create_location_node(
        self,
        name: str,
        description: str,
        location_type: str = "",
        characteristics: List[str] = None,
        interview_id: str = "",
        turn: int = 0,
        **extra_attributes
    ) -> models.LocationNode:
        """创建地点节点"""
        
        # 只过滤并传递 LocationNode 支持的字段
        location_fields = {
            'country', 'administrative_division', 'coordinates', 'time_periods_lived',
            'era_descriptions', 'cultural_significance', 'emotional_significance',
            'landmark_features', 'notable_places', 'community_members', 'life_events_here',
            'daily_activities', 'hardships_or_joys', 'frequency_of_visits', 'last_visit',
            'still_connected', 'tags', 'attributes', 'parent_entity_id', 'related_entity_ids'
        }
        filtered_attrs = {k: v for k, v in extra_attributes.items() if k in location_fields}
        
        # 确保 description 是有意义的内容
        if not description or description.startswith("Location of"):
            description = f"{name}: 地点信息待补充"
        
        location = models.LocationNode(
            id=f"loc_{uuid.uuid4().hex[:8]}",
            name=name,
            description=description,
            location_type=location_type or "未分类",
            characteristics=characteristics or [],
            source_interview_id=interview_id,
            source_turn=turn,
            confidence=0.8,
            **filtered_attrs
        )
        
        node_dict = asdict(location)
        node_dict = self._sanitize_node_dict(node_dict)
        
        print(f"[MANAGER] Creating location: {location.name} (ID: {location.id})")
        
        if self.driver:
            self.driver.insert_node(node_dict)
        
        self.node_cache[location.id] = location
        return location
    
    def create_emotion_node(
        self,
        name: str,
        description: str,
        emotion_category: str = "",
        intensity: float = 0.5,
        triggered_by: List[str] = None,
        interview_id: str = "",
        turn: int = 0,
        **extra_attributes
    ) -> models.EmotionNode:
        """创建情感节点"""
        
        # 过滤并只传递 EmotionNode 支持的字段
        emotion_fields = {
            'emotion_subcategory', 'valence', 'persistence', 'duration_description',
            'manifestations', 'associated_events', 'associated_people', 'personal_reflection',
            'coping_strategies', 'tags', 'attributes', 'parent_entity_id', 'related_entity_ids'
        }
        filtered_attrs = {k: v for k, v in extra_attributes.items() if k in emotion_fields}
        
        # 确保 description 是有意义的内容
        if not description or description.startswith("Emotional tone"):
            description = f"{name}: 情感表现和背景待补充"
        
        emotion = models.EmotionNode(
            id=f"emotion_{uuid.uuid4().hex[:8]}",
            name=name,
            description=description,
            emotion_category=emotion_category or name,
            intensity=intensity,
            triggered_by=triggered_by or [],
            source_interview_id=interview_id,
            source_turn=turn,
            confidence=0.8,
            **filtered_attrs
        )
        
        node_dict = asdict(emotion)
        node_dict = self._sanitize_node_dict(node_dict)
        
        print(f"[MANAGER] Creating emotion: {emotion.name} (ID: {emotion.id})")
        
        if self.driver:
            self.driver.insert_node(node_dict)
        
        self.node_cache[emotion.id] = emotion
        return emotion
    
    def create_topic_node(
        self,
        name: str,
        description: str,
        category: str = "",
        core_message: str = "",
        related_events: List[str] = None,
        interview_id: str = "",
        turn: int = 0,
        **extra_attributes
    ) -> models.TopicNode:
        """创建主题节点"""
        
        # 过滤并只传递 TopicNode 支持的字段
        topic_fields = {
            'topic_category', 'topic_priority', 'key_beliefs', 'values_expressed',
            'frequency_across_interviews', 'times_mentioned', 'turns_mentioned',
            'related_people', 'related_locations', 'related_emotions', 'related_topics',
            'underlying_themes', 'impact_or_influence', 'evolution_of_perspective',
            'tags', 'attributes', 'parent_entity_id', 'related_entity_ids'
        }
        filtered_attrs = {k: v for k, v in extra_attributes.items() if k in topic_fields}
        
        topic = models.TopicNode(
            id=f"topic_{uuid.uuid4().hex[:8]}",
            name=name,
            description=description,
            topic_category=category,
            core_message=core_message,
            related_events=related_events or [],
            source_interview_id=interview_id,
            source_turn=turn,
            confidence=0.8,
            **filtered_attrs
        )
        
        node_dict = asdict(topic)
        node_dict = self._sanitize_node_dict(node_dict)
        
        print(f"[MANAGER] Creating topic: {topic.name} (ID: {topic.id})")
        
        if self.driver:
            self.driver.insert_node(node_dict)
        
        self.node_cache[topic.id] = topic
        return topic
    
    def create_insight_node(
        self,
        title: str,
        description: str,
        insight_type: str = "pattern",
        evidence_level: str = "medium",
        supporting_events: List[str] = None,
        **extra_attributes
    ) -> models.InsightNode:
        """创建洞察节点"""
        
        # 过滤并只传递 InsightNode 支持的字段
        insight_fields = {
            'insight_category', 'detailed_description', 'inference_chain',
            'supporting_quotes', 'contradicting_examples', 'confidence_score',
            'validation_status', 'validator_notes', 'significance', 'implications',
            'relevant_for_future_questions', 'tags', 'attributes', 'parent_entity_id',
            'related_entity_ids'
        }
        filtered_attrs = {k: v for k, v in extra_attributes.items() if k in insight_fields}
        
        insight = models.InsightNode(
            id=f"insight_{uuid.uuid4().hex[:8]}",
            name=title,
            description=description,
            title=title,
            insight_type=insight_type,
            evidence_level=evidence_level,
            supporting_events=supporting_events or [],
            confidence=0.7,
            **filtered_attrs
        )
        
        node_dict = asdict(insight)
        node_dict = self._sanitize_node_dict(node_dict)
        
        print(f"[MANAGER] Creating insight: {insight.title} (ID: {insight.id})")
        
        if self.driver:
            self.driver.insert_node(node_dict)
        
        self.node_cache[insight.id] = insight
        return insight
    
    # ===== 查询接口 =====
    
    def query_by_text_similarity(
        self,
        text: str,
        entity_type: Optional[str] = None,
        top_k: int = 10,
        interview_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """按文本相似度查询"""
        
        try:
            # 在 driver 层直接进行采访ID过滤
            results = self.driver.query_by_text_similarity(
                text=text,
                entity_type=entity_type,
                max_results=top_k,
                interview_id=interview_id
            )
            
            return results
        except Exception as e:
            print(f"Query failed: {e}")
            return []
    
    def get_entity_neighbors(
        self,
        entity_id: str,
        max_depth: int = 2,
        relation_types: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """获取实体邻域"""
        
        try:
            neighbors = self.driver.get_neighbors(
                node_id=entity_id,
                max_depth=max_depth,
                relation_types=relation_types
            )
            return neighbors
        except Exception as e:
            print(f"Get neighbors failed: {e}")
            return {}
    
    def get_entity_by_hop(
        self,
        entity_id: str,
        hop_count: int = 2,
        interview_id: Optional[str] = None,
        max_nodes: int = 100
    ) -> Dict[str, Any]:
        """
        获取某个实体周围N跳范围内的所有节点和关系
        
        Args:
            entity_id: 实体ID
            hop_count: 跳数（1-5）
            interview_id: 采访ID（可选，用于隔离）
            max_nodes: 单个hop返回的最大节点数
        
        Returns:
            {
                "center": 中心节点,
                "neighbors_by_hop": {
                    1: [节点列表],
                    2: [节点列表],
                    ...
                },
                "relationships": [关系列表],
                "total_nodes": 总节点数,
                "total_relations": 总关系数
            }
        """
        
        try:
            result = self.driver.query_by_hop(
                node_id=entity_id,
                hop_count=hop_count,
                interview_id=interview_id,
                max_nodes=max_nodes
            )
            return result
        except Exception as e:
            print(f"Get entity by hop failed: {e}")
            return {
                "center": None,
                "neighbors_by_hop": {},
                "relationships": [],
                "error": str(e)
            }
    
    def detect_patterns(
        self,
        interview_id: str,
        pattern_type: str = "all"
    ) -> List[Dict[str, Any]]:
        """检测模式（简单实现）"""
        
        try:
            # 查询该采访中 significance_level == "high" 的事件
            # 使用通用 Entity 标签 + type 字段过滤，避免标签警告
            query = """
            MATCH (e:Entity)
            WHERE e.type = "Event"
            AND e.source_interview_id = $interviewId
            AND e.significance_level = "high"
            RETURN {
                type: "significant_event",
                entity_id: e.id,
                entity_name: e.name,
                reason: "High significance event"
            } as pattern
            """
            
            result = self.driver._execute_query(
                query,
                {"interviewId": interview_id}
            )
            
            patterns = [r.get("pattern") for r in (result or []) if r.get("pattern")]
            print(f"[MANAGER] Detected {len(patterns)} patterns in {interview_id}")
            return patterns
            
        except Exception as e:
            print(f"Pattern detection failed: {e}")
            return []
    
    def get_graph_statistics(self, interview_id: Optional[str] = None) -> Dict[str, Any]:
        """获取图统计"""
        
        try:
            stats = self.driver.get_graph_statistics(interview_id=interview_id)
            return stats
        except Exception as e:
            print(f"Get statistics failed: {e}")
            return {}
    
    # ===== 向量去重相关方法 =====
    
    def search_similar_nodes(
        self,
        entity_name: str,
        entity_type: str,
        similarity_threshold: float = 0.80,
        top_k: int = 5
    ) -> List[Tuple[str, float, Dict[str, Any]]]:
        """
        使用向量相似度搜索相似的节点（用于去重）
        
        Args:
            entity_name: 实体名称
            entity_type: 实体类型
            similarity_threshold: 相似度阈值
            top_k: 返回的最多结果数
        
        Returns:
            List[(node_id, similarity_score, metadata)]
        """
        
        if not self.enable_vector_dedup or not self.vector_store:
            print("[MANAGER] 向量去重未启用")
            return []
        
        try:
            # 组合查询文本
            query_text = f"{entity_name} ({entity_type})"
            
            # 执行向量搜索
            results = self.vector_store.search(
                query_text=query_text,
                top_k=top_k,
                threshold=similarity_threshold
            )
            
            print(f"[MANAGER] 向量搜索 '{query_text}': 找到 {len(results)} 个相似节点 (阈值={similarity_threshold})")
            return results
        
        except Exception as e:
            print(f"[MANAGER] ⚠️ 向量搜索失败: {e}")
            return []
    
    def add_node_to_vector_store(
        self,
        node_id: str,
        entity_name: str,
        entity_type: str,
        description: str
    ) -> None:
        """
        将节点添加到向量存储（用于后续查询）
        
        Args:
            node_id: 节点ID
            entity_name: 实体名称
            entity_type: 实体类型
            description: 描述
        """
        
        if not self.enable_vector_dedup or not self.vector_store:
            return
        
        try:
            # 组合用于嵌入的文本
            text_for_embedding = f"{entity_name} ({entity_type}) {description}"
            
            # 添加到向量存储
            self.vector_store.add(
                node_id=node_id,
                text=text_for_embedding,
                metadata={
                    "node_id": node_id,
                    "name": entity_name,
                    "type": entity_type,
                    "node_description": description[:100]
                }
            )
            
            print(f"[MANAGER] ✓ 节点已添加到向量存储: {node_id}")
        
        except Exception as e:
            print(f"[MANAGER] ⚠️ 添加节点到向量存储失败: {e}")
    
    def upsert_node(
        self,
        node_id: str,
        entity_name: str,
        entity_type: str,
        description: str
    ) -> None:
        """
        如果节点存在则更新，不存在则添加（到向量存储）
        
        Args:
            node_id: 节点ID
            entity_name: 实体名称
            entity_type: 实体类型
            description: 描述
        """
        
        if not self.enable_vector_dedup or not self.vector_store:
            return
        
        try:
            text_for_embedding = f"{entity_name} ({entity_type}) {description}"
            
            self.vector_store.update(
                node_id=node_id,
                text=text_for_embedding,
                metadata={
                    "node_id": node_id,
                    "name": entity_name,
                    "type": entity_type,
                    "node_description": description[:100]
                }
            )
            
            print(f"[MANAGER] ✓ 节点已更新/添加到向量存储: {node_id}")
        
        except Exception as e:
            print(f"[MANAGER] ⚠️ 更新节点失败: {e}")
    
    def get_node_by_id(self, node_id: str) -> Optional[Dict[str, Any]]:
        """获取节点信息（从缓存或图数据库）"""
        
        # 先检查缓存
        if node_id in self.node_cache:
            return dict(asdict(self.node_cache[node_id]))
        
        # 从数据库查询（简单实现）
        try:
            # 使用driver执行查询
            query = "MATCH (n {id: $node_id}) RETURN properties(n) as props"
            result = self.driver._execute_query(query, {"node_id": node_id})
            
            if result and len(result) > 0:
                return result[0].get("props")
            
            return None
        
        except Exception as e:
            print(f"[MANAGER] 获取节点失败: {e}")
            return None
    
    def insert_memory(
        self,
        entity_name: str,
        entity_type: str,
        description: str = "",
        key_details: str = "",
        interview_id: str = ""
    ) -> Dict[str, Any]:
        """
        通用的记忆插入接口（被MemoryExtractionAgent调用）
        
        Args:
            entity_name: 实体名称
            entity_type: 实体类型 (Event/Person/Location/Emotion/Topic)
            description: 描述
            key_details: 关键细节
            interview_id: 采访ID
        
        Returns:
            新创建的节点信息
        """
        
        # 根据type创建相应的节点
        node = None
        
        if entity_type == "Event":
            node = self.create_event_node(
                name=entity_name,
                description=description,
                interview_id=interview_id
            )
        elif entity_type == "Person":
            node = self.create_person_node(
                name=entity_name,
                description=description,
                interview_id=interview_id
            )
        elif entity_type == "Location":
            node = self.create_location_node(
                name=entity_name,
                description=description,
                interview_id=interview_id
            )
        elif entity_type == "Emotion":
            node = self.create_emotion_node(
                name=entity_name,
                description=description,
                interview_id=interview_id
            )
        elif entity_type == "Topic":
            node = self.create_topic_node(
                name=entity_name,
                description=description,
                interview_id=interview_id
            )
        else:
            # 默认创建通用Event
            node = self.create_event_node(
                name=entity_name,
                description=description,
                interview_id=interview_id
            )
        
        # 添加到向量存储（用于后续去重）
        if node:
            self.add_node_to_vector_store(
                node_id=node.id,
                entity_name=entity_name,
                entity_type=entity_type,
                description=description
            )
        
        # 返回节点信息
        return {
            "id": node.id,
            "name": node.name,
            "type": entity_type,
            "description": description
        } if node else {}
    
    def insert_edge(
        self,
        source_id: str,
        target_id: str,
        relation_type: str,
        properties: Optional[Dict[str, Any]] = None
    ) -> bool:
        """创建图中两个节点之间的关系
        
        Args:
            source_id: 源节点ID
            target_id: 目标节点ID
            relation_type: 关系类型（如 INVOLVES, OCCURS_AT 等）
            properties: 关系属性
        
        Returns:
            是否成功创建关系
        """
        try:
            success = self.driver.insert_edge(
                source_id=source_id,
                target_id=target_id,
                relation_type=relation_type,
                properties=properties or {}
            )
            return success
        except Exception as e:
            print(f"[MANAGER] Error creating edge: {source_id} -[{relation_type}]-> {target_id}: {e}")
            return False
