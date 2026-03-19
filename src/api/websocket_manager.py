"""
动态事件图谱 - WebSocket管理器

本模块提供WebSocket连接管理和图谱状态广播功能。
支持多客户端连接、按会话分组、实时状态广播。
"""

import json
import logging
from typing import Dict, Set, Any, Optional
from datetime import datetime
from fastapi import WebSocket

from src.core.interfaces import (
    IGraphBroadcaster,
    ExtractedEvent,
    NodeStatus,
    EventAddedUpdate,
    EventUpdatedUpdate,
    ThemeStatusUpdate
)

logger = logging.getLogger(__name__)


class WebSocketManager(IGraphBroadcaster):
    """
    WebSocket连接管理和广播器

    管理所有WebSocket连接，按session_id分组存储，
    提供图谱状态变更的实时广播功能。

    Attributes:
        active_connections: 按session_id分组的活跃连接字典
            格式: {session_id: {client_id: WebSocket}}
    """

    def __init__(self):
        # session_id -> {client_id: WebSocket}
        self.active_connections: Dict[str, Dict[str, WebSocket]] = {}
        logger.info("WebSocket管理器初始化完成")

    async def connect(self, session_id: str, client_id: str, websocket: WebSocket) -> None:
        """
        处理客户端连接

        Args:
            session_id: 会话ID，用于分组管理连接
            client_id: 客户端唯一标识
            websocket: FastAPI WebSocket对象

        流程:
            1. 接受WebSocket连接
            2. 将连接加入对应session_id的分组
            3. 记录连接日志
        """
        try:
            await websocket.accept()

            # 初始化session的连接字典
            if session_id not in self.active_connections:
                self.active_connections[session_id] = {}

            # 存储连接
            self.active_connections[session_id][client_id] = websocket

            logger.info(
                f"客户端连接成功 - session_id: {session_id}, "
                f"client_id: {client_id}, "
                f"当前session连接数: {len(self.active_connections[session_id])}"
            )

            # 发送连接成功确认
            await self._send_personal_message(
                websocket,
                {
                    "type": "connection_established",
                    "session_id": session_id,
                    "client_id": client_id,
                    "timestamp": datetime.now().isoformat()
                }
            )

        except Exception as e:
            logger.error(f"客户端连接失败 - session_id: {session_id}, client_id: {client_id}, error: {e}")
            raise

    async def disconnect(self, session_id: str, client_id: str) -> None:
        """
        处理客户端断开连接

        Args:
            session_id: 会话ID
            client_id: 客户端唯一标识

        流程:
            1. 从对应session中移除连接
            2. 清理空的session分组
            3. 记录断开日志
        """
        try:
            if session_id in self.active_connections:
                if client_id in self.active_connections[session_id]:
                    # 关闭WebSocket连接
                    websocket = self.active_connections[session_id][client_id]
                    try:
                        await websocket.close()
                    except Exception:
                        # 连接可能已关闭，忽略错误
                        pass

                    # 移除连接记录
                    del self.active_connections[session_id][client_id]
                    logger.info(
                        f"客户端断开连接 - session_id: {session_id}, "
                        f"client_id: {client_id}, "
                        f"剩余连接数: {len(self.active_connections[session_id])}"
                    )

                # 清理空的session分组
                if not self.active_connections[session_id]:
                    del self.active_connections[session_id]
                    logger.info(f"清理空session分组: {session_id}")

        except Exception as e:
            logger.error(f"断开连接处理异常 - session_id: {session_id}, client_id: {client_id}, error: {e}")

    async def _send_personal_message(
        self,
        websocket: WebSocket,
        message: Dict[str, Any]
    ) -> bool:
        """
        向单个客户端发送消息

        Args:
            websocket: 目标WebSocket连接
            message: 要发送的消息字典

        Returns:
            发送是否成功
        """
        try:
            await websocket.send_json(message)
            return True
        except Exception as e:
            logger.error(f"发送个人消息失败: {e}")
            return False

    async def send_personal_message(
        self,
        session_id: str,
        client_id: str,
        message: Dict[str, Any]
    ) -> bool:
        """
        向指定客户端发送个人消息

        Args:
            session_id: 会话ID
            client_id: 客户端ID
            message: 消息内容

        Returns:
            发送是否成功
        """
        try:
            if session_id not in self.active_connections:
                logger.warning(f"发送个人消息失败 - session不存在: {session_id}")
                return False

            if client_id not in self.active_connections[session_id]:
                logger.warning(f"发送个人消息失败 - client不存在: {client_id}")
                return False

            websocket = self.active_connections[session_id][client_id]
            return await self._send_personal_message(websocket, message)

        except Exception as e:
            logger.error(f"发送个人消息异常 - session: {session_id}, client: {client_id}, error: {e}")
            return False

    async def broadcast_to_session(
        self,
        session_id: str,
        message: Dict[str, Any]
    ) -> int:
        """
        广播消息到指定会话的所有客户端

        Args:
            session_id: 目标会话ID
            message: 要广播的消息字典

        Returns:
            成功发送的客户端数量

        注意:
            发送失败不会抛出异常，而是记录警告日志
        """
        if session_id not in self.active_connections:
            logger.warning(f"广播消息失败 - session不存在或无连接: {session_id}")
            return 0

        connections = self.active_connections[session_id]
        if not connections:
            logger.warning(f"广播消息失败 - session无活跃连接: {session_id}")
            return 0

        success_count = 0
        failed_clients = []

        for client_id, websocket in list(connections.items()):
            try:
                await websocket.send_json(message)
                success_count += 1
            except Exception as e:
                failed_clients.append(client_id)
                logger.warning(f"向客户端发送消息失败 - client_id: {client_id}, error: {e}")

        # 清理发送失败的连接
        for client_id in failed_clients:
            await self.disconnect(session_id, client_id)

        logger.debug(
            f"广播完成 - session_id: {session_id}, "
            f"成功: {success_count}/{len(connections)}, "
            f"消息类型: {message.get('update_type', 'unknown')}"
        )

        return success_count

    async def broadcast_event_added(
        self,
        session_id: str,
        event: ExtractedEvent,
        theme_id: Optional[str] = None
    ) -> None:
        """
        广播新事件添加

        Args:
            session_id: 目标会话ID
            event: 新添加的事件
            theme_id: 关联的主题ID（可选）

        流程:
            1. 创建EventAddedUpdate事件对象
            2. 转换为字典格式
            3. 广播到指定session的所有客户端
        """
        try:
            update = EventAddedUpdate(
                event=event,
                theme_id=theme_id
            )

            message = update.to_dict()
            sent_count = await self.broadcast_to_session(session_id, message)

            logger.info(
                f"广播事件添加 - session_id: {session_id}, "
                f"event_id: {event.event_id}, "
                f"theme_id: {theme_id}, "
                f"接收客户端数: {sent_count}"
            )

        except Exception as e:
            logger.error(f"广播事件添加失败 - session_id: {session_id}, event_id: {event.event_id}, error: {e}")

    async def broadcast_event_updated(
        self,
        session_id: str,
        event_id: str,
        updated_slots: Dict[str, Any]
    ) -> None:
        """
        广播事件更新

        Args:
            session_id: 目标会话ID
            event_id: 更新的事件ID
            updated_slots: 更新的槽位数据

        流程:
            1. 创建EventUpdatedUpdate事件对象
            2. 转换为字典格式
            3. 广播到指定session的所有客户端
        """
        try:
            # 计算新的置信度（基于槽位填充率）
            # 这里简化处理，实际可能需要从存储中读取完整事件
            new_confidence = self._calculate_confidence(updated_slots)

            update = EventUpdatedUpdate(
                event_id=event_id,
                updated_slots=updated_slots,
                new_confidence=new_confidence
            )

            message = update.to_dict()
            sent_count = await self.broadcast_to_session(session_id, message)

            logger.info(
                f"广播事件更新 - session_id: {session_id}, "
                f"event_id: {event_id}, "
                f"更新槽位数: {len(updated_slots)}, "
                f"接收客户端数: {sent_count}"
            )

        except Exception as e:
            logger.error(f"广播事件更新失败 - session_id: {session_id}, event_id: {event_id}, error: {e}")

    async def broadcast_theme_status_changed(
        self,
        session_id: str,
        theme_id: str,
        old_status: NodeStatus,
        new_status: NodeStatus
    ) -> None:
        """
        广播主题状态变更

        Args:
            session_id: 目标会话ID
            theme_id: 主题ID
            old_status: 原状态
            new_status: 新状态

        流程:
            1. 创建ThemeStatusUpdate事件对象
            2. 转换为字典格式
            3. 广播到指定session的所有客户端
        """
        try:
            update = ThemeStatusUpdate(
                theme_id=theme_id,
                old_status=old_status,
                new_status=new_status
            )

            message = update.to_dict()
            sent_count = await self.broadcast_to_session(session_id, message)

            logger.info(
                f"广播主题状态变更 - session_id: {session_id}, "
                f"theme_id: {theme_id}, "
                f"状态: {old_status.value} -> {new_status.value}, "
                f"接收客户端数: {sent_count}"
            )

        except Exception as e:
            logger.error(
                f"广播主题状态变更失败 - session_id: {session_id}, "
                f"theme_id: {theme_id}, error: {e}"
            )

    def _calculate_confidence(self, slots: Dict[str, Any]) -> float:
        """
        基于槽位填充率计算置信度

        Args:
            slots: 槽位数据字典

        Returns:
            置信度分数 (0-1)
        """
        core_fields = ["time", "location", "people", "event", "feeling"]
        filled_count = sum(
            1 for field in core_fields
            if field in slots and slots[field] is not None and slots[field] != []
        )
        return filled_count / len(core_fields)

    def get_session_stats(self, session_id: str) -> Dict[str, Any]:
        """
        获取会话连接统计信息

        Args:
            session_id: 会话ID

        Returns:
            统计信息字典
        """
        if session_id not in self.active_connections:
            return {
                "session_id": session_id,
                "connected": False,
                "client_count": 0,
                "clients": []
            }

        return {
            "session_id": session_id,
            "connected": True,
            "client_count": len(self.active_connections[session_id]),
            "clients": list(self.active_connections[session_id].keys())
        }

    def get_all_stats(self) -> Dict[str, Any]:
        """
        获取所有连接统计信息

        Returns:
            全局统计信息字典
        """
        total_sessions = len(self.active_connections)
        total_clients = sum(
            len(clients) for clients in self.active_connections.values()
        )

        return {
            "total_sessions": total_sessions,
            "total_clients": total_clients,
            "sessions": {
                session_id: len(clients)
                for session_id, clients in self.active_connections.items()
            }
        }

    async def close_all_connections(self) -> None:
        """
        关闭所有WebSocket连接

        用于服务器关闭时的清理工作
        """
        logger.info("开始关闭所有WebSocket连接...")

        for session_id in list(self.active_connections.keys()):
            for client_id in list(self.active_connections[session_id].keys()):
                await self.disconnect(session_id, client_id)

        self.active_connections.clear()
        logger.info("所有WebSocket连接已关闭")


# 全局WebSocket管理器实例
websocket_manager = WebSocketManager()
