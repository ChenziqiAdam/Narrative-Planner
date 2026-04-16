# 记忆提取 Agent 使用的工具集
# 用于：向量相似度搜索、冲突检测、节点查询等

import json
from typing import List, Optional
from camel.toolkits import FunctionTool


def create_memory_extraction_tools(extraction_agent) -> List[FunctionTool]:
    """
    创建记忆提取 Agent 的内部工具集
    
    Args:
        extraction_agent: MemoryExtractionAgent 实例（用于访问 memory_manager 和 vector_store）
    
    Returns:
        工具列表：[vector_search_tool, conflict_check_tool, get_node_details_tool]
    """
    
    # ========== 工具1：向量相似度搜索 ==========
    def vector_search_similar_nodes(
        entity_name: str,
        entity_type: str,
        top_k: int = 3
    ) -> str:
        """
        使用向量相似度搜索相似的已存在节点
        
        Args:
            entity_name: 要搜索的实体名称
            entity_type: 实体类型 (Person|Event|Location|Emotion|Topic)
            top_k: 返回的最多结果数
        
        Returns:
            JSON格式的搜索结果
            {
                "status": "no_similar|found_similar|error",
                "query": "entity_name",
                "candidates_count": int,
                "candidates": [
                    {
                        "node_id": "id",
                        "similarity_score": 0.95,
                        "node_name": "name",
                        "node_type": "type",
                        "node_description": "desc"
                    }
                ]
            }
        """
        try:
            # 组合查询文本
            query_text = f"{entity_name} ({entity_type})"
            
            # 执行向量搜索
            results = extraction_agent.vector_store.search(
                query_text=query_text,
                top_k=top_k,
                threshold=extraction_agent.dedup_threshold
            )
            
            if not results:
                return json.dumps({
                    "status": "no_similar",
                    "message": f"未找到与'{entity_name}'相似的节点（相似度>{extraction_agent.dedup_threshold}）"
                })
            
            # 格式化候选节点信息
            candidates = []
            for node_id, similarity, metadata in results:
                candidates.append({
                    "node_id": node_id,
                    "similarity_score": round(similarity, 3),
                    "node_name": metadata.get("name", "unknown"),
                    "node_type": metadata.get("type", "unknown"),
                    "node_description": metadata.get("node_description", "")[:100]
                })
            
            return json.dumps({
                "status": "found_similar",
                "query": entity_name,
                "candidates_count": len(candidates),
                "candidates": candidates
            })
        
        except Exception as e:
            print(f"[MemoryExtractionTools] ⚠️ 向量搜索失败: {e}")
            return json.dumps({
                "status": "error",
                "message": f"向量搜索出错: {str(e)}"
            })
    
    # ========== 工具2：冲突检测 ==========
    def check_conflict_between_nodes(
        existing_node_id: str,
        new_entity_name: str,
        new_entity_description: str
    ) -> str:
        """
        检测新旧节点之间的数据冲突
        
        Args:
            existing_node_id: 要比较的现存节点ID
            new_entity_name: 新实体的名称
            new_entity_description: 新实体的描述
        
        Returns:
            冲突分析结果JSON
            {
                "status": "analyzed|not_found|error",
                "existing_node_id": "id",
                "conflict_count": int,
                "conflicts": [
                    {
                        "field": "name|description",
                        "existing": "value",
                        "new": "value",
                        "severity": "low|medium|high"
                    }
                ],
                "mergeability_score": 0.85,
                "recommendation": "merge|review"
            }
        """
        try:
            if not extraction_agent.memory_manager:
                return json.dumps({"status": "error", "message": "内存管理器未初始化"})
            
            # 获取现存节点信息
            existing = extraction_agent.memory_manager.get_node_by_id(existing_node_id)
            
            if not existing:
                return json.dumps({
                    "status": "node_not_found",
                    "message": f"节点{existing_node_id}不存在"
                })
            
            conflicts = []
            mergeability_score = 1.0  # 可合并性评分（1.0=可合并）
            
            # 检测name冲突
            if existing.get("name") != new_entity_name:
                conflicts.append({
                    "field": "name",
                    "existing": existing.get("name"),
                    "new": new_entity_name,
                    "severity": "low"
                })
            
            # 检测description冲突
            if existing.get("description") and new_entity_description:
                if existing.get("description") != new_entity_description:
                    conflicts.append({
                        "field": "description",
                        "existing": existing.get("description")[:100],
                        "new": new_entity_description[:100],
                        "severity": "medium"
                    })
                    mergeability_score *= 0.8
            
            return json.dumps({
                "status": "analyzed",
                "existing_node_id": existing_node_id,
                "conflict_count": len(conflicts),
                "conflicts": conflicts,
                "mergeability_score": round(mergeability_score, 2),
                "recommendation": "merge" if mergeability_score > 0.7 else "review"
            })
        
        except Exception as e:
            print(f"[MemoryExtractionTools] ⚠️ 冲突检测失败: {e}")
            return json.dumps({
                "status": "error",
                "message": f"冲突检测出错: {str(e)}"
            })
    
    # ========== 工具3：获取现有节点详情 ==========
    def get_node_details(node_id: str) -> str:
        """
        获取节点的完整信息
        
        Args:
            node_id: 节点ID
        
        Returns:
            节点详情JSON
            {
                "status": "found|not_found|error",
                "node": {...}
            }
        """
        try:
            if not extraction_agent.memory_manager:
                return json.dumps({"status": "error"})
            
            node = extraction_agent.memory_manager.get_node_by_id(node_id)
            
            if not node:
                return json.dumps({
                    "status": "not_found",
                    "node_id": node_id
                })
            
            return json.dumps({
                "status": "found",
                "node": node
            })
        
        except Exception as e:
            return json.dumps({
                "status": "error",
                "message": str(e)
            })
    
    # ========== 工具4：查询图数据库中的同类型实体 ==========
    def query_existing_entities_by_type(
        entity_type: str,
        limit: int = 10
    ) -> str:
        """
        查询图数据库中已经存在的同类型实体
        
        这是真正的图数据库查询，而不是向量搜索。
        用于了解当前图中已有哪些节点，帮助做出更好的去重决策。
        
        Args:
            entity_type: 实体类型（Person|Event|Location|Emotion|Topic）
            limit: 返回的最大实体数
        
        Returns:
            JSON格式的查询结果
            {
                "status": "found|empty|error",
                "entity_type": "type",
                "total_count": int,
                "existing_entities": [
                    {
                        "node_id": "id",
                        "name": "name",
                        "description": "desc",
                        "created_at": "timestamp"
                    }
                ]
            }
        """
        try:
            if not extraction_agent.memory_manager:
                return json.dumps({"status": "error", "message": "内存管理器未初始化"})
            
            # 从Neo4j查询该类型的所有实体
            driver = extraction_agent.memory_manager.driver
            query_str = f"""
            MATCH (n:{entity_type})
            RETURN n.id as node_id, n.name as name, n.description as description, n.created_at as created_at
            LIMIT {min(limit, 100)}
            """
            
            results = driver._execute_query(query_str, {})
            
            if not results:
                return json.dumps({
                    "status": "empty",
                    "entity_type": entity_type,
                    "total_count": 0,
                    "existing_entities": [],
                    "message": f"图中尚未存在类型为'{entity_type}'的实体"
                })
            
            # 格式化结果
            entities = []
            for record in results:
                entities.append({
                    "node_id": record.get("node_id", ""),
                    "name": record.get("name", ""),
                    "description": record.get("description", "")[:100],
                    "created_at": record.get("created_at", "")
                })
            
            return json.dumps({
                "status": "found",
                "entity_type": entity_type,
                "total_count": len(entities),
                "existing_entities": entities[:limit]
            })
        
        except Exception as e:
            print(f"[MemoryExtractionTools] ⚠️ 图查询失败: {e}")
            return json.dumps({
                "status": "error",
                "message": f"查询出错: {str(e)}"
            })
    
    # ========== 工具5：查询相关节点 ==========
    def query_related_nodes(
        entity_id: str,
        max_depth: int = 2
    ) -> str:
        """
        查询与某个节点相关的其他节点（邻域结构）
        
        用于理解节点在知识图谱中的位置和上下文关系。
        
        Args:
            entity_id: 实体ID
            max_depth: 最大关系深度（1-3，默认2）
        
        Returns:
            JSON格式的邻域信息
            {
                "status": "found|not_found|error",
                "center_node_id": "id",
                "related_nodes": [
                    {
                        "node_id": "id",
                        "name": "name",
                        "type": "type",
                        "relation_types": ["INVOLVES", "OCCURS_AT"],
                        "distance": 1
                    }
                ],
                "total_relations": int
            }
        """
        try:
            if not extraction_agent.memory_manager:
                return json.dumps({"status": "error", "message": "内存管理器未初始化"})
            
            # 使用get_entity_neighbors查询邻域
            neighbors_result = extraction_agent.memory_manager.get_entity_neighbors(
                entity_id=entity_id,
                max_depth=min(max_depth, 3)
            )
            
            if not neighbors_result or "error" in neighbors_result:
                return json.dumps({
                    "status": "not_found",
                    "entity_id": entity_id,
                    "message": f"节点{entity_id}不存在或无相关节点"
                })
            
            # 格式化邻域信息
            related_nodes = neighbors_result.get("neighbors", [])
            
            return json.dumps({
                "status": "found",
                "center_node_id": entity_id,
                "related_nodes": [
                    {
                        "node_id": node.get("id", ""),
                        "name": node.get("name", ""),
                        "type": node.get("type", ""),
                        "relation_types": node.get("relation_types", []),
                        "distance": node.get("distance", 0)
                    }
                    for node in (related_nodes[:10] if related_nodes else [])
                ],
                "total_relations": len(related_nodes)
            })
        
        except Exception as e:
            print(f"[MemoryExtractionTools] ⚠️ 邻域查询失败: {e}")
            return json.dumps({
                "status": "error",
                "message": f"查询出错: {str(e)}"
            })
    
    # ========== 工具6：获取图统计信息 ==========
    def get_graph_overview() -> str:
        """
        获取当前知识图谱的统计信息
        
        帮助agent了解图的当前规模和结构。
        
        Returns:
            JSON格式的图统计信息
            {
                "status": "ok|error",
                "total_nodes": int,
                "node_count_by_type": {"Person": 10, "Event": 5, ...},
                "total_relations": int,
                "relation_count_by_type": {"INVOLVES": 8, "OCCURS_AT": 5, ...},
                "interview_id": "string"
            }
        """
        try:
            if not extraction_agent.memory_manager:
                return json.dumps({"status": "error", "message": "内存管理器未初始化"})
            
            stats = extraction_agent.memory_manager.get_graph_statistics(
                interview_id=extraction_agent.interview_id
            )
            
            return json.dumps({
                "status": "ok",
                "total_nodes": stats.get("total_nodes", 0),
                "node_count_by_type": stats.get("node_count_by_type", {}),
                "total_relations": stats.get("total_relations", 0),
                "relation_count_by_type": stats.get("relation_count_by_type", {}),
                "interview_id": extraction_agent.interview_id
            })
        
        except Exception as e:
            print(f"[MemoryExtractionTools] ⚠️ 图统计查询失败: {e}")
            return json.dumps({
                "status": "error",
                "message": f"查询出错: {str(e)}"
            })
    
    # 包装为FunctionTool
    tools = [
        FunctionTool(vector_search_similar_nodes),
        FunctionTool(check_conflict_between_nodes),
        FunctionTool(get_node_details),
        FunctionTool(query_existing_entities_by_type),
        FunctionTool(query_related_nodes),
        FunctionTool(get_graph_overview)
    ]
    
    return tools
