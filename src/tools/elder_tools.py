import json
import logging
import re
from typing import List, Optional, Dict, Any

logger = logging.getLogger(__name__)

class ElderMemorySystem:
    """老人记忆系统"""
    
    def __init__(self, elder_profile_path: str):
        """
        初始化记忆系统
        
        Args:
            elder_profile_path: 老人档案JSON文件路径
        """
        with open(elder_profile_path, 'r', encoding='utf-8') as f:
            self.elder_profile = json.load(f)
        
        # 获取记忆数据
        self.memories_data = self.elder_profile.get("elder_profile", {})
        
        # 构建记忆索引
        self._build_memory_index()

        from src.services.entity_vector_store import EntityVectorStore
        self._vector_store = EntityVectorStore()
        try:
            self._build_vector_index()
        except Exception as exc:
            logger.warning("向量索引构建失败（语义搜索不可用）: %s", exc)

    def _build_vector_index(self) -> None:
        for memory_id, memory_info in self.memory_index.items():
            memory = memory_info["memory"]
            text = " ".join(filter(None, [
                memory.get("event_name", ""),
                memory.get("description", ""),
                memory.get("details", ""),
            ]))
            if text.strip():
                self._vector_store.add(
                    entity_id=memory_id,
                    entity_type="Memory",
                    text=text,
                )

    def _build_memory_index(self):
        """构建内存索引，加速搜索"""
        self.memory_index = {}
        
        # 索引所有记忆事件
        for period_key, period_data in self.memories_data.get("life_memories_by_period", {}).items():
            for memory in period_data.get("memory_events", []):
                memory_id = memory.get("event_id")
                if memory_id:
                    self.memory_index[memory_id] = {
                        "period": period_key,
                        "memory": memory
                    }
    
    def search_memories_by_keywords(
        self, 
        keywords: List[str], 
        period: Optional[str] = None,
        emotion_weight: Optional[int] = None,
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """
        根据关键词搜索记忆
        
        Args:
            keywords: 搜索关键词列表
            period: 时期限制（如"period_1"）
            emotion_weight: 情感强度过滤
            limit: 返回结果数量限制
            
        Returns:
            记忆片段列表
        """
        results = []

        for memory_id, memory_info in self.memory_index.items():
            memory = memory_info["memory"]
            memory_period = memory_info["period"]
            
            # 按时期过滤
            if period and memory_period != period:
                continue
            
            # 按情感强度过滤
            if emotion_weight is not None:
                mem_emotion = memory.get("emotional_weight", 0)
                if emotion_weight > 0 and mem_emotion < emotion_weight:
                    continue
            
            # 计算关键词匹配度
            match_score = 0
            memory_text = f"{memory.get('event_name', '')} {memory.get('description', '')} {memory.get('details', '')}"
            memory_text = memory_text.lower()
            
            for keyword in keywords:
                keyword_lower = keyword.lower()
                if keyword_lower in memory_text:
                    match_score += 1
            
            # 按标签匹配
            tags = memory.get("tags", [])
            for keyword in keywords:
                if keyword in tags:
                    match_score += 2  # 标签匹配权重更高
            
            if match_score > 0:
                results.append({
                    "memory_id": memory_id,
                    "memory": memory,
                    "period": memory_period,
                    "match_score": match_score
                })
        
        # 按匹配度排序
        results.sort(key=lambda x: x["match_score"], reverse=True)
        return results[:limit]
    
    def get_memory_by_id(self, memory_id: str) -> Optional[Dict[str, Any]]:
        """
        根据记忆ID获取特定记忆
        
        Args:
            memory_id: 记忆ID
            
        Returns:
            记忆片段，如果不存在则返回None
        """
        memory_info = self.memory_index.get(memory_id)
        if memory_info:
            return memory_info["memory"]
        return None
    
    def search_memories_by_tags(
        self, 
        tags: List[str], 
        period: Optional[str] = None,
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """
        根据标签搜索记忆
        
        Args:
            tags: 标签列表
            period: 时期限制
            limit: 返回结果数量限制
            
        Returns:
            记忆片段列表
        """
        results = []
        
        for memory_id, memory_info in self.memory_index.items():
            memory = memory_info["memory"]
            memory_period = memory_info["period"]
            
            # 按时期过滤
            if period and memory_period != period:
                continue
            
            # 按标签匹配
            memory_tags = set(memory.get("tags", []))
            search_tags = set(tags)
            
            if memory_tags.intersection(search_tags):
                match_count = len(memory_tags.intersection(search_tags))
                results.append({
                    "memory_id": memory_id,
                    "memory": memory,
                    "period": memory_period,
                    "match_count": match_count
                })
        
        # 按匹配数量排序
        results.sort(key=lambda x: x["match_count"], reverse=True)

        return results[:limit]
    
    def get_memories_by_period(
        self, 
        period: str, 
        sort_by_emotion: bool = False,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        获取特定时期的记忆
        
        Args:
            period: 时期名称
            sort_by_emotion: 是否按情感强度排序
            limit: 返回结果数量限制
            
        Returns:
            记忆片段列表
        """
        results = []
        
        for memory_id, memory_info in self.memory_index.items():
            if memory_info["period"] == period:
                results.append({
                    "memory_id": memory_id,
                    "memory": memory_info["memory"],
                    "period": period
                })
        if sort_by_emotion:
            results.sort(key=lambda x: x["memory"].get("emotional_weight", 0), reverse=True)
        return results[:limit]
    
    def get_related_memories(
        self, 
        memory_id: str, 
        max_related: int = 3
    ) -> List[Dict[str, Any]]:
        """
        获取相关记忆
        
        Args:
            memory_id: 源记忆ID
            max_related: 最大相关记忆数量
            
        Returns:
            相关记忆列表
        """
        source_memory = self.get_memory_by_id(memory_id)
        if not source_memory:
            return []
        linked_ids = source_memory.get("linked_memory_ids", [])
        related_memories = []
        for linked_id in linked_ids[:max_related]:
            related_memory = self.get_memory_by_id(linked_id)
            if related_memory:
                related_memories.append({
                    "memory_id": linked_id,
                    "memory": related_memory
                })
        
        return related_memories

    def search_memories_by_semantic(
        self,
        query: str,
        top_k: int = 3,
    ) -> List[Dict[str, Any]]:
        """语义搜索记忆，适合模糊或概念性查询。返回格式与 search_memories_by_keywords 一致。"""
        try:
            hits = self._vector_store.search_by_text(query, top_k=top_k, entity_type="Memory")
        except Exception as exc:
            logger.warning("Semantic memory search unavailable; using lexical fallback: %s", exc)
            return self._lexical_memory_fallback(query, top_k)

        results = []
        for memory_id, _entity_type, score in hits:
            memory_info = self.memory_index.get(memory_id)
            if memory_info:
                results.append({
                    "memory_id": memory_id,
                    "memory": memory_info["memory"],
                    "period": memory_info["period"],
                    "similarity_score": score,
                })
        return results

    def _lexical_memory_fallback(self, query: str, top_k: int) -> List[Dict[str, Any]]:
        query_tokens = set(_fallback_query_tokens(query))
        if not query_tokens:
            return []

        ranked: List[Dict[str, Any]] = []
        for memory_id, memory_info in self.memory_index.items():
            memory = memory_info["memory"]
            memory_text = " ".join(filter(None, [
                memory.get("event_name", ""),
                memory.get("description", ""),
                memory.get("details", ""),
                " ".join(memory.get("tags", []) or []),
            ]))
            memory_tokens = set(_fallback_query_tokens(memory_text))
            if not memory_tokens:
                continue
            overlap = len(query_tokens & memory_tokens)
            if overlap <= 0:
                continue
            score = overlap / max(len(query_tokens), 1)
            ranked.append({
                "memory_id": memory_id,
                "memory": memory,
                "period": memory_info["period"],
                "similarity_score": float(min(score, 1.0)),
            })

        ranked.sort(key=lambda item: item["similarity_score"], reverse=True)
        return ranked[:top_k]


def _fallback_query_tokens(text: str) -> List[str]:
    normalized = (text or "").lower()
    compact = re.sub(r"\s+", "", normalized)
    tokens = re.findall(r"[a-z0-9_]+", normalized)
    tokens.extend(char for char in compact if not char.isspace())
    tokens.extend(compact[i:i + 2] for i in range(max(0, len(compact) - 1)))
    tokens.extend(compact[i:i + 3] for i in range(max(0, len(compact) - 2)))
    return [token for token in tokens if token]


def get_tool_schemas() -> List[Dict[str, Any]]:
    """返回 OpenAI function call 格式的工具 schema 列表"""
    return [
        {
            "type": "function",
            "function": {
                "name": "search_memories_by_keywords",
                "description": "根据关键词搜索老人记忆",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "keywords": {"type": "array", "items": {"type": "string"}, "description": "搜索关键词列表"},
                        "period": {"type": "string", "description": "时期限制，如 period_1"},
                        "emotion_weight": {"type": "integer", "description": "情感强度过滤（最低值）"},
                        "limit": {"type": "integer", "description": "返回结果数量限制", "default": 5},
                    },
                    "required": ["keywords"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_memory_by_id",
                "description": "根据记忆ID获取特定记忆",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "memory_id": {"type": "string", "description": "记忆ID"},
                    },
                    "required": ["memory_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search_memories_by_tags",
                "description": "根据标签搜索记忆",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "tags": {"type": "array", "items": {"type": "string"}, "description": "标签列表"},
                        "period": {"type": "string", "description": "时期限制"},
                        "limit": {"type": "integer", "description": "返回结果数量限制", "default": 5},
                    },
                    "required": ["tags"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_memories_by_period",
                "description": "获取特定时期的记忆",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "period": {"type": "string", "description": "时期名称"},
                        "sort_by_emotion": {"type": "boolean", "description": "是否按情感强度排序"},
                        "limit": {"type": "integer", "description": "返回结果数量限制", "default": 10},
                    },
                    "required": ["period"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_related_memories",
                "description": "获取与指定记忆相关的记忆",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "memory_id": {"type": "string", "description": "源记忆ID"},
                        "max_related": {"type": "integer", "description": "最大相关记忆数量", "default": 3},
                    },
                    "required": ["memory_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search_memories_by_semantic",
                "description": "用自然语言语义搜索老人记忆，适合模糊或概念性查询（如'艰难时期'、'最自豪的事'）",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "自然语言查询"},
                        "top_k": {"type": "integer", "description": "返回结果数量限制", "default": 3},
                    },
                    "required": ["query"],
                },
            },
        },
    ]


def get_tool_callables(ms: ElderMemorySystem) -> Dict[str, Any]:
    """返回工具名称到可调用函数的映射"""
    return {
        "search_memories_by_keywords": ms.search_memories_by_keywords,
        "get_memory_by_id": ms.get_memory_by_id,
        "search_memories_by_tags": ms.search_memories_by_tags,
        "get_memories_by_period": ms.get_memories_by_period,
        "get_related_memories": ms.get_related_memories,
        "search_memories_by_semantic": ms.search_memories_by_semantic,
    }


if __name__ == "__main__":
    ms = ElderMemorySystem("prompts/roles/elder_profile_example.json")
    import pprint
    pprint.pprint(get_tool_schemas())
