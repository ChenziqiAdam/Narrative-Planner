# Graph RAG 记忆工具定义 - 同步版本
# 使用同步 API，无异步复杂度

import json
from typing import Optional, List
from camel.toolkits import FunctionTool

# 注意: tools_extraction_agent.py 已创建但暂不导入（CAMEL-OpenAI版本兼容性问题）
# 未来升级依赖时可启用 MemoryExtractionToolKit


def create_graph_memory_tools(memory_manager, interview_id: str = "default_interview") -> List[FunctionTool]:
    """
    创建图记忆系统的工具集（同步版本）
    
    Args:
        memory_manager: EnhancedGraphMemoryManager 实例
        interview_id: 当前采访 ID，用于数据隔离
        
    Returns:
        FunctionTool 对象列表
    """
    
    print(f"[TOOLS] Creating tools for interview: {interview_id}")
    
    # ========== 工具1：查询记忆 ==========
    def query_memory_tool(
        query_text: str,
        entity_type: str = "all",
        max_results: int = 5
    ) -> str:
        """查询已有的记忆中的相关信息"""
        
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
    
    
    # ========== 工具2：存储记忆（支持多类型 + 向量去重）==========
    def store_memory_tool(
        event_name: str,
        description: str,
        entity_type: str = "Event",
        key_details: Optional[str] = None
    ) -> str:
        """
        显式地向记忆系统中存储新的信息，支持向量去重检查
        
        支持的entity_type:
        - Event: 事件、故事、经历
        - Person: 人物、家庭成员、朋友、同事
        - Location: 地点、城市、地区、建筑物
        - Emotion: 情感、感受、心态
        - Topic: 话题、主题、观点
        """
        
        try:
            print(f"[STORE_MEMORY] 存储新节点: {event_name} (类型: {entity_type})")
            
            # 规范化entity_type
            entity_type_map = {
                "event": "Event",
                "Event": "Event",
                "事件": "Event",
                "person": "Person",
                "Person": "Person",
                "人物": "Person",
                "location": "Location",
                "Location": "Location",
                "地点": "Location",
                "emotion": "Emotion",
                "Emotion": "Emotion",
                "情感": "Emotion",
                "topic": "Topic",
                "Topic": "Topic",
                "话题": "Topic"
            }
            
            normalized_type = entity_type_map.get(entity_type, "Event")
            
            # ===== 向量去重检查 =====
            similar_nodes = memory_manager.search_similar_nodes(
                entity_name=event_name,
                entity_type=normalized_type,
                similarity_threshold=0.80,  # 80% 相似度作为去重阈值
                top_k=3
            )
            
            if similar_nodes:
                print(f"[STORE_MEMORY] 发现 {len(similar_nodes)} 个相似节点:")
                for node_id, similarity, metadata in similar_nodes:
                    existing_name = metadata.get('name', 'Unknown')
                    existing_desc = metadata.get('node_description', '')[:50]
                    print(f"  - {existing_name} (相似度: {similarity:.2%}, ID: {node_id})")
                    if similarity > 0.95:
                        print(f"[STORE_MEMORY] ⚠️ 极高相似度 (>95%)，可能是重复节点，跳过创建")
                        return f"✓ 已跳过重复存储:\n  节点 '{existing_name}' 已存在 (相似度: {similarity:.2%})\n  ID: {node_id}\n  操作: 已合并"
            
            # 解析额外属性
            attributes = {}
            if key_details:
                try:
                    parsed = json.loads(key_details)
                    if isinstance(parsed, dict):
                        for k, v in parsed.items():
                            if isinstance(v, (str, int, float, bool, type(None), list)):
                                attributes[k] = v
                except (json.JSONDecodeError, TypeError):
                    pass
            
            # 创建节点
            standard_args = {
                'name': event_name,
                'description': description,
                'interview_id': interview_id,
                'turn': 0
            }
            standard_args.update(attributes)
            
            # 根据规范化后的type调用对应的create方法
            if normalized_type == "Event":
                node = memory_manager.create_event_node(**standard_args)
            elif normalized_type == "Person":
                node = memory_manager.create_person_node(**standard_args)
            elif normalized_type == "Location":
                node = memory_manager.create_location_node(**standard_args)
            elif normalized_type == "Emotion":
                node = memory_manager.create_emotion_node(**standard_args)
            elif normalized_type == "Topic":
                node = memory_manager.create_topic_node(**standard_args)
            else:
                node = memory_manager.create_event_node(**standard_args)
            
            # 添加新节点到向量存储（用于后续查询去重）
            memory_manager.add_node_to_vector_store(
                node_id=node.id,
                entity_name=event_name,
                entity_type=normalized_type,
                description=description
            )
            
            print(f"[STORE_MEMORY] ✓ 记忆已存储: {event_name} (关键词: {normalized_type}, ID: {node.id})")
            return f"✓ 已成功存储记忆:\n  类型: {normalized_type}\n  名称: {event_name}\n  ID: {node.id}\n  提示: 此信息已保存为{normalized_type}节点"
            
        except Exception as e:
            print(f"[STORE_MEMORY] ✗ 错误: {e}")
            return f"存储记忆时出错: {str(e)}"
    
    
    # ========== 工具3：获取访谈摘要 ==========
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
    
    
    # ========== 工具4：检测行为模式 ==========
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
    
    
    # ========== 工具5：按hop查询实体上下文 ==========
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
    
    
    # ========== 工具6：提取并去重访谈记忆 ==========
    def extract_interview_memories_tool(
        interview_text: str = "",
        apply_deduplication: bool = True
    ) -> str:
        """
        使用 MemoryExtractionAgent 从访谈文本中智能提取记忆并进行去重
        
        注意：这个工具在访谈完成后调用，不是在每轮对话中调用
        它会调用 MemoryExtractionAgent 来：
        1. 智能识别5种类型的实体 (Event, Person, Location, Emotion, Topic)
        2. 检查与现有节点的相似性
        3. 根据相似度阈值决定是否创建新节点或合并
        4. 返回去重和合并的统计信息
        """
        
        try:
            from src.agents.memory_extraction_agent import MemoryExtractionAgent
            
            print(f"[EXTRACT_MEMORIES] 触发智能记忆提取和去重 (apply_dedup={apply_deduplication})")
            
            # 创建 MemoryExtractionAgent 实例
            extraction_agent = MemoryExtractionAgent(
                memory_manager=memory_manager,
                interview_id=interview_id,
                dedup_threshold=0.80  # 80% 相似度作为分界线
            )
            
            # 如果没有提供 interview_text，使用访谈摘要
            if not interview_text:
                print(f"[EXTRACT_MEMORIES] 无提供的文本，从图数据库获取访谈摘要...")
                stats = memory_manager.get_graph_statistics(interview_id=interview_id)
                interview_text = f"访谈统计: {json.dumps(stats, ensure_ascii=False)}"
            
            # 调用提取和存储方法
            result = extraction_agent.extract_and_store(interview_text)
            
            print(f"[EXTRACT_MEMORIES] ✓ 提取完成:")
            print(f"  - 提取的实体: {result.get('extracted_count', 0)}")
            print(f"  - 新增节点: {result.get('stored_count', 0)}")
            print(f"  - 已合并: {result.get('merged_count', 0)}")
            print(f"  - 已跳过: {result.get('skipped_count', 0)}")
            print(f"  - 错误数: {len(result.get('errors', []))}")
            
            # 格式化返回结果
            output = f"""✓ 访谈记忆提取完成:
【提取统计】
  - 识别的实体总数: {result.get('extracted_count', 0)}
  - 新创建节点: {result.get('stored_count', 0)}
  - 通过向量去重合并的节点: {result.get('merged_count', 0)}
  - 跳过的节点: {result.get('skipped_count', 0)}

【处理状态】
  - 状态: {result.get('status', 'unknown')}"""
            
            if result.get('errors'):
                output += f"\n【错误信息】\n"
                for error in result.get('errors', [])[:3]:  # 只显示前3个错误
                    output += f"  - {error}\n"
            
            return output
            
        except ImportError as e:
            print(f"[EXTRACT_MEMORIES] ✗ 无法导入 MemoryExtractionAgent: {e}")
            return f"✗ 错误: 无法加载内存提取模块"
        except Exception as e:
            print(f"[EXTRACT_MEMORIES] ✗ 提取失败: {e}")
            return f"✗ 提取记忆时出错: {str(e)}"
    
    
    # ========== 创建工具对象列表 ==========
    tools = [
        FunctionTool(query_memory_tool),
        FunctionTool(store_memory_tool),
        FunctionTool(get_interview_summary_tool),
        FunctionTool(detect_patterns_tool),
        FunctionTool(get_entity_context_tool),
        FunctionTool(extract_interview_memories_tool),
    ]
    
    print(f"[TOOLS] ✓ Created {len(tools)} graph memory tools")
    return tools
