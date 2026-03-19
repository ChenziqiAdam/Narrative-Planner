/**
 * App - 主应用组件
 *
 * 叙事导航者 - 动态事件图谱可视化界面
 * 适配对比调试系统，支持从URL参数接收sessionId并通过WebSocket接收实时更新
 */

import React, { useState, useEffect, useCallback } from 'react'
import PersonView from './components/PersonView'
import ThemeView from './components/ThemeView'
import TimelineCanvas from './components/TimelineCanvas'
import CoverageDashboard from './components/CoverageDashboard'
import NodeDetailPanel from './components/NodeDetailPanel'
import { useGraphWebSocket } from './hooks/useGraphWebSocket'
import { GraphState, ThemeNode, EventNode, PeopleNode, NodeStatus } from './types'
import { getMockGraphState } from './data/mockData'
import './styles/App.css'

type ViewMode = 'person' | 'theme' | 'timeline'

const App: React.FC = () => {
  const initialSessionId = new URLSearchParams(window.location.search).get('session')
  const [sessionId] = useState<string | null>(initialSessionId)

  // 使用WebSocket hook接收实时图谱更新
  const { connectionStatus, graphState: wsGraphState, isConnected } = useGraphWebSocket({
    sessionId,
    onGraphInit: (data) => {
      console.log('Graph initialized:', data)
    },
    onGraphUpdate: (data) => {
      console.log('Graph updated:', data)
    },
    onNewEvent: (event) => {
      console.log('New event:', event)
    },
    onConnected: () => {
      console.log('WebSocket connected')
    },
    onDisconnected: () => {
      console.log('WebSocket disconnected')
    },
  })

  // 本地状态
  const [graphState, setGraphState] = useState<GraphState | null>(null)
  const [loading, setLoading] = useState(true)
  const [selectedNode, setSelectedNode] = useState<{
    node: ThemeNode | EventNode | PeopleNode
    type: 'theme' | 'event' | 'person'
  } | null>(null)
  const [viewMode, setViewMode] = useState<ViewMode>(initialSessionId ? 'theme' : 'person')
  const [filterStatus, setFilterStatus] = useState<NodeStatus | 'all'>('all')
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)

  // 加载初始数据（如果有sessionId则等待WebSocket数据，否则使用mock数据）
  useEffect(() => {
    if (sessionId) {
      // 有sessionId时，等待WebSocket数据
      if (wsGraphState) {
        setGraphState(wsGraphState)
        setLoading(false)
      }
    } else {
      // 无sessionId时，使用mock数据
      const loadData = async () => {
        try {
          const data = await getMockGraphState()
          setGraphState(data)
        } catch (error) {
          console.error('Failed to load graph data:', error)
        } finally {
          setLoading(false)
        }
      }
      loadData()
    }
  }, [sessionId, wsGraphState])

  // 节点点击处理
  const handleNodeClick = useCallback(
    (node: ThemeNode | EventNode | PeopleNode, type: 'theme' | 'event' | 'person') => {
      setSelectedNode({ node, type })
    },
    []
  )

  // 加载中状态
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

  // 无数据状态
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

  // 获取选中节点ID
  const getSelectedNodeId = () => {
    if (!selectedNode) return undefined
    if (selectedNode.type === 'theme') {
      return (selectedNode.node as ThemeNode).theme_id
    }
    if (selectedNode.type === 'person') {
      return (selectedNode.node as PeopleNode).people_id
    }
    return (selectedNode.node as EventNode).event_id
  }

  return (
    <div className="app-container">
      {/* 顶部导航栏 */}
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
              className={`tab-btn ${viewMode === 'person' ? 'active' : ''}`}
              onClick={() => setViewMode('person')}
            >
              <span className="tab-icon">👤</span>
              人物视图
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
          <div className="filter-group">
            <label>状态：</label>
            <select
              value={filterStatus}
              onChange={(e) =>
                setFilterStatus(e.target.value as NodeStatus | 'all')
              }
            >
              <option value="all">全部</option>
              <option value={NodeStatus.PENDING}>待触达</option>
              <option value={NodeStatus.MENTIONED}>已提及</option>
              <option value={NodeStatus.EXHAUSTED}>已挖透</option>
            </select>
          </div>
          <div className="session-info">
            <span className="session-label">叙事进度</span>
            <span className="session-turns">
              {graphState.event_count} 个事件
            </span>
          </div>
        </div>
      </header>

      {/* 主内容区 */}
      <main className="app-main">
        {/* 视图画布 */}
        <section className="graph-section">
          {viewMode === 'person' ? (
            <PersonView
              graphState={graphState}
              onNodeClick={handleNodeClick}
              selectedNodeId={getSelectedNodeId()}
              filterStatus={filterStatus}
            />
          ) : viewMode === 'theme' ? (
            <ThemeView
              graphState={graphState}
              onNodeClick={handleNodeClick}
              selectedNodeId={getSelectedNodeId()}
              filterStatus={filterStatus}
            />
          ) : (
            <TimelineCanvas
              graphState={graphState}
              onNodeClick={handleNodeClick}
              selectedNodeId={getSelectedNodeId()}
              filterStatus={filterStatus}
            />
          )}
        </section>

        {/* 右侧边栏 */}
        <aside className={`sidebar ${sidebarCollapsed ? 'collapsed' : ''}`}>
          <button
            className="sidebar-toggle"
            onClick={() => setSidebarCollapsed(!sidebarCollapsed)}
          >
            {sidebarCollapsed ? '◀' : '▶'}
          </button>
          {!sidebarCollapsed && (
            <>
              {/* 覆盖率仪表盘 */}
              <div className="sidebar-section">
                <CoverageDashboard graphState={graphState} />
              </div>

              {/* 节点详情面板 */}
              <div className="sidebar-section detail-section">
                <NodeDetailPanel
                  node={selectedNode?.node || null}
                  type={selectedNode?.type || null}
                  graphState={graphState}
                />
              </div>
            </>
          )}
        </aside>
      </main>

      {/* 底部状态栏 */}
      <footer className="app-footer">
        <div className="footer-left">
          <span className="update-time">
            更新：{new Date(graphState.timestamp).toLocaleString('zh-CN')}
          </span>
        </div>
        <div className="footer-center">
          <div className="quick-stats">
            <div className="stat-item">
              <span className="stat-value">{graphState.theme_count}</span>
              <span className="stat-label">主题</span>
            </div>
            <div className="stat-divider" />
            <div className="stat-item">
              <span className="stat-value">{graphState.event_count}</span>
              <span className="stat-label">事件</span>
            </div>
            <div className="stat-divider" />
            <div className="stat-item pending">
              <span className="stat-value">{graphState.pending_themes}</span>
              <span className="stat-label">待触达</span>
            </div>
            <div className="stat-item mentioned">
              <span className="stat-value">{graphState.mentioned_themes}</span>
              <span className="stat-label">已提及</span>
            </div>
            <div className="stat-item exhausted">
              <span className="stat-value">{graphState.exhausted_themes}</span>
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
