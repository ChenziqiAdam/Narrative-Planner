/**
 * PersonView - 人物视图组件
 *
 * 以人物为主键的树状结构视图
 * 展示人物关系和相关事件
 */

import React from 'react'
import {
  GraphState,
  PeopleNode,
  EventNode,
  NodeStatus,
} from '../types'
import './PersonView.css'

interface PersonViewProps {
  graphState: GraphState
  onNodeClick?: (node: PeopleNode | EventNode, type: 'person' | 'event') => void
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

const PersonView: React.FC<PersonViewProps> = ({
  graphState,
  onNodeClick,
  selectedNodeId,
  filterStatus = 'all',
  className = '',
}) => {
  const { people_nodes, event_nodes } = graphState

  // 获取人物相关的事件详情
  const getEventDetails = (eventIds: string[]) => {
    return eventIds
      .map(id => event_nodes[id])
      .filter(Boolean)
      .filter(event => {
        if (filterStatus === 'all') return true
        const theme = graphState.theme_nodes[event.theme_id]
        return theme?.status === filterStatus
      })
  }

  // 获取关系目标人物名称
  const getRelationTarget = (targetId: string) => {
    return people_nodes[targetId]?.name || targetId
  }

  // 按关系类型分组人物
  const groupedPeople = React.useMemo(() => {
    const groups: Record<string, Array<[string, PeopleNode]>> = {
      '家人': [],
      '朋友': [],
      '工作': [],
      '其他': [],
    }

    Object.entries(people_nodes).forEach(([id, person]) => {
      const relation = person.relation.toLowerCase()
      if (['父亲', '母亲', '丈夫', '妻子', '儿子', '女儿', '兄弟姐妹', '爷爷', '奶奶', '孙子', '孙女'].includes(relation)) {
        groups['家人'].push([id, person])
      } else if (['朋友', '邻居', '同学', '老乡'].includes(relation)) {
        groups['朋友'].push([id, person])
      } else if (['师傅', '工友', '同事', '领导', '下属', '老师', '学生'].includes(relation)) {
        groups['工作'].push([id, person])
      } else {
        groups['其他'].push([id, person])
      }
    })

    return groups
  }, [people_nodes])

  return (
    <div className={`person-view-container ${className}`}>
      <div className="person-view-content">
        {Object.entries(groupedPeople).map(([group, people]) => (
          people.length > 0 && (
            <div key={group} className="person-group">
              <h3 className="group-title">{group}</h3>
              <div className="person-list">
                {people.map(([id, person]) => {
                  const relatedEvents = getEventDetails(person.related_events)

                  return (
                    <div
                      key={id}
                      className={`person-card ${selectedNodeId === id ? 'selected' : ''}`}
                      onClick={() => onNodeClick?.(person, 'person')}
                    >
                      {/* 人物头部 */}
                      <div className="person-header">
                        <div className="person-avatar">
                          {person.name.charAt(0)}
                        </div>
                        <div className="person-info">
                          <span className="person-name">{person.name}</span>
                          <span className="person-relation">{person.relation}</span>
                        </div>
                      </div>

                      {/* 人物描述 */}
                      {person.description && (
                        <p className="person-description">{person.description}</p>
                      )}

                      {/* 人物关系 */}
                      {person.relationships.length > 0 && (
                        <div className="person-relationships">
                          <span className="relations-label">关系：</span>
                          <div className="relations-list">
                            {person.relationships.map((rel, idx) => (
                              <span key={idx} className="relation-tag">
                                {getRelationTarget(rel.target_id)} ({rel.relation_type})
                              </span>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* 相关事件 */}
                      {relatedEvents.length > 0 && (
                        <div className="person-events">
                          <span className="events-label">相关事件 ({relatedEvents.length})</span>
                          <div className="events-tree">
                            {relatedEvents.map(event => {
                              const theme = graphState.theme_nodes[event.theme_id]
                              const borderColor = theme
                                ? STATUS_BORDER_COLORS[theme.status]
                                : '#9CA3AF'

                              return (
                                <div
                                  key={event.event_id}
                                  className={`event-node ${selectedNodeId === event.event_id ? 'selected' : ''}`}
                                  style={{ borderLeftColor: borderColor }}
                                  onClick={(e) => {
                                    e.stopPropagation()
                                    onNodeClick?.(event, 'event')
                                  }}
                                >
                                  <div className="event-title">{event.title}</div>
                                  {event.slots.time && (
                                    <div className="event-time">{event.slots.time}</div>
                                  )}
                                </div>
                              )
                            })}
                          </div>
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            </div>
          )
        ))}
      </div>
    </div>
  )
}

export default PersonView
