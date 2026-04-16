# Planner Agent 工具集 - 仅支持查询功能
# 不包含创建、写入、提取等操作
# 所有查询先由提取 agent 优化后再执行

import json
from typing import Optional, List
from camel.toolkits import FunctionTool


def create_planner_query_tools(memory_manager, interview_id: str = "default_interview") -> List[FunctionTool]:
    """
    创建 Planner Agent 的工具集（仅查询功能）
    
    这些工具用于 Planner 在规划访谈策略时查询已有的记忆信息。
    所有查询流程：
    1. Planner 提交查询请求
    2. MemoryExtractionAgent 优化查询语句
    3. 执行优化后的查询
    4. 返回结果
    
    Args:
        memory_manager: EnhancedGraphMemoryManager 实例
        interview_id: 当前采访 ID，用于数据隔离
        
    Returns:
        FunctionTool 对象列表
    """
    
    print(f"[PLANNER_TOOLS] 初始化 Planner 查询工具集 (采访ID: {interview_id})")
    
    # ========== 工具1：查询记忆 ==========
    def query_memory_tool(
        query_text: str,
        entity_type: str = "all",
        max_results: int = 5
    ) -> str:
        """
        查询已有的记忆中的相关信息
        
        注意：查询会先由提取 Agent 进行优化
        """
        
        try:
            print(f"[QUERY_MEMORY] 查询: {query_text}")
            entity_type_filter = None if entity_type == "all" else entity_type
            
            results = memory_manager.query_by_text_similarity(
                text=query_text,
                entity_type=entity_type_filter,
                top_k=max_results,
                interview_id=interview_id
            )
            
            if not results:
                return f"没有找到关于 '{query_text}' 的记忆信息。"
            
            formatted_results = []
            for i, result in enumerate(results, 1):
                if isinstance(result, dict):
                    item = f"""【结果 {i}】
类型: {result.get('type', 'Unknown')}
名称: {result.get('name', 'N/A')}
描述: {result.get('description', 'N/A')[:100]}..."""
                    formatted_results.append(item)
            
            print(f"[QUERY_MEMORY] ✓ 返回 {len(formatted_results)} 个结果")
            return "以下是匹配的记忆信息：\n" + "\n".join(formatted_results)
            
        except Exception as e:
            print(f"[QUERY_MEMORY] ✗ 错误: {e}")
            return f"查询记忆时出错: {str(e)}"
    
    
    # ========== 工具2：获取访谈摘要 ==========
    def get_interview_summary_tool() -> str:
        """获取当前访谈的关键信息摘要"""
        
        try:
            print(f"[SUMMARY_TOOL] 获取访谈摘要... (采访: {interview_id})")
            
            stats = memory_manager.get_graph_statistics(interview_id=interview_id)
            
            if not stats:
                return f"当前采访 {interview_id} 的记忆系统中还没有数据。"
            
            summary_text = f"【访谈摘要】 (采访ID: {interview_id})\n\n统计信息:"
            
            if isinstance(stats, dict):
                for key, value in stats.items():
                    if key not in ["error"]:
                        summary_text += f"\n  - {key}: {value}"
            
            print(f"[SUMMARY_TOOL] ✓ 摘要包含统计: {list(stats.keys())}")
            return summary_text
            
        except Exception as e:
            print(f"[SUMMARY_TOOL] ✗ 错误: {e}")
            return f"获取摘要时出错: {str(e)}"
    
    
    # ========== 工具3：检测行为模式 ==========
    def detect_patterns_tool(pattern_type: str = "all") -> str:
        """检测当前记忆中的行为模式"""
        
        try:
            print(f"[PATTERNS] 检测行为模式: {pattern_type} (采访: {interview_id})")
            
            patterns = memory_manager.detect_patterns(
                interview_id=interview_id,
                pattern_type=pattern_type
            )
            
            if not patterns:
                return "暂未检测到明显的行为模式。"
            
            pattern_text = "【检测到的行为模式】:\n\n"
            
            if isinstance(patterns, list):
                for i, pattern in enumerate(patterns, 1):
                    if isinstance(pattern, dict):
                        pattern_text += f"{i}. {pattern.get('entity_name', 'N/A')}\n"
                        pattern_text += f"   类型: {pattern.get('type', 'N/A')}\n"
                        pattern_text += f"   原因: {pattern.get('reason', 'N/A')}\n\n"
            
            print(f"[PATTERNS] ✓ 检测到 {len(patterns)} 个模式")
            return pattern_text
            
        except Exception as e:
            print(f"[PATTERNS] ✗ 错误: {e}")
            return f"检测模式时出错: {str(e)}"
    
    
    # ========== 工具4：按hop查询实体上下文 ==========
    def get_entity_context_tool(
        entity_id: str,
        hop_count: int = 2
    ) -> str:
        """
        获取某个实体周围N跳范围内的完整上下文图
        用于理解一个节点与其他节点的关系
        """
        
        try:
            print(f"[ENTITY_CONTEXT] 查询实体 {entity_id} 的{hop_count}跳上下文")
            
            result = memory_manager.get_entity_by_hop(
                entity_id=entity_id,
                hop_count=hop_count,
                interview_id=interview_id,
                max_nodes=100
            )
            
            if not result.get("center"):
                return f"实体 {entity_id} 不存在。"
            
            # 格式化返回结果
            output_lines = []
            
            # 中心节点信息
            center = result["center"]
            output_lines.append(f"【中心实体】")
            output_lines.append(f"  ID: {center.get('id')}")
            output_lines.append(f"  类型: {center.get('type')}")
            output_lines.append(f"  名称: {center.get('name')}")
            output_lines.append(f"  描述: {center.get('description', 'N/A')[:100]}")
            output_lines.append("")
            
            # 按hop分类的邻域节点
            neighbors_by_hop = result.get("neighbors_by_hop", {})
            for hop in sorted(neighbors_by_hop.keys()):
                nodes = neighbors_by_hop[hop]
                output_lines.append(f"【{hop}跳邻域节点】({len(nodes)}个)")
                for i, node in enumerate(nodes[:20], 1): 
                    output_lines.append(f"  {i}. {node.get('name')} ({node.get('type')})")
                if len(nodes) > 20:
                    output_lines.append(f"  ... 还有 {len(nodes)-20} 个节点")
                output_lines.append("")
            
            # 关系摘要
            relationships = result.get("relationships", [])
            if relationships:
                output_lines.append(f"【关系统计】")
                rel_types = {}
                for rel in relationships:
                    rel_type = rel.get('relation_type', 'UNKNOWN')
                    rel_types[rel_type] = rel_types.get(rel_type, 0) + 1
                for rel_type, count in sorted(rel_types.items()):
                    output_lines.append(f"  - {rel_type}: {count} 条")
                output_lines.append("")
            
            output_lines.append(f"【统计信息】")
            output_lines.append(f"  总节点数: {result.get('total_nodes', 0)}")
            output_lines.append(f"  总关系数: {result.get('total_relations', 0)}")
            
            print(f"[ENTITY_CONTEXT] ✓ 返回{result.get('total_nodes', 0)}个节点和{result.get('total_relations', 0)}个关系")
            return "\n".join(output_lines)
            
        except Exception as e:
            print(f"[ENTITY_CONTEXT] ✗ 错误: {e}")
            return f"获取实体上下文时出错: {str(e)}"
    
    
    # ========== 创建工具对象列表 ==========
    tools = [
        FunctionTool(query_memory_tool),
        FunctionTool(get_interview_summary_tool),
        FunctionTool(detect_patterns_tool),
        FunctionTool(get_entity_context_tool),
    ]
    
    print(f"[PLANNER_TOOLS] ✓ 创建了 {len(tools)} 个查询工具")
    return tools
