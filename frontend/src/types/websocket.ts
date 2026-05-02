/**
 * WebSocket 类型定义 (GraphRAG)
 *
 * 用于实时对话和图谱更新的消息类型
 */

import { GraphState, NodeStatus } from './index'

// ==================== WebSocket 消息类型 ====================

export type WSMessageType =
  | 'token'
  | 'response_complete'
  | 'fragment_added'
  | 'theme_status_changed'
  | 'graph_sync'
  | 'error'
  | 'connected'
  | 'disconnected'

export interface WSMessage {
  type: WSMessageType
  payload: unknown
  timestamp: string
}

export interface TokenMessage extends WSMessage {
  type: 'token'
  payload: {
    content: string
    message_id: string
  }
}

export interface ResponseCompleteMessage extends WSMessage {
  type: 'response_complete'
  payload: {
    message_id: string
    full_content: string
  }
}

/** 叙事片段数据 */
export interface NarrativeFragmentData {
  fragment_id: string
  rich_text: string
  theme_id?: string
  confidence: number
  properties: Record<string, any>
}

export interface FragmentAddedMessage extends WSMessage {
  type: 'fragment_added'
  payload: {
    fragment: NarrativeFragmentData
    theme_updates?: {
      theme_id: string
      new_status: NodeStatus
    }[]
  }
}

export interface ThemeStatusUpdate {
  theme_id: string
  old_status: NodeStatus
  new_status: NodeStatus
  reason: string
}

export interface ThemeStatusChangedMessage extends WSMessage {
  type: 'theme_status_changed'
  payload: {
    updates: ThemeStatusUpdate[]
  }
}

export interface GraphSyncMessage extends WSMessage {
  type: 'graph_sync'
  payload: {
    graph_state: GraphState
    sync_id: string
  }
}

export interface WSErrorMessage extends WSMessage {
  type: 'error'
  payload: {
    code: string
    message: string
    details?: unknown
  }
}

export interface WSConnectedMessage extends WSMessage {
  type: 'connected'
  payload: {
    session_id: string
    client_id: string
  }
}

export interface WSDisconnectedMessage extends WSMessage {
  type: 'disconnected'
  payload: {
    reason: string
    code: number
  }
}

// ==================== 对话消息类型 ====================

export type MessageSender = 'user' | 'ai' | 'system'

export interface ChatMessage {
  id: string
  sender: MessageSender
  content: string
  timestamp: string
  isStreaming?: boolean
  extractedFragments?: NarrativeFragmentData[]
}

export interface SendMessageRequest {
  type: 'chat_message'
  payload: {
    content: string
    session_id: string
    context?: {
      current_theme_id?: string
    }
  }
}

// ==================== WebSocket 连接配置 ====================

export interface WSConnectionOptions {
  sessionId: string
  reconnectAttempts?: number
  reconnectInterval?: number
  heartbeatInterval?: number
  onFragmentAdded?: (fragment: NarrativeFragmentData) => void
  onThemeStatusChanged?: (update: ThemeStatusUpdate) => void
  onGraphSync?: (graphState: GraphState) => void
  onError?: (error: { code: string; message: string }) => void
  onConnected?: () => void
  onDisconnected?: (reason: string) => void
}

export enum WSConnectionStatus {
  CONNECTING = 'connecting',
  CONNECTED = 'connected',
  DISCONNECTED = 'disconnected',
  RECONNECTING = 'reconnecting',
  ERROR = 'error',
}

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
