# 记忆提取Agent - 负责智能提取、去重和存储
# 解耦设计：Agent类、工具定义、提示词定义分离

import os
import json
from typing import List, Dict, Any, Optional
from datetime import datetime

from src.agents.base_agents import BaseAgent
from src.memory.vector_storage import VectorStore, create_vector_store
from src.tools.memory_extraction_tools import create_memory_extraction_tools
from prompts.memory_extraction_prompts import (
    get_memory_extraction_system_message,
    get_memory_extraction_step_message,
    get_incremental_extraction_message
)


class MemoryExtractionAgent(BaseAgent):
    """
    记忆提取与去重Agent
    
    职责：
    1. 从对话文本中智能提取实体（事件、人物、地点、情感、观点）
    2. 使用向量相似度查询检测潜在重复
    3. 智能冲突检测与解决（merge/update/create）
    4. 存储到Neo4j图数据库并同步到向量数据库
    
    设计原则：
    - 独立的agent，不占用PlannerAgent的对话时间
    - 支持批量提取（访谈完成后）或增量提取（每轮对话后）
    - 工具、提示词、Agent类完全解耦
    
    用法：
    ```python
    extraction_agent = MemoryExtractionAgent(
        memory_manager=manager,
        interview_id="interview_001"
    )
    
    # 方式1：批量提取（访谈完成后调用一次）
    result = extraction_agent.extract_and_store(full_interview_text)
    
    # 方式2：增量提取（每轮对话后调用）
    result = extraction_agent.incremental_extract(
        turn_number=1,
        interviewee_response="用户的回答",
        context="上下文信息"
    )
    ```
    """
    
    def __init__(
        self,
        memory_manager,
        vector_store: Optional[VectorStore] = None,
        interview_id: str = "default",
        dedup_threshold: float = 0.80,
        max_message_window_size: int = 20
    ):
        """
        初始化记忆提取Agent
        
        Args:
            memory_manager: EnhancedGraphMemoryManager实例（必需）
            vector_store: VectorStore实例（为None则自动创建）
            interview_id: 当前采访ID
            dedup_threshold: 去重相似度阈值（0-1）
            max_message_window_size: 对话历史窗口大小
        """
        # 存储配置
        self.memory_manager = memory_manager
        self.vector_store = vector_store or create_vector_store("auto")
        self.interview_id = interview_id
        self.dedup_threshold = dedup_threshold
        
        # 初始化历史记录
        self.extraction_history: List[Dict] = []
        self.profile_data: Dict[str, Any] = {}
        
        # 创建工具（从独立的工具模块导入）
        tools = create_memory_extraction_tools(self)
        
        # 调用父类初始化
        super().__init__(tools=tools, max_message_window_size=max_message_window_size)
        
        print(f"[MemoryExtractionAgent] ✓ 已初始化 (interview_id={interview_id}, threshold={dedup_threshold})")
    
    def _create_system_message(self):
        """获取系统提示词（从独立模块导入）"""
        return get_memory_extraction_system_message()
    
    def _create_step_message(self, interview_text: str):
        """获取批量提取提示词（从独立模块导入）"""
        return get_memory_extraction_step_message(interview_text)
    
    def _create_incremental_step_message(self, turn_number: int, interviewee_response: str, context: str = ""):
        """获取增量提取提示词（从独立模块导入）"""
        return get_incremental_extraction_message(turn_number, interviewee_response, context)
    
    def extract_and_store(self, interview_text: str) -> Dict[str, Any]:
        """
        【批量模式】在访谈完成后一次性提取所有记忆
        
        Args:
            interview_text: 完整的采访文本
        
        Returns:
            {
                "status": "success|error",
                "extracted_count": int,
                "stored_count": int,
                "merged_count": int,
                "skipped_count": int,
                "errors": []
            }
        """
        print(f"\n[MemoryExtractionAgent] 【批量提取】开始 (文本长度={len(interview_text)})")
        
        try:
            # ========== 第1步：调用LLM进行智能提取 ==========
            input_msg = self._create_step_message(interview_text)
            agent = getattr(self, "agent", None)
            
            if agent and hasattr(agent, 'step'):
                print("[MemoryExtractionAgent] 调用LLM进行批量提取...")
                response = agent.step(input_msg)
                result_text = response.msgs[0].content if response.msgs else "{}"
            else:
                print("[MemoryExtractionAgent] ⚠️ Agent不可用，跳过提取")
                result_text = "{}"
            
            # ========== 第2步：解析LLM返回的JSON ==========
            extraction_result = self.parse_json_response(result_text)
            
            if not extraction_result or "extraction_result" not in extraction_result:
                print("[MemoryExtractionAgent] ⚠️ 无效的JSON响应")
                extraction_result = {"extraction_result": {"final_operations": []}}
            
            ext_res = extraction_result.get("extraction_result", {})
            extracted_count = len(ext_res.get("extracted_entities", []))
            
            # ========== 第3步：执行存储操作 ==========
            stored_count, merged_count, skipped_count, relationship_count, errors, stored_entities = \
                self._execute_storage_operations(ext_res.get("final_operations", []))
            
            # ========== 第4步：返回结果 ==========
            result = {
                "status": "success",
                "mode": "batch",
                "extracted_count": extracted_count,
                "stored_count": stored_count,
                "merged_count": merged_count,
                "skipped_count": skipped_count,
                "relationship_count": relationship_count,
                "stored_entities": stored_entities,
                "errors": errors
            }
            
            print(f"[MemoryExtractionAgent] ✓ 批量提取完成 | 提取={extracted_count} 存储={stored_count} 合并={merged_count} 跳过={skipped_count} 关系={relationship_count}")
            
            # 保存到历史
            self._save_extraction_history("batch", result)
            
            return result
        
        except Exception as e:
            error_msg = f"记忆提取失败: {str(e)}"
            print(f"[MemoryExtractionAgent] ✗ {error_msg}")
            return {
                "status": "error",
                "mode": "batch",
                "message": error_msg,
                "extracted_count": 0,
                "stored_count": 0,
                "merged_count": 0,
                "skipped_count": 0,
                "errors": [error_msg]
            }
    
    def incremental_extract(
        self,
        turn_number: int,
        interviewee_response: str,
        context: str = ""
    ) -> Dict[str, Any]:
        """
        【增量模式】在每轮对话后进行增量式记忆提取
        
        这个方法应该在每轮对话完成后调用，用于及时更新记忆图而不等待整个访谈完成。
        
        Args:
            turn_number: 对话轮数
            interviewee_response: 被访谈者在本轮的回答
            context: 可选的上下文（如当前的Planner决策、对话主题等）
        
        Returns:
            {
                "status": "success|error",
                "mode": "incremental",
                "turn": int,
                "extracted_count": int,
                "stored_count": int,
                "merged_count": int,
                "errors": []
            }
        """
        print(f"\n[MemoryExtractionAgent] 【增量提取】第{turn_number}轮 (回答长度={len(interviewee_response)})")
        
        try:
            # ========== 第1步：调用LLM进行增量提取 ==========
            input_msg = self._create_incremental_step_message(
                turn_number,
                interviewee_response,
                context
            )
            agent = getattr(self, "agent", None)
            
            if agent and hasattr(agent, 'step'):
                print(f"[MemoryExtractionAgent] 调用LLM进行第{turn_number}轮增量提取...")
                response = agent.step(input_msg)
                result_text = response.msgs[0].content if response.msgs else "{}"
            else:
                print("[MemoryExtractionAgent] ⚠️ Agent不可用，跳过提取")
                result_text = "{}"
            
            # ========== 第2步：解析LLM返回的JSON ==========
            extraction_result = self.parse_json_response(result_text)
            
            if not extraction_result or "extraction_result" not in extraction_result:
                print(f"[MemoryExtractionAgent] 第{turn_number}轮无新实体提取")
                extraction_result = {"extraction_result": {"final_operations": []}}
            
            ext_res = extraction_result.get("extraction_result", {})
            extracted_count = len(ext_res.get("extracted_entities", []))
            
            # ========== 第3步：执行存储操作 ==========
            stored_count, merged_count, skipped_count, relationship_count, errors, stored_entities = \
                self._execute_storage_operations(ext_res.get("final_operations", []))
            
            # ========== 第4步：返回结果 ==========
            result = {
                "status": "success",
                "mode": "incremental",
                "turn": turn_number,
                "extracted_count": extracted_count,
                "stored_count": stored_count,
                "merged_count": merged_count,
                "skipped_count": skipped_count,
                "relationship_count": relationship_count,
                "stored_entities": stored_entities,
                "errors": errors
            }
            
            if extracted_count > 0:
                print(f"[MemoryExtractionAgent] ✓ 第{turn_number}轮增量提取完成 | 提取={extracted_count} 存储={stored_count} 合并={merged_count} 关系={relationship_count}")
            
            # 保存到历史
            self._save_extraction_history("incremental", result, turn_number)
            
            return result
        
        except Exception as e:
            error_msg = f"第{turn_number}轮增量提取失败: {str(e)}"
            print(f"[MemoryExtractionAgent] ✗ {error_msg}")
            return {
                "status": "error",
                "mode": "incremental",
                "turn": turn_number,
                "message": error_msg,
                "extracted_count": 0,
                "stored_count": 0,
                "merged_count": 0,
                "skipped_count": 0,
                "errors": [error_msg]
            }
    
    def _execute_storage_operations(self, operations: List[Dict]) -> tuple:
        """
        执行存储操作（create/merge/skip/create_relationship）
        
        Returns:
            (stored_count, merged_count, skipped_count, relationship_count, errors, stored_entities)
        """
        stored_count = 0
        merged_count = 0
        skipped_count = 0
        relationship_count = 0
        errors = []
        stored_entities = []
        
        # First pass: handle entity creation and merging
        entity_id_mapping = {}  # Map temp IDs from LLM to actual node IDs
        
        for operation in operations:
            try:
                action = operation.get("action", "create")
                
                if action == "create":
                    entity = operation.get("entity", {})
                    if not entity:
                        continue
                    
                    print(f"  → 创建新节点: {entity.get('name')}")
                    node = self.memory_manager.insert_memory(
                        entity_name=entity.get('name', '未命名'),
                        entity_type=entity.get('type', 'Event'),
                        description=entity.get('description', ''),
                        key_details=entity.get('key_details', ''),
                        interview_id=self.interview_id
                    )
                    
                    # Store mapping from temp ID to actual node ID
                    if 'id' in entity:
                        entity_id_mapping[entity['id']] = node['id']
                        print(f"    [ID MAPPING] {entity['id']} → {node['id']}")
                    
                    # 存储向量
                    text_for_embedding = f"{entity.get('name')} ({entity.get('type')}) {entity.get('description', '')}"
                    self.vector_store.add(
                        node_id=node['id'],
                        text=text_for_embedding,
                        metadata={
                            "node_id": node['id'],
                            "name": entity.get('name'),
                            "type": entity.get('type'),
                            "interview_id": self.interview_id
                        }
                    )
                    
                    stored_count += 1
                    stored_entities.append(node)
                
                elif action == "merge":
                    merge_with_id = operation.get("merge_with_id")
                    entity = operation.get("entity", {})
                    
                    print(f"  → 合并节点: {entity.get('name')} -> {merge_with_id}")
                    
                    # Store mapping from temp ID to merge target ID
                    if 'id' in entity:
                        entity_id_mapping[entity['id']] = merge_with_id
                        print(f"    [ID MAPPING] {entity['id']} → {merge_with_id} (merge)")
                    
                    if merge_with_id:
                        existing = self.memory_manager.get_node_by_id(merge_with_id)
                        
                        if existing:
                            text_for_embedding = f"{existing.get('name')} ({existing.get('type')}) {existing.get('description', '')}"
                            self.vector_store.update(
                                node_id=merge_with_id,
                                text=text_for_embedding,
                                metadata={
                                    "name": existing.get('name'),
                                    "type": existing.get('type'),
                                    "interview_id": self.interview_id
                                }
                            )
                            merged_count += 1
                
                elif action == "skip":
                    print(f"  → 跳过: {operation.get('entity', {}).get('name')}")
                    skipped_count += 1
            
            except Exception as e:
                error_msg = f"执行{action}操作失败: {str(e)}"
                print(f"  ✗ {error_msg}")
                errors.append(error_msg)
        
        # Second pass: handle relationships with actual node IDs
        for operation in operations:
            try:
                action = operation.get("action")
                
                if action == "create_relationship":
                    source_id = operation.get("source_id")
                    target_id = operation.get("target_id")
                    relation_type = operation.get("relation_type")
                    
                    # Map temp IDs to actual node IDs
                    actual_source_id = entity_id_mapping.get(source_id, source_id)
                    actual_target_id = entity_id_mapping.get(target_id, target_id)
                    
                    print(f"  → 创建关系: {actual_source_id} -[{relation_type}]-> {actual_target_id}")
                    
                    success = self.memory_manager.insert_edge(
                        source_id=actual_source_id,
                        target_id=actual_target_id,
                        relation_type=relation_type,
                        properties={}
                    )
                    
                    if success:
                        relationship_count += 1
                    else:
                        error_msg = f"Failed to create relationship: {actual_source_id} -[{relation_type}]-> {actual_target_id}"
                        print(f"  ✗ {error_msg}")
                        errors.append(error_msg)
            
            except Exception as e:
                error_msg = f"执行关系操作失败: {str(e)}"
                print(f"  ✗ {error_msg}")
                errors.append(error_msg)
        
        return stored_count, merged_count, skipped_count, relationship_count, errors, stored_entities
    
    def _save_extraction_history(self, mode: str, result: Dict, turn_number: int = None):
        """保存提取历史"""
        history_entry = {
            "timestamp": datetime.now().isoformat(),
            "interview_id": self.interview_id,
            "mode": mode,
            "result": result
        }
        if turn_number is not None:
            history_entry["turn"] = turn_number
        
        self.extraction_history.append(history_entry)
    
    def respond(self, message: str) -> str:
        """
        兼容BaseAgent的respond接口
        
        Args:
            message: 采访文本
        
        Returns:
            JSON格式的提取结果
        """
        result = self.extract_and_store(message)
        return json.dumps(result, ensure_ascii=False, indent=2)
    
    def get_extraction_history(self) -> List[Dict]:
        """获取提取历史"""
        return self.extraction_history
    
    def get_vector_store_stats(self) -> Dict[str, Any]:
        """获取向量存储统计信息"""
        if hasattr(self.vector_store, 'get_stats'):
            return self.vector_store.get_stats()
        return {}
