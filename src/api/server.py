"""
动态事件图谱 FastAPI 服务端

提供WebSocket和REST API端点，用于：
1. 实时流式访谈对话
2. 动态事件图谱管理
3. 断点保存和恢复
"""

import logging
import uuid
from typing import Dict, Any, Optional
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# 导入项目模块
from src.api.websocket_manager import websocket_manager
from src.core.graph_manager import GraphManager
from src.core.event_node import EventNode
from src.config import Config

# Neo4j 条件导入
if Config.NEO4J_ENABLED:
    from src.services.neo4j_graph_adapter import Neo4jGraphAdapter

logger = logging.getLogger(__name__)

# ==================== 数据模型 ====================

class CreateSessionRequest(BaseModel):
    """创建会话请求"""
    basic_info: str = Field(default="", description="受访者的基本信息")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="额外元数据")


class CreateSessionResponse(BaseModel):
    """创建会话响应"""
    session_id: str
    status: str
    created_at: str
    message: str


class GraphStateResponse(BaseModel):
    """图谱状态响应"""
    session_id: str
    coverage_metrics: Dict[str, Any]
    theme_count: int
    event_count: int
    pending_themes: int
    mentioned_themes: int
    exhausted_themes: int
    timestamp: str


class CheckpointResponse(BaseModel):
    """断点保存响应"""
    session_id: str
    saved: bool
    path: Optional[str]
    timestamp: str
    message: str


class UserMessageRequest(BaseModel):
    """用户消息请求（用于REST API）"""
    message: str = Field(..., description="用户消息内容")


class SessionEndResponse(BaseModel):
    """会话结束响应"""
    session_id: str
    ended: bool
    timestamp: str
    message: str


# ==================== 全局状态管理 ====================

# 会话存储: session_id -> GraphManager (或 Neo4jGraphAdapter)
active_graphs: Dict[str, Any] = {}


# ==================== 生命周期管理 ====================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    应用生命周期管理

    启动时初始化，关闭时清理资源。
    """
    # 启动
    logger.info("=" * 50)
    logger.info("动态事件图谱 API 服务启动")
    logger.info(f"日志级别: {Config.LOG_LEVEL}")
    logger.info(f"Neo4j: {'启用' if Config.NEO4J_ENABLED else '未启用'}")
    logger.info("=" * 50)

    yield

    # 关闭
    logger.info("=" * 50)
    logger.info("动态事件图谱 API 服务关闭")
    logger.info(f"清理 {len(active_graphs)} 个活动会话")
    logger.info("=" * 50)

    # 关闭所有WebSocket连接
    await websocket_manager.close_all_connections()

    # 清理所有会话
    active_graphs.clear()


# ==================== FastAPI 应用实例 ====================

app = FastAPI(
    title="动态事件图谱 API",
    description="提供实时流式访谈和动态事件图谱管理功能",
    version="1.0.0",
    lifespan=lifespan
)

# CORS配置 - 允许前端访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",  # Vite默认开发服务器
        "http://localhost:3000",  # React默认开发服务器
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==================== WebSocket 端点 ====================

@app.websocket("/ws/interview/{session_id}")
async def interview_websocket(websocket: WebSocket, session_id: str):
    """
    访谈WebSocket端点

    处理实时流式对话：
    1. 接收用户消息
    2. 流式返回AI响应token
    3. 自动广播图谱更新

    消息格式:
    - 客户端 -> 服务器: {"type": "message", "content": "用户输入"}
    - 服务器 -> 客户端: {"type": "token", "token": "文本片段", "is_final": false}
    - 服务器 -> 客户端: {"type": "graph_update", "update_type": "...", "data": {...}}
    """
    client_id = str(uuid.uuid4())[:8]

    try:
        # 接受连接 - 使用新的接口参数顺序
        await websocket_manager.connect(session_id, client_id, websocket)

        # 检查会话是否存在
        if session_id not in active_graphs:
            await websocket_manager.broadcast_to_session(
                session_id,
                {
                    "type": "system",
                    "message_type": "error",
                    "content": {"code": "SESSION_NOT_FOUND", "message": f"会话 {session_id} 不存在，请先创建会话"}
                }
            )
            await websocket.close(code=4004, reason="Session not found")
            return

        graph_manager = active_graphs[session_id]

        # 发送连接成功消息
        await websocket_manager.broadcast_to_session(
            session_id,
            {
                "type": "system",
                "message_type": "connected",
                "content": {
                    "session_id": session_id,
                    "client_id": client_id,
                    "graph_state": graph_manager.get_graph_state()
                }
            }
        )

        # 消息处理循环
        while True:
            try:
                # 接收客户端消息
                data = await websocket.receive_json()
                msg_type = data.get("type", "message")

                if msg_type == "message":
                    # 处理用户消息
                    user_content = data.get("content", "").strip()
                    if not user_content:
                        await websocket_manager.broadcast_to_session(
                            session_id,
                            {
                                "type": "system",
                                "message_type": "error",
                                "content": {"code": "EMPTY_MESSAGE", "message": "消息内容不能为空"}
                            }
                        )
                        continue

                    # TODO: 集成StreamingInterviewEngine处理消息
                    # 目前返回模拟的流式响应
                    await _process_user_message_stream(session_id, user_content, graph_manager)

                elif msg_type == "ping":
                    # 心跳响应
                    await websocket.send_json({"type": "pong", "timestamp": datetime.now().isoformat()})

                elif msg_type == "get_graph_state":
                    # 请求图谱状态
                    state = graph_manager.get_graph_state()
                    await websocket_manager.broadcast_to_session(
                        session_id,
                        {
                            "type": "system",
                            "message_type": "graph_state",
                            "content": state
                        }
                    )

                else:
                    logger.warning(f"未知消息类型: {msg_type}")

            except WebSocketDisconnect:
                logger.info(f"客户端 {client_id} 断开连接")
                break
            except Exception as e:
                logger.error(f"处理消息时出错: {e}", exc_info=True)
                await websocket_manager.broadcast_to_session(
                    session_id,
                    {
                        "type": "system",
                        "message_type": "error",
                        "content": {"code": "PROCESSING_ERROR", "message": str(e)}
                    }
                )

    except WebSocketDisconnect:
        logger.info(f"WebSocket断开 - 会话: {session_id}, 客户端: {client_id}")
    except Exception as e:
        logger.error(f"WebSocket错误 - 会话: {session_id}, 客户端: {client_id}: {e}", exc_info=True)
    finally:
        await websocket_manager.disconnect(session_id, client_id)


async def _process_user_message_stream(
    session_id: str,
    user_content: str,
    graph_manager: Any
):
    """
    处理用户消息并流式返回响应

    TODO: 集成实际的StreamingInterviewEngine
    目前使用模拟数据演示流程。
    """
    # 模拟流式响应
    import asyncio

    response_text = f"感谢您的分享。关于\"{user_content[:20]}...\", 能详细说说当时的情况吗？"

    # 流式发送token
    for char in response_text:
        await websocket_manager.broadcast_to_session(
            session_id,
            {"type": "token", "token": char, "is_final": False}
        )
        await asyncio.sleep(0.02)  # 模拟延迟

    # 发送结束标记
    await websocket_manager.broadcast_to_session(
        session_id,
        {"type": "token", "token": "", "is_final": True}
    )

    # 模拟事件提取和图谱更新
    # TODO: 实际应调用EventExtractor
    if len(user_content) > 10:
        # 模拟添加一个事件
        event = EventNode(
            event_id=f"evt_{uuid.uuid4().hex[:12]}",
            theme_id="THEME_01_LIFE_CHAPTERS",  # 示例主题
            title=f"事件: {user_content[:15]}...",
            description=user_content,
        )

        # 添加到图谱
        graph_manager.add_event_node(event, event.theme_id)

        # 广播图谱更新
        await websocket_manager.broadcast_to_session(
            session_id,
            {
                "type": "graph_update",
                "update_type": "event_added",
                "data": {
                    "event_id": event.event_id,
                    "theme_id": event.theme_id,
                    "title": event.title,
                    "graph_state": graph_manager.get_graph_state()
                }
            }
        )


# ==================== REST API 端点 ====================

@app.post("/api/session", response_model=CreateSessionResponse)
async def create_session(request: CreateSessionRequest):
    """
    创建新会话

    初始化一个新的访谈会话，创建对应的图谱管理器。

    Returns:
        包含session_id和初始状态的信息
    """
    try:
        # 生成会话ID
        session_id = f"session_{uuid.uuid4().hex[:16]}"

        # 创建图谱管理器
        if Config.NEO4J_ENABLED:
            graph_manager = Neo4jGraphAdapter()
            logger.info("使用 Neo4jGraphAdapter 创建会话")
        else:
            graph_manager = GraphManager()
            logger.info("使用 GraphManager (NetworkX) 创建会话")
        active_graphs[session_id] = graph_manager

        logger.info(f"创建新会话: {session_id}")

        return CreateSessionResponse(
            session_id=session_id,
            status="created",
            created_at=datetime.now().isoformat(),
            message="会话创建成功，请通过WebSocket连接 /ws/interview/{session_id} 开始对话"
        )

    except Exception as e:
        logger.error(f"创建会话失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"创建会话失败: {str(e)}")


@app.get("/api/graph/{session_id}", response_model=GraphStateResponse)
async def get_graph_state(session_id: str):
    """
    获取图谱状态

    返回指定会话的当前图谱状态，包括：
    - 覆盖率指标
    - 主题统计
    - 事件数量
    """
    if session_id not in active_graphs:
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")

    try:
        graph_manager = active_graphs[session_id]
        state = graph_manager.get_graph_state()

        return GraphStateResponse(
            session_id=session_id,
            coverage_metrics=state["coverage_metrics"],
            theme_count=state["theme_count"],
            event_count=state["event_count"],
            pending_themes=state["pending_themes"],
            mentioned_themes=state["mentioned_themes"],
            exhausted_themes=state["exhausted_themes"],
            timestamp=state["timestamp"]
        )

    except Exception as e:
        logger.error(f"获取图谱状态失败 - 会话 {session_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取图谱状态失败: {str(e)}")


@app.post("/api/graph/{session_id}/checkpoint", response_model=CheckpointResponse)
async def save_checkpoint(session_id: str, background_tasks: BackgroundTasks):
    """
    保存断点

    将当前会话的图谱状态保存到磁盘，支持后续恢复。
    """
    if session_id not in active_graphs:
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")

    try:
        graph_manager = active_graphs[session_id]

        # 在后台执行保存操作
        def do_save():
            from pathlib import Path
            output_dir = Path(Config.DATA_DIR) / "interviews" / session_id
            return graph_manager.save_checkpoint(session_id, output_dir)

        # 同步执行保存（因为需要返回结果）
        success = do_save()

        if success:
            output_path = f"{Config.DATA_DIR}/interviews/{session_id}"
            return CheckpointResponse(
                session_id=session_id,
                saved=True,
                path=output_path,
                timestamp=datetime.now().isoformat(),
                message="断点保存成功"
            )
        else:
            raise HTTPException(status_code=500, detail="保存断点失败")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"保存断点失败 - 会话 {session_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"保存断点失败: {str(e)}")


@app.delete("/api/session/{session_id}", response_model=SessionEndResponse)
async def end_session(session_id: str):
    """
    结束会话

    关闭指定会话，清理相关资源。建议在结束前调用保存断点。
    """
    if session_id not in active_graphs:
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")

    try:
        # 获取连接数
        stats = websocket_manager.get_session_stats(session_id)
        connection_count = stats.get("client_count", 0)

        # 清理图谱数据
        del active_graphs[session_id]

        logger.info(f"会话已结束: {session_id} (清理了 {connection_count} 个WebSocket连接)")

        return SessionEndResponse(
            session_id=session_id,
            ended=True,
            timestamp=datetime.now().isoformat(),
            message=f"会话已结束，清理了 {connection_count} 个连接"
        )

    except Exception as e:
        logger.error(f"结束会话失败 - 会话 {session_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"结束会话失败: {str(e)}")


# ==================== 附加端点 ====================

@app.get("/api/session/{session_id}/themes")
async def get_session_themes(session_id: str, status: Optional[str] = None):
    """
    获取会话的主题列表

    Args:
        session_id: 会话ID
        status: 可选的状态过滤 (pending, mentioned, exhausted)
    """
    if session_id not in active_graphs:
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")

    try:
        graph_manager = active_graphs[session_id]

        if status == "pending":
            themes = graph_manager.get_pending_theme_nodes()
        elif status == "mentioned":
            themes = graph_manager.get_mentioned_theme_nodes()
        elif status == "exhausted":
            themes = graph_manager.get_exhausted_theme_nodes()
        else:
            themes = list(graph_manager.theme_nodes.values())

        return {
            "session_id": session_id,
            "themes": [theme.to_dict() for theme in themes],
            "count": len(themes)
        }

    except Exception as e:
        logger.error(f"获取主题列表失败 - 会话 {session_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取主题列表失败: {str(e)}")


@app.get("/api/session/{session_id}/events")
async def get_session_events(session_id: str, theme_id: Optional[str] = None):
    """
    获取会话的事件列表

    Args:
        session_id: 会话ID
        theme_id: 可选的主题ID过滤
    """
    if session_id not in active_graphs:
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")

    try:
        graph_manager = active_graphs[session_id]

        events = list(graph_manager.event_nodes.values())

        # 按主题过滤
        if theme_id:
            events = [e for e in events if e.theme_id == theme_id]

        return {
            "session_id": session_id,
            "events": [event.to_dict() for event in events],
            "count": len(events)
        }

    except Exception as e:
        logger.error(f"获取事件列表失败 - 会话 {session_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取事件列表失败: {str(e)}")


@app.get("/health")
async def health_check():
    """健康检查端点"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "active_sessions": len(active_graphs),
        "total_websocket_connections": websocket_manager.get_all_stats()["total_clients"]
    }


@app.get("/")
async def root():
    """根路径 - API信息"""
    return {
        "name": "动态事件图谱 API",
        "version": "1.0.0",
        "endpoints": {
            "websocket": "/ws/interview/{session_id}",
            "rest": [
                "POST /api/session - 创建会话",
                "GET /api/graph/{session_id} - 获取图谱状态",
                "POST /api/graph/{session_id}/checkpoint - 保存断点",
                "DELETE /api/session/{session_id} - 结束会话",
                "GET /api/session/{session_id}/themes - 获取主题列表",
                "GET /api/session/{session_id}/events - 获取事件列表",
            ]
        }
    }


# ==================== 主入口 ====================

if __name__ == "__main__":
    import uvicorn

    # 配置日志
    logging.basicConfig(
        level=getattr(logging, Config.LOG_LEVEL),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    # 启动服务器
    uvicorn.run(
        "src.api.server:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level=Config.LOG_LEVEL.lower()
    )
