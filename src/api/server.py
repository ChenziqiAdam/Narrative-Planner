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
from src.orchestration.session_orchestrator import SessionOrchestrator
from src.config import Config

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
    first_question: str = ""
    graph_state: Dict[str, Any] = Field(default_factory=dict)


class GraphStateResponse(BaseModel):
    """图谱状态响应"""
    session_id: str
    coverage_metrics: Dict[str, Any]
    theme_nodes: list[Dict[str, Any]] = Field(default_factory=list)
    narrative_fragments: Dict[str, Any] = Field(default_factory=dict)
    dynamic_profile: Dict[str, Any] = Field(default_factory=dict)
    theme_count: int = 0
    event_count: int = 0
    pending_themes: int = 0
    mentioned_themes: int = 0
    exhausted_themes: int = 0
    turn_count: int = 0
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


def _parse_elder_info(basic_info: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
    """Build an ElderProfile payload from API input without requiring old parsers."""
    elder_info = dict(metadata or {})
    text = (basic_info or "").strip()
    if text and "background" not in elder_info:
        elder_info["background"] = text
    return elder_info


def _graph_state_response_payload(session_id: str, state: Dict[str, Any]) -> Dict[str, Any]:
    themes = state.get("theme_nodes", []) or []
    fragments = state.get("narrative_fragments", {}) or {}
    return {
        **state,
        "session_id": session_id,
        "theme_count": len(themes),
        "event_count": len(fragments),
        "pending_themes": sum(1 for item in themes if item.get("status") == "pending"),
        "mentioned_themes": sum(1 for item in themes if item.get("status") == "mentioned"),
        "exhausted_themes": sum(1 for item in themes if item.get("status") == "exhausted"),
    }


# ==================== 全局状态管理 ====================

# 会话存储: session_id -> SessionOrchestrator
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
    logger.info(f"Neo4j: 启用")
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

@app.websocket("/ws/planner/{session_id}")
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

        orchestrator = active_graphs[session_id]
        graph_state = orchestrator.get_graph_state()

        # 发送连接成功消息
        await websocket_manager.broadcast_to_session(
            session_id,
            {
                "type": "system",
                "message_type": "connected",
                "content": {
                    "session_id": session_id,
                    "client_id": client_id,
                    "graph_state": graph_state
                }
            }
        )
        await websocket_manager.broadcast_to_session(
            session_id,
            {
                "type": "graph_init",
                "data": graph_state,
                "timestamp": datetime.now().isoformat(),
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

                    await _process_user_message_stream(session_id, user_content, orchestrator)

                elif msg_type == "ping":
                    # 心跳响应
                    await websocket.send_json({"type": "pong", "timestamp": datetime.now().isoformat()})

                elif msg_type == "get_graph_state":
                    # 请求图谱状态
                    state = orchestrator.get_graph_state()
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
    orchestrator: SessionOrchestrator,
):
    """处理用户消息，运行 GraphRAG 管线并返回下一问。"""
    import asyncio

    result = await orchestrator.process_user_response(user_content)
    response_text = result.get("question", "")
    for char in response_text:
        await websocket_manager.broadcast_to_session(
            session_id,
            {"type": "token", "token": char, "is_final": False}
        )
        await asyncio.sleep(0.005)

    await websocket_manager.broadcast_to_session(
        session_id,
        {"type": "token", "token": "", "is_final": True}
    )

    await websocket_manager.broadcast_to_session(
        session_id,
        {
            "type": "graph_update",
            "update_type": "graph_rag_turn_processed",
            "data": result.get("current_graph_state", {}),
            "debug_trace": result.get("debug_trace", {}),
            "timestamp": datetime.now().isoformat(),
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

        elder_info = _parse_elder_info(request.basic_info, request.metadata)
        orchestrator = SessionOrchestrator(session_id)
        state = orchestrator.initialize_session(elder_info)
        active_graphs[session_id] = orchestrator
        logger.info("使用 SessionOrchestrator(GraphRAG) 创建会话")

        logger.info(f"创建新会话: {session_id}")

        return CreateSessionResponse(
            session_id=session_id,
            status="created",
            created_at=datetime.now().isoformat(),
            message="会话创建成功，请通过WebSocket连接 /ws/interview/{session_id} 或 /ws/planner/{session_id} 开始对话",
            first_question=state.pending_question or "",
            graph_state=orchestrator.get_graph_state(),
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
        orchestrator = active_graphs[session_id]
        state = _graph_state_response_payload(session_id, orchestrator.get_graph_state())
        return GraphStateResponse(**state)

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
        orchestrator = active_graphs[session_id]
        output_path = orchestrator.save_session()
        return CheckpointResponse(
            session_id=session_id,
            saved=True,
            path=output_path,
            timestamp=datetime.now().isoformat(),
            message="断点保存成功"
        )

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

        orchestrator = active_graphs.pop(session_id)
        close = getattr(orchestrator, "close", None)
        if close:
            await close()

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
        graph_state = active_graphs[session_id].get_graph_state()
        themes = graph_state.get("theme_nodes", [])
        if status:
            themes = [theme for theme in themes if theme.get("status") == status]

        return {
            "session_id": session_id,
            "themes": themes,
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
        graph_state = active_graphs[session_id].get_graph_state()
        events = list((graph_state.get("narrative_fragments") or {}).values())

        # 按主题过滤
        if theme_id:
            events = [event for event in events if event.get("theme_id") == theme_id]

        return {
            "session_id": session_id,
            "events": events,
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
            "websocket": "/ws/interview/{session_id} 或 /ws/planner/{session_id}",
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
