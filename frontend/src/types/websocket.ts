/**
 * WebSocket 类型定义
 *
 * 用于实时对话和图谱更新的消息类型
 */

import { GraphState, NodeStatus } from './index'

// ==================== WebSocket 消息类型 ====================

/** WebSocket 消息类型 */
export type WSMessageType =
  | 'token'                    // 流式token（AI回复片段）
  | 'response_complete'        // AI回复完成
  | 'event_added'              // 新事件添加
  | 'event_updated'            // 事件更新
  | 'theme_status_changed'     // 主题状态变更
  | 'graph_sync'               // 图谱状态同步
  | 'error'                    // 错误消息
  | 'connected'                // 连接成功
  | 'disconnected'             // 连接断开

/** WebSocket 消息基础接口 */
export interface WSMessage {
  type: WSMessageType
  payload: unknown
  timestamp: string
}

/** Token 消息 - 流式AI回复 */
export interface TokenMessage extends WSMessage {
  type: 'token'
  payload: {
    content: string           // token内容
    message_id: string        // 消息唯一标识
  }
}

/** 回复完成消息 */
export interface ResponseCompleteMessage extends WSMessage {
  type: 'response_complete'
  payload: {
    message_id: string
    full_content: string      // 完整回复内容
  }
}

/** 提取的事件数据结构 */
export interface ExtractedEvent {
  event_id: string
  slots: {
    time?: string
    location?: string
    people?: string[]
    event: string
    feeling?: string
  }
  confidence: number          // 置信度 0-1
  theme_id?: string           // 关联的主题ID
}

/** 事件添加消息 */
export interface EventAddedMessage extends WSMessage {
  type: 'event_added'
  payload: {
    event: ExtractedEvent
    theme_updates?: {
      theme_id: string
      new_status: NodeStatus
    }[]
  }
}

/** 事件更新消息 */
export interface EventUpdatedMessage extends WSMessage {
  type: 'event_updated'
  payload: {
    event_id: string
    updates: Partial<ExtractedEvent['slots']>
    confidence?: number
  }
}

/** 主题状态更新 */
export interface ThemeStatusUpdate {
  theme_id: string
  old_status: NodeStatus
  new_status: NodeStatus
  reason: string             // 状态变更原因
}

/** 主题状态变更消息 */
export interface ThemeStatusChangedMessage extends WSMessage {
  type: 'theme_status_changed'
  payload: {
    updates: ThemeStatusUpdate[]
  }
}

/** 图谱同步消息 */
export interface GraphSyncMessage extends WSMessage {
  type: 'graph_sync'
  payload: {
    graph_state: GraphState   // 完整图谱状态
    sync_id: string           // 同步标识
  }
}

/** 错误消息 */
export interface WSErrorMessage extends WSMessage {
  type: 'error'
  payload: {
    code: string
    message: string
    details?: unknown
  }
}

/** 连接成功消息 */
export interface WSConnectedMessage extends WSMessage {
  type: 'connected'
  payload: {
    session_id: string
    client_id: string
  }
}

/** 连接断开消息 */
export interface WSDisconnectedMessage extends WSMessage {
  type: 'disconnected'
  payload: {
    reason: string
    code: number
  }
}

// ==================== 对话消息类型 ====================

/** 消息发送者类型 */
export type MessageSender = 'user' | 'ai' | 'system'

/** 对话消息 */
export interface ChatMessage {
  id: string
  sender: MessageSender
  content: string
  timestamp: string
  isStreaming?: boolean      // 是否正在流式输出
  extractedEvents?: ExtractedEvent[]  // 从消息中提取的事件
}

/** 发送消息请求 */
export interface SendMessageRequest {
  type: 'chat_message'
  payload: {
    content: string
    session_id: string
    context?: {
      current_theme_id?: string
      mentioned_events?: string[]
    }
  }
}

// ==================== WebSocket 连接配置 ====================

/** WebSocket 连接选项 */
export interface WSConnectionOptions {
  sessionId: string
  reconnectAttempts?: number      // 最大重连次数，默认5
  reconnectInterval?: number      // 重连间隔(ms)，默认3000
  heartbeatInterval?: number      // 心跳间隔(ms)，默认30000
  onEventAdded?: (event: ExtractedEvent) => void
  onEventUpdated?: (eventId: string, updates: Partial<ExtractedEvent['slots']>) => void
  onThemeStatusChanged?: (update: ThemeStatusUpdate) => void
  onGraphSync?: (graphState: GraphState) => void
  onError?: (error: { code: string; message: string }) => void
  onConnected?: () => void
  onDisconnected?: (reason: string) => void
}

/** WebSocket 连接状态 */
export enum WSConnectionStatus {
  CONNECTING = 'connecting',
  CONNECTED = 'connected',
  DISCONNECTED = 'disconnected',
  RECONNECTING = 'reconnecting',
  ERROR = 'error',
}

/** useGraphWebSocket Hook 返回值 */
export interface UseGraphWebSocketReturn {
  isConnected: boolean
  connectionStatus: WSConnectionStatus
  streamingMessage: string
  isStreaming: boolean
  messages: ChatMessage[]
  sendMessage: (content: string, context?: SendMessageRequest['payload']['context']) => void
  graphState: GraphState | null
  clearStreamingMessage: () => void
  reconnect: () => void
  disconnect: () => void
}
