/**
 * ThemeView - 主题视图组件
 *
 * 以列表方式呈现主题节点
 * 每个主题显示：标题、状态（颜色编码）、叙事丰富度进度条、关联实体数量
 */

import React from 'react'
import {
  GraphState,
  NodeStatus,
  StatusColors,
} from '../types'
import './ThemeView.css'

interface ThemeViewProps {
  graphState: GraphState | null
  onNodeSelect: (node: { type: string; id: string }) => void
  className?: string
}

// 状态标签配置
const STATUS_LABELS: Record<NodeStatus, { text: string; color: string }> = {
  [NodeStatus.PENDING]: { text: '待触达', color: StatusColors[NodeStatus.PENDING] },
  [NodeStatus.MENTIONED]: { text: '已提及', color: StatusColors[NodeStatus.MENTIONED] },
  [NodeStatus.EXHAUSTED]: { text: '已挖透', color: StatusColors[NodeStatus.EXHAUSTED] },
}

/** 叙事丰富度进度条 */
const RichnessBar: React.FC<{ value: number; color: string }> = ({ value, color }) => {
  const pct = Math.round(Math.max(0, Math.min(1, value)) * 100)
  return (
    <div className="richness-bar-track">
      <div
        className="richness-bar-fill"
        style={{ width: `${pct}%`, backgroundColor: color }}
      />
    </div>
  )
}

const ThemeView: React.FC<ThemeViewProps> = ({
  graphState,
  onNodeSelect,
  className = '',
}) => {
  // 空状态
  if (!graphState || !graphState.theme_nodes || graphState.theme_nodes.length === 0) {
    return (
      <div className={`theme-view-container ${className}`}>
        <div className="theme-view-empty">
          <span className="empty-icon">📋</span>
          <span>暂无主题数据</span>
        </div>
      </div>
    )
  }

  const themes = graphState.theme_nodes

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

        {/* 主题列表 */}
        <div className="mindmap-branches">
          {themes.map(theme => {
            const statusInfo = STATUS_LABELS[theme.status]

            return (
              <div key={theme.theme_id} className="theme-branch">
                <div
                  className="theme-node"
                  style={{ borderLeftColor: statusInfo.color }}
                  onClick={() =>
                    onNodeSelect({ type: 'theme', id: theme.theme_id })
                  }
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
                    <span className="meta-item richness-item">
                      <span className="meta-label">丰富度</span>
                      <RichnessBar value={theme.narrative_richness} color={statusInfo.color} />
                      <span className="meta-value">{Math.round(theme.narrative_richness * 100)}%</span>
                    </span>
                    <span className="meta-item">
                      实体 {theme.entity_count}
                    </span>
                    <span className="meta-item">
                      深度 {theme.exploration_depth}
                    </span>
                  </div>
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
