/**
 * ThemeView - 主题思维导图视图组件
 *
 * 以思维导图方式呈现主题层级结构
 * 一级：人生篇章、关键场景、未来剧本、挑战、个人思想
 * 二级：各领域下的细分主题
 * 三级：每个主题覆盖的事件
 */

import React from 'react'
import {
  GraphState,
  ThemeNode,
  EventNode,
  Domain,
  NodeStatus,
} from '../types'
import './ThemeView.css'

interface ThemeViewProps {
  graphState: GraphState
  onNodeClick?: (node: ThemeNode | EventNode, type: 'theme' | 'event') => void
  selectedNodeId?: string | null
  filterStatus?: NodeStatus | 'all'
  className?: string
}

// 领域颜色配置
const DOMAIN_CONFIG: Record<string, { color: string; bgColor: string; icon: string }> = {
  [Domain.LIFE_CHAPTERS]: {
    color: '#3B82F6',
    bgColor: '#EFF6FF',
    icon: '📖',
  },
  [Domain.KEY_SCENES]: {
    color: '#8B5CF6',
    bgColor: '#F5F3FF',
    icon: '🎬',
  },
  [Domain.FUTURE_SCRIPTS]: {
    color: '#06B6D4',
    bgColor: '#ECFEFF',
    icon: '🌟',
  },
  [Domain.CHALLENGES]: {
    color: '#EF4444',
    bgColor: '#FEF2F2',
    icon: '⛰️',
  },
  [Domain.PERSONAL_THOUGHTS]: {
    color: '#EC4899',
    bgColor: '#FDF2F8',
    icon: '💭',
  },
  [Domain.PERSONAL_IDEOLOGY]: {
    color: '#EC4899',
    bgColor: '#FDF2F8',
    icon: '💭',
  },
  [Domain.CONTEXT_MANAGEMENT]: {
    color: '#6B7280',
    bgColor: '#F9FAFB',
    icon: '🧭',
  },
}

// 领域中文名称
const DOMAIN_NAMES: Record<string, string> = {
  [Domain.LIFE_CHAPTERS]: '人生篇章',
  [Domain.KEY_SCENES]: '关键场景',
  [Domain.FUTURE_SCRIPTS]: '未来剧本',
  [Domain.CHALLENGES]: '挑战',
  [Domain.PERSONAL_THOUGHTS]: '个人思想',
  [Domain.PERSONAL_IDEOLOGY]: '个人思想',
  [Domain.CONTEXT_MANAGEMENT]: '上下文管理',
}

// 状态标签
const STATUS_LABELS: Record<NodeStatus, { text: string; color: string }> = {
  [NodeStatus.PENDING]: { text: '待触达', color: '#9CA3AF' },
  [NodeStatus.MENTIONED]: { text: '已提及', color: '#F59E0B' },
  [NodeStatus.EXHAUSTED]: { text: '已挖透', color: '#10B981' },
}

const ThemeView: React.FC<ThemeViewProps> = ({
  graphState,
  onNodeClick,
  selectedNodeId,
  filterStatus = 'all',
  className = '',
}) => {
  // 按领域分组主题
  const themesByDomain = React.useMemo(() => {
    const grouped: Record<string, Array<[string, ThemeNode]>> = {}

    Object.entries(graphState.theme_nodes).forEach(([id, theme]) => {
      // 状态过滤
      if (filterStatus !== 'all' && theme.status !== filterStatus) return

      const domain = theme.domain
      if (!grouped[domain]) {
        grouped[domain] = []
      }
      grouped[domain].push([id, theme])
    })

    return grouped
  }, [graphState.theme_nodes, filterStatus])

  // 获取主题的事件列表
  const getThemeEvents = (themeId: string) => {
    const theme = graphState.theme_nodes[themeId]
    if (!theme) return []

    return (theme.extracted_events || [])
      .map(eventId => graphState.event_nodes[eventId])
      .filter(Boolean)
  }

  // 按领域顺序渲染
  const domainOrder = [
    Domain.LIFE_CHAPTERS,
    Domain.KEY_SCENES,
    Domain.FUTURE_SCRIPTS,
    Domain.CHALLENGES,
    Domain.PERSONAL_THOUGHTS,
    Domain.PERSONAL_IDEOLOGY,
    Domain.CONTEXT_MANAGEMENT,
  ]

  return (
    <div className={`theme-view-container ${className}`}>
      <div className="theme-view-content">
        {/* 中心节点 - 受访者 */}
        <div className="mindmap-center">
          <div className="center-node">
            <span className="center-avatar">👵</span>
            <span className="center-name">
              {graphState.elder_info?.name || '受访者'}
            </span>
          </div>
        </div>

        {/* 思维导图分支 */}
        <div className="mindmap-branches">
          {domainOrder.map(domain => {
            const themes = themesByDomain[domain] || []
            if (themes.length === 0) return null

            const config = DOMAIN_CONFIG[domain]

            return (
              <div
                key={domain}
                className="domain-branch"
                style={{ '--branch-color': config.color } as React.CSSProperties}
              >
                {/* 领域节点 */}
                <div
                  className="domain-node"
                  style={{
                    backgroundColor: config.bgColor,
                    borderColor: config.color,
                  }}
                >
                  <span className="domain-icon">{config.icon}</span>
                  <span className="domain-name" style={{ color: '#111827' }}>{DOMAIN_NAMES[domain]}</span>
                  <span className="domain-count">{themes.length}</span>
                </div>

                {/* 主题分支 */}
                <div className="theme-branches">
                  {themes.map(([themeId, theme]) => {
                    const events = getThemeEvents(themeId)
                    const statusInfo = STATUS_LABELS[theme.status]

                    return (
                      <div key={themeId} className="theme-branch">
                        {/* 主题节点 */}
                        <div
                          className={`theme-node ${selectedNodeId === themeId ? 'selected' : ''}`}
                          style={{ borderLeftColor: statusInfo.color }}
                          onClick={() => onNodeClick?.(theme, 'theme')}
                        >
                          <div className="theme-header">
                            <span className="theme-title">{theme.title}</span>
                            <span
                              className="theme-status"
                              style={{
                                backgroundColor: `${statusInfo.color}20`,
                                color: statusInfo.color,
                              }}
                            >
                              {statusInfo.text}
                            </span>
                          </div>
                          <div className="theme-meta">
                            <span className="meta-item">
                              📋 {(theme.extracted_events || []).length} 事件
                            </span>
                            <span className="meta-item">
                              ✓ {Object.values(theme.slots_filled || {}).filter(Boolean).length} 槽位
                            </span>
                          </div>
                        </div>

                        {/* 事件叶子节点 */}
                        {events.length > 0 && (
                          <div className="event-leaves">
                            {events.map(event => (
                              <div
                                key={event.event_id}
                                className={`event-leaf ${selectedNodeId === event.event_id ? 'selected' : ''}`}
                                onClick={(e) => {
                                  e.stopPropagation()
                                  onNodeClick?.(event, 'event')
                                }}
                              >
                                <span className="event-dot" />
                                <span className="event-text">{event.title}</span>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    )
                  })}
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

export default ThemeView
