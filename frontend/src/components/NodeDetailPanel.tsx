import React from 'react'
import {
  ThemeNode,
  NodeStatus,
  NarrativeFragmentNode,
  GraphState,
} from '../types'
import './NodeDetailPanel.css'

interface NodeDetailPanelProps {
  selectedNode: { type: 'theme' | 'fragment'; id: string } | null
  graphState: GraphState | null
  onClose: () => void
  className?: string
}

/** Human-readable labels for known fragment property keys */
const PROPERTY_LABELS: Record<string, string> = {
  time_anchor: '时间锚点',
  location: '地点',
  people_names: '相关人物',
  emotional_tone: '情感基调',
  event_type: '事件类型',
  duration: '持续时间',
  significance: '重要性',
  trigger: '触发因素',
  outcome: '结果',
}

const statusConfig: Record<NodeStatus, { label: string; color: string }> = {
  [NodeStatus.PENDING]: { label: '待触达', color: '#9CA3AF' },
  [NodeStatus.MENTIONED]: { label: '已提及', color: '#F59E0B' },
  [NodeStatus.EXHAUSTED]: { label: '已挖透', color: '#10B981' },
}

/** Format a properties value for display */
function formatPropertyValue(value: unknown): string {
  if (value === null || value === undefined) return '-'
  if (Array.isArray(value)) return value.join(', ')
  if (typeof value === 'object') return JSON.stringify(value, null, 2)
  return String(value)
}

const NodeDetailPanel: React.FC<NodeDetailPanelProps> = ({
  selectedNode,
  graphState,
  onClose,
  className = '',
}) => {
  // Resolve the actual node data from graphState
  const themeNode: ThemeNode | null =
    selectedNode?.type === 'theme'
      ? graphState?.theme_nodes.find((t) => t.theme_id === selectedNode.id) ?? null
      : null

  const fragmentNode: NarrativeFragmentNode | null =
    selectedNode?.type === 'fragment'
      ? graphState?.narrative_fragments[selectedNode.id] ?? null
      : null

  if (!selectedNode) {
    return (
      <div className={`node-detail-panel empty ${className}`}>
        <div className="empty-state">
          <span className="empty-icon">○</span>
          <p>点击节点查看详情</p>
        </div>
      </div>
    )
  }

  if (!themeNode && !fragmentNode) {
    return (
      <div className={`node-detail-panel empty ${className}`}>
        <div className="empty-state">
          <span className="empty-icon">○</span>
          <p>未找到节点数据</p>
        </div>
        <button className="close-btn" onClick={onClose}>
          ×
        </button>
      </div>
    )
  }

  return (
    <div className={`node-detail-panel ${className}`}>
      <div className="panel-header">
        <div className="header-top">
          <span
            className="node-type-badge"
            style={{
              backgroundColor: selectedNode.type === 'theme' ? '#3B82F6' : '#F59E0B',
            }}
          >
            {selectedNode.type === 'theme' ? '主题' : '叙事片段'}
          </span>
        </div>

        <h2 className="node-title">
          {themeNode?.title ?? fragmentNode?.fragment_id ?? selectedNode.id}
        </h2>

        <button className="close-btn" onClick={onClose}>
          ×
        </button>
      </div>

      <div className="panel-content">
        {/* ===== Theme Detail ===== */}
        {themeNode && (
          <>
            {/* Status */}
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

            {/* Narrative Richness Progress Bar */}
            <div className="info-section">
              <h3 className="section-label">叙事丰富度</h3>
              <div className="progress-info">
                <div className="progress-header">
                  <span>丰富度评分</span>
                  <span className="depth-value">
                    {Math.round(themeNode.narrative_richness * 100)}%
                  </span>
                </div>
                <div className="completion-bar">
                  <div
                    className="completion-fill"
                    style={{ width: `${themeNode.narrative_richness * 100}%` }}
                  />
                </div>
              </div>
            </div>

            {/* Entity Count & Exploration Depth */}
            <div className="info-section">
              <h3 className="section-label">探索指标</h3>
              <div className="metrics-grid">
                <div className="metric-item">
                  <span className="metric-label">关联实体</span>
                  <span className="metric-value">{themeNode.entity_count}</span>
                </div>
                <div className="metric-item">
                  <span className="metric-label">探索深度</span>
                  <div className="depth-pips">
                    {[1, 2, 3, 4, 5].map((level) => (
                      <div
                        key={level}
                        className={`depth-pip ${level <= themeNode.exploration_depth ? 'active' : ''}`}
                      />
                    ))}
                  </div>
                  <span className="metric-value">{themeNode.exploration_depth}/5</span>
                </div>
              </div>
            </div>
          </>
        )}

        {/* ===== Fragment Detail ===== */}
        {fragmentNode && (
          <>
            {/* Rich Text */}
            <div className="info-section">
              <h3 className="section-label">叙事文本</h3>
              <p className="description">{fragmentNode.rich_text}</p>
            </div>

            {/* Confidence & Narrative Richness */}
            <div className="info-section">
              <h3 className="section-label">分析指标</h3>
              <div className="metrics-grid">
                <div className="metric-item">
                  <span className="metric-label">置信度</span>
                  <div className="metric-bar">
                    <div
                      className="metric-fill"
                      style={{ width: `${fragmentNode.confidence * 100}%` }}
                    />
                  </div>
                  <span className="metric-value">
                    {Math.round(fragmentNode.confidence * 100)}%
                  </span>
                </div>
                <div className="metric-item">
                  <span className="metric-label">叙事丰富度</span>
                  <div className="metric-bar">
                    <div
                      className="metric-fill"
                      style={{
                        width: `${fragmentNode.narrative_richness * 100}%`,
                      }}
                    />
                  </div>
                  <span className="metric-value">
                    {Math.round(fragmentNode.narrative_richness * 100)}%
                  </span>
                </div>
              </div>
            </div>

            {/* Properties as Key-Value Pairs */}
            {Object.keys(fragmentNode.properties).length > 0 && (
              <div className="info-section">
                <h3 className="section-label">结构化信息</h3>
                <div className="slots-detail">
                  {Object.entries(fragmentNode.properties).map(([key, value]) => (
                    <div key={key} className="slot-row filled">
                      <span className="slot-key">
                        {PROPERTY_LABELS[key] || key}
                      </span>
                      <span className="slot-value">
                        {formatPropertyValue(value)}
                      </span>
                    </div>
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
