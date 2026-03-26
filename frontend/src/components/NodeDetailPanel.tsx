import React from 'react'
import {
  ThemeNode,
  EventNode,
  PeopleNode,
  PeopleRelationship,
  NodeStatus,
  Domain,
  DomainLabels,
  SLOT_NAMES,
  GraphState,
} from '../types'
import './NodeDetailPanel.css'

interface NodeDetailPanelProps {
  node: ThemeNode | EventNode | PeopleNode | null
  type: 'theme' | 'event' | 'person' | null
  graphState?: GraphState
  onClose?: () => void
  className?: string
}

type CompatPeopleNode = PeopleNode & {
  person_id?: string
  display_name?: string
  relation_to_elder?: string | null
  summary?: string | null
  related_event_ids?: string[]
}

const DomainColors: Record<string, string> = {
  [Domain.LIFE_CHAPTERS]: '#3B82F6',
  [Domain.KEY_SCENES]: '#8B5CF6',
  [Domain.FUTURE_SCRIPTS]: '#06B6D4',
  [Domain.CHALLENGES]: '#EF4444',
  [Domain.PERSONAL_THOUGHTS]: '#EC4899',
  [Domain.PERSONAL_IDEOLOGY]: '#EC4899',
  [Domain.CONTEXT_MANAGEMENT]: '#6B7280',
}

const statusConfig: Record<NodeStatus, { label: string; color: string }> = {
  [NodeStatus.PENDING]: { label: '待触达', color: '#9CA3AF' },
  [NodeStatus.MENTIONED]: { label: '已提及', color: '#F59E0B' },
  [NodeStatus.EXHAUSTED]: { label: '已挖透', color: '#10B981' },
}

function getPersonDisplayName(person: PeopleNode): string {
  const compatPerson = person as CompatPeopleNode
  return compatPerson.name || compatPerson.display_name || compatPerson.person_id || compatPerson.people_id || '未命名人物'
}

function getPersonRelation(person: PeopleNode): string {
  const compatPerson = person as CompatPeopleNode
  return compatPerson.relation || compatPerson.relation_to_elder || '关系待补充'
}

function getPersonDescription(person: PeopleNode): string {
  const compatPerson = person as CompatPeopleNode
  return compatPerson.description || compatPerson.summary || ''
}

function getPersonEventIds(person: PeopleNode): string[] {
  const compatPerson = person as CompatPeopleNode
  return compatPerson.related_events || compatPerson.related_event_ids || []
}

function getPersonRelationships(person: PeopleNode): PeopleRelationship[] {
  return person.relationships || []
}

function getEmotionInfo(score: number): { icon: string; label: string; className: string } {
  if (score > 0.3) {
    return { icon: '积极', label: '积极正向', className: 'positive' }
  }
  if (score < -0.3) {
    return { icon: '低落', label: '消极负面', className: 'negative' }
  }
  return { icon: '平稳', label: '中性平和', className: 'neutral' }
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
          <span className="empty-icon">○</span>
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
  const emotionInfo = eventNode ? getEmotionInfo(eventNode.emotional_score || 0) : null
  const eventIds = personNode ? getPersonEventIds(personNode) : []
  const relationships = personNode ? getPersonRelationships(personNode) : []

  return (
    <div className={`node-detail-panel ${className}`}>
      <div className="panel-header">
        <div className="header-top">
          <span
            className="node-type-badge"
            style={{
              backgroundColor: isTheme
                ? DomainColors[themeNode?.domain || Domain.CONTEXT_MANAGEMENT]
                : isPerson
                ? '#EC4899'
                : '#F59E0B',
            }}
          >
            {isTheme ? '主题' : isPerson ? '人物' : '事件'}
          </span>
          {isTheme && themeNode && (
            <span className="domain-badge">{DomainLabels[themeNode.domain] || themeNode.domain}</span>
          )}
          {isPerson && personNode && (
            <span className="domain-badge">{getPersonRelation(personNode)}</span>
          )}
        </div>

        <h2 className="node-title">
          {isTheme && themeNode && themeNode.title}
          {isPerson && personNode && getPersonDisplayName(personNode)}
          {eventNode && eventNode.title}
        </h2>

        {onClose && (
          <button className="close-btn" onClick={onClose}>
            ×
          </button>
        )}
      </div>

      <div className="panel-content">
        {isPerson && personNode && (
          <>
            {getPersonDescription(personNode) && (
              <div className="info-section">
                <h3 className="section-label">人物描述</h3>
                <p className="description">{getPersonDescription(personNode)}</p>
              </div>
            )}

            <div className="info-section">
              <h3 className="section-label">关联事件</h3>
              {eventIds.length > 0 ? (
                <div className="events-list">
                  {eventIds.map((eventId) => {
                    const event = graphState?.event_nodes?.[eventId]
                    return (
                      <div key={eventId} className="event-tag">
                        {event?.title || eventId}
                      </div>
                    )
                  })}
                </div>
              ) : (
                <p className="description">暂无关联事件</p>
              )}
            </div>

            {relationships.length > 0 && (
              <div className="info-section">
                <h3 className="section-label">人物关系</h3>
                <div className="questions-list">
                  {relationships.map((rel, index) => {
                    const targetPerson = graphState?.people_nodes?.[rel.target_id]
                    return (
                      <div key={`${rel.target_id}-${index}`} className="question-item">
                        <span className="question-number">{index + 1}</span>
                        <p className="question-text">
                          {getPersonDisplayName(
                            targetPerson || ({ person_id: rel.target_id } as unknown as PeopleNode)
                          )} ({rel.relation_type})
                        </p>
                      </div>
                    )
                  })}
                </div>
              </div>
            )}
          </>
        )}

        {isTheme && themeNode && (
          <>
            <div className="info-section">
              <h3 className="section-label">状态</h3>
              <div className="status-display">
                <span
                  className="status-tag"
                  style={{
                    backgroundColor: `${statusConfig[themeNode.status].color}20`,
                    color: statusConfig[themeNode.status].color,
                    borderColor: statusConfig[themeNode.status].color,
                  }}
                >
                  {statusConfig[themeNode.status].label}
                </span>
              </div>
            </div>

            <div className="info-section">
              <h3 className="section-label">槽位填充</h3>
              <div className="slots-grid">
                {Object.entries(themeNode.slots_filled || {}).map(([slot, filled]) => (
                  <div key={slot} className={`slot-item ${filled ? 'filled' : ''}`}>
                    <span className="slot-icon">{filled ? '✓' : '○'}</span>
                    <span className="slot-name">{SLOT_NAMES[slot] || slot}</span>
                  </div>
                ))}
              </div>
            </div>

            {(themeNode.extracted_events || []).length > 0 && (
              <div className="info-section">
                <h3 className="section-label">已提取事件</h3>
                <div className="events-list">
                  {(themeNode.extracted_events || []).map((eventId) => {
                    const event = graphState?.event_nodes?.[eventId]
                    return (
                      <div key={eventId} className="event-tag">
                        {event?.title || eventId}
                      </div>
                    )
                  })}
                </div>
              </div>
            )}

            {(themeNode.seed_questions || []).length > 0 && (
              <div className="info-section">
                <h3 className="section-label">种子问题</h3>
                <div className="questions-list">
                  {(themeNode.seed_questions || []).slice(0, 3).map((question, index) => (
                    <div key={`${index}-${question}`} className="question-item">
                      <span className="question-number">{index + 1}</span>
                      <p className="question-text">{question}</p>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </>
        )}

        {eventNode && (
          <>
            <div className="info-section">
              <h3 className="section-label">事件概述</h3>
              <p className="description">{eventNode.slots?.event || eventNode.title}</p>
            </div>

            <div className="info-section">
              <h3 className="section-label">时间与地点</h3>
              <div className="time-location">
                <div className="info-row">
                  <span className="info-key">时间</span>
                  <span className="info-value">{eventNode.slots?.time || '未补充'}</span>
                </div>
                <div className="info-row">
                  <span className="info-key">地点</span>
                  <span className="info-value">{eventNode.location || eventNode.slots?.location || '未补充'}</span>
                </div>
              </div>
            </div>

            <div className="info-section">
              <h3 className="section-label">槽位信息</h3>
              <div className="slots-grid">
                {Object.entries(eventNode.slots || {}).map(([slot, value]) => (
                  <div key={slot} className={`slot-item ${value ? 'filled' : ''}`}>
                    <span className="slot-icon">{value ? '✓' : '○'}</span>
                    <span className="slot-name">{SLOT_NAMES[slot] || slot}</span>
                  </div>
                ))}
              </div>
            </div>

            {eventNode.people_involved?.length > 0 && (
              <div className="info-section">
                <h3 className="section-label">涉及人物</h3>
                <div className="events-list">
                  {eventNode.people_involved.map((personId) => {
                    const person = graphState?.people_nodes?.[personId]
                    return (
                      <div key={personId} className="event-tag">
                        {person ? getPersonDisplayName(person) : personId}
                      </div>
                    )
                  })}
                </div>
              </div>
            )}

            <div className="info-section">
              <h3 className="section-label">情绪与深度</h3>
              <div className="progress-info">
                <div className="progress-header">
                  <span>{emotionInfo?.icon} {emotionInfo?.label}</span>
                  <span className="depth-value">{eventNode.depth_level || 0}/5</span>
                </div>
                <div className="depth-indicator">
                  {[1, 2, 3, 4, 5].map((level) => (
                    <div
                      key={level}
                      className={`depth-level ${level <= (eventNode.depth_level || 0) ? 'active' : ''}`}
                    />
                  ))}
                </div>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

export default NodeDetailPanel
