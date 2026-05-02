/**
 * TimelineCanvas - 叙事片段时间轴视图
 *
 * 按创建顺序排列叙事片段节点
 * 显示：rich_text（截断）、theme_id、confidence 指标
 * properties 中的 time_anchor、location、people_names 显示为标签
 */

import React from 'react'
import {
  GraphState,
} from '../types'
import './TimelineCanvas.css'

interface TimelineCanvasProps {
  graphState: GraphState | null
  onNodeSelect: (node: { type: string; id: string }) => void
  selectedNodeId?: string | null
  className?: string
}

/** 置信度颜色：高(绿) 中(黄) 低(红) */
function getConfidenceColor(confidence: number): string {
  if (confidence >= 0.7) return '#10B981'
  if (confidence >= 0.4) return '#F59E0B'
  return '#EF4444'
}

/** 截断文本 */
function truncate(text: string, maxLen: number): string {
  if (text.length <= maxLen) return text
  return text.slice(0, maxLen) + '...'
}

/** 从 properties 中提取标签 */
function extractPropertyTags(properties: Record<string, any>): Array<{ key: string; label: string; value: string }> {
  const tags: Array<{ key: string; label: string; value: string }> = []
  if (properties.time_anchor) {
    tags.push({ key: 'time_anchor', label: '时间', value: String(properties.time_anchor) })
  }
  if (properties.location) {
    tags.push({ key: 'location', label: '地点', value: String(properties.location) })
  }
  if (properties.people_names) {
    const names = Array.isArray(properties.people_names)
      ? properties.people_names.join(', ')
      : String(properties.people_names)
    tags.push({ key: 'people_names', label: '人物', value: names })
  }
  return tags
}

const TimelineCanvas: React.FC<TimelineCanvasProps> = ({
  graphState,
  onNodeSelect,
  selectedNodeId,
  className = '',
}) => {
  if (!graphState) {
    return (
      <div className={`timeline-canvas-container ${className}`}>
        <div className="timeline-content">
          <div className="timeline-empty">
            <span className="empty-icon">📋</span>
            <p>暂无图谱数据</p>
          </div>
        </div>
      </div>
    )
  }

  // 按创建顺序（Record 插入顺序）排列片段
  const sortedFragments = Object.entries(graphState.narrative_fragments)

  return (
    <div className={`timeline-canvas-container ${className}`}>
      <div className="timeline-content">
        {sortedFragments.length === 0 ? (
          <div className="timeline-empty">
            <span className="empty-icon">📋</span>
            <p>暂无叙事片段数据</p>
          </div>
        ) : (
          <div className="timeline-events">
            <div className="timeline-line" />
            {sortedFragments.map(([id, fragment]) => {
              const confidenceColor = getConfidenceColor(fragment.confidence)
              const propertyTags = extractPropertyTags(fragment.properties || {})

              return (
                <div key={id} className="timeline-event-wrapper">
                  {/* 时间轴圆点 */}
                  <div
                    className="timeline-dot"
                    style={{ backgroundColor: confidenceColor }}
                  />

                  {/* 片段卡片 */}
                  <div
                    className={`timeline-node event-node ${selectedNodeId === id ? 'selected' : ''}`}
                    style={{ borderColor: confidenceColor }}
                    onClick={() => onNodeSelect({ type: 'fragment', id: fragment.fragment_id })}
                  >
                    {/* 头部：主题标签 + 置信度 */}
                    <div className="event-header">
                      {fragment.theme_id && (
                        <div className="event-theme-tag">
                          {fragment.theme_id}
                        </div>
                      )}
                      <div style={{ flex: 1 }} />
                      <span
                        className="metric-value"
                        style={{ color: confidenceColor, fontSize: '12px' }}
                      >
                        {(fragment.confidence * 100).toFixed(0)}%
                      </span>
                    </div>

                    {/* 叙事文本（截断） */}
                    <div className="fragment-rich-text">
                      {truncate(fragment.rich_text, 160)}
                    </div>

                    {/* 置信度条 */}
                    <div className="event-metrics">
                      <div className="metric-item">
                        <span className="metric-label">置信度</span>
                        <div className="metric-bar-wrapper">
                          <div className="metric-bar">
                            <div
                              className="metric-fill"
                              style={{
                                width: `${fragment.confidence * 100}%`,
                                backgroundColor: confidenceColor,
                              }}
                            />
                          </div>
                        </div>
                      </div>
                    </div>

                    {/* 属性标签 */}
                    {propertyTags.length > 0 && (
                      <div className="event-tags">
                        {propertyTags.map((tag) => (
                          <span key={tag.key} className="tag-item">
                            {tag.label}: {truncate(tag.value, 30)}
                          </span>
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
