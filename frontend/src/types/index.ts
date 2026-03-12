/**
 * 动态事件图谱 - 数据类型定义
 *
 * 新的主题分类结构：
 * - 人生篇章
 * - 关键场景：高光、低谷、转折、童年记忆、成人记忆、神秘体验、智慧事件
 * - 未来剧本：梦想与期望、项目规划
 * - 挑战：健康、失落、失败
 * - 个人思想：宗教或信仰、个人价值观、社会价值观、转变和发展
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
  // 人生篇章
  LIFE_CHAPTERS = 'life_chapters',
  // 关键场景
  KEY_SCENES = 'key_scenes',
  // 未来剧本
  FUTURE_SCRIPTS = 'future_scripts',
  // 挑战
  CHALLENGES = 'challenges',
  // 个人思想
  PERSONAL_THOUGHTS = 'personal_thoughts',
}

/** 领域中文名称映射 */
export const DomainLabels: Record<string, string> = {
  [Domain.LIFE_CHAPTERS]: '人生篇章',
  [Domain.KEY_SCENES]: '关键场景',
  [Domain.FUTURE_SCRIPTS]: '未来剧本',
  [Domain.CHALLENGES]: '挑战',
  [Domain.PERSONAL_THOUGHTS]: '个人思想',
}

/** 领域颜色映射 - 低饱和度版本 */
export const DomainColors: Record<string, string> = {
  [Domain.LIFE_CHAPTERS]: '#BFDBFE',   // 淡蓝
  [Domain.KEY_SCENES]: '#DDD6FE',      // 淡紫
  [Domain.FUTURE_SCRIPTS]: '#A5F3FC',  // 淡青
  [Domain.CHALLENGES]: '#FECACA',      // 淡红
  [Domain.PERSONAL_THOUGHTS]: '#FBCFE8', // 淡粉
}

/** 领域边框颜色映射 - 更深的边框 */
export const DomainBorderColors: Record<string, string> = {
  [Domain.LIFE_CHAPTERS]: '#3B82F6',   // 蓝
  [Domain.KEY_SCENES]: '#8B5CF6',      // 紫
  [Domain.FUTURE_SCRIPTS]: '#06B6D4',  // 青
  [Domain.CHALLENGES]: '#EF4444',      // 红
  [Domain.PERSONAL_THOUGHTS]: '#EC4899', // 粉
}

/** 子主题类型 - 关键场景下的细分 */
export enum KeySceneSubType {
  HIGHLIGHT = 'highlight',           // 高光
  LOW_POINT = 'low_point',           // 低谷
  TURNING_POINT = 'turning_point',   // 转折
  CHILDHOOD = 'childhood',           // 童年记忆
  ADULTHOOD = 'adulthood',           // 成人记忆
  MYSTERY = 'mystery',               // 神秘体验
  WISDOM = 'wisdom',                 // 智慧事件
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

/** 子主题类型 - 未来剧本下的细分 */
export enum FutureScriptSubType {
  DREAMS = 'dreams',         // 梦想与期望
  PROJECTS = 'projects',     // 项目规划
}

export const FutureScriptSubTypeLabels: Record<string, string> = {
  [FutureScriptSubType.DREAMS]: '梦想与期望',
  [FutureScriptSubType.PROJECTS]: '项目规划',
}

/** 子主题类型 - 挑战下的细分 */
export enum ChallengeSubType {
  HEALTH = 'health',   // 健康
  LOSS = 'loss',       // 失落
  FAILURE = 'failure', // 失败
}

export const ChallengeSubTypeLabels: Record<string, string> = {
  [ChallengeSubType.HEALTH]: '健康',
  [ChallengeSubType.LOSS]: '失落',
  [ChallengeSubType.FAILURE]: '失败',
}

/** 子主题类型 - 个人思想下的细分 */
export enum PersonalThoughtSubType {
  RELIGION = 'religion',                   // 宗教或信仰
  PERSONAL_VALUES = 'personal_values',     // 个人价值观
  SOCIAL_VALUES = 'social_values',         // 社会价值观
  TRANSFORMATION = 'transformation',       // 转变和发展
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

/** 5个核心槽位名称 */
export const SLOT_NAMES: Record<string, string> = {
  time: '时间',
  location: '地点',
  people: '人物',
  event: '事件',
  reflection: '感悟',
}

/** 主题节点 */
export interface ThemeNode {
  theme_id: string                    // PK - 主题唯一标识
  domain: Domain                      // FK - 所属领域
  title: string                       // NOT NULL - 主题标题
  status: NodeStatus                  // 状态：pending/mentioned/exhausted
  slots_filled: Record<string, boolean> // 槽位填充状态
  seed_questions: string[]            // 种子问题列表
  depends_on: string[]                // FK[] - 依赖的主题ID
  extracted_events: string[]          // FK[] - 已提取的事件ID
}

/** 人物节点 */
export interface PeopleNode {
  people_id: string                   // PK - 人物唯一标识
  name: string                        // NOT NULL - 人物姓名
  relation: string                    // 与老人的关系（如"丈夫"、"大儿子"、"师傅"）
  description: string | null          // 人物描述
  related_events: string[]            // FK[] - 相关事件ID列表
  relationships: PeopleRelationship[] // 与其他人物的关系
  created_at: string | null
}

/** 人物关系 */
export interface PeopleRelationship {
  target_id: string                   // FK - 另一个人物ID
  relation_type: string               // 关系类型（如"夫妻"、"父子"、"师徒"）
}

/** 事件节点 */
export interface EventNode {
  event_id: string                    // PK - 事件唯一标识
  theme_id: string                    // FK - 所属主题
  title: string                       // NOT NULL - 事件标题
  location: string | null             // 地点
  people_involved: string[]           // FK[] - 涉及人物（PeopleNode IDs）
  slots: {                            // 5个核心槽位
    time: string | null               // 时间
    location: string | null           // 地点
    people: string | null             // 人物
    event: string | null              // 事件描述
    reflection: string | null         // 感悟/反思
  }
  emotional_score: number             // -1.0~1.0 - 情绪能量（从事件+感悟计算）
  depth_level: number                 // 0-5 - 挖掘深度（从事件+感悟计算）
  typical_dialogue?: string           // 典型对话
  tags?: string[]                     // 标签
}

// ==================== 图谱状态 ====================

/** 覆盖率指标 */
export interface CoverageMetrics {
  overall_coverage: number
  domain_coverage: Record<string, number>
  slot_coverage: {
    time: number
    location: number
    people: number
    event: number
    reflection: number
  }
  people_coverage: number  // 人物覆盖率
}

/** 图谱状态 */
export interface GraphState {
  theme_nodes: Record<string, ThemeNode>
  event_nodes: Record<string, EventNode>
  people_nodes: Record<string, PeopleNode>
  coverage_metrics: CoverageMetrics
  theme_count: number
  event_count: number
  people_count: number
  pending_themes: number
  mentioned_themes: number
  exhausted_themes: number
  timestamp: string
  // 老人基本信息
  elder_info?: {
    name: string
    age: number
    hometown: string
  }
}

// ==================== Cytoscape 数据类型 ====================

/** Cytoscape 节点数据 */
export interface CyNodeData {
  id: string
  label: string
  type: 'theme' | 'event' | 'person'
  domain?: string
  status?: NodeStatus
  completion?: number
  depth?: number
  timeAnchor?: string
  emotionalScore?: number
  relation?: string  // 人物与老人的关系
}

/** Cytoscape 边数据 */
export interface CyEdgeData {
  id: string
  source: string
  target: string
  type: 'dependency' | 'contains' | 'involves' | 'related'
}

/** Cytoscape 元素 */
export interface CyElements {
  nodes: Array<{ data: CyNodeData; classes: string }>
  edges: Array<{ data: CyEdgeData; classes: string }>
}
