/**
 * CoverageDashboard - 覆盖率仪表盘组件
 *
 * 展示访谈进度和各维度覆盖率
 */

import React from 'react'
import { GraphState, Domain, DomainLabels, NodeStatus } from '../types'
import './CoverageDashboard.css'

interface CoverageDashboardProps {
  graphState: GraphState
  className?: string
}

const CoverageDashboard: React.FC<CoverageDashboardProps> = ({
  graphState,
  className = '',
}) => {
  const { coverage_metrics, theme_count, event_count, pending_themes, mentioned_themes, exhausted_themes } = graphState

  // 计算总体覆盖率百分比
  const overallPercentage = Math.round(coverage_metrics.overall_coverage * 100)

  // 状态统计
  const statusStats = [
    { label: '待触达', count: pending_themes, color: '#9CA3AF', status: NodeStatus.PENDING },
    { label: '已提及', count: mentioned_themes, color: '#F59E0B', status: NodeStatus.MENTIONED },
    { label: '已挖透', count: exhausted_themes, color: '#10B981', status: NodeStatus.EXHAUSTED },
  ]

  // 维度覆盖率
  const dimensionLabels: Record<string, string> = {
    time: '时间维度',
    space: '空间维度',
    people: '人物维度',
    emotion: '情感维度',
    reflection: '反思维度',
  }

  return (
    <div className={`coverage-dashboard ${className}`}>
      {/* 总体覆盖率 */}
      <div className="coverage-section overall-coverage">
        <h3 className="section-title">总体覆盖率</h3>
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

      {/* 主题节点统计 */}
      <div className="coverage-section theme-stats">
        <h3 className="section-title">主题节点统计</h3>
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
                    width: `${(stat.count / theme_count) * 100}%`,
                    backgroundColor: stat.color,
                  }}
                />
              </div>
              <span className="count">{stat.count}</span>
            </div>
          ))}
        </div>
        <div className="total-events">
          <span className="label">已提取事件</span>
          <span className="value">{event_count}</span>
        </div>
      </div>

      {/* 槽位覆盖率 */}
      <div className="coverage-section dimension-coverage">
        <h3 className="section-title">槽位覆盖</h3>
        <div className="dimension-bars">
          {Object.entries(coverage_metrics.slot_coverage || {}).map(([key, value]) => (
            <div key={key} className="dimension-item">
              <div className="dimension-header">
                <span className="dimension-label">{dimensionLabels[key] || key}</span>
                <span className="dimension-value">{Math.round((value as number) * 100)}%</span>
              </div>
              <div className="dimension-bar-container">
                <div
                  className="dimension-bar-fill"
                  style={{
                    width: `${(value as number) * 100}%`,
                    backgroundColor: (value as number) >= 0.8 ? '#10B981' :
                                     (value as number) >= 0.5 ? '#F59E0B' : '#EF4444',
                  }}
                />
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* 领域覆盖 */}
      <div className="coverage-section domain-coverage">
        <h3 className="section-title">领域覆盖</h3>
        <div className="domain-grid">
          {Object.entries(coverage_metrics.domain_coverage || {}).map(([domain, value]) => (
            <div key={domain} className="domain-item">
              <div
                className="domain-indicator"
                style={{
                  backgroundColor: value >= 0.8 ? '#10B981' :
                                   value >= 0.5 ? '#F59E0B' : '#EF4444',
                  opacity: 0.2 + value * 0.8,
                }}
              />
              <span className="domain-name">{DomainLabels[domain as Domain] || domain}</span>
              <span className="domain-value">{Math.round(value * 100)}%</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

export default CoverageDashboard
