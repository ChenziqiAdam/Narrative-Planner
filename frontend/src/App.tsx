/**
 * App - 主应用组件 (GraphRAG)
 *
 * 叙事导航者 - 动态事件图谱可视化界面
 */

import React, { useState, useEffect, useCallback } from 'react'
import ThemeView from './components/ThemeView'
import TimelineCanvas from './components/TimelineCanvas'
import CoverageDashboard from './components/CoverageDashboard'
import NodeDetailPanel from './components/NodeDetailPanel'
import GraphCanvas from './components/GraphCanvas'
import { useGraphWebSocket } from './hooks/useGraphWebSocket'
import { GraphState, NodeStatus } from './types'
import './styles/App.css'

type ViewMode = 'graph' | 'theme' | 'timeline'

const App: React.FC = () => {
  const initialSessionId = new URLSearchParams(window.location.search).get('session')
  const [sessionId] = useState<string | null>(initialSessionId)

  const { connectionStatus, graphState: wsGraphState, isConnected } = useGraphWebSocket({
    sessionId,
    onGraphInit: (data) => console.log('Graph initialized:', data),
    onGraphUpdate: (data) => console.log('Graph updated:', data),
    onConnected: () => console.log('WebSocket connected'),
    onDisconnected: () => console.log('WebSocket disconnected'),
  })

  const [graphState, setGraphState] = useState<GraphState | null>(null)
  const [loading, setLoading] = useState(true)
  const [selectedNode, setSelectedNode] = useState<{
    type: 'theme' | 'fragment'
    id: string
  } | null>(null)
  const [viewMode, setViewMode] = useState<ViewMode>('theme')
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)

  useEffect(() => {
    if (sessionId) {
      if (wsGraphState) {
        setGraphState(wsGraphState)
        setLoading(false)
      }
    } else {
      setLoading(false)
    }
  }, [sessionId, wsGraphState])

  const handleNodeSelect = useCallback(
    (nodeInfo: { type: string; id: string }) => {
      if (nodeInfo.type === 'theme' || nodeInfo.type === 'fragment') {
        setSelectedNode({ type: nodeInfo.type, id: nodeInfo.id })
      }
    },
    []
  )

  if (loading) {
    return (
      <div className="app-loading">
        <div className="loading-content">
          <div className="loading-spinner" />
          <p>加载叙事图谱...</p>
        </div>
      </div>
    )
  }

  if (!graphState) {
    return (
      <div className="app-error">
        <div className="error-content">
          <span className="error-icon">⚠️</span>
          <p>无法加载图谱数据</p>
          <button onClick={() => window.location.reload()}>重新加载</button>
        </div>
      </div>
    )
  }

  const themeCount = graphState.theme_nodes?.length ?? 0
  const fragmentCount = Object.keys(graphState.narrative_fragments ?? {}).length
  const statusCounts = (graphState.theme_nodes ?? []).reduce(
    (acc, t) => {
      acc[t.status] = (acc[t.status] || 0) + 1
      return acc
    },
    {} as Record<string, number>
  )

  return (
    <div className="app-container">
      <header className="app-header">
        <div className="header-left">
          <h1 className="app-title">
            <span className="title-icon">◈</span>
            叙事导航者
          </h1>
          {graphState.elder_info && (
            <span className="elder-name">
              {graphState.elder_info.name}
              {graphState.elder_info.age ? ` · ${graphState.elder_info.age}岁` : ''}
            </span>
          )}
        </div>
        <div className="header-center">
          <div className="view-mode-tabs">
            <button
              className={`tab-btn ${viewMode === 'graph' ? 'active' : ''}`}
              onClick={() => setViewMode('graph')}
            >
              <span className="tab-icon">🔗</span>
              图谱视图
            </button>
            <button
              className={`tab-btn ${viewMode === 'theme' ? 'active' : ''}`}
              onClick={() => setViewMode('theme')}
            >
              <span className="tab-icon">🌳</span>
              主题视图
            </button>
            <button
              className={`tab-btn ${viewMode === 'timeline' ? 'active' : ''}`}
              onClick={() => setViewMode('timeline')}
            >
              <span className="tab-icon">⏱</span>
              时间轴
            </button>
          </div>
        </div>
        <div className="header-right">
          {sessionId && (
            <div className="connection-status" title={connectionStatus}>
              <span className={`status-dot ${isConnected ? 'connected' : 'disconnected'}`} />
              <span className="session-id">会话: {sessionId.slice(0, 8)}...</span>
            </div>
          )}
          <div className="session-info">
            <span className="session-label">叙事进度</span>
            <span className="session-turns">
              {fragmentCount} 个叙事片段
            </span>
          </div>
        </div>
      </header>

      <main className="app-main">
        <section className="graph-section">
          {viewMode === 'graph' ? (
            <GraphCanvas
              graphState={graphState}
              onNodeSelect={handleNodeSelect}
            />
          ) : viewMode === 'theme' ? (
            <ThemeView
              graphState={graphState}
              onNodeSelect={handleNodeSelect}
            />
          ) : (
            <TimelineCanvas
              graphState={graphState}
              onNodeSelect={handleNodeSelect}
            />
          )}
        </section>

        <aside className={`sidebar ${sidebarCollapsed ? 'collapsed' : ''}`}>
          <button
            className="sidebar-toggle"
            onClick={() => setSidebarCollapsed(!sidebarCollapsed)}
          >
            {sidebarCollapsed ? '◀' : '▶'}
          </button>
          {!sidebarCollapsed && (
            <>
              <div className="sidebar-section">
                <CoverageDashboard graphState={graphState} />
              </div>
              <div className="sidebar-section detail-section">
                <NodeDetailPanel
                  selectedNode={selectedNode}
                  graphState={graphState}
                  onClose={() => setSelectedNode(null)}
                />
              </div>
            </>
          )}
        </aside>
      </main>

      <footer className="app-footer">
        <div className="footer-left">
          <span className="update-time">
            更新：{new Date(graphState.timestamp).toLocaleString('zh-CN')}
          </span>
        </div>
        <div className="footer-center">
          <div className="quick-stats">
            <div className="stat-item">
              <span className="stat-value">{themeCount}</span>
              <span className="stat-label">主题</span>
            </div>
            <div className="stat-divider" />
            <div className="stat-item">
              <span className="stat-value">{fragmentCount}</span>
              <span className="stat-label">叙事片段</span>
            </div>
            <div className="stat-divider" />
            <div className="stat-item pending">
              <span className="stat-value">{statusCounts[NodeStatus.PENDING] ?? 0}</span>
              <span className="stat-label">待触达</span>
            </div>
            <div className="stat-item mentioned">
              <span className="stat-value">{statusCounts[NodeStatus.MENTIONED] ?? 0}</span>
              <span className="stat-label">已提及</span>
            </div>
            <div className="stat-item exhausted">
              <span className="stat-value">{statusCounts[NodeStatus.EXHAUSTED] ?? 0}</span>
              <span className="stat-label">已挖透</span>
            </div>
          </div>
        </div>
        <div className="footer-right">
          {graphState.elder_info && (
            <span className="elder-info-footer">
              {graphState.elder_info.hometown || ''}
            </span>
          )}
        </div>
      </footer>
    </div>
  )
}

export default App
