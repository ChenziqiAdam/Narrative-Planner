import React from 'react'
import { EventNode, GraphState, NodeStatus, PeopleNode } from '../types'
import {
  getRelationGroup,
  getRelationGroupLabel,
  getRelationLabel,
  isSelfReference,
  RelationGroupKey,
} from '../utils/relationLexicon'
import './PersonView.css'

interface PersonViewProps {
  graphState: GraphState
  onNodeClick?: (node: PeopleNode | EventNode, type: 'person' | 'event') => void
  selectedNodeId?: string | null
  filterStatus?: NodeStatus | 'all'
  className?: string
}

type CompatPeopleNode = PeopleNode & {
  person_id?: string
  display_name?: string
  relation_to_elder?: string | null
  summary?: string | null
  related_event_ids?: string[]
  aliases?: string[]
}

const GROUP_CONFIG: Record<RelationGroupKey, { color: string; bgColor: string; icon: string }> = {
  family: {
    color: '#ec4899',
    bgColor: '#fdf2f8',
    icon: '家',
  },
  friend: {
    color: '#8b5cf6',
    bgColor: '#f5f3ff',
    icon: '友',
  },
  work: {
    color: '#3b82f6',
    bgColor: '#eff6ff',
    icon: '工',
  },
  other: {
    color: '#6b7280',
    bgColor: '#f9fafb',
    icon: '其',
  },
}

const STATUS_COLORS: Record<NodeStatus, string> = {
  [NodeStatus.PENDING]: '#9ca3af',
  [NodeStatus.MENTIONED]: '#f59e0b',
  [NodeStatus.EXHAUSTED]: '#10b981',
}

const getCompatPerson = (person: PeopleNode): CompatPeopleNode => person as CompatPeopleNode

const getPersonId = (person: PeopleNode, fallbackId: string): string => {
  const compat = getCompatPerson(person)
  return compat.person_id || compat.people_id || fallbackId
}

const getPersonName = (person: PeopleNode): string => {
  const compat = getCompatPerson(person)
  return compat.name || compat.display_name || '未命名人物'
}

const getAliases = (person: PeopleNode): string[] => {
  const compat = getCompatPerson(person)
  return compat.aliases || []
}

const getPersonRelationRaw = (person: PeopleNode): string => {
  const compat = getCompatPerson(person)
  return (compat.relation || compat.relation_to_elder || '').trim()
}

const getPersonRelation = (person: PeopleNode): string =>
  getRelationLabel(getPersonRelationRaw(person))

const getPersonSummary = (person: PeopleNode): string => {
  const compat = getCompatPerson(person)
  return compat.description || compat.summary || ''
}

const getRelatedEventIds = (person: PeopleNode): string[] => {
  const compat = getCompatPerson(person)
  return compat.related_events || compat.related_event_ids || []
}

const getRelationships = (person: PeopleNode) => person.relationships || []

const getPersonGroup = (person: PeopleNode): RelationGroupKey =>
  getRelationGroup(
    [
      getPersonName(person),
      getPersonRelationRaw(person),
      getPersonSummary(person),
      ...getAliases(person),
    ],
    getPersonRelationRaw(person),
  )

const PersonView: React.FC<PersonViewProps> = ({
  graphState,
  onNodeClick,
  selectedNodeId,
  filterStatus = 'all',
  className = '',
}) => {
  const visibleGroups = React.useMemo(() => {
    const themeNodes = graphState.theme_nodes || {}
    const eventNodes = graphState.event_nodes || {}
    const grouped: Record<RelationGroupKey, Array<{
      id: string
      person: PeopleNode
      relation: string
      summary: string
      events: EventNode[]
      relationships: ReturnType<typeof getRelationships>
    }>> = {
      family: [],
      friend: [],
      work: [],
      other: [],
    }

    Object.entries(graphState.people_nodes || {}).forEach(([fallbackId, person]) => {
      if (isSelfReference(getPersonName(person))) {
        return
      }

      const personId = getPersonId(person, fallbackId)
      const relation = getPersonRelation(person)
      const group = getPersonGroup(person)
      const events = getRelatedEventIds(person)
        .map(eventId => eventNodes[eventId])
        .filter((event): event is EventNode => Boolean(event))
        .filter(event => {
          if (filterStatus === 'all') return true
          const theme = themeNodes[event.theme_id]
          return theme?.status === filterStatus
        })

      if (filterStatus !== 'all' && events.length === 0) {
        return
      }

      grouped[group].push({
        id: personId,
        person,
        relation,
        summary: getPersonSummary(person),
        events,
        relationships: getRelationships(person),
      })
    })

    return grouped
  }, [graphState, filterStatus])

  const groupOrder: RelationGroupKey[] = ['family', 'friend', 'work', 'other']
  const totalPeople = groupOrder.reduce((count, group) => count + visibleGroups[group].length, 0)

  if (totalPeople === 0) {
    return (
      <div className={`person-view-container ${className}`}>
        <div className="person-view-empty">
          <div className="empty-icon">人</div>
          <p>当前没有可展示的人物关系</p>
        </div>
      </div>
    )
  }

  return (
    <div className={`person-view-container ${className}`}>
      <div className="person-view-content">
        <div className="person-root-card">
          <div className="person-root-avatar">访</div>
          <div className="person-root-meta">
            <div className="person-root-title">{graphState.elder_info?.name || '受访者'}</div>
            <div className="person-root-subtitle">
              已识别人物 {totalPeople} 位，关联事件 {graphState.event_count} 个
            </div>
          </div>
        </div>

        <div className="person-group-grid">
          {groupOrder.map(group => {
            const items = visibleGroups[group]
            if (items.length === 0) return null

            const config = GROUP_CONFIG[group]
            return (
              <section
                key={group}
                className="person-group-card"
                style={{ '--group-color': config.color, '--group-bg': config.bgColor } as React.CSSProperties}
              >
                <header className="person-group-header">
                  <div className="person-group-title">
                    <span className="person-group-icon">{config.icon}</span>
                    <span>{getRelationGroupLabel(group)}</span>
                  </div>
                  <span className="person-group-count">{items.length}</span>
                </header>

                <div className="person-card-list">
                  {items.map(({ id, person, relation, summary, events, relationships }) => {
                    const isSelected = selectedNodeId === id
                    return (
                      <article
                        key={id}
                        className={`person-card ${isSelected ? 'selected' : ''}`}
                        onClick={() => onNodeClick?.(person, 'person')}
                      >
                        <div className="person-card-header">
                          <div>
                            <div className="person-name">{getPersonName(person)}</div>
                            <div className="person-relation">{relation}</div>
                          </div>
                          <div className="person-metrics">
                            <span className="metric-pill">{events.length} 事件</span>
                            {relationships.length > 0 && (
                              <span className="metric-pill subtle">{relationships.length} 关系</span>
                            )}
                          </div>
                        </div>

                        {summary && <p className="person-summary">{summary}</p>}

                        {events.length > 0 ? (
                          <div className="person-event-list">
                            {events.map(event => {
                              const theme = graphState.theme_nodes[event.theme_id]
                              const borderColor = theme ? STATUS_COLORS[theme.status] : '#9ca3af'
                              const isEventSelected = selectedNodeId === event.event_id
                              return (
                                <button
                                  key={event.event_id}
                                  className={`person-event-chip ${isEventSelected ? 'selected' : ''}`}
                                  style={{ '--event-color': borderColor } as React.CSSProperties}
                                  onClick={evt => {
                                    evt.stopPropagation()
                                    onNodeClick?.(event, 'event')
                                  }}
                                >
                                  <span className="event-chip-dot" />
                                  <span>{event.title}</span>
                                </button>
                              )
                            })}
                          </div>
                        ) : (
                          <div className="person-empty-events">当前筛选条件下暂无关联事件</div>
                        )}
                      </article>
                    )
                  })}
                </div>
              </section>
            )
          })}
        </div>
      </div>
    </div>
  )
}

export default PersonView
