/**
 * TimelineCanvas - 时间轴视图组件
 *
 * 按时间轴排列事件节点
 * 显示5个核心槽位：[时间] [地点] [人物] [事件] [感受]
 * 以及情绪能量和挖掘深度
 */

import React from 'react'
import {
  GraphState,
  EventNode,
  NodeStatus,
} from '../types'
import './TimelineCanvas.css'

interface TimelineCanvasProps {
  graphState: GraphState
  onNodeClick?: (node: EventNode, type: 'event') => void
  selectedNodeId?: string | null
  filterStatus?: NodeStatus | 'all'
  className?: string
}

// 状态边框颜色
const STATUS_BORDER_COLORS: Record<NodeStatus, string> = {
  [NodeStatus.PENDING]: '#9CA3AF',
  [NodeStatus.MENTIONED]: '#F59E0B',
  [NodeStatus.EXHAUSTED]: '#10B981',
}

// 情绪颜色映射
const EMOTION_COLORS: Record<string, string> = {
  positive: '#10B981',
  neutral: '#6B7280',
  negative: '#EF4444',
}

// 获取情绪类别
function getEmotionClass(score: number): string {
  if (score > 0.3) return 'positive'
  if (score < -0.3) return 'negative'
  return 'neutral'
}

// 获取情绪图标
function getEmotionIcon(score: number): string {
  if (score > 0.3) return '😊'
  if (score > 0) return '🙂'
  if (score === 0) return '😐'
  if (score > -0.3) return '😕'
  return '😢'
}

const TimelineCanvas: React.FC<TimelineCanvasProps> = ({
  graphState,
  onNodeClick,
  selectedNodeId,
  filterStatus = 'all',
  className = '',
}) => {
  // 过滤并排序事件节点（按时间锚点）
  const sortedEvents = Object.entries(graphState.event_nodes)
    .filter(([_, event]) => {
      const theme = graphState.theme_nodes[event.theme_id]
      if (!theme) return false
      // 按状态筛选
      if (filterStatus !== 'all' && theme.status !== filterStatus) return false
      return true
    })
    .sort(([, a], [, b]) => {
      // 按槽位时间排序
      const timeA = a.slots.time || ''
      const timeB = b.slots.time || ''
      return timeA.localeCompare(timeB)
    })

  return (
    <div className={`timeline-canvas-container ${className}`}>
      <div className="timeline-content">
        {sortedEvents.length === 0 ? (
          <div className="timeline-empty">
            <span className="empty-icon">📋</span>
            <p>暂无事件数据</p>
          </div>
        ) : (
          <div className="timeline-events">
            <div className="timeline-line" />
            {sortedEvents.map(([id, event]) => {
              const theme = graphState.theme_nodes[event.theme_id]
              const borderColor = theme
                ? STATUS_BORDER_COLORS[theme.status]
                : '#9CA3AF'
              const emotionClass = getEmotionClass(event.emotional_score)
              const emotionColor = EMOTION_COLORS[emotionClass]

              return (
                <div key={id} className="timeline-event-wrapper">
                  {/* 时间轴圆点 */}
                  <div
                    className="timeline-dot"
                    style={{ backgroundColor: borderColor }}
                  />

                  {/* 事件卡片 */}
                  <div
                    className={`timeline-node event-node ${selectedNodeId === id ? 'selected' : ''}`}
                    style={{ borderColor }}
                    onClick={() => onNodeClick?.(event, 'event')}
                  >
                    {/* 事件头部：时间 + 标题 */}
                    <div className="event-header">
                      <div className="event-time">
                        🕐 {event.slots.time || '时间未知'}
                      </div>
                      <div className="event-title">{event.title}</div>
                      {theme && (
                        <div className="event-theme-tag">
                          {theme.title}
                        </div>
                      )}
                    </div>

                    {/* 5个核心槽位 */}
                    <div className="event-slots">
                      <div className="slot-row">
                        <span className="slot-label">📍 地点</span>
                        <span className="slot-value">
                          {event.slots.location || <em>未填充</em>}
                        </span>
                      </div>
                      <div className="slot-row">
                        <span className="slot-label">👥 人物</span>
                        <span className="slot-value">
                          {event.slots.people || <em>未填充</em>}
                        </span>
                      </div>
                      <div className="slot-row">
                        <span className="slot-label">📝 事件</span>
                        <span className="slot-value event-description">
                          {event.slots.event || <em>未填充</em>}
                        </span>
                      </div>
                      <div className="slot-row">
                        <span className="slot-label">💭 感受</span>
                        <span className="slot-value reflection-text">
                          {event.slots.reflection || <em>未填充</em>}
                        </span>
                      </div>
                    </div>

                    {/* 分析指标 */}
                    <div className="event-metrics">
                      {/* 情绪能量 */}
                      <div className="metric-item">
                        <span className="metric-label">
                          {getEmotionIcon(event.emotional_score)} 情绪能量
                        </span>
                        <div className="metric-bar-wrapper">
                          <div className="metric-bar">
                            <div
                              className="metric-fill"
                              style={{
                                width: `${(event.emotional_score + 1) * 50}%`,
                                backgroundColor: emotionColor,
                              }}
                            />
                          </div>
                          <span
                            className="metric-value"
                            style={{ color: emotionColor }}
                          >
                            {event.emotional_score.toFixed(2)}
                          </span>
                        </div>
                      </div>

                      {/* 挖掘深度 */}
                      <div className="metric-item">
                        <span className="metric-label">⛏️ 挖掘深度</span>
                        <div className="depth-indicator">
                          {[1, 2, 3, 4, 5].map(level => (
                            <div
                              key={level}
                              className={`depth-pip ${level <= event.depth_level ? 'active' : ''}`}
                            />
                          ))}
                          <span className="depth-value">{event.depth_level}/5</span>
                        </div>
                      </div>
                    </div>

                    {/* 标签 */}
                    {event.tags && event.tags.length > 0 && (
                      <div className="event-tags">
                        {event.tags.map((tag, idx) => (
                          <span key={idx} className="tag-item">{tag}</span>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}

export default TimelineCanvas
