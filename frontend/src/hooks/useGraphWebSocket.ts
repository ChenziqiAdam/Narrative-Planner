/**
 * useGraphWebSocket Hook
 *
 * 管理WebSocket连接，处理实时对话和图谱更新
 * 功能：
 * 1. WebSocket连接管理
 * 2. 流式token接收
 * 3. 图谱更新事件处理
 * 4. 自动重连机制
 */

import { useState, useEffect, useRef, useCallback } from 'react'
import {
  WSMessage,
  TokenMessage,
  ResponseCompleteMessage,
  EventAddedMessage,
  ThemeStatusChangedMessage,
  GraphSyncMessage,
  WSErrorMessage,
  WSConnectedMessage,
  ChatMessage,
  SendMessageRequest,
  WSConnectionOptions,
  WSConnectionStatus,
  UseGraphWebSocketReturn,
  ExtractedEvent,
  ThemeStatusUpdate,
} from '../types/websocket'
import { GraphState } from '../types'

/** WebSocket服务器地址 */
const WS_BASE_URL = (import.meta as { env?: { VITE_WS_URL?: string } }).env?.VITE_WS_URL || 'ws://localhost:8000/ws'

/**
 * 创建WebSocket URL
 * @param sessionId 会话ID
 * @returns 完整的WebSocket URL
 */
function createWebSocketUrl(sessionId: string): string {
  const baseUrl = WS_BASE_URL.replace(/\/$/, '')
  return `${baseUrl}/${sessionId}`
}

/**
 * 生成唯一消息ID
 * @returns 消息ID
 */
function generateMessageId(): string {
  return `msg_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`
}

/**
 * 获取当前时间戳（ISO格式）
 * @returns ISO格式时间戳
 */
function getTimestamp(): string {
  return new Date().toISOString()
}

/**
 * Graph WebSocket Hook
 *
 * @param options 连接配置选项
 * @returns Hook状态和操作函数
 */
export function useGraphWebSocket(options: WSConnectionOptions): UseGraphWebSocketReturn {
  const {
    sessionId,
    reconnectAttempts = 5,
    reconnectInterval = 3000,
    heartbeatInterval = 30000,
    onEventAdded,
    onEventUpdated,
    onThemeStatusChanged,
    onGraphSync,
    onError,
    onConnected,
    onDisconnected,
  } = options

  // WebSocket实例引用
  const wsRef = useRef<WebSocket | null>(null)
  // 重连计数器
  const reconnectCountRef = useRef(0)
  // 重连定时器
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  // 心跳定时器
  const heartbeatTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  // 当前流式消息ID
  const currentMessageIdRef = useRef<string | null>(null)
  // 稳定的回调引用
  const callbacksRef = useRef({
    onEventAdded,
    onEventUpdated,
    onThemeStatusChanged,
    onGraphSync,
    onError,
    onConnected,
    onDisconnected,
  })

  // 更新回调引用
  useEffect(() => {
    callbacksRef.current = {
      onEventAdded,
      onEventUpdated,
      onThemeStatusChanged,
      onGraphSync,
      onError,
      onConnected,
      onDisconnected,
    }
  }, [onEventAdded, onEventUpdated, onThemeStatusChanged, onGraphSync, onError, onConnected, onDisconnected])

  // 连接状态
  const [connectionStatus, setConnectionStatus] = useState<WSConnectionStatus>(
    WSConnectionStatus.DISCONNECTED
  )
  const isConnected = connectionStatus === WSConnectionStatus.CONNECTED

  // 消息列表
  const [messages, setMessages] = useState<ChatMessage[]>([])
  // 当前流式消息内容
  const [streamingMessage, setStreamingMessage] = useState('')
  // 是否正在流式输出
  const [isStreaming, setIsStreaming] = useState(false)
  // 图谱状态
  const [graphState, setGraphState] = useState<GraphState | null>(null)

  /**
   * 清理重连定时器
   */
  const clearReconnectTimer = useCallback(() => {
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current)
      reconnectTimerRef.current = null
    }
  }, [])

  /**
   * 清理心跳定时器
   */
  const clearHeartbeatTimer = useCallback(() => {
    if (heartbeatTimerRef.current) {
      clearInterval(heartbeatTimerRef.current)
      heartbeatTimerRef.current = null
    }
  }, [])

  /**
   * 启动心跳
   */
  const startHeartbeat = useCallback(() => {
    clearHeartbeatTimer()
    heartbeatTimerRef.current = setInterval(() => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        // 发送ping消息保持连接
        wsRef.current.send(JSON.stringify({
          type: 'ping',
          timestamp: getTimestamp(),
        }))
      }
    }, heartbeatInterval)
  }, [heartbeatInterval, clearHeartbeatTimer])

  /**
   * 处理收到的消息
   */
  const handleMessage = useCallback((data: WSMessage) => {
    switch (data.type) {
      case 'token': {
        const tokenMsg = data as TokenMessage
        const { content, message_id } = tokenMsg.payload

        // 如果是新消息的开始
        if (currentMessageIdRef.current !== message_id) {
          currentMessageIdRef.current = message_id
          setStreamingMessage(content)
          setIsStreaming(true)
        } else {
          // 追加token
          setStreamingMessage((prev) => prev + content)
        }
        break
      }

      case 'response_complete': {
        const completeMsg = data as ResponseCompleteMessage
        const { message_id, full_content } = completeMsg.payload

        // 将流式消息转为完整消息
        setMessages((prev) => [
          ...prev,
          {
            id: message_id,
            sender: 'ai',
            content: full_content,
            timestamp: getTimestamp(),
            isStreaming: false,
          },
        ])

        // 清空流式状态
        setStreamingMessage('')
        setIsStreaming(false)
        currentMessageIdRef.current = null
        break
      }

      case 'event_added': {
        const eventMsg = data as EventAddedMessage
        const { event, theme_updates } = eventMsg.payload

        // 更新最后一条AI消息，添加提取的事件
        setMessages((prev) => {
          const lastMsg = prev[prev.length - 1]
          if (lastMsg && lastMsg.sender === 'ai') {
            const updatedMessages = [...prev]
            updatedMessages[updatedMessages.length - 1] = {
              ...lastMsg,
              extractedEvents: [...(lastMsg.extractedEvents || []), event],
            }
            return updatedMessages
          }
          return prev
        })

        // 触发回调
        if (callbacksRef.current.onEventAdded) {
          callbacksRef.current.onEventAdded(event)
        }

        // 处理主题状态更新
        if (theme_updates && callbacksRef.current.onThemeStatusChanged) {
          theme_updates.forEach((update) => {
            callbacksRef.current.onThemeStatusChanged!({
              theme_id: update.theme_id,
              old_status: update.new_status, // 简化处理，实际需要获取旧状态
              new_status: update.new_status,
              reason: '事件添加导致状态变更',
            })
          })
        }
        break
      }

      case 'event_updated': {
        // 触发事件更新回调
        if (callbacksRef.current.onEventUpdated) {
          // 从payload中提取event_id和updates
          const { event_id, updates } = data.payload as {
            event_id: string
            updates: ExtractedEvent['slots']
          }
          callbacksRef.current.onEventUpdated(event_id, updates)
        }
        break
      }

      case 'theme_status_changed': {
        const statusMsg = data as ThemeStatusChangedMessage
        const { updates } = statusMsg.payload

        // 触发回调
        if (callbacksRef.current.onThemeStatusChanged) {
          updates.forEach((update: ThemeStatusUpdate) => {
            callbacksRef.current.onThemeStatusChanged!(update)
          })
        }
        break
      }

      case 'graph_sync': {
        const syncMsg = data as GraphSyncMessage
        const { graph_state } = syncMsg.payload

        setGraphState(graph_state)

        // 触发回调
        if (callbacksRef.current.onGraphSync) {
          callbacksRef.current.onGraphSync(graph_state)
        }
        break
      }

      case 'error': {
        const errorMsg = data as WSErrorMessage
        const { code, message } = errorMsg.payload

        console.error('WebSocket错误:', code, message)

        // 触发回调
        if (callbacksRef.current.onError) {
          callbacksRef.current.onError({ code, message })
        }
        break
      }

      case 'connected': {
        const connectedMsg = data as WSConnectedMessage
        console.log('WebSocket连接成功:', connectedMsg.payload)

        setConnectionStatus(WSConnectionStatus.CONNECTED)
        reconnectCountRef.current = 0

        // 启动心跳
        startHeartbeat()

        // 触发回调
        if (callbacksRef.current.onConnected) {
          callbacksRef.current.onConnected()
        }
        break
      }

      default:
        console.warn('未知的WebSocket消息类型:', data.type)
    }
  }, [startHeartbeat])

  /**
   * 建立WebSocket连接
   */
  const connect = useCallback(() => {
    // 如果已有连接，先关闭
    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }

    clearReconnectTimer()
    setConnectionStatus(WSConnectionStatus.CONNECTING)

    try {
      const wsUrl = createWebSocketUrl(sessionId)
      const ws = new WebSocket(wsUrl)

      ws.onopen = () => {
        console.log('WebSocket连接已建立')
      }

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data) as WSMessage
          handleMessage(data)
        } catch (error) {
          console.error('解析WebSocket消息失败:', error)
        }
      }

      ws.onclose = (event) => {
        console.log('WebSocket连接关闭:', event.code, event.reason)
        clearHeartbeatTimer()
        setConnectionStatus(WSConnectionStatus.DISCONNECTED)

        // 触发断开回调
        if (callbacksRef.current.onDisconnected) {
          callbacksRef.current.onDisconnected(event.reason || '连接关闭')
        }

        // 尝试重连
        if (reconnectCountRef.current < reconnectAttempts) {
          reconnectCountRef.current += 1
          setConnectionStatus(WSConnectionStatus.RECONNECTING)

          reconnectTimerRef.current = setTimeout(() => {
            console.log(`尝试重连 (${reconnectCountRef.current}/${reconnectAttempts})`)
            connect()
          }, reconnectInterval)
        }
      }

      ws.onerror = (error) => {
        console.error('WebSocket错误:', error)
        setConnectionStatus(WSConnectionStatus.ERROR)

        // 触发错误回调
        if (callbacksRef.current.onError) {
          callbacksRef.current.onError({
            code: 'WS_ERROR',
            message: 'WebSocket连接错误',
          })
        }
      }

      wsRef.current = ws
    } catch (error) {
      console.error('创建WebSocket连接失败:', error)
      setConnectionStatus(WSConnectionStatus.ERROR)
    }
  }, [sessionId, reconnectAttempts, reconnectInterval, handleMessage, clearReconnectTimer, clearHeartbeatTimer])

  /**
   * 断开WebSocket连接
   */
  const disconnect = useCallback(() => {
    clearReconnectTimer()
    clearHeartbeatTimer()
    reconnectCountRef.current = reconnectAttempts // 阻止自动重连

    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }

    setConnectionStatus(WSConnectionStatus.DISCONNECTED)
  }, [reconnectAttempts, clearReconnectTimer, clearHeartbeatTimer])

  /**
   * 手动重连
   */
  const reconnect = useCallback(() => {
    reconnectCountRef.current = 0
    connect()
  }, [connect])

  /**
   * 发送消息
   */
  const sendMessage = useCallback((
    content: string,
    context?: SendMessageRequest['payload']['context']
  ) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      console.error('WebSocket未连接，无法发送消息')
      return
    }

    const messageId = generateMessageId()
    const timestamp = getTimestamp()

    // 添加用户消息到列表
    const userMessage: ChatMessage = {
      id: messageId,
      sender: 'user',
      content,
      timestamp,
    }
    setMessages((prev) => [...prev, userMessage])

    // 发送消息到服务器
    const request: SendMessageRequest = {
      type: 'chat_message',
      payload: {
        content,
        session_id: sessionId,
        context,
      },
    }

    wsRef.current.send(JSON.stringify(request))
  }, [sessionId])

  /**
   * 清空流式消息
   */
  const clearStreamingMessage = useCallback(() => {
    setStreamingMessage('')
    setIsStreaming(false)
    currentMessageIdRef.current = null
  }, [])

  // 组件挂载时建立连接
  useEffect(() => {
    connect()

    // 组件卸载时清理
    return () => {
      disconnect()
    }
  }, [connect, disconnect])

  return {
    isConnected,
    connectionStatus,
    streamingMessage,
    isStreaming,
    messages,
    sendMessage,
    graphState,
    clearStreamingMessage,
    reconnect,
    disconnect,
  }
}

export default useGraphWebSocket
