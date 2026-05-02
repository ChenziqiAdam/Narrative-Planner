/**
 * GraphCanvas - 图谱画布组件
 *
 * 使用 Cytoscape.js 渲染叙事图谱
 * 主题节点为较大圆形，叙事片段为较小节点并连接到所属主题
 */

import React, { useEffect, useRef, useCallback, useState, useMemo } from 'react'
import cytoscape, { Core } from 'cytoscape'
import {
  GraphState,
  NarrativeFragmentNode,
  ThemeNode,
  NodeStatus,
  StatusColors,
  CyElements,
  CyNodeData,
  CyEdgeData,
} from '../types'
import './GraphCanvas.css'

// ==================== 常量 ====================

/** 截断标签的最大字符数 */
const MAX_LABEL_LENGTH = 12

/** 主题节点基础大小 */
const THEME_NODE_SIZE = 60
/** 片段节点基础大小 */
const FRAGMENT_NODE_SIZE = 30

// ==================== 辅助函数 ====================

/** 截断文本，超出部分用省略号代替 */
function truncate(text: string, maxLen: number): string {
  if (text.length <= maxLen) return text
  return text.slice(0, maxLen) + '...'
}

/** 根据 narrative_richness (0-1) 计算节点大小 */
function richnessToSize(baseSize: number, richness: number): number {
  return baseSize * (0.7 + 0.6 * richness)
}

/** 获取主题节点在 Cytoscape 中的 CSS 类 */
function themeClasses(theme: ThemeNode): string {
  return `theme-node status-${theme.status}`
}

/** 获取片段节点在 Cytoscape 中的 CSS 类 */
function fragmentClasses(_fragment: NarrativeFragmentNode): string {
  return 'fragment-node'
}

// ==================== Cytoscape 样式 ====================

function getCytoscapeStyles(): cytoscape.StylesheetJson {
  return [
    // --- 主题节点 ---
    {
      selector: 'node[type="theme"]',
      style: {
        'label': 'data(label)',
        'text-valign': 'center',
        'text-halign': 'center',
        'font-size': '11px',
        'font-weight': 600,
        'color': '#1F2937',
        'text-outline-width': 2,
        'text-outline-color': '#fff',
        'shape': 'ellipse',
        'width': 'data(nodeWidth)',
        'height': 'data(nodeHeight)',
        'border-width': 3,
        'border-color': 'data(borderColor)',
        'background-color': 'data(bgColor)',
        'text-wrap': 'wrap',
        'text-max-width': '80px',
      },
    },
    // 主题节点 - pending 状态
    {
      selector: 'node[type="theme"].status-pending',
      style: {
        'border-style': 'dashed',
      },
    },
    // --- 片段节点 ---
    {
      selector: 'node[type="fragment"]',
      style: {
        'label': 'data(label)',
        'text-valign': 'center',
        'text-halign': 'center',
        'font-size': '9px',
        'font-weight': 400,
        'color': '#4B5563',
        'text-outline-width': 1,
        'text-outline-color': '#fff',
        'shape': 'round-rectangle',
        'width': 'data(nodeWidth)',
        'height': 'data(nodeHeight)',
        'border-width': 1,
        'border-color': '#D1D5DB',
        'background-color': '#F9FAFB',
        'text-wrap': 'ellipsis',
        'text-max-width': '60px',
      },
    },
    // --- 边 ---
    {
      selector: 'edge',
      style: {
        'width': 1.5,
        'line-color': '#D1D5DB',
        'target-arrow-color': '#D1D5DB',
        'target-arrow-shape': 'none',
        'curve-style': 'bezier',
        'opacity': 0.6,
      },
    },
    // 主题-片段包含边
    {
      selector: 'edge[type="contains"]',
      style: {
        'line-style': 'dashed',
        'line-color': '#9CA3AF',
        'width': 1,
      },
    },
    // --- 交互状态 ---
    {
      selector: 'node.highlighted',
      style: {
        'border-width': 4,
        'border-color': '#3B82F6',
        'opacity': 1,
      },
    },
    {
      selector: 'node.dimmed',
      style: {
        'opacity': 0.25,
      },
    },
    {
      selector: 'node:active',
      style: {
        'overlay-opacity': 0.1,
      },
    },
  ]
}

// ==================== 元素构建 ====================

/**
 * 从 GraphState 构建 Cytoscape 元素数组
 */
function buildElements(graphState: GraphState): CyElements {
  const nodes: Array<{ data: CyNodeData; classes: string }> = []
  const edges: Array<{ data: CyEdgeData; classes: string }> = []

  // 1. 主题节点
  for (const theme of graphState.theme_nodes) {
    const size = richnessToSize(THEME_NODE_SIZE, theme.narrative_richness)
    const bgColor = StatusColors[theme.status] || '#E5E7EB'
    const borderColor = StatusColors[theme.status] || '#9CA3AF'

    nodes.push({
      data: {
        id: theme.theme_id,
        label: truncate(theme.title, MAX_LABEL_LENGTH),
        type: 'theme',
        status: theme.status,
        narrative_richness: theme.narrative_richness,
        bgColor,
        borderColor,
        nodeWidth: size,
        nodeHeight: size,
      } as CyNodeData & Record<string, unknown>,
      classes: themeClasses(theme),
    })
  }

  // 2. 叙事片段节点 + 到主题的边
  const fragments = graphState.narrative_fragments
  for (const [fragmentId, fragment] of Object.entries(fragments)) {
    const size = richnessToSize(FRAGMENT_NODE_SIZE, fragment.narrative_richness)

    nodes.push({
      data: {
        id: fragmentId,
        label: truncate(fragment.rich_text, MAX_LABEL_LENGTH),
        type: 'fragment',
        narrative_richness: fragment.narrative_richness,
        nodeWidth: size * 1.8,
        nodeHeight: size,
      } as CyNodeData & Record<string, unknown>,
      classes: fragmentClasses(fragment),
    })

    // 片段 -> 主题 的包含边
    if (fragment.theme_id) {
      edges.push({
        data: {
          id: `edge-${fragmentId}-${fragment.theme_id}`,
          source: fragmentId,
          target: fragment.theme_id,
          type: 'contains',
        },
        classes: 'contains-edge',
      })
    }
  }

  return { nodes, edges }
}

// ==================== 布局配置 ====================

function getLayoutConfig(): cytoscape.LayoutOptions {
  return {
    name: 'cose',
    padding: 40,
    nodeRepulsion: () => 8000,
    idealEdgeLength: () => 80,
    gravity: 0.3,
    animate: true,
    animationDuration: 400,
    randomize: false,
    componentSpacing: 100,
  } as cytoscape.LayoutOptions
}

// ==================== 组件 ====================

interface GraphCanvasProps {
  graphState: GraphState | null
  onNodeSelect: (node: { type: string; id: string }) => void
  className?: string
}

const GraphCanvas: React.FC<GraphCanvasProps> = ({
  graphState,
  onNodeSelect,
  className = '',
}) => {
  const containerRef = useRef<HTMLDivElement>(null)
  const cyRef = useRef<Core | null>(null)
  const [zoomLevel, setZoomLevel] = useState(1)

  // 稳定的回调引用
  const onNodeSelectRef = useRef(onNodeSelect)
  useEffect(() => {
    onNodeSelectRef.current = onNodeSelect
  }, [onNodeSelect])

  // 初始化 Cytoscape 实例（仅一次）
  useEffect(() => {
    if (!containerRef.current) return

    const styles = getCytoscapeStyles()

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

    // 监听缩放
    cy.on('zoom', () => {
      setZoomLevel(cy.zoom())
    })

    // 节点点击 -> 通知父组件
    cy.on('tap', 'node', (evt) => {
      const node = evt.target
      const data = node.data() as CyNodeData
      if (data.type && data.id) {
        onNodeSelectRef.current({ type: data.type, id: data.id })
      }
    })

    // 边悬停光标
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

  // 当 graphState 变化时重建元素
  useEffect(() => {
    const cy = cyRef.current
    if (!cy || !graphState) return

    const elements = buildElements(graphState)

    cy.elements().remove()
    cy.add([
      ...elements.nodes as cytoscape.ElementDefinition[],
      ...elements.edges as cytoscape.ElementDefinition[],
    ])

    // 运行布局
    const layoutConfig = getLayoutConfig()
    cy.layout(layoutConfig).run()

    // 适配视图
    setTimeout(() => {
      cy.fit(undefined, 80)
      setZoomLevel(cy.zoom())
    }, 100)
  }, [graphState])

  // 导出图片
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

  // 状态图例数据
  const statusLegend = useMemo(() => [
    { status: NodeStatus.PENDING, label: '待触达', cssClass: 'pending' },
    { status: NodeStatus.MENTIONED, label: '已提及', cssClass: 'mentioned' },
    { status: NodeStatus.EXHAUSTED, label: '已挖透', cssClass: 'exhausted' },
  ], [])

  return (
    <div className={`graph-canvas-container ${className}`}>
      {/* 状态图例 */}
      <div className="graph-legend">
        <div className="legend-section">
          {statusLegend.map(({ status, label, cssClass }) => (
            <div key={status} className="legend-item">
              <span
                className={`legend-dot ${cssClass}`}
                style={{ borderColor: StatusColors[status] }}
              />
              <span>{label}</span>
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
