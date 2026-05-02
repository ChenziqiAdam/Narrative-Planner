/**
 * 动态事件图谱 - 数据类型定义 (GraphRAG)
 *
 * 核心设计原则：
 * - 不再有固定的 8 槽位 schema
 * - 实体和关系自由提取，字段全部可选
 * - rich_text 保存完整叙事，properties 保存可选结构化信息
 */

// ==================== 枚举定义 ====================

/** 节点状态 */
export enum NodeStatus {
  PENDING = 'pending',       // 预设待触达
  MENTIONED = 'mentioned',   // 已提及未展开
  EXHAUSTED = 'exhausted',   // 已挖透
}

/** 领域类型 - 按新的主题分类 */
export enum Domain {
  LIFE_CHAPTERS = 'life_chapters',
  KEY_SCENES = 'key_scenes',
  FUTURE_SCRIPTS = 'future_scripts',
  CHALLENGES = 'challenges',
  PERSONAL_THOUGHTS = 'personal_thoughts',
  PERSONAL_IDEOLOGY = 'personal_ideology',
  CONTEXT_MANAGEMENT = 'context_management',
}

/** 领域中文名称映射 */
export const DomainLabels: Record<string, string> = {
  [Domain.LIFE_CHAPTERS]: '人生篇章',
  [Domain.KEY_SCENES]: '关键场景',
  [Domain.FUTURE_SCRIPTS]: '未来剧本',
  [Domain.CHALLENGES]: '挑战',
  [Domain.PERSONAL_THOUGHTS]: '个人思想',
  [Domain.PERSONAL_IDEOLOGY]: '个人思想',
  [Domain.CONTEXT_MANAGEMENT]: '上下文管理',
}

/** 领域颜色映射 - 低饱和度版本 */
export const DomainColors: Record<string, string> = {
  [Domain.LIFE_CHAPTERS]: '#BFDBFE',
  [Domain.KEY_SCENES]: '#DDD6FE',
  [Domain.FUTURE_SCRIPTS]: '#A5F3FC',
  [Domain.CHALLENGES]: '#FECACA',
  [Domain.PERSONAL_THOUGHTS]: '#FBCFE8',
  [Domain.PERSONAL_IDEOLOGY]: '#FBCFE8',
  [Domain.CONTEXT_MANAGEMENT]: '#E5E7EB',
}

/** 领域边框颜色映射 */
export const DomainBorderColors: Record<string, string> = {
  [Domain.LIFE_CHAPTERS]: '#3B82F6',
  [Domain.KEY_SCENES]: '#8B5CF6',
  [Domain.FUTURE_SCRIPTS]: '#06B6D4',
  [Domain.CHALLENGES]: '#EF4444',
  [Domain.PERSONAL_THOUGHTS]: '#EC4899',
  [Domain.PERSONAL_IDEOLOGY]: '#EC4899',
  [Domain.CONTEXT_MANAGEMENT]: '#6B7280',
}

/** 子主题类型 */
export enum KeySceneSubType {
  HIGHLIGHT = 'highlight',
  LOW_POINT = 'low_point',
  TURNING_POINT = 'turning_point',
  CHILDHOOD = 'childhood',
  ADULTHOOD = 'adulthood',
  MYSTERY = 'mystery',
  WISDOM = 'wisdom',
}

export const KeySceneSubTypeLabels: Record<string, string> = {
  [KeySceneSubType.HIGHLIGHT]: '高光',
  [KeySceneSubType.LOW_POINT]: '低谷',
  [KeySceneSubType.TURNING_POINT]: '转折',
  [KeySceneSubType.CHILDHOOD]: '童年记忆',
  [KeySceneSubType.ADULTHOOD]: '成人记忆',
  [KeySceneSubType.MYSTERY]: '神秘体验',
  [KeySceneSubType.WISDOM]: '智慧事件',
}

export enum FutureScriptSubType {
  DREAMS = 'dreams',
  PROJECTS = 'projects',
}

export const FutureScriptSubTypeLabels: Record<string, string> = {
  [FutureScriptSubType.DREAMS]: '梦想与期望',
  [FutureScriptSubType.PROJECTS]: '项目规划',
}

export enum ChallengeSubType {
  HEALTH = 'health',
  LOSS = 'loss',
  FAILURE = 'failure',
}

export const ChallengeSubTypeLabels: Record<string, string> = {
  [ChallengeSubType.HEALTH]: '健康',
  [ChallengeSubType.LOSS]: '失落',
  [ChallengeSubType.FAILURE]: '失败',
}

export enum PersonalThoughtSubType {
  RELIGION = 'religion',
  PERSONAL_VALUES = 'personal_values',
  SOCIAL_VALUES = 'social_values',
  TRANSFORMATION = 'transformation',
}

export const PersonalThoughtSubTypeLabels: Record<string, string> = {
  [PersonalThoughtSubType.RELIGION]: '宗教或信仰',
  [PersonalThoughtSubType.PERSONAL_VALUES]: '个人价值观',
  [PersonalThoughtSubType.SOCIAL_VALUES]: '社会价值观',
  [PersonalThoughtSubType.TRANSFORMATION]: '转变和发展',
}

/** 状态颜色映射 */
export const StatusColors: Record<NodeStatus, string> = {
  [NodeStatus.PENDING]: '#9CA3AF',
  [NodeStatus.MENTIONED]: '#F59E0B',
  [NodeStatus.EXHAUSTED]: '#10B981',
}

// ==================== 节点数据模型 ====================

/** 主题节点 */
export interface ThemeNode {
  theme_id: string
  title: string
  status: NodeStatus
  priority: number
  narrative_richness: number       // 0-1 叙事丰富度
  entity_count: number             // 关联实体数量
  exploration_depth: number        // 探索深度
}

/** 人物节点 */
export interface PeopleNode {
  people_id: string
  name: string
  relation: string
  description: string | null
  related_events: string[]
  relationships: PeopleRelationship[]
  created_at: string | null
}

export interface PeopleRelationship {
  target_id: string
  relation_type: string
}

/** 叙事片段节点（替代旧 EventNode） */
export interface NarrativeFragmentNode {
  fragment_id: string
  rich_text: string                // 完整叙事文本
  source_turn_ids: string[]
  theme_id: string | null
  confidence: number
  narrative_richness: number       // 0-1 四维评分
  properties: Record<string, any>  // time_anchor, location, people_names, emotional_tone...
  merge_status: string
}

/** 实体类型 */
export type EntityType = 'Event' | 'Person' | 'Location' | 'Emotion' | 'Insight'

/** 关系边 */
export interface RelationshipEdge {
  source_id: string
  target_id: string
  relation_type: string
  properties?: Record<string, any>
}

// ==================== 图谱状态 ====================

/** 覆盖率指标 */
export interface CoverageMetrics {
  theme_richness: Record<string, number>   // 主题→叙事丰富度
  overall_richness: number                  // 全局平均
}

/** 图谱状态 */
export interface GraphState {
  session_id: string
  coverage_metrics: CoverageMetrics
  theme_nodes: ThemeNode[]
  narrative_fragments: Record<string, NarrativeFragmentNode>
  dynamic_profile?: Record<string, any>
  turn_count: number
  timestamp: string
  elder_info?: {
    name: string
    age: number
    hometown: string
  }
}

// ==================== Cytoscape 数据类型 ====================

export interface CyNodeData {
  id: string
  label: string
  type: 'theme' | 'fragment' | 'person' | 'location' | 'emotion'
  domain?: string
  status?: NodeStatus
  narrative_richness?: number
  entity_type?: EntityType
  relation?: string
}

export interface CyEdgeData {
  id: string
  source: string
  target: string
  type: 'dependency' | 'contains' | 'involves' | 'located_at' | 'triggers'
}

export interface CyElements {
  nodes: Array<{ data: CyNodeData; classes: string }>
  edges: Array<{ data: CyEdgeData; classes: string }>
}
