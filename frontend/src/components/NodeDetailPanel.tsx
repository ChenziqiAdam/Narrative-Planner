/**
 * NodeDetailPanel - 节点详情面板组件
 *
 * 展示主题节点、事件节点、人物节点的详细信息
 * 事件节点显示5个核心槽位填充情况、情绪色彩
 */

import React from 'react'
import {
  ThemeNode,
  EventNode,
  PeopleNode,
  NodeStatus,
  Domain,
  DomainLabels,
  SLOT_NAMES,
} from '../types'
import './NodeDetailPanel.css'

import { GraphState } from '../types'

interface NodeDetailPanelProps {
  node: ThemeNode | EventNode | PeopleNode | null
  type: 'theme' | 'event' | 'person' | null
  graphState?: GraphState // 用于解析人物名称
  onClose?: () => void
  className?: string
}

// 领域颜色映射（低饱和度）
const DomainColors: Record<Domain, string> = {
  [Domain.LIFE_CHAPTERS]: '#3B82F6',
  [Domain.KEY_SCENES]: '#8B5CF6',
  [Domain.FUTURE_SCRIPTS]: '#06B6D4',
  [Domain.CHALLENGES]: '#EF4444',
  [Domain.PERSONAL_THOUGHTS]: '#EC4899',
  [Domain.PERSONAL_IDEOLOGY]: '#EC4899',
  [Domain.CONTEXT_MANAGEMENT]: '#6B7280',
}

// 状态标签配置
const statusConfig: Record<NodeStatus, { label: string; color: string }> = {
  [NodeStatus.PENDING]: { label: '待触达', color: '#9CA3AF' },
  [NodeStatus.MENTIONED]: { label: '已提及', color: '#F59E0B' },
  [NodeStatus.EXHAUSTED]: { label: '已挖透', color: '#10B981' },
}

// 获取情绪描述
function getEmotionInfo(score: number): { icon: string; label: string; className: string } {
  if (score > 0.3) {
    return { icon: '😊', label: '积极正向', className: 'positive' }
  } else if (score < -0.3) {
    return { icon: '😢', label: '消极负面', className: 'negative' }
  }
  return { icon: '😐', label: '中性平和', className: 'neutral' }
}

const NodeDetailPanel: React.FC<NodeDetailPanelProps> = ({
  node,
  type,
  graphState,
  onClose,
  className = '',
}) => {
  if (!node || !type) {
    return (
      <div className={`node-detail-panel empty ${className}`}>
        <div className="empty-state">
          <span className="empty-icon">◎</span>
          <p>点击节点查看详情</p>
        </div>
      </div>
    )
  }

  const isTheme = type === 'theme'
  const isPerson = type === 'person'
  const themeNode = isTheme ? (node as ThemeNode) : null
  const eventNode = !isTheme && !isPerson ? (node as EventNode) : null
  const personNode = isPerson ? (node as PeopleNode) : null

  return (
    <div className={`node-detail-panel ${className}`}>
      {/* 头部 */}
      <div className="panel-header">
        <div className="header-top">
          <span
            className="node-type-badge"
            style={{
              backgroundColor: isTheme
                ? DomainColors[themeNode!.domain]
                : isPerson
                ? '#EC4899'
                : '#F59E0B',
            }}
          >
            {isTheme ? '主题' : isPerson ? '人物' : '事件'}
          </span>
          {isTheme && themeNode && (
            <span className="domain-badge">
              {DomainLabels[themeNode.domain]}
            </span>
          )}
          {isPerson && personNode && (
            <span className="domain-badge">
              {personNode.relation}
            </span>
          )}
        </div>
        <h2 className="node-title">{isPerson && personNode ? personNode.name : (node as ThemeNode | EventNode).title}</h2>
        {onClose && (
          <button className="close-btn" onClick={onClose}>
            ✕
          </button>
        )}
      </div>

      {/* 内容 */}
      <div className="panel-content">
        {/* 描述 - 仅事件节点有 location */}
        {!isTheme && !isPerson && eventNode && eventNode.location && (
          <div className="info-section">
            <h3 className="section-label">地点</h3>
            <p className="description">{eventNode.location}</p>
          </div>
        )}

        {/* 人物节点专属信息 */}
        {isPerson && personNode && (
          <>
            {/* 人物描述 */}
            {personNode.description && (
              <div className="info-section">
                <h3 className="section-label">人物描述</h3>
                <p className="description">{personNode.description}</p>
              </div>
            )}

            {/* 相关事件 */}
            {personNode.related_events.length > 0 && (
              <div className="info-section">
                <h3 className="section-label">
                  相关事件 ({personNode.related_events.length})
                </h3>
                <div className="events-list">
                  {personNode.related_events.map((eventId) => {
                    const event = graphState?.event_nodes[eventId]
                    return (
                      <div key={eventId} className="event-tag">
                        {event?.title || eventId}
                      </div>
                    )
                  })}
                </div>
              </div>
            )}

            {/* 人物关系 */}
            {personNode.relationships.length > 0 && (
              <div className="info-section">
                <h3 className="section-label">人物关系</h3>
                <div className="relationships-list">
                  {personNode.relationships.map((rel, index) => {
                    const targetPerson = graphState?.people_nodes?.[rel.target_id]
                    return (
                      <div key={index} className="relationship-item">
                        <span className="relation-arrow">→</span>
                        <span className="relation-target">
                          {targetPerson?.name || rel.target_id}
                        </span>
                        <span className="relation-type">({rel.relation_type})</span>
                      </div>
                    )
                  })}
                </div>
              </div>
            )}
          </>
        )}

        {/* 主题节点专属信息 */}
        {isTheme && themeNode && (
          <>
            {/* 状态 */}
            <div className="info-section">
              <h3 className="section-label">状态</h3>
              <div className="status-display">
                <span
                  className="status-tag"
                  style={{
                    backgroundColor: statusConfig[themeNode.status].color + '20',
                    color: statusConfig[themeNode.status].color,
                    borderColor: statusConfig[themeNode.status].color,
                  }}
                >
                  {statusConfig[themeNode.status].label}
                </span>
              </div>
            </div>

            {/* 槽位填充 */}
            {Object.keys(themeNode.slots_filled).length > 0 && (
              <div className="info-section">
                <h3 className="section-label">槽位填充</h3>
                <div className="slots-grid">
                  {Object.entries(themeNode.slots_filled).map(([slot, filled]) => (
                    <div
                      key={slot}
                      className={`slot-item ${filled ? 'filled' : ''}`}
                    >
                      <span className="slot-icon">{filled ? '✓' : '○'}</span>
                      <span className="slot-name">{SLOT_NAMES[slot] || slot}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* 已提取事件 */}
            {(themeNode.extracted_events || []).length > 0 && (
              <div className="info-section">
                <h3 className="section-label">
                  已提取事件 ({(themeNode.extracted_events || []).length})
                </h3>
                <div className="events-list">
                  {(themeNode.extracted_events || []).map((eventId) => {
                    const event = graphState?.event_nodes[eventId]
                    return (
                      <div key={eventId} className="event-tag">
                        {event?.title || eventId}
                      </div>
                    )
                  })}
                </div>
              </div>
            )}

            {/* 依赖主题 */}
            {themeNode.depends_on.length > 0 && (
              <div className="info-section">
                <h3 className="section-label">依赖主题</h3>
                <div className="depends-list">
                  {themeNode.depends_on.map((depId) => {
                    const depTheme = graphState?.theme_nodes[depId]
                    return (
                      <div key={depId} className="depend-tag">
                        {depTheme?.title || depId}
                      </div>
                    )
                  })}
                </div>
              </div>
            )}

            {/* 种子问题 */}
            {themeNode.seed_questions.length > 0 && (
              <div className="info-section">
                <h3 className="section-label">种子问题</h3>
                <div className="questions-list">
                  {themeNode.seed_questions.slice(0, 3).map((q, i) => (
                    <div key={i} className="question-item">
                      <span className="question-number">{i + 1}</span>
                      <p className="question-text">{q}</p>
                    </div>
                  ))}
                  {themeNode.seed_questions.length > 3 && (
                    <p className="more-questions">
                      还有 {themeNode.seed_questions.length - 3} 个问题...
                    </p>
                  )}
                </div>
              </div>
            )}
          </>
        )}

        {/* 事件节点专属信息 */}
        {!isTheme && !isPerson && eventNode && (
          <>
            {/* 5个核心槽位 */}
            <div className="info-section">
              <h3 className="section-label">叙事要素 (5个核心槽位)</h3>
              <div className="slots-detail">
                {Object.entries(SLOT_NAMES).map(([key, label]) => {
                  const value = eventNode.slots[key as keyof EventNode['slots']]
                  return (
                    <div key={key} className={`slot-row ${value ? 'filled' : ''}`}>
                      <span className="slot-key">{label}</span>
                      <span className="slot-value">
                        {value || <em>未填充</em>}
                      </span>
                    </div>
                  )
                })}
              </div>
            </div>

            {/* 涉及人物 */}
            {eventNode.people_involved.length > 0 && (
              <div className="info-section">
                <h3 className="section-label">涉及人物</h3>
                <div className="people-tags">
                  {eventNode.people_involved.map((personId) => {
                    const person = graphState?.people_nodes?.[personId]
                    return (
                      <span key={personId} className="person-tag">
                        👤 {person?.name || personId}
                      </span>
                    )
                  })}
                </div>
              </div>
            )}

            {/* 分析指标 - 情绪能量 */}
            <div className="info-section">
              <h3 className="section-label">分析指标</h3>
              <div className="metrics-grid">
                {/* 情绪能量 */}
                <div className="metric-item">
                  <span className="metric-label">情绪能量</span>
                  <div className="metric-bar">
                    <div
                      className="metric-fill"
                      style={{
                        width: `${(eventNode.emotional_score + 1) * 50}%`,
                        backgroundColor:
                          eventNode.emotional_score > 0.3
                            ? '#10B981'
                            : eventNode.emotional_score < -0.3
                            ? '#EF4444'
                            : '#6B7280',
                      }}
                    />
                  </div>
                  <span className="metric-value">
                    {eventNode.emotional_score.toFixed(2)}
                  </span>
                </div>

                {/* 情绪指示器 */}
                <div
                  className={`emotion-indicator ${getEmotionInfo(eventNode.emotional_score).className}`}
                >
                  <span className="emotion-icon">
                    {getEmotionInfo(eventNode.emotional_score).icon}
                  </span>
                  <span>{getEmotionInfo(eventNode.emotional_score).label}</span>
                </div>

                {/* 挖掘深度 */}
                <div className="metric-item">
                  <span className="metric-label">挖掘深度</span>
                  <div className="depth-pips">
                    {[1, 2, 3, 4, 5].map((level) => (
                      <div
                        key={level}
                        className={`depth-pip ${
                          level <= eventNode.depth_level ? 'active' : ''
                        }`}
                      />
                    ))}
                  </div>
                  <span className="metric-value">{eventNode.depth_level}/5</span>
                </div>
              </div>
            </div>

            {/* 典型对话 */}
            {eventNode.typical_dialogue && (
              <div className="info-section">
                <h3 className="section-label">典型对话</h3>
                <p className="typical-dialogue">"{eventNode.typical_dialogue}"</p>
              </div>
            )}

            {/* 标签 */}
            {eventNode.tags && eventNode.tags.length > 0 && (
              <div className="info-section">
                <h3 className="section-label">标签</h3>
                <div className="tags-list">
                  {eventNode.tags.map((tag, index) => (
                    <span key={index} className="tag-item">
                      {tag}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}

export default NodeDetailPanel
