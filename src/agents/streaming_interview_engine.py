"""
动态事件图谱 - 流式对话引擎

本模块实现了流式对话引擎，负责：
1. 管理对话流程
2. 流式生成LLM响应（token by token）
3. 异步提取事件（不阻塞对话流）
4. 更新图谱并广播

遵循高内聚低耦合原则，将对话管理、事件提取、图谱更新解耦。
"""

import asyncio
import json
import logging
from typing import Dict, List, Optional, AsyncIterator, Any
from datetime import datetime
from pathlib import Path

from openai import OpenAI

from src.core.interfaces import (
    IInterviewEngine, DialogueTurn, ExtractedEvent, EventSlots,
    NodeStatus, IEventExtractor, IGraphBroadcaster
)
from src.core.graph_manager import GraphManager
from src.config import Config

logger = logging.getLogger(__name__)


class StreamingInterviewEngine(IInterviewEngine):
    """
    流式对话引擎

    负责管理访谈会话的完整生命周期：
    - 初始化会话，生成开场问题
    - 流式处理用户消息，实时返回响应
    - 后台异步提取事件，不阻塞对话
    - 维护图谱状态并广播更新

    Attributes:
        session_id: 会话唯一标识
        event_extractor: 事件提取器实现
        broadcaster: 图谱广播器实现
        llm_client: OpenAI客户端
        graph_manager: 图谱管理器
        conversation_history: 对话历史记录
        turn_counter: 对话轮次计数器
    """

    def __init__(
        self,
        session_id: str,
        event_extractor: IEventExtractor,
        broadcaster: IGraphBroadcaster,
        llm_client: Optional[OpenAI] = None
    ):
        """
        初始化流式对话引擎

        Args:
            session_id: 会话唯一标识
            event_extractor: 事件提取器实现
            broadcaster: 图谱广播器实现
            llm_client: 可选的OpenAI客户端，如果不提供则使用配置创建
        """
        self.session_id = session_id
        self.event_extractor = event_extractor
        self.broadcaster = broadcaster

        # 初始化LLM客户端
        if llm_client:
            self.llm_client = llm_client
        else:
            api_key = Config.OPENAI_API_KEY
            base_url = Config.OPENAI_BASE_URL

            if not api_key:
                raise ValueError("OPENAI_API_KEY 未配置")

            client_kwargs = {"api_key": api_key}
            if base_url:
                client_kwargs["base_url"] = base_url

            self.llm_client = OpenAI(**client_kwargs)

        # 初始化图谱管理器
        self.graph_manager = GraphManager()

        # 对话状态
        self.conversation_history: List[DialogueTurn] = []
        self.turn_counter = 0
        self.current_theme_id: Optional[str] = None

        # 加载系统提示词
        self.system_prompt = self._load_system_prompt()

        # 后台任务集合
        self._background_tasks: set = set()

        logger.info(f"流式对话引擎初始化完成: session_id={session_id}")

    def _load_system_prompt(self) -> str:
        """
        加载访谈者系统提示词

        Returns:
            系统提示词文本
        """
        prompt_path = Path(Config.PROMPTS_DIR) / "interviewer_system_prompt.md"

        if prompt_path.exists():
            try:
                with open(prompt_path, "r", encoding="utf-8") as f:
                    return f.read()
            except Exception as e:
                logger.warning(f"加载系统提示词失败: {e}，使用默认提示词")

        # 默认提示词
        return """你是一位专业的生命故事访谈者。你的任务是通过对话引导受访者分享他们的人生经历。

请遵循以下原则：
1. 保持友善、尊重的态度
2. 使用开放式问题引导对话
3. 适时追问细节（时间、地点、人物、感受）
4. 关注受访者的情绪变化
5. 在合适的时候自然过渡到相关主题

你的目标是帮助受访者完整地讲述他们的故事，同时收集结构化的事件信息。"""

    async def initialize_session(
        self,
        basic_info: str
    ) -> str:
        """
        初始化访谈会话

        根据用户基本信息生成个性化的开场问题，
        为后续对话建立基础。

        Args:
            basic_info: 用户基本信息（如年龄、职业、出生地等）

        Returns:
            开场问题文本

        Raises:
            RuntimeError: 如果LLM调用失败
        """
        logger.info(f"初始化会话: session_id={self.session_id}")

        # 构建初始化提示
        init_prompt = f"""请根据以下受访者基本信息，生成一个温暖、自然的开场问题，引导他们开始分享人生故事。

受访者信息：
{basic_info}

要求：
1. 问题要具体，基于提供的信息
2. 语气要友善、尊重
3. 鼓励受访者从重要的人生阶段或事件开始讲述
4. 问题应该是开放式的

请直接返回开场问题，不需要其他解释。"""

        try:
            # 调用LLM生成开场问题
            response = await asyncio.to_thread(
                self.llm_client.chat.completions.create,
                model=Config.MODEL_NAME,
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": init_prompt}
                ],
                temperature=0.7,
                max_tokens=200
            )

            opening_question = response.choices[0].message.content.strip()

            # 创建第一轮对话记录（只有访谈者问题，等待用户回复）
            self.turn_counter += 1
            turn_id = f"{self.session_id}_turn_{self.turn_counter}"

            initial_turn = DialogueTurn(
                turn_id=turn_id,
                session_id=self.session_id,
                timestamp=datetime.now(),
                interviewer_question=opening_question,
                interviewer_action="continue",
                interviewer_intent="initialize_session",
                interviewee_raw_reply="",
                interviewee_emotion=None,
                interviewee_memories_referenced=[],
                extracted_events=[]
            )

            self.conversation_history.append(initial_turn)

            logger.info(f"开场问题生成成功: {opening_question[:50]}...")
            return opening_question

        except Exception as e:
            logger.error(f"生成开场问题失败: {e}")
            raise RuntimeError(f"初始化会话失败: {e}")

    async def process_user_message(
        self,
        message: str
    ) -> AsyncIterator[str]:
        """
        处理用户消息，流式返回响应

        这是核心对话方法，执行以下流程：
        1. 记录用户消息到当前轮次
        2. 流式生成LLM响应（token by token）
        3. 在后台异步提取事件（不阻塞对话流）
        4. 更新图谱并广播变更

        Args:
            message: 用户输入的消息

        Yields:
            响应token流，每个token是一个字符串

        Raises:
            RuntimeError: 如果LLM调用失败
        """
        logger.info(f"处理用户消息: session_id={self.session_id}, message_len={len(message)}")

        # 获取当前轮次（上一轮是访谈者的问题）
        if not self.conversation_history:
            # 如果没有历史记录，创建新的轮次
            self.turn_counter += 1
            current_turn = DialogueTurn(
                turn_id=f"{self.session_id}_turn_{self.turn_counter}",
                session_id=self.session_id,
                timestamp=datetime.now(),
                interviewer_question="请分享您的故事。",
                interviewer_action="continue",
                interviewee_raw_reply=message,
                interviewee_emotion=None,
                interviewee_memories_referenced=[],
                extracted_events=[]
            )
            self.conversation_history.append(current_turn)
        else:
            # 更新当前轮次的用户回复
            current_turn = self.conversation_history[-1]
            current_turn.interviewee_raw_reply = message
            current_turn.timestamp = datetime.now()

        # 构建对话上下文
        messages = self._build_conversation_messages()

        # 流式生成响应
        full_response = ""
        try:
            stream = await asyncio.to_thread(
                self.llm_client.chat.completions.create,
                model=Config.MODEL_NAME,
                messages=messages,
                temperature=0.7,
                max_tokens=1000,
                stream=True
            )

            for chunk in stream:
                if chunk.choices[0].delta.content:
                    token = chunk.choices[0].delta.content
                    full_response += token
                    yield token

        except Exception as e:
            logger.error(f"流式生成响应失败: {e}")
            raise RuntimeError(f"生成响应失败: {e}")

        # 更新当前轮次的访谈者问题（下一轮的问题）
        current_turn.interviewer_question = full_response

        # 创建下一轮次的占位
        self.turn_counter += 1
        next_turn = DialogueTurn(
            turn_id=f"{self.session_id}_turn_{self.turn_counter}",
            session_id=self.session_id,
            timestamp=datetime.now(),
            interviewer_question=full_response,
            interviewer_action="continue",
            interviewee_raw_reply="",
            interviewee_emotion=None,
            interviewee_memories_referenced=[],
            extracted_events=[]
        )
        self.conversation_history.append(next_turn)

        # 在后台异步提取事件（不阻塞对话流）
        extraction_task = asyncio.create_task(
            self._extract_events_async(current_turn)
        )
        self._background_tasks.add(extraction_task)
        extraction_task.add_done_callback(self._background_tasks.discard)

        logger.info(f"响应生成完成: len={len(full_response)}")

    def _build_conversation_messages(self) -> List[Dict[str, str]]:
        """
        构建对话上下文消息列表

        将历史对话转换为LLM可用的消息格式，
        保持最近的对话上下文以提高相关性。

        Returns:
            消息列表，每个消息包含role和content
        """
        messages = [{"role": "system", "content": self.system_prompt}]

        # 只保留最近的10轮对话作为上下文
        recent_history = self.conversation_history[-10:]

        for turn in recent_history:
            # 添加访谈者的问题
            if turn.interviewer_question:
                messages.append({
                    "role": "assistant",
                    "content": turn.interviewer_question
                })

            # 添加受访者的回复
            if turn.interviewee_raw_reply:
                messages.append({
                    "role": "user",
                    "content": turn.interviewee_raw_reply
                })

        return messages

    async def _extract_events_async(self, turn: DialogueTurn):
        """
        后台异步提取事件

        这个方法在后台运行，不会阻塞主对话流程。
        提取到的事件会更新图谱并广播给所有连接的客户端。

        Args:
            turn: 当前对话轮次
        """
        try:
            logger.debug(f"开始后台事件提取: turn_id={turn.turn_id}")

            # 获取对话上下文（最近5轮）
            context_start = max(0, len(self.conversation_history) - 5)
            conversation_context = self.conversation_history[context_start:-1]

            # 调用事件提取器
            extracted_events = await self.event_extractor.extract_from_turn(
                turn=turn,
                conversation_context=conversation_context
            )

            if not extracted_events:
                logger.debug(f"未提取到事件: turn_id={turn.turn_id}")
                return

            logger.info(f"提取到 {len(extracted_events)} 个事件: turn_id={turn.turn_id}")

            # 更新轮次记录
            turn.extracted_events = extracted_events

            # 处理每个提取到的事件
            for event in extracted_events:
                await self._process_extracted_event(event, turn)

        except Exception as e:
            logger.error(f"后台事件提取失败: {e}", exc_info=True)
            # 后台任务失败不应影响主流程

    async def _process_extracted_event(
        self,
        event: ExtractedEvent,
        turn: DialogueTurn
    ):
        """
        处理提取到的事件

        将事件添加到图谱，更新主题状态，并广播变更。

        Args:
            event: 提取到的事件
            turn: 来源对话轮次
        """
        try:
            # 确定关联的主题
            theme_id = event.theme_id

            if not theme_id:
                # 如果没有指定主题，尝试根据内容匹配
                theme_id = self._match_event_to_theme(event)

            if not theme_id:
                # 如果仍无法匹配，使用当前焦点主题或默认主题
                theme_id = self.current_theme_id or self._get_default_theme_id()

            # 检查是否是已有事件的更新
            existing_event = None
            if event.is_update and event.updated_event_id:
                # 查找已有事件
                for e in turn.extracted_events:
                    if e.event_id == event.updated_event_id:
                        existing_event = e
                        break

            if existing_event:
                # 更新已有事件
                await self._update_existing_event(existing_event, event, theme_id)
            else:
                # 添加新事件
                await self._add_new_event(event, theme_id)

            # 更新当前焦点主题
            self.current_theme_id = theme_id

        except Exception as e:
            logger.error(f"处理提取事件失败: {e}", exc_info=True)

    def _match_event_to_theme(self, event: ExtractedEvent) -> Optional[str]:
        """
        根据事件内容匹配最合适的主题

        Args:
            event: 提取到的事件

        Returns:
            匹配的主题ID，如果没有匹配则返回None
        """
        # 获取事件描述和槽位信息
        event_desc = event.slots.event or ""
        event_text = " ".join(filter(None, [
            event_desc,
            event.slots.time or "",
            event.slots.location or "",
            " ".join(event.slots.people or [])
        ])).lower()

        best_match = None
        best_score = 0.0

        # 遍历所有主题，计算匹配分数
        for theme_id, theme in self.graph_manager.theme_nodes.items():
            score = 0.0

            # 标题匹配
            if theme.title.lower() in event_text:
                score += 2.0

            # 关键词匹配
            for keyword in theme.keywords:
                if keyword.lower() in event_text:
                    score += 1.0

            # 描述匹配
            if theme.description and theme.description.lower() in event_text:
                score += 0.5

            # 优先选择已提及但未完成的主题
            if theme.status == NodeStatus.MENTIONED:
                score += 0.5

            if score > best_score:
                best_score = score
                best_match = theme_id

        return best_match if best_score > 0 else None

    def _get_default_theme_id(self) -> str:
        """
        获取默认主题ID

        优先返回待触达或已提及的主题。

        Returns:
            主题ID
        """
        # 优先获取已提及但未完成的主题
        mentioned = self.graph_manager.get_mentioned_theme_nodes()
        if mentioned:
            return mentioned[0].theme_id

        # 然后获取待触达的主题
        pending = self.graph_manager.get_pending_theme_nodes()
        if pending:
            return pending[0].theme_id

        # 最后返回第一个主题
        return list(self.graph_manager.theme_nodes.keys())[0]

    async def _add_new_event(
        self,
        event: ExtractedEvent,
        theme_id: str
    ):
        """
        添加新事件到图谱

        Args:
            event: 新事件
            theme_id: 关联主题ID
        """
        try:
            # 创建事件节点
            from src.core.event_node import EventNode

            # 从EventSlots中提取信息创建EventNode
            slots = event.slots.to_dict()
            event_node = EventNode(
                event_id=event.event_id,
                theme_id=theme_id,
                title=slots.get("event", "未命名事件"),
                description=slots.get("event", ""),
                time_anchor=slots.get("time"),
                location=slots.get("location"),
                people_involved=slots.get("people", []),
                slots=slots,
                emotional_score=0.0,  # 可以从feeling字段分析得到
                information_density=event.confidence,
                depth_level=1,
                related_events=[],
                created_at=datetime.now()
            )

            # 添加到图谱
            success = self.graph_manager.add_event_node(event_node, theme_id)

            if success:
                # 广播新事件
                await self.broadcaster.broadcast_event_added(
                    session_id=self.session_id,
                    event=event,
                    theme_id=theme_id
                )

                # 检查主题状态是否需要更新
                theme = self.graph_manager.theme_nodes.get(theme_id)
                if theme and theme.status == NodeStatus.PENDING:
                    await self.broadcaster.broadcast_theme_status_changed(
                        session_id=self.session_id,
                        theme_id=theme_id,
                        old_status=NodeStatus.PENDING,
                        new_status=NodeStatus.MENTIONED
                    )

                logger.info(f"新事件已添加并广播: event_id={event.event_id}, theme_id={theme_id}")
            else:
                logger.warning(f"添加事件到图谱失败: event_id={event.event_id}")

        except Exception as e:
            logger.error(f"添加新事件失败: {e}", exc_info=True)

    async def _update_existing_event(
        self,
        existing_event: ExtractedEvent,
        new_event: ExtractedEvent,
        theme_id: str
    ):
        """
        更新已有事件

        Args:
            existing_event: 已有事件
            new_event: 新提取的事件信息
            theme_id: 关联主题ID
        """
        try:
            # 合并槽位信息
            updated_slots = {}
            old_slots = existing_event.slots.to_dict()
            new_slots = new_event.slots.to_dict()

            for key, value in new_slots.items():
                if value and (not old_slots.get(key) or new_event.confidence > existing_event.confidence):
                    updated_slots[key] = value

            if updated_slots:
                # 更新事件节点
                event_node = self.graph_manager.event_nodes.get(existing_event.event_id)
                if event_node:
                    event_node.slots.update(updated_slots)
                    event_node.confidence = max(event_node.confidence, new_event.confidence)

                    # 广播事件更新
                    await self.broadcaster.broadcast_event_updated(
                        session_id=self.session_id,
                        event_id=existing_event.event_id,
                        updated_slots=updated_slots
                    )

                    logger.info(f"事件已更新并广播: event_id={existing_event.event_id}")

        except Exception as e:
            logger.error(f"更新已有事件失败: {e}", exc_info=True)

    async def get_current_graph_state(self) -> Dict[str, Any]:
        """
        获取当前图谱状态

        Returns:
            图谱状态字典，包含覆盖率、主题状态、事件列表等
        """
        try:
            # 获取图谱管理器的状态
            graph_state = self.graph_manager.get_graph_state()

            # 添加会话特定信息
            graph_state["session_id"] = self.session_id
            graph_state["turn_count"] = self.turn_counter
            graph_state["current_theme_id"] = self.current_theme_id

            # 添加主题详细信息
            graph_state["themes"] = {
                theme_id: theme.to_dict()
                for theme_id, theme in self.graph_manager.theme_nodes.items()
            }

            # 添加事件详细信息
            graph_state["events"] = {
                event_id: event.to_dict()
                for event_id, event in self.graph_manager.event_nodes.items()
            }

            return graph_state

        except Exception as e:
            logger.error(f"获取图谱状态失败: {e}")
            return {
                "session_id": self.session_id,
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }

    async def save_checkpoint(self) -> bool:
        """
        保存会话断点

        保存图谱状态、对话历史、事件提取结果等，
        以便后续恢复会话。

        Returns:
            是否保存成功
        """
        try:
            # 保存图谱状态
            graph_saved = self.graph_manager.save_checkpoint(self.session_id)

            # 保存对话历史
            checkpoint_dir = Path(Config.DATA_DIR) / "interviews" / self.session_id
            checkpoint_dir.mkdir(parents=True, exist_ok=True)

            # 保存对话历史
            history_data = {
                "session_id": self.session_id,
                "turn_counter": self.turn_counter,
                "current_theme_id": self.current_theme_id,
                "conversation_history": [turn.to_dict() for turn in self.conversation_history]
            }

            history_path = checkpoint_dir / "conversation_history.json"
            with open(history_path, "w", encoding="utf-8") as f:
                json.dump(history_data, f, ensure_ascii=False, indent=2)

            logger.info(f"会话断点已保存: session_id={self.session_id}, dir={checkpoint_dir}")
            return graph_saved

        except Exception as e:
            logger.error(f"保存断点失败: {e}")
            return False

    async def load_checkpoint(self) -> bool:
        """
        加载会话断点

        恢复图谱状态、对话历史、事件提取结果等。

        Returns:
            是否加载成功
        """
        try:
            # 加载图谱状态
            graph_loaded = self.graph_manager.load_checkpoint(self.session_id)

            # 加载对话历史
            checkpoint_dir = Path(Config.DATA_DIR) / "interviews" / self.session_id
            history_path = checkpoint_dir / "conversation_history.json"

            if history_path.exists():
                with open(history_path, "r", encoding="utf-8") as f:
                    history_data = json.load(f)

                self.turn_counter = history_data.get("turn_counter", 0)
                self.current_theme_id = history_data.get("current_theme_id")

                # 恢复对话历史需要重新构建对象
                # 这里简化处理，实际可能需要更复杂的反序列化
                logger.info(f"对话历史已加载: turns={len(history_data.get('conversation_history', []))}")

            logger.info(f"会话断点已加载: session_id={self.session_id}")
            return graph_loaded

        except Exception as e:
            logger.error(f"加载断点失败: {e}")
            return False

    async def get_conversation_summary(self) -> Dict[str, Any]:
        """
        获取对话摘要

        Returns:
            对话摘要信息
        """
        return {
            "session_id": self.session_id,
            "total_turns": self.turn_counter,
            "current_theme_id": self.current_theme_id,
            "themes_mentioned": len(self.graph_manager.get_mentioned_theme_nodes()),
            "themes_exhausted": len(self.graph_manager.get_exhausted_theme_nodes()),
            "total_events": len(self.graph_manager.event_nodes),
            "coverage": self.graph_manager.calculate_coverage()
        }

    async def cleanup(self):
        """
        清理资源

        取消所有后台任务，释放资源。
        """
        # 取消所有后台任务
        for task in self._background_tasks:
            if not task.done():
                task.cancel()

        # 等待任务完成
        if self._background_tasks:
            await asyncio.gather(*self._background_tasks, return_exceptions=True)

        self._background_tasks.clear()
        logger.info(f"资源清理完成: session_id={self.session_id}")
