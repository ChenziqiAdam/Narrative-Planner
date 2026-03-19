/**
 * PersonView - 人物思维导图视图组件
 *
 * 使用 AntV G6 实现真正的思维导图效果
 * 中心：受访者老人
 * 一级：关系类别（家人/朋友/工作/其他）
 * 二级：人物节点
 * 三级：相关事件
 */

import React, { useEffect, useRef, useCallback } from 'react'
import { Graph, GraphData, NodeData } from '@antv/g6'
import {
  GraphState,
  PeopleNode,
  EventNode,
  NodeStatus,
} from '../types'
import './PersonView.css'

interface PersonViewProps {
  graphState: GraphState
  onNodeClick?: (node: PeopleNode | EventNode, type: 'person' | 'event') => void
  selectedNodeId?: string | null
  filterStatus?: NodeStatus | 'all'
  className?: string
}

// 关系类别配置
const RELATION_CONFIG: Record<string, { color: string; bgColor: string; icon: string }> = {
  '家人': {
    color: '#EC4899',
    bgColor: '#FDF2F8',
    icon: '👨‍👩‍👧',
  },
  '朋友': {
    color: '#8B5CF6',
    bgColor: '#F5F3FF',
    icon: '👫',
  },
  '工作': {
    color: '#3B82F6',
    bgColor: '#EFF6FF',
    icon: '💼',
  },
  '其他': {
    color: '#6B7280',
    bgColor: '#F9FAFB',
    icon: '📌',
  },
}

// 状态颜色
const STATUS_COLORS: Record<NodeStatus, string> = {
  [NodeStatus.PENDING]: '#9CA3AF',
  [NodeStatus.MENTIONED]: '#F59E0B',
  [NodeStatus.EXHAUSTED]: '#10B981',
}

const PersonView: React.FC<PersonViewProps> = ({
  graphState,
  onNodeClick,
  selectedNodeId,
  filterStatus = 'all',
  className = '',
}) => {
  const containerRef = useRef<HTMLDivElement>(null)
  const graphRef = useRef<Graph | null>(null)
  const onNodeClickRef = useRef(onNodeClick)

  useEffect(() => {
    onNodeClickRef.current = onNodeClick
  }, [onNodeClick])

  // 获取关系类别
  const getRelationGroup = (relation: string): string => {
    const lower = relation.toLowerCase()
    const family = ['父亲', '母亲', '丈夫', '妻子', '儿子', '女儿', '兄弟姐妹', '爷爷', '奶奶', '孙子', '孙女', '老伴']
    const friend = ['朋友', '邻居', '同学', '老乡']
    const work = ['师傅', '工友', '同事', '领导', '下属', '老师', '学生']

    if (family.some(r => lower.includes(r))) return '家人'
    if (friend.some(r => lower.includes(r))) return '朋友'
    if (work.some(r => lower.includes(r))) return '工作'
    return '其他'
  }

  // 转换数据为 G6 格式
  const transformData = useCallback((): GraphData => {
    const { people_nodes, event_nodes, theme_nodes, elder_info } = graphState
    const nodes: NodeData[] = []
    const edges: { source: string; target: string }[] = []

    // 根节点 - 受访者
    nodes.push({
      id: 'root',
      type: 'root-node',
      style: {
        labelText: elder_info?.name || '受访者',
        labelFill: '#111827',
        labelFontSize: 16,
        labelFontWeight: 'bold',
        fill: '#FFFFFF',
        stroke: '#3B82F6',
        lineWidth: 3,
        size: [120, 50],
      },
      data: { type: 'root' },
    })

    // 按关系类别分组
    const groups: Record<string, Array<[string, PeopleNode]>> = {
      '家人': [],
      '朋友': [],
      '工作': [],
      '其他': [],
    }

    Object.entries(people_nodes).forEach(([id, person]) => {
      const group = getRelationGroup(person.relation)
      groups[group].push([id, person])
    })

    // 关系类别顺序
    const relationOrder = ['家人', '朋友', '工作', '其他']
    let sideIndex = 0

    relationOrder.forEach((group) => {
      const people = groups[group]
      if (people.length === 0) return

      const config = RELATION_CONFIG[group]
      const groupId = `group-${group}`

      // 类别节点
      nodes.push({
        id: groupId,
        type: 'group-node',
        style: {
          labelText: `${config.icon} ${group}`,
          labelFill: config.color,
          labelFontSize: 14,
          labelFontWeight: 'bold',
          fill: config.bgColor,
          stroke: config.color,
          lineWidth: 2,
          size: [100, 36],
        },
        data: { type: 'group', group },
      })
      edges.push({ source: 'root', target: groupId })

      // 人物节点
      people.forEach(([personId, person], index) => {
        const isSelected = selectedNodeId === personId
        const personNodeId = `person-${personId}`

        nodes.push({
          id: personNodeId,
          type: 'person-node',
          style: {
            labelText: person.name,
            labelFill: '#374151',
            labelFontSize: 13,
            fill: isSelected ? '#EFF6FF' : '#FAFAFA',
            stroke: isSelected ? '#3B82F6' : config.color,
            lineWidth: isSelected ? 3 : 2,
            size: [90, 34],
          },
          data: { type: 'person', person, personId },
        })
        edges.push({ source: groupId, target: personNodeId })

        // 相关事件节点
        const events = person.related_events
          .map(id => event_nodes[id])
          .filter(Boolean)
          .filter(event => {
            if (filterStatus === 'all') return true
            const theme = theme_nodes[event.theme_id]
            return theme?.status === filterStatus
          })

        events.forEach((event, eventIndex) => {
          const eventNodeId = `event-${event.event_id}`
          const theme = theme_nodes[event.theme_id]
          const statusColor = theme ? STATUS_COLORS[theme.status] : '#9CA3AF'
          const isEventSelected = selectedNodeId === event.event_id

          // 检查事件节点是否已存在
          if (!nodes.find(n => n.id === eventNodeId)) {
            nodes.push({
              id: eventNodeId,
              type: 'event-node',
              style: {
                labelText: event.title,
                labelFill: '#4B5563',
                labelFontSize: 11,
                fill: isEventSelected ? '#EFF6FF' : '#FFFFFF',
                stroke: statusColor,
                lineWidth: isEventSelected ? 2 : 1,
                size: [120, 28],
              },
              data: { type: 'event', event },
            })
          }
          edges.push({ source: personNodeId, target: eventNodeId })
        })

        // 分配左右侧
        sideIndex++
      })
    })

    return { nodes, edges }
  }, [graphState, selectedNodeId, filterStatus])

  // 初始化图
  useEffect(() => {
    if (!containerRef.current) return

    const graph = new Graph({
      container: containerRef.current,
      width: containerRef.current.clientWidth,
      height: containerRef.current.clientHeight,
      data: { nodes: [], edges: [] },
      layout: {
        type: 'mindmap',
        direction: 'LR', // 从左向右：根节点在左，子节点向右展开
        getWidth: () => 100,
        getHeight: () => 40,
        getHGap: () => 60,
        getVGap: () => 20,
      },
      behaviors: ['drag-canvas', 'zoom-canvas', 'drag-element'],
      node: {
        type: 'rect',
        style: {
          radius: 8,
          labelPlacement: 'center',
          labelMaxWidth: 140,
        },
      },
      edge: {
        type: 'cubic-horizontal',
        style: {
          stroke: '#E5E7EB',
          lineWidth: 2,
        },
      },
    })

    graphRef.current = graph

    // 点击事件
    graph.on('node:click', (evt) => {
      const nodeData = evt.target.getData()
      if (nodeData.type === 'person' && nodeData.person) {
        onNodeClickRef.current?.(nodeData.person as PeopleNode, 'person')
      } else if (nodeData.type === 'event' && nodeData.event) {
        onNodeClickRef.current?.(nodeData.event as EventNode, 'event')
      }
    })

    // 初始渲染
    graph.render()

    return () => {
      graph.destroy()
    }
  }, [])

  // 更新数据
  useEffect(() => {
    const graph = graphRef.current
    if (!graph) return

    const data = transformData()
    graph.setData(data)
    graph.render()

    // 适配视图
    setTimeout(() => {
      graph.fitView()
    }, 100)
  }, [transformData])

  // 处理选中节点高亮
  useEffect(() => {
    const graph = graphRef.current
    if (!graph || !selectedNodeId) return

    // 查找对应的节点
    const personNodeId = `person-${selectedNodeId}`
    const eventNodeId = `event-${selectedNodeId}`

    // 聚焦到选中节点
    const node = graph.getNodeData(personNodeId) || graph.getNodeData(eventNodeId)
    if (node) {
      graph.focusElement(node.id, { animation: true })
    }
  }, [selectedNodeId])

  return (
    <div className={`person-mindmap-container ${className}`}>
      <div ref={containerRef} className="person-mindmap-canvas" />
      {/* 图例 */}
      <div className="person-mindmap-legend">
        <div className="legend-title">关系类别</div>
        {Object.entries(RELATION_CONFIG).map(([group, config]) => (
          <div key={group} className="legend-item">
            <span className="legend-color" style={{ backgroundColor: config.color }} />
            <span className="legend-label">{config.icon} {group}</span>
          </div>
        ))}
        <div className="legend-divider" />
        <div className="legend-title">事件状态</div>
        {Object.entries(STATUS_COLORS).map(([status, color]) => (
          <div key={status} className="legend-item">
            <span className="legend-color" style={{ backgroundColor: color }} />
            <span className="legend-label">
              {status === NodeStatus.PENDING && '待触达'}
              {status === NodeStatus.MENTIONED && '已提及'}
              {status === NodeStatus.EXHAUSTED && '已挖透'}
            </span>
          </div>
        ))}
      </div>
      {/* 操作提示 */}
      <div className="person-mindmap-hint">
        <span>🖱️ 拖拽移动画布</span>
        <span>🔍 滚轮缩放</span>
        <span>👆 点击节点查看详情</span>
      </div>
    </div>
  )
}

export default PersonView
