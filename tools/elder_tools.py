from camel.toolkits import FunctionTool

import json
from typing import List, Optional, Dict, Any
from datetime import datetime

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
    ) -> List[Dict[str, Any]]:
        """
        根据关键词搜索记忆
        
        Args:
            keywords: 搜索关键词列表
            period: 时期限制（如"period_1"）
            
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
        return results
    
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


def get_tools(ms:ElderMemorySystem) -> List[FunctionTool]:
    """获取老人记忆系统的工具列表"""
    tools = [
            FunctionTool(ms.search_memories_by_keywords),
            FunctionTool(ms.get_memory_by_id),
            FunctionTool(ms.search_memories_by_tags),
            FunctionTool(ms.get_memories_by_period),
            FunctionTool(ms.get_related_memories),
        ]
    return tools

def get_tools_schemas(tools:List[FunctionTool]) -> List[Dict[str, Any]]:
    tools_schemas = []
    for tool in tools:
        tools_schemas.append(tool.get_openai_function_schema())
    return tools_schemas

if __name__ == "__main__":
    ms = ElderMemorySystem("prompts/roles/elder_profile_example.json")
    tools = get_tools(ms)
    print(get_tools_schemas(tools))