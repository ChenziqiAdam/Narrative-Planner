/**
 * GraphCanvas - 图谱画布组件
 *
 * 使用 Cytoscape.js 渲染动态事件图谱
 * 支持按主题分区布局和状态筛选
 */

import React, { useEffect, useRef, useCallback, useState } from 'react'
import cytoscape, { Core, NodeSingular } from 'cytoscape'
import {
  GraphState,
  CyNodeData,
  ThemeNode,
  EventNode,
  NodeStatus,
  Domain,
} from '../types'
import {
  transformToCytoscape,
  getCytoscapeStyles,
  getDomainGroupedLayout,
} from '../utils/graphTransformer'
import './GraphCanvas.css'

interface GraphCanvasProps {
  graphState: GraphState
  onNodeClick?: (node: ThemeNode | EventNode, type: 'theme' | 'event') => void
  selectedNodeId?: string | null
  filterStatus?: NodeStatus | 'all'
  className?: string
}

const GraphCanvas: React.FC<GraphCanvasProps> = ({
  graphState,
  onNodeClick,
  selectedNodeId,
  filterStatus = 'all',
  className = '',
}) => {
  const containerRef = useRef<HTMLDivElement>(null)
  const cyRef = useRef<Core | null>(null)
  const [zoomLevel, setZoomLevel] = useState(1)
  const [highlightDomain, setHighlightDomain] = useState<Domain | null>(null)

  // 稳定的回调引用
  const onNodeClickRef = useRef(onNodeClick)

  useEffect(() => {
    onNodeClickRef.current = onNodeClick
  }, [onNodeClick])

  // 初始化 Cytoscape
  useEffect(() => {
    if (!containerRef.current) return

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const styles = getCytoscapeStyles() as any

    const cy = cytoscape({
      container: containerRef.current,
      elements: [],
      style: styles,
      layout: { name: 'preset' },
      minZoom: 0.2,
      maxZoom: 3,
      wheelSensitivity: 0.3,
    })

    cyRef.current = cy

    // 监听缩放变化
    cy.on('zoom', () => {
      setZoomLevel(cy.zoom())
    })

    // 节点点击事件
    cy.on('tap', 'node', (evt) => {
      const node = evt.target as NodeSingular
      const data = node.data() as CyNodeData
      const nodeType = data.type

      if (onNodeClickRef.current) {
        if (nodeType === 'theme') {
          const themeNode = graphState.theme_nodes[data.id]
          if (themeNode) {
            onNodeClickRef.current(themeNode, 'theme')
          }
        } else {
          const eventNode = graphState.event_nodes[data.id]
          if (eventNode) {
            onNodeClickRef.current(eventNode, 'event')
          }
        }
      }
    })

    // 边悬停提示
    cy.on('mouseover', 'edge', () => {
      containerRef.current?.style.setProperty('cursor', 'pointer')
    })

    cy.on('mouseout', 'edge', () => {
      containerRef.current?.style.setProperty('cursor', 'default')
    })

    return () => {
      cy.destroy()
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // 更新图谱数据和布局
  useEffect(() => {
    const cy = cyRef.current
    if (!cy) return

    const elements = transformToCytoscape(graphState)

    // 筛选节点
    let filteredNodes = elements.nodes
    let filteredEdges = elements.edges

    if (filterStatus !== 'all') {
      filteredNodes = filteredNodes.filter((n) => {
        if (n.data.type === 'theme') {
          const theme = graphState.theme_nodes[n.data.id]
          return theme?.status === filterStatus
        }
        // 事件节点保留，但检查其主题是否被筛选
        const event = graphState.event_nodes[n.data.id]
        if (event) {
          const theme = graphState.theme_nodes[event.theme_id]
          return theme?.status === filterStatus
        }
        return true
      })

      const nodeIds = new Set(filteredNodes.map((n) => n.data.id))
      filteredEdges = filteredEdges.filter((e) =>
        nodeIds.has(e.data.source) && nodeIds.has(e.data.target)
      )
    }

    cy.elements().remove()
    cy.add({
      nodes: filteredNodes,
      edges: filteredEdges,
    })

    // 使用领域分组布局
    const layoutConfig = getDomainGroupedLayout()
    cy.layout(layoutConfig).run()

    // 适配视图
    setTimeout(() => {
      cy.fit(undefined, 80)
      setZoomLevel(cy.zoom())
    }, 100)
  }, [graphState, filterStatus])

  // 处理选中节点
  useEffect(() => {
    const cy = cyRef.current
    if (!cy || !selectedNodeId) return

    // 清除之前的选中状态
    cy.elements().removeClass('highlighted')

    // 高亮选中的节点
    const node = cy.getElementById(selectedNodeId)
    if (node && node.length > 0) {
      node.addClass('highlighted')
      node.select()

      // 将选中节点移动到视图中心
      cy.animate({
        center: { eles: node },
        zoom: 1,
        duration: 500,
      })
    }
  }, [selectedNodeId])

  // 处理领域高亮
  useEffect(() => {
    const cy = cyRef.current
    if (!cy) return

    if (highlightDomain) {
      cy.nodes().forEach((node) => {
        const data = node.data() as CyNodeData
        if (data.domain === highlightDomain) {
          node.removeClass('dimmed')
        } else {
          node.addClass('dimmed')
        }
      })
    } else {
      cy.nodes().removeClass('dimmed')
    }
  }, [highlightDomain])

  // 导出图谱为图片
  const exportImage = useCallback(() => {
    const cy = cyRef.current
    if (!cy) return null

    return cy.png({ full: true, scale: 2 })
  }, [])

  // 重置视图
  const resetView = useCallback(() => {
    const cy = cyRef.current
    if (!cy) return

    cy.fit(undefined, 80)
    setZoomLevel(cy.zoom())
  }, [])

  // 放大
  const zoomIn = useCallback(() => {
    const cy = cyRef.current
    if (!cy) return

    cy.zoom(cy.zoom() * 1.2)
  }, [])

  // 缩小
  const zoomOut = useCallback(() => {
    const cy = cyRef.current
    if (!cy) return

    cy.zoom(cy.zoom() / 1.2)
  }, [])

  return (
    <div className={`graph-canvas-container ${className}`}>
      {/* 领域图例 */}
      <div className="domain-legend">
        <div className="legend-title">主题分区</div>
        <div className="legend-items">
          {Object.entries(Domain).map(([_key, domain]) => (
            <div
              key={domain}
              className={`legend-item ${highlightDomain === domain ? 'active' : ''}`}
              onMouseEnter={() => setHighlightDomain(domain)}
              onMouseLeave={() => setHighlightDomain(null)}
            >
              <span
                className="legend-color"
                style={{
                  backgroundColor: `var(--domain-${domain.replace('_', '-')})`,
                }}
              />
              <span className="legend-label">
                {graphState.theme_nodes &&
                  Object.values(graphState.theme_nodes).filter(
                    (t) => t.domain === domain
                  ).length > 0 &&
                  Object.values(graphState.theme_nodes).filter(
                    (t) => t.domain === domain
                  )[0]?.title}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* 工具栏 */}
      <div className="graph-toolbar">
        <button onClick={resetView} title="重置视图">
          <span className="icon">⟲</span>
        </button>
        <button onClick={exportImage} title="导出图片">
          <span className="icon">📷</span>
        </button>
        <div className="zoom-controls">
          <button onClick={zoomIn} title="放大">
            +
          </button>
          <span className="zoom-level">{Math.round(zoomLevel * 100)}%</span>
          <button onClick={zoomOut} title="缩小">
            -
          </button>
        </div>
      </div>

      {/* 图谱画布 */}
      <div ref={containerRef} className="graph-canvas" />
    </div>
  )
}

export default GraphCanvas
