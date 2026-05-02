/**
 * CoverageDashboard - 叙事丰富度仪表盘组件
 *
 * 展示访谈进度和主题叙事丰富度
 */

import React, { useMemo } from 'react'
import { GraphState, ThemeNode, NodeStatus } from '../types'
import './CoverageDashboard.css'

interface CoverageDashboardProps {
  graphState: GraphState | null
  className?: string
}

const CoverageDashboard: React.FC<CoverageDashboardProps> = ({
  graphState,
  className = '',
}) => {
  // 计算派生数据
  const { overallPercentage, statusStats, topThemes, themeCount, fragmentCount } = useMemo(() => {
    if (!graphState) {
      return {
        overallPercentage: 0,
        statusStats: [],
        topThemes: [] as ThemeNode[],
        themeCount: 0,
        fragmentCount: 0,
      }
    }

    const { coverage_metrics, theme_nodes, narrative_fragments } = graphState

    // 总体叙事丰富度百分比
    const overallPercentage = Math.round(coverage_metrics.overall_richness * 100)

    // 按状态统计主题数量
    const pendingCount = theme_nodes.filter(t => t.status === NodeStatus.PENDING).length
    const mentionedCount = theme_nodes.filter(t => t.status === NodeStatus.MENTIONED).length
    const exhaustedCount = theme_nodes.filter(t => t.status === NodeStatus.EXHAUSTED).length

    const statusStats = [
      { label: '待触达', count: pendingCount, color: '#9CA3AF', status: NodeStatus.PENDING },
      { label: '已提及', count: mentionedCount, color: '#F59E0B', status: NodeStatus.MENTIONED },
      { label: '已挖透', count: exhaustedCount, color: '#10B981', status: NodeStatus.EXHAUSTED },
    ]

    // 按叙事丰富度排序，取前5
    const topThemes = [...theme_nodes]
      .sort((a, b) => b.narrative_richness - a.narrative_richness)
      .slice(0, 5)

    // 叙事片段总数
    const fragmentCount = Object.keys(narrative_fragments).length

    return {
      overallPercentage,
      statusStats,
      topThemes,
      themeCount: theme_nodes.length,
      fragmentCount,
    }
  }, [graphState])

  if (!graphState) {
    return null
  }

  return (
    <div className={`coverage-dashboard ${className}`}>
      {/* 总体叙事丰富度 */}
      <div className="coverage-section overall-coverage">
        <h3 className="section-title">叙事丰富度</h3>
        <div className="progress-ring-container">
          <svg className="progress-ring" width="120" height="120">
            <circle
              className="progress-ring-bg"
              cx="60"
              cy="60"
              r="52"
              strokeWidth="8"
            />
            <circle
              className="progress-ring-fill"
              cx="60"
              cy="60"
              r="52"
              strokeWidth="8"
              strokeDasharray={`${overallPercentage * 3.27} 327`}
              style={{
                stroke: overallPercentage >= 80 ? '#10B981' :
                        overallPercentage >= 50 ? '#F59E0B' : '#EF4444'
              }}
            />
          </svg>
          <div className="progress-text">
            <span className="percentage">{overallPercentage}</span>
            <span className="unit">%</span>
          </div>
        </div>
      </div>

      {/* 主题状态统计 */}
      <div className="coverage-section theme-stats">
        <h3 className="section-title">主题状态统计</h3>
        <div className="status-bars">
          {statusStats.map((stat) => (
            <div key={stat.status} className="status-bar-item">
              <div className="status-label">
                <span className="status-dot" style={{ backgroundColor: stat.color }} />
                <span>{stat.label}</span>
              </div>
              <div className="bar-container">
                <div
                  className="bar-fill"
                  style={{
                    width: themeCount > 0 ? `${(stat.count / themeCount) * 100}%` : '0%',
                    backgroundColor: stat.color,
                  }}
                />
              </div>
              <span className="count">{stat.count}</span>
            </div>
          ))}
        </div>
        <div className="total-events">
          <span className="label">叙事片段</span>
          <span className="value">{fragmentCount}</span>
        </div>
      </div>

      {/* 叙事丰富度 Top 5 */}
      <div className="coverage-section dimension-coverage">
        <h3 className="section-title">丰富度 Top 5</h3>
        <div className="dimension-bars">
          {topThemes.map((theme) => {
            const richnessPercent = Math.round(theme.narrative_richness * 100)
            return (
              <div key={theme.theme_id} className="dimension-item">
                <div className="dimension-header">
                  <span className="dimension-label">{theme.title}</span>
                  <span className="dimension-value">{richnessPercent}%</span>
                </div>
                <div className="dimension-bar-container">
                  <div
                    className="dimension-bar-fill"
                    style={{
                      width: `${richnessPercent}%`,
                      backgroundColor: theme.narrative_richness >= 0.8 ? '#10B981' :
                                       theme.narrative_richness >= 0.5 ? '#F59E0B' : '#EF4444',
                    }}
                  />
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

export default CoverageDashboard
