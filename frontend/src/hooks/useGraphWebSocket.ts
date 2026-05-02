/**
 * useGraphWebSocket Hook
 *
 * 管理WebSocket连接，处理实时对话和图谱更新
 * 适配对比调试系统的WebSocket协议
 */

import { useState, useEffect, useRef, useCallback } from 'react'
import { EventNode, GraphState, NodeStatus } from '../types'

type WebSocketPayload = Record<string, unknown>

/** 连接状态 */
export enum WSConnectionStatus {
  CONNECTING = 'connecting',
  CONNECTED = 'connected',
  DISCONNECTED = 'disconnected',
  RECONNECTING = 'reconnecting',
  ERROR = 'error',
}

/** WebSocket消息类型 */
interface WSMessage {
  type: string
  data?: GraphState
  delta?: Partial<GraphState>
  event?: { event_id?: string } & WebSocketPayload
  node_id?: string
  payload?: {
    event?: WebSocketPayload
    graph_state?: GraphState
  }
  session_id?: string
  status?: string
  [key: string]: unknown
}

interface UseGraphWebSocketOptions {
  sessionId?: string | null
  onGraphInit?: (data: GraphState) => void
  onGraphUpdate?: (data: GraphState) => void
  onGraphDelta?: (delta: Partial<GraphState>) => void
  onNodeStatusChange?: (nodeId: string, status: string) => void
  onNewEvent?: (event: EventNode | WebSocketPayload) => void
  onConnected?: () => void
  onDisconnected?: () => void
  onError?: (error: unknown) => void
}

interface UseGraphWebSocketReturn {
  connectionStatus: WSConnectionStatus
  graphState: GraphState | null
  isConnected: boolean
  reconnect: () => void
}

function buildPlannerWebSocketUrl(sessionId: string): string {
  const params = new URLSearchParams(window.location.search)
  const backendFromQuery = params.get('backend')
  const backendFromEnv = (import.meta as { env?: { VITE_BACKEND_URL?: string } }).env?.VITE_BACKEND_URL
  const backendOrigin = backendFromQuery || backendFromEnv || 'http://localhost:9999'
  const backendUrl = new URL(backendOrigin)
  const protocol = backendUrl.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${backendUrl.host}/ws/planner/${sessionId}`
}

/**
 * Graph WebSocket Hook
 *
 * 用于数据看板接收来自对比调试系统的图谱更新
 */
export function useGraphWebSocket(options: UseGraphWebSocketOptions): UseGraphWebSocketReturn {
  const { sessionId } = options

  const wsRef = useRef<WebSocket | null>(null)
  const handlersRef = useRef({
    onGraphInit: options.onGraphInit,
    onGraphUpdate: options.onGraphUpdate,
    onGraphDelta: options.onGraphDelta,
    onNodeStatusChange: options.onNodeStatusChange,
    onNewEvent: options.onNewEvent,
    onConnected: options.onConnected,
    onDisconnected: options.onDisconnected,
    onError: options.onError,
  })
  const [connectionStatus, setConnectionStatus] = useState<WSConnectionStatus>(
    WSConnectionStatus.DISCONNECTED
  )
  const [graphState, setGraphState] = useState<GraphState | null>(null)

  const isConnected = connectionStatus === WSConnectionStatus.CONNECTED

  useEffect(() => {
    handlersRef.current = {
      onGraphInit: options.onGraphInit,
      onGraphUpdate: options.onGraphUpdate,
      onGraphDelta: options.onGraphDelta,
      onNodeStatusChange: options.onNodeStatusChange,
      onNewEvent: options.onNewEvent,
      onConnected: options.onConnected,
      onDisconnected: options.onDisconnected,
      onError: options.onError,
    }
  }, [
    options.onConnected,
    options.onDisconnected,
    options.onError,
    options.onGraphDelta,
    options.onGraphInit,
    options.onGraphUpdate,
    options.onNewEvent,
    options.onNodeStatusChange,
  ])

  /**
   * 处理收到的消息
   */
  const handleMessage = useCallback((data: WSMessage) => {
    console.log('WebSocket message:', data.type, data)

    switch (data.type) {
      case 'connection_established':
        console.log('WebSocket连接已建立:', data.session_id)
        setConnectionStatus(WSConnectionStatus.CONNECTED)
        handlersRef.current.onConnected?.()
        break

      case 'graph_init':
        // 初始化完整图谱
        if (data.data) {
          setGraphState(data.data)
          handlersRef.current.onGraphInit?.(data.data)
        }
        break

      case 'graph_update':
        // 完整图谱更新
        if (data.data) {
          setGraphState(data.data)
          handlersRef.current.onGraphUpdate?.(data.data)
        }
        break

      case 'graph_delta':
        // 增量更新
        if (data.delta) {
          setGraphState((prev) => {
            if (!prev) return prev
            // 合并更新
            return { ...prev, ...data.delta }
          })
          handlersRef.current.onGraphDelta?.(data.delta)
        }
        break

      case 'node_status_change':
        // 节点状态变更
        if (typeof data.node_id === 'string' && typeof data.status === 'string') {
          const { node_id } = data
          const status = data.status as NodeStatus
          setGraphState((prev) => {
            if (!prev) return prev
            // 更新主题节点状态
            if (prev.theme_nodes && prev.theme_nodes[node_id]) {
              return {
                ...prev,
                theme_nodes: {
                  ...prev.theme_nodes,
                  [node_id]: {
                    ...prev.theme_nodes[node_id],
                    status,
                  },
                },
              }
            }
            return prev
          })
          handlersRef.current.onNodeStatusChange?.(node_id, status)
        }
        break

      case 'new_event':
        // 新增事件
        if (data.event && typeof data.event.event_id === 'string') {
          const eventId = data.event.event_id
          const event = data.event as unknown as EventNode
          setGraphState((prev) => {
            if (!prev) return prev
            // 添加事件到图谱
            return {
              ...prev,
              event_nodes: {
                ...prev.event_nodes,
                [eventId]: event,
              },
              event_count: (prev.event_count || 0) + 1,
            }
          })
          handlersRef.current.onNewEvent?.(event)
        }
        break

      case 'event_added':
        // 事件添加（原有格式兼容）
        if (data.payload?.event) {
          handlersRef.current.onNewEvent?.(data.payload.event)
        }
        break

      case 'graph_sync':
        // 图谱同步（原有格式兼容）
        if (data.payload?.graph_state) {
          setGraphState(data.payload.graph_state)
          handlersRef.current.onGraphUpdate?.(data.payload.graph_state)
        }
        break

      case 'error':
        console.error('WebSocket错误:', data)
        handlersRef.current.onError?.(data)
        break

      case 'pong':
        // 心跳响应
        break

      default:
        console.warn('未知的WebSocket消息类型:', data.type)
    }
  }, [])

  /**
   * 建立WebSocket连接
   */
  const connect = useCallback(() => {
    if (!sessionId) {
      console.log('No sessionId provided, skipping WebSocket connection')
      return
    }

    // 关闭已有连接
    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }

    setConnectionStatus(WSConnectionStatus.CONNECTING)

    try {
      // Connect back to the backend that opened this dashboard window.
      const wsUrl = buildPlannerWebSocketUrl(sessionId)
      console.log('Connecting to WebSocket:', wsUrl)

      const ws = new WebSocket(wsUrl)

      ws.onopen = () => {
        console.log('WebSocket连接已打开')
        // 发送订阅消息
        ws.send(JSON.stringify({
          type: 'subscribe',
          topics: ['graph', 'events', 'status']
        }))
      }

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data) as WSMessage
          handleMessage(data)
        } catch (error) {
          console.error('解析WebSocket消息失败:', error, event.data)
        }
      }

      ws.onclose = (event) => {
        console.log('WebSocket连接关闭:', event.code, event.reason)
        setConnectionStatus(WSConnectionStatus.DISCONNECTED)
        handlersRef.current.onDisconnected?.()
      }

      ws.onerror = (error) => {
        console.error('WebSocket错误:', error)
        setConnectionStatus(WSConnectionStatus.ERROR)
        handlersRef.current.onError?.({ code: 'WS_ERROR', message: 'WebSocket连接错误' })
      }

      wsRef.current = ws
    } catch (error) {
      console.error('创建WebSocket连接失败:', error)
      setConnectionStatus(WSConnectionStatus.ERROR)
    }
  }, [sessionId, handleMessage])

  /**
   * 断开WebSocket连接
   */
  const disconnect = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }
    setConnectionStatus(WSConnectionStatus.DISCONNECTED)
  }, [])

  /**
   * 手动重连
   */
  const reconnect = useCallback(() => {
    disconnect()
    connect()
  }, [connect, disconnect])

  // 组件挂载时建立连接
  useEffect(() => {
    connect()

    // 组件卸载时清理
    return () => {
      disconnect()
    }
  }, [connect, disconnect])

  // 心跳保持
  useEffect(() => {
    if (!isConnected) return

    const heartbeat = setInterval(() => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ type: 'ping' }))
      }
    }, 30000)

    return () => clearInterval(heartbeat)
  }, [isConnected])

  return {
    connectionStatus,
    graphState,
    isConnected,
    reconnect,
  }
}

export default useGraphWebSocket
