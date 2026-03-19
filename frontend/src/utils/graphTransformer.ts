/**
 * 图谱数据转换器
 *
 * 将后端 GraphManager 状态转换为 Cytoscape 可视化格式
 * 支持按主题分区布局
 */

import cytoscape from 'cytoscape'
import dagre from 'cytoscape-dagre'
import coseBilkent from 'cytoscape-cose-bilkent'

import {
  GraphState,
  NodeStatus,
  Domain,
  DomainColors,
  DomainBorderColors,
  CyElements,
  CyNodeData,
  CyEdgeData,
} from '../types'

// 注册 Cytoscape 布局扩展
cytoscape.use(dagre)
cytoscape.use(coseBilkent)

/**
 * 将后端图谱状态转换为 Cytoscape 元素格式
 * 按主题分区，事件节点连接到所属主题
 */
export function transformToCytoscape(graphState: GraphState): CyElements {
  const nodes: Array<{ data: CyNodeData; classes: string }> = []
  const edges: Array<{ data: CyEdgeData; classes: string }> = []

  // 转换主题节点
  for (const [id, theme] of Object.entries(graphState.theme_nodes)) {
    nodes.push({
      data: {
        id,
        label: theme.title,
        type: 'theme',
        domain: theme.domain,
        status: theme.status,
        completion: theme.extracted_events.length / 10, // 用已提取事件数估算完成度
      },
      classes: `theme-node status-${theme.status} domain-${theme.domain}`,
    })

    // 添加主题依赖边
    theme.depends_on.forEach((depId) => {
      if (graphState.theme_nodes[depId]) {
        edges.push({
          data: {
            id: `edge-dep-${depId}-${id}`,
            source: depId,
            target: id,
            type: 'dependency',
          },
          classes: 'dependency-edge',
        })
      }
    })
  }

  // 转换事件节点
  for (const [id, event] of Object.entries(graphState.event_nodes)) {
    // 计算槽位完成度
    const slotValues = Object.values(event.slots)
    const filledSlots = slotValues.filter(v => v !== null).length
    const slotCompletion = filledSlots / slotValues.length

    nodes.push({
      data: {
        id,
        label: event.title,
        type: 'event',
        timeAnchor: event.slots.time ?? undefined,
        emotionalScore: event.emotional_score,
        completion: slotCompletion,
        depth: event.depth_level,
      },
      classes: `event-node depth-${Math.min(event.depth_level, 5)} emotion-${getEmotionClass(event.emotional_score)}`,
    })

    // 添加包含边（主题 -> 事件）
    edges.push({
      data: {
        id: `edge-contains-${event.theme_id}-${id}`,
        source: event.theme_id,
        target: id,
        type: 'contains',
      },
      classes: 'contains-edge',
    })
  }

  // 转换人物节点
  if (graphState.people_nodes) {
    for (const [id, person] of Object.entries(graphState.people_nodes)) {
      nodes.push({
        data: {
          id,
          label: person.name,
          type: 'person',
          relation: person.relation,
        },
        classes: 'person-node',
      })

      // 添加涉及边（事件 -> 人物）
      person.related_events.forEach((eventId) => {
        edges.push({
          data: {
            id: `edge-involves-${eventId}-${id}`,
            source: eventId,
            target: id,
            type: 'involves',
          },
          classes: 'involves-edge',
        })
      })

      // 添加人物关系边
      person.relationships.forEach((rel) => {
        edges.push({
          data: {
            id: `edge-related-${id}-${rel.target_id}`,
            source: id,
            target: rel.target_id,
            type: 'related',
          },
          classes: 'related-edge person-relationship',
        })
      })
    }
  }

  return { nodes, edges }
}

/**
 * 根据情绪分数获取情绪类别
 */
function getEmotionClass(score: number): string {
  if (score > 0.5) return 'positive'
  if (score > 0) return 'slightly-positive'
  if (score === 0) return 'neutral'
  if (score > -0.5) return 'slightly-negative'
  return 'negative'
}

/**
 * 获取 Cytoscape 样式配置
 * 主题分区样式，气泡风格
 */
export function getCytoscapeStyles() {
  return [
    // ==================== 主题节点样式 ====================
    {
      selector: 'node.theme-node',
      style: {
        'width': 100,
        'height': 100,
        'shape': 'roundrectangle',
        'background-color': 'data(domain)',
        'background-color-map': DomainColors,
        'background-opacity': 0.4,
        'label': 'data(label)',
        'font-size': 12,
        'font-weight': '600',
        'color': '#374151',
        'text-valign': 'center',
        'text-halign': 'center',
        'text-wrap': 'wrap',
        'text-max-width': 90,
        'border-width': 3,
        'border-color': 'data(domain)',
        'border-color-map': DomainBorderColors,
        'border-opacity': 0.8,
        'text-margin-y': 0,
      },
    },
    // 待触达状态
    {
      selector: 'node.status-pending',
      style: {
        'border-style': 'dashed',
        'border-opacity': 0.5,
        'background-opacity': 0.15,
        'color': '#9CA3AF',
      },
    },
    // 已提及状态
    {
      selector: 'node.status-mentioned',
      style: {
        'border-style': 'solid',
        'border-width': 4,
        'border-opacity': 1,
        'background-opacity': 0.5,
      },
    },
    // 已挖透状态
    {
      selector: 'node.status-exhausted',
      style: {
        'border-style': 'solid',
        'border-width': 4,
        'border-opacity': 1,
        'background-opacity': 0.6,
      },
    },

    // ==================== 领域颜色 ====================
    {
      selector: 'node.domain-life_chapters',
      style: {
        'background-color': DomainColors[Domain.LIFE_CHAPTERS],
        'border-color': DomainBorderColors[Domain.LIFE_CHAPTERS],
      },
    },
    {
      selector: 'node.domain-key_scenes',
      style: {
        'background-color': DomainColors[Domain.KEY_SCENES],
        'border-color': DomainBorderColors[Domain.KEY_SCENES],
      },
    },
    {
      selector: 'node.domain-future_scripts',
      style: {
        'background-color': DomainColors[Domain.FUTURE_SCRIPTS],
        'border-color': DomainBorderColors[Domain.FUTURE_SCRIPTS],
      },
    },
    {
      selector: 'node.domain-challenges',
      style: {
        'background-color': DomainColors[Domain.CHALLENGES],
        'border-color': DomainBorderColors[Domain.CHALLENGES],
      },
    },
    {
      selector: 'node.domain-personal_thoughts',
      style: {
        'background-color': DomainColors[Domain.PERSONAL_THOUGHTS],
        'border-color': DomainBorderColors[Domain.PERSONAL_THOUGHTS],
      },
    },

    // ==================== 事件节点样式 ====================
    {
      selector: 'node.event-node',
      style: {
        'width': 70,
        'height': 70,
        'shape': 'ellipse',
        'background-color': '#FEF3C7',
        'background-opacity': 0.6,
        'label': 'data(label)',
        'font-size': 10,
        'color': '#374151',
        'text-valign': 'center',
        'text-halign': 'center',
        'text-wrap': 'wrap',
        'text-max-width': 60,
        'border-width': 2,
        'border-color': '#FCD34D',
        'border-opacity': 0.8,
      },
    },
    // 事件情绪颜色 - 积极
    {
      selector: 'node.emotion-positive',
      style: {
        'background-color': '#D1FAE5',
        'border-color': '#10B981',
      },
    },
    {
      selector: 'node.emotion-slightly-positive',
      style: {
        'background-color': '#ECFDF5',
        'border-color': '#34D399',
      },
    },
    // 事件情绪颜色 - 中性
    {
      selector: 'node.emotion-neutral',
      style: {
        'background-color': '#F3F4F6',
        'border-color': '#9CA3AF',
      },
    },
    // 事件情绪颜色 - 消极
    {
      selector: 'node.emotion-slightly-negative',
      style: {
        'background-color': '#FEF3C7',
        'border-color': '#FBBF24',
      },
    },
    {
      selector: 'node.emotion-negative',
      style: {
        'background-color': '#FEE2E2',
        'border-color': '#EF4444',
      },
    },
    // 事件深度边框
    {
      selector: 'node.depth-5',
      style: { 'border-width': 4 },
    },
    {
      selector: 'node.depth-4',
      style: { 'border-width': 3.5 },
    },
    {
      selector: 'node.depth-3',
      style: { 'border-width': 3 },
    },
    {
      selector: 'node.depth-2',
      style: { 'border-width': 2.5 },
    },
    {
      selector: 'node.depth-1',
      style: { 'border-width': 2 },
    },

    // ==================== 人物节点样式 ====================
    {
      selector: 'node.person-node',
      style: {
        'width': 60,
        'height': 60,
        'shape': 'diamond',
        'background-color': '#FDF4FF',
        'background-opacity': 0.8,
        'label': 'data(label)',
        'font-size': 10,
        'font-weight': '600',
        'color': '#374151',
        'text-valign': 'center',
        'text-halign': 'center',
        'text-wrap': 'wrap',
        'text-max-width': 50,
        'border-width': 2,
        'border-color': '#EC4899',
        'border-opacity': 0.8,
      },
    },

    // ==================== 边样式 ====================
    {
      selector: 'edge',
      style: {
        'width': 1.5,
        'line-color': '#D1D5DB',
        'target-arrow-color': '#D1D5DB',
        'target-arrow-shape': 'triangle',
        'curve-style': 'bezier',
        'arrow-scale': 0.5,
        'opacity': 0.5,
      },
    },
    {
      selector: 'edge.dependency-edge',
      style: {
        'line-color': '#9CA3AF',
        'line-style': 'dashed',
        'target-arrow-color': '#9CA3AF',
        'width': 1,
      },
    },
    {
      selector: 'edge.contains-edge',
      style: {
        'line-color': '#93C5FD',
        'width': 2,
        'target-arrow-color': '#93C5FD',
        'opacity': 0.7,
      },
    },
    {
      selector: 'edge.related-edge',
      style: {
        'line-color': '#C4B5FD',
        'line-style': 'dotted',
        'target-arrow-color': '#C4B5FD',
        'width': 1,
      },
    },
    {
      selector: 'edge.involves-edge',
      style: {
        'line-color': '#EC4899',
        'width': 1.5,
        'target-arrow-color': '#EC4899',
        'opacity': 0.6,
        'line-style': 'solid',
      },
    },

    // ==================== 选中/高亮状态 ====================
    {
      selector: 'node:selected',
      style: {
        'border-width': 5,
        'border-color': '#3B82F6',
        'border-opacity': 1,
        'shadow-color': '#3B82F6',
        'shadow-blur': 10,
        'shadow-opacity': 0.3,
      },
    },
    {
      selector: 'node.highlighted',
      style: {
        'border-width': 4,
        'border-color': '#F59E0B',
        'border-opacity': 1,
        'shadow-color': '#F59E0B',
        'shadow-blur': 8,
        'shadow-opacity': 0.4,
      },
    },
  ]
}

/**
 * 获取 Cytoscape 布局配置
 * 使用 dagre 布局，支持按领域分组
 */
export function getCytoscapeLayout() {
  return {
    name: 'dagre',
    nodeSep: 60,
    edgeSep: 40,
    rankSep: 100,
    rankDir: 'TB',
    animate: true,
    animationDuration: 500,
  }
}

/**
 * 根据领域分组获取布局选项
 */
export function getDomainGroupedLayout() {
  return {
    name: 'cose-bilkent',
    // 分组配置
    idealEdgeLength: 80,
    nodeOverlapAvoidance: 50,
    randomize: false,
    animate: true,
    animationDuration: 800,
    // 分组行为
    tile: true,
    nestingFactor: 1.2,
    gravity: 0.25,
    // 布局质量
    quality: 'proof',
    fit: true,
    padding: 30,
  }
}

/**
 * 获取时间轴排序的事件列表
 */
export function getEventsSortedByTime(graphState: GraphState): Array<[string, typeof graphState.event_nodes[string]]> {
  return Object.entries(graphState.event_nodes)
    .filter(([_, event]) => event.slots.time)
    .sort(([, a], [, b]) => {
      const timeA = a.slots.time || ''
      const timeB = b.slots.time || ''
      return timeA.localeCompare(timeB)
    })
}

/**
 * 根据领域过滤元素
 */
export function getElementsByDomain(
  elements: CyElements,
  domain: Domain,
  graphState: GraphState
): CyElements {
  const themeIds = Object.entries(graphState.theme_nodes)
    .filter(([_, theme]) => theme.domain === domain)
    .map(([id]) => id)

  const eventIds = Object.entries(graphState.event_nodes)
    .filter(([_, event]) => themeIds.includes(event.theme_id))
    .map(([id]) => id)

  return {
    nodes: elements.nodes.filter(
      (n) => themeIds.includes(n.data.id) || eventIds.includes(n.data.id)
    ),
    edges: elements.edges.filter((e) => {
      const sourceInDomain = themeIds.includes(e.data.source) || eventIds.includes(e.data.source)
      const targetInDomain = themeIds.includes(e.data.target) || eventIds.includes(e.data.target)
      return sourceInDomain && targetInDomain
    }),
  }
}

/**
 * 根据状态过滤节点
 */
export function filterByStatus(
  elements: CyElements,
  status: NodeStatus,
  graphState: GraphState
): CyElements {
  const themeIdsByStatus = Object.entries(graphState.theme_nodes)
    .filter(([_, theme]) => theme.status === status)
    .map(([id]) => id)

  return {
    nodes: elements.nodes.filter((n) => {
      if (n.data.type === 'theme') {
        return themeIdsByStatus.includes(n.data.id)
      }
      return true // 保留事件节点
    }),
    edges: elements.edges.filter((e) => {
      // contains 类型的边总是保留（主题到事件的连接）
      if (e.data.type === 'contains') return true
      const sourceTheme = graphState.theme_nodes[e.data.source]
      const targetTheme = graphState.theme_nodes[e.data.target]
      return sourceTheme?.status === status || targetTheme?.status === status
    }),
  }
}
