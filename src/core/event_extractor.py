"""
动态事件图谱 - 事件提取器模块

基于LLM的事件提取器实现，支持异步提取和队列控制。
"""

import asyncio
import json
import logging
import uuid
from difflib import SequenceMatcher
from typing import List, Optional
from datetime import datetime
from openai import OpenAI

from src.core.interfaces import (
    IEventExtractor, ExtractedEvent, EventSlots,
    DialogueTurn
)
from src.config import Config

logger = logging.getLogger(__name__)


class EventExtractor(IEventExtractor):
    """
    基于LLM的事件提取器

    使用OpenAI API从对话中提取结构化事件，支持异步处理和队列控制。

    Attributes:
        client: OpenAI客户端实例
        model: 使用的模型名称
        extraction_queue: 异步提取任务队列
        is_extracting: 是否正在执行提取任务
        similarity_threshold: 事件相似度阈值（默认0.7）
    """

    def __init__(self, client: Optional[OpenAI] = None):
        """
        初始化事件提取器

        Args:
            client: 可选的OpenAI客户端实例，如果未提供则使用配置创建
        """
        # 初始化OpenAI客户端
        self.client = client or OpenAI(
            api_key=Config.OPENAI_API_KEY,
            base_url=Config.OPENAI_BASE_URL
        )
        self.model = Config.MODEL_NAME

        # 异步队列控制
        self.extraction_queue = asyncio.Queue()
        self.is_extracting = False
        self._worker_task: Optional[asyncio.Task] = None

        # 相似度阈值
        self.similarity_threshold = 0.7

        # 加载提示词模板
        self._prompt_template = self._load_prompt_template()

        logger.info(f"EventExtractor initialized with model: {self.model}")

    def _load_prompt_template(self) -> str:
        """
        加载提示词模板文件

        Returns:
            提示词模板字符串
        """
        try:
            with open(
                f"{Config.PROMPTS_DIR}/event_extraction_prompt.md",
                "r",
                encoding="utf-8"
            ) as f:
                return f.read()
        except FileNotFoundError:
            logger.error("Event extraction prompt file not found")
            # 返回默认提示词模板
            return self._get_default_prompt_template()
        except Exception as e:
            logger.error(f"Error loading prompt template: {e}")
            return self._get_default_prompt_template()

    def _get_default_prompt_template(self) -> str:
        """
        获取默认提示词模板（当文件加载失败时使用）

        Returns:
            默认提示词模板字符串
        """
        return """# 事件提取提示词

请从以下对话内容中提取关键事件，并以JSON格式返回。

## 输出格式

```json
{
  "events": [
    {
      "time": "时间描述",
      "location": "地点描述",
      "people": ["人物1", "人物2"],
      "event": "事件描述",
      "feeling": "感受描述",
      "unexpanded_clues": "未展开线索（如：具体细节未展开、新人物背景未说明）",
      "cause": "起因（如有）",
      "result": "结果（如有）",
      "reflection": "反思（如有）"
    }
  ],
  "confidence": 0.85
}
```

## 输入数据

### 当前对话轮次
- 访谈者问题: {interviewer_question}
- 受访者回复: {interviewee_reply}

### 对话上下文（最近{context_length}轮）
{conversation_context}

## 注意事项

1. 只提取JSON数据，不要添加其他说明文字
2. 如果没有提取到任何事件，返回 `{"events": [], "confidence": 0}`
3. 确保JSON格式正确
"""

    def _format_context(self, context: List[DialogueTurn]) -> str:
        """
        格式化对话上下文

        Args:
            context: 对话轮次列表

        Returns:
            格式化后的上下文字符串
        """
        if not context:
            return "无"

        formatted = []
        for i, turn in enumerate(context, 1):
            formatted.append(
                f"轮次{i}:\n"
                f"  问: {turn.interviewer_question}\n"
                f"  答: {turn.interviewee_raw_reply}"
            )
        return "\n\n".join(formatted)

    def _build_prompt(
        self,
        turn: DialogueTurn,
        conversation_context: List[DialogueTurn]
    ) -> str:
        """
        构建完整的提示词

        根据新的提示词格式，构建JSON格式的输入数据。

        Args:
            turn: 当前对话轮次
            conversation_context: 对话上下文

        Returns:
            完整的提示词字符串（JSON格式输入）
        """
        # 构建上下文列表
        context_list = []
        for i, ctx_turn in enumerate(conversation_context[-3:], start=-len(conversation_context[-3:])):
            context_list.append({
                "turn": i,
                "interviewer": ctx_turn.interviewer_question,
                "respondent": ctx_turn.interviewee_raw_reply
            })

        # 构建输入JSON
        input_data = {
            "current_turn": {
                "interviewer": turn.interviewer_question,
                "respondent": turn.interviewee_raw_reply
            },
            "context": context_list,
            "existing_events": []  # 可扩展为传入已有事件
        }

        # 返回提示词模板 + JSON输入
        return f"""{self._prompt_template}

## 当前输入数据

```json
{json.dumps(input_data, ensure_ascii=False, indent=2)}
```

请根据以上输入数据，按照输出格式要求返回事件提取结果。
"""

    def _parse_llm_response(self, response_text: str) -> tuple[List[dict], float, Optional[str], bool]:
        """
        解析LLM的JSON响应

        根据新的提示词格式，解析包含 has_event, events, is_update, related_event_id 的响应。

        Args:
            response_text: LLM返回的原始文本

        Returns:
            (事件列表, 置信度, 关联事件ID, 是否为更新) 元组
        """
        try:
            # 清理响应文本，提取JSON部分
            # 处理可能的markdown代码块
            if "```json" in response_text:
                json_str = response_text.split("```json")[1].split("```")[0].strip()
            elif "```" in response_text:
                json_str = response_text.split("```")[1].split("```")[0].strip()
            else:
                json_str = response_text.strip()

            data = json.loads(json_str)

            # 检查是否有事件
            has_event = data.get("has_event", False)
            if not has_event:
                return [], 0.0, None, False

            events = data.get("events", [])
            is_update = data.get("is_update", False)
            related_event_id = data.get("related_event_id")

            # 验证事件数据并提取置信度
            validated_events = []
            for event_data in events:
                if "slots" in event_data and event_data["slots"].get("event"):
                    # 合并slots和extended_slots
                    slots = event_data.get("slots", {})
                    extended_slots = event_data.get("extended_slots", {})
                    merged_event = {**slots, **extended_slots}
                    merged_event["title"] = event_data.get("title", "")
                    merged_event["theme_hint"] = event_data.get("theme_hint")
                    merged_event["event_confidence"] = event_data.get("confidence", 0.5)
                    validated_events.append(merged_event)

            # 计算平均置信度
            avg_confidence = sum(
                e.get("event_confidence", 0.5) for e in validated_events
            ) / len(validated_events) if validated_events else 0.0

            return validated_events, avg_confidence, related_event_id, is_update

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response as JSON: {e}")
            logger.debug(f"Response text: {response_text}")
            return [], 0.0, None, False
        except Exception as e:
            logger.error(f"Error parsing LLM response: {e}")
            return [], 0.0, None, False

    def _create_event_from_data(
        self,
        event_data: dict,
        confidence: float,
        turn: DialogueTurn,
        is_update: bool = False,
        related_event_id: Optional[str] = None
    ) -> ExtractedEvent:
        """
        从解析的数据创建ExtractedEvent对象

        Args:
            event_data: 解析后的事件数据字典
            confidence: 置信度分数
            turn: 来源对话轮次
            is_update: 是否为更新事件
            related_event_id: 关联的已有事件ID

        Returns:
            ExtractedEvent对象
        """
        slots = EventSlots(
            time=event_data.get("time"),
            location=event_data.get("location"),
            people=event_data.get("people"),
            event=event_data.get("event"),
            feeling=event_data.get("feeling"),
            unexpanded_clues=event_data.get("unexpanded_clues"),
            cause=event_data.get("cause"),
            result=event_data.get("result"),
            reflection=event_data.get("reflection")
        )

        return ExtractedEvent(
            event_id=f"evt_{uuid.uuid4().hex[:12]}",
            extracted_at=datetime.now(),
            slots=slots,
            confidence=confidence,
            theme_id=event_data.get("theme_hint"),
            source_turns=[turn.turn_id],
            is_update=is_update,
            updated_event_id=related_event_id if is_update else None
        )

    async def _call_llm(self, prompt: str) -> str:
        """
        异步调用LLM API

        Args:
            prompt: 提示词

        Returns:
            LLM响应文本
        """
        try:
            # 使用线程池执行同步的OpenAI调用
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {
                            "role": "system",
                            "content": "你是一个专业的事件提取助手，负责从访谈对话中提取结构化事件信息。"
                        },
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.3,  # 较低温度以获得更稳定的输出
                    max_tokens=2000
                )
            )

            return response.choices[0].message.content or ""

        except Exception as e:
            logger.error(f"LLM API call failed: {e}")
            raise

    async def _extraction_worker(self):
        """
        提取任务工作线程

        持续从队列中获取提取任务并执行。
        当队列堆积超过2个任务时，跳过落后的任务。
        """
        self.is_extracting = True
        logger.info("Extraction worker started")

        while self.is_extracting:
            try:
                # 获取队列中的任务
                # 如果队列堆积超过2个，跳过当前任务
                if self.extraction_queue.qsize() > 2:
                    # 跳过落后的任务
                    try:
                        skipped_task = self.extraction_queue.get_nowait()
                        logger.warning(
                            f"Queue backlog detected ({self.extraction_queue.qsize()} tasks), "
                            f"skipping extraction for turn {skipped_task.get('turn_id', 'unknown')}"
                        )
                        # 标记任务完成
                        if 'future' in skipped_task:
                            skipped_task['future'].set_result([])
                        continue
                    except asyncio.QueueEmpty:
                        pass

                # 等待新任务，设置超时以便检查is_extracting状态
                try:
                    task = await asyncio.wait_for(
                        self.extraction_queue.get(),
                        timeout=1.0
                    )
                except asyncio.TimeoutError:
                    continue

                turn = task['turn']
                context = task['context']
                future = task['future']

                try:
                    # 执行提取
                    events = await self._do_extraction(turn, context)
                    future.set_result(events)
                except Exception as e:
                    logger.error(f"Extraction failed: {e}")
                    future.set_exception(e)

            except Exception as e:
                logger.error(f"Worker error: {e}")

        logger.info("Extraction worker stopped")

    async def _do_extraction(
        self,
        turn: DialogueTurn,
        conversation_context: List[DialogueTurn]
    ) -> List[ExtractedEvent]:
        """
        执行实际的事件提取

        Args:
            turn: 当前对话轮次
            conversation_context: 对话上下文

        Returns:
            提取到的事件列表
        """
        try:
            # 构建提示词
            prompt = self._build_prompt(turn, conversation_context)

            # 调用LLM
            response_text = await self._call_llm(prompt)

            # 解析响应
            events_data, confidence, related_event_id, is_update = self._parse_llm_response(response_text)

            # 创建事件对象
            events = [
                self._create_event_from_data(
                    data, confidence, turn, is_update, related_event_id
                )
                for data in events_data
            ]

            logger.info(
                f"Extracted {len(events)} events from turn {turn.turn_id} "
                f"with confidence {confidence:.2f}"
            )

            return events

        except Exception as e:
            logger.error(f"Event extraction failed: {e}")
            return []

    async def extract_from_turn(
        self,
        turn: DialogueTurn,
        conversation_context: List[DialogueTurn]
    ) -> List[ExtractedEvent]:
        """
        从单轮对话中提取事件

        异步将提取任务加入队列，不阻塞主流程。

        Args:
            turn: 当前对话轮次
            conversation_context: 最近N轮对话上下文

        Returns:
            提取到的事件列表（可能为空）
        """
        # 启动工作线程（如果未启动）
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._extraction_worker())

        # 创建Future以等待结果
        future = asyncio.get_event_loop().create_future()

        # 将任务加入队列
        await self.extraction_queue.put({
            'turn': turn,
            'context': conversation_context,
            'future': future,
            'turn_id': turn.turn_id
        })

        try:
            # 等待结果，设置超时
            events = await asyncio.wait_for(
                future,
                timeout=Config.REQUEST_TIMEOUT * 2
            )
            return events
        except asyncio.TimeoutError:
            logger.error(f"Extraction timeout for turn {turn.turn_id}")
            return []
        except Exception as e:
            logger.error(f"Extraction error: {e}")
            return []

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
        # 构建增量提取提示词
        existing_slots = existing_event.slots.to_dict()

        prompt = f"""请分析新对话内容，判断是否可以补充或更新已有事件的信息。

## 已有事件信息
{json.dumps(existing_slots, ensure_ascii=False, indent=2)}

## 新对话内容
访谈者问题: {new_turn.interviewer_question}
受访者回复: {new_turn.interviewee_raw_reply}

## 任务
判断新对话是否包含可以补充已有事件的信息。
如果有补充信息，请以JSON格式返回更新的槽位：
```json
{{
  "has_update": true,
  "updates": {{
    "time": "新的时间（如有）",
    "location": "新的地点（如有）",
    ...
  }}
}}
```

如果没有补充信息，返回：
```json
{{"has_update": false}}
```
"""

        try:
            response_text = await self._call_llm(prompt)

            # 解析JSON响应
            if "```json" in response_text:
                json_str = response_text.split("```json")[1].split("```")[0].strip()
            elif "```" in response_text:
                json_str = response_text.split("```")[1].split("```")[0].strip()
            else:
                json_str = response_text.strip()

            data = json.loads(json_str)

            if data.get("has_update") and "updates" in data:
                updates = data["updates"]
                # 合并更新到现有槽位
                merged_slots = EventSlots(
                    time=updates.get("time") or existing_event.slots.time,
                    location=updates.get("location") or existing_event.slots.location,
                    people=updates.get("people") or existing_event.slots.people,
                    event=existing_event.slots.event,  # 事件描述不更新
                    feeling=updates.get("feeling") or existing_event.slots.feeling,
                    unexpanded_clues=updates.get("unexpanded_clues") or existing_event.slots.unexpanded_clues,
                    cause=updates.get("cause") or existing_event.slots.cause,
                    result=updates.get("result") or existing_event.slots.result,
                    reflection=updates.get("reflection") or existing_event.slots.reflection
                )

                logger.info(
                    f"Incremental update for event {existing_event.event_id}: "
                    f"{list(updates.keys())}"
                )
                return merged_slots

            return None

        except Exception as e:
            logger.error(f"Incremental extraction failed: {e}")
            return None

    def _calculate_similarity(
        self,
        event1: ExtractedEvent,
        event2: ExtractedEvent
    ) -> float:
        """
        计算两个事件的相似度

        基于标题相似度和时间匹配。

        Args:
            event1: 第一个事件
            event2: 第二个事件

        Returns:
            相似度分数（0-1）
        """
        if not event1.slots.event or not event2.slots.event:
            return 0.0

        # 计算事件描述的文本相似度
        text_similarity = SequenceMatcher(
            None,
            event1.slots.event,
            event2.slots.event
        ).ratio()

        # 时间匹配度
        time_similarity = 0.0
        if event1.slots.time and event2.slots.time:
            if event1.slots.time == event2.slots.time:
                time_similarity = 1.0
            else:
                # 简单的时间文本相似度
                time_similarity = SequenceMatcher(
                    None,
                    event1.slots.time,
                    event2.slots.time
                ).ratio() * 0.5

        # 地点匹配度
        location_similarity = 0.0
        if event1.slots.location and event2.slots.location:
            if event1.slots.location == event2.slots.location:
                location_similarity = 0.5

        # 综合相似度：文本相似度占主要权重
        total_similarity = (
            text_similarity * 0.7 +
            time_similarity * 0.2 +
            location_similarity * 0.1
        )

        return total_similarity

    async def find_similar_event(
        self,
        candidate: ExtractedEvent,
        existing_events: List[ExtractedEvent]
    ) -> Optional[ExtractedEvent]:
        """
        查找相似事件（用于去重）

        使用标题相似度和时间匹配判断事件是否重复。
        相似度阈值设为0.7。

        Args:
            candidate: 候选事件
            existing_events: 已有事件列表

        Returns:
            最相似的事件（如果相似度超过阈值），否则None
        """
        if not existing_events:
            return None

        most_similar = None
        highest_similarity = 0.0

        for existing in existing_events:
            similarity = self._calculate_similarity(candidate, existing)

            if similarity > highest_similarity:
                highest_similarity = similarity
                most_similar = existing

        if highest_similarity >= self.similarity_threshold:
            logger.info(
                f"Found similar event: {candidate.event_id} ~ "
                f"{most_similar.event_id} "
                f"(similarity: {highest_similarity:.2f})"
            )
            return most_similar

        return None

    async def stop(self):
        """
        停止提取器工作线程

        清理资源，等待队列中的任务完成。
        """
        self.is_extracting = False

        if self._worker_task and not self._worker_task.done():
            # 等待工作线程结束
            try:
                await asyncio.wait_for(self._worker_task, timeout=5.0)
            except asyncio.TimeoutError:
                self._worker_task.cancel()
                try:
                    await self._worker_task
                except asyncio.CancelledError:
                    pass

        logger.info("EventExtractor stopped")
