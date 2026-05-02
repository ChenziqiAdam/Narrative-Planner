/**
 * LiveInterviewPanel - 实时对话面板组件
 *
 * 功能：
 * 1. 显示WebSocket连接状态
 * 2. 消息列表展示（用户+AI）
 * 3. 输入框和发送按钮
 * 4. 打字中指示器
 * 5. 自动滚动到底部
 * 6. 显示提取的叙事片段标签
 */

import React, { useRef, useEffect, useCallback, useState } from 'react'
import {
  ChatMessage,
  WSConnectionStatus,
  NarrativeFragmentData,
} from '../types/websocket'
import { GraphState } from '../types'
import './LiveInterviewPanel.css'

/** 组件属性 */
interface LiveInterviewPanelProps {
  /** 是否已连接 */
  isConnected: boolean
  /** 连接状态 */
  connectionStatus: WSConnectionStatus
  /** 消息列表 */
  messages: ChatMessage[]
  /** 当前流式消息内容 */
  streamingMessage: string
  /** 是否正在流式输出 */
  isStreaming: boolean
  /** 发送消息回调 */
  onSendMessage: (content: string) => void
  /** 重连回调 */
  onReconnect: () => void
  /** 当前图谱状态（用于显示上下文） */
  graphState?: GraphState | null
  /** 是否禁用输入 */
  disabled?: boolean
  /** 自定义类名 */
  className?: string
}

/**
 * 格式化时间戳
 * @param timestamp ISO格式时间戳
 * @returns 格式化后的时间字符串
 */
function formatTime(timestamp: string): string {
  const date = new Date(timestamp)
  return date.toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
  })
}

/**
 * 获取连接状态显示文本
 * @param status 连接状态
 * @returns 显示文本
 */
function getConnectionStatusText(status: WSConnectionStatus): string {
  switch (status) {
    case WSConnectionStatus.CONNECTED:
      return '已连接'
    case WSConnectionStatus.CONNECTING:
      return '连接中...'
    case WSConnectionStatus.RECONNECTING:
      return '重连中...'
    case WSConnectionStatus.DISCONNECTED:
      return '已断开'
    case WSConnectionStatus.ERROR:
      return '连接错误'
    default:
      return '未知状态'
  }
}

/**
 * 获取连接状态样式类名
 * @param status 连接状态
 * @returns CSS类名
 */
function getConnectionStatusClass(status: WSConnectionStatus): string {
  switch (status) {
    case WSConnectionStatus.CONNECTED:
      return 'status-connected'
    case WSConnectionStatus.CONNECTING:
    case WSConnectionStatus.RECONNECTING:
      return 'status-connecting'
    case WSConnectionStatus.DISCONNECTED:
    case WSConnectionStatus.ERROR:
      return 'status-disconnected'
    default:
      return ''
  }
}

/** 截断文本的最大长度 */
const FRAGMENT_TEXT_MAX_LENGTH = 60

/**
 * 截断文本
 * @param text 原始文本
 * @param maxLength 最大长度
 * @returns 截断后的文本
 */
function truncateText(text: string, maxLength: number = FRAGMENT_TEXT_MAX_LENGTH): string {
  if (text.length <= maxLength) return text
  return text.slice(0, maxLength) + '...'
}

/**
 * 获取置信度对应的样式类名
 * @param confidence 置信度 (0-1)
 * @returns CSS类名
 */
function getConfidenceClass(confidence: number): string {
  if (confidence >= 0.8) return 'confidence-high'
  if (confidence >= 0.5) return 'confidence-medium'
  return 'confidence-low'
}

/**
 * 渲染叙事片段标签
 */
const FragmentTag: React.FC<{ fragment: NarrativeFragmentData }> = ({ fragment }) => {
  const [expanded, setExpanded] = useState(false)

  return (
    <div className="fragment-tag">
      <div
        className="fragment-tag-header"
        onClick={() => setExpanded(!expanded)}
      >
        <span className="fragment-tag-icon">✦</span>
        <span className="fragment-tag-text">
          {truncateText(fragment.rich_text)}
        </span>
        {fragment.theme_id && (
          <span className="fragment-tag-theme">{fragment.theme_id}</span>
        )}
        <span className={`fragment-tag-confidence ${getConfidenceClass(fragment.confidence)}`}>
          {Math.round(fragment.confidence * 100)}%
        </span>
        <span className={`fragment-tag-expand ${expanded ? 'expanded' : ''}`}>
          ▼
        </span>
      </div>
      {expanded && (
        <div className="fragment-tag-details">
          <div className="fragment-detail-item">
            <span className="detail-label">片段ID:</span>
            <span className="detail-value">{fragment.fragment_id}</span>
          </div>
          <div className="fragment-detail-item">
            <span className="detail-label">完整文本:</span>
            <span className="detail-value">{fragment.rich_text}</span>
          </div>
          {fragment.theme_id && (
            <div className="fragment-detail-item">
              <span className="detail-label">主题:</span>
              <span className="detail-value">{fragment.theme_id}</span>
            </div>
          )}
          {Object.keys(fragment.properties).length > 0 && (
            <div className="fragment-detail-item">
              <span className="detail-label">属性:</span>
              <span className="detail-value">
                {Object.entries(fragment.properties)
                  .map(([key, value]) => `${key}: ${String(value)}`)
                  .join(', ')}
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

/**
 * 消息项组件
 */
const MessageItem: React.FC<{ message: ChatMessage }> = ({ message }) => {
  const isUser = message.sender === 'user'
  const isSystem = message.sender === 'system'

  return (
    <div
      className={`message-item ${isUser ? 'message-user' : ''} ${
        isSystem ? 'message-system' : ''
      }`}
    >
      <div className="message-avatar">
        {isUser ? '👤' : isSystem ? '🔔' : '🤖'}
      </div>
      <div className="message-content-wrapper">
        <div className="message-header">
          <span className="message-sender">
            {isUser ? '您' : isSystem ? '系统' : 'AI助手'}
          </span>
          <span className="message-time">{formatTime(message.timestamp)}</span>
        </div>
        <div className="message-content">
          {message.content.split('\n').map((line, index) => (
            <p key={index}>{line || ' '}</p>
          ))}
        </div>
        {/* 显示提取的叙事片段 */}
        {message.extractedFragments && message.extractedFragments.length > 0 && (
          <div className="message-extracted-fragments">
            <div className="extracted-fragments-title">提取的叙事片段:</div>
            {message.extractedFragments.map((fragment, index) => (
              <FragmentTag
                key={`${fragment.fragment_id}-${index}`}
                fragment={fragment}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

/**
 * 打字中指示器组件
 */
const TypingIndicator: React.FC = () => {
  return (
    <div className="message-item message-ai typing-indicator">
      <div className="message-avatar">🤖</div>
      <div className="message-content-wrapper">
        <div className="message-header">
          <span className="message-sender">AI助手</span>
        </div>
        <div className="typing-dots">
          <span className="dot" />
          <span className="dot" />
          <span className="dot" />
        </div>
      </div>
    </div>
  )
}

/**
 * 流式消息组件
 */
const StreamingMessage: React.FC<{ content: string }> = ({ content }) => {
  return (
    <div className="message-item message-ai streaming-message">
      <div className="message-avatar">🤖</div>
      <div className="message-content-wrapper">
        <div className="message-header">
          <span className="message-sender">AI助手</span>
          <span className="streaming-badge">输出中...</span>
        </div>
        <div className="message-content streaming">
          {content.split('\n').map((line, index) => (
            <p key={index}>{line || ' '}</p>
          ))}
          <span className="streaming-cursor">▊</span>
        </div>
      </div>
    </div>
  )
}

/**
 * 实时对话面板组件
 */
const LiveInterviewPanel: React.FC<LiveInterviewPanelProps> = ({
  isConnected,
  connectionStatus,
  messages,
  streamingMessage,
  isStreaming,
  onSendMessage,
  onReconnect,
  graphState,
  disabled = false,
  className = '',
}) => {
  // 输入框内容
  const [inputValue, setInputValue] = useState('')
  // 消息列表容器引用（用于自动滚动）
  const messagesContainerRef = useRef<HTMLDivElement>(null)
  // 输入框引用
  const inputRef = useRef<HTMLTextAreaElement>(null)
  // 是否自动滚动（用户手动滚动时暂停）
  const autoScrollRef = useRef(true)

  /**
   * 自动滚动到底部
   */
  const scrollToBottom = useCallback(() => {
    if (messagesContainerRef.current && autoScrollRef.current) {
      const container = messagesContainerRef.current
      container.scrollTop = container.scrollHeight
    }
  }, [])

  /**
   * 处理消息列表变化，自动滚动
   */
  useEffect(() => {
    scrollToBottom()
  }, [messages, streamingMessage, scrollToBottom])

  /**
   * 处理滚动事件
   * 检测用户是否手动滚动，如果是则暂停自动滚动
   */
  const handleScroll = useCallback(() => {
    if (messagesContainerRef.current) {
      const container = messagesContainerRef.current
      const isAtBottom =
        container.scrollHeight - container.scrollTop - container.clientHeight < 50
      autoScrollRef.current = isAtBottom
    }
  }, [])

  /**
   * 发送消息处理
   */
  const handleSend = useCallback(() => {
    const trimmedValue = inputValue.trim()
    if (!trimmedValue || !isConnected || disabled) {
      return
    }

    onSendMessage(trimmedValue)
    setInputValue('')
    autoScrollRef.current = true

    // 重新聚焦输入框
    if (inputRef.current) {
      inputRef.current.focus()
    }
  }, [inputValue, isConnected, disabled, onSendMessage])

  /**
   * 处理键盘事件
   * Enter发送，Shift+Enter换行
   */
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault()
        handleSend()
      }
    },
    [handleSend]
  )

  /**
   * 处理重连
   */
  const handleReconnect = useCallback(() => {
    onReconnect()
  }, [onReconnect])

  // 计算输入框行数
  const inputRows = Math.min(5, Math.max(1, inputValue.split('\n').length))

  return (
    <div className={`live-interview-panel ${className}`}>
      {/* 面板头部 - 连接状态 */}
      <div className="panel-header">
        <div className="panel-title">
          <span className="title-icon">💬</span>
          <span>实时对话</span>
        </div>
        <div className="connection-status-wrapper">
          <div
            className={`connection-status ${getConnectionStatusClass(
              connectionStatus
            )}`}
          >
            <span className="status-dot" />
            <span className="status-text">
              {getConnectionStatusText(connectionStatus)}
            </span>
          </div>
          {!isConnected && (
            <button
              className="reconnect-btn"
              onClick={handleReconnect}
              disabled={
                connectionStatus === WSConnectionStatus.CONNECTING ||
                connectionStatus === WSConnectionStatus.RECONNECTING
              }
            >
              重连
            </button>
          )}
        </div>
      </div>

      {/* 消息列表 */}
      <div
        ref={messagesContainerRef}
        className="messages-container"
        onScroll={handleScroll}
      >
        {messages.length === 0 && !isStreaming ? (
          <div className="empty-state">
            <div className="empty-icon">📝</div>
            <p>开始您的叙事之旅</p>
            <p className="empty-hint">
              与AI助手对话，分享您的故事和回忆
            </p>
          </div>
        ) : (
          <>
            {messages.map((message, index) => (
              <MessageItem key={`${message.id}-${index}`} message={message} />
            ))}
            {/* 流式消息 */}
            {isStreaming && streamingMessage && (
              <StreamingMessage content={streamingMessage} />
            )}
            {/* 打字中指示器（仅在没有流式内容时显示） */}
            {isStreaming && !streamingMessage && <TypingIndicator />}
          </>
        )}
      </div>

      {/* 输入区域 */}
      <div className="input-area">
        {!isConnected && (
          <div className="input-overlay">
            <span>连接已断开，请重连后继续对话</span>
          </div>
        )}
        <div className="input-wrapper">
          <textarea
            ref={inputRef}
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={
              isConnected
                ? '输入消息，按Enter发送，Shift+Enter换行...'
                : '等待连接...'
            }
            rows={inputRows}
            disabled={!isConnected || disabled}
            className="message-input"
          />
          <button
            onClick={handleSend}
            disabled={
              !isConnected ||
              disabled ||
              !inputValue.trim() ||
              isStreaming
            }
            className="send-btn"
            title="发送消息"
          >
            {isStreaming ? (
              <span className="send-icon spinning">⏳</span>
            ) : (
              <span className="send-icon">➤</span>
            )}
          </button>
        </div>
        <div className="input-hint">
          <span>Enter 发送 · Shift+Enter 换行</span>
          {graphState && (
            <span className="context-info">
              当前会话: {graphState.elder_info?.name || '未知'}
            </span>
          )}
        </div>
      </div>
    </div>
  )
}

export default LiveInterviewPanel
