/**
 * Mock 数据 - 模拟图谱状态
 *
 * 基于 elder_profile_example.json 丰富数据
 * 新增：人物节点（PeopleNode）
 */

import {
  GraphState,
  ThemeNode,
  EventNode,
  PeopleNode,
  NodeStatus,
  Domain,
} from '../types'

// ==================== 人物节点 ====================
const mockPeopleNodes: Record<string, PeopleNode> = {
  // 家庭成员
  p001: {
    people_id: 'p001',
    name: '母亲',
    relation: '母亲',
    description: '陈秀英的母亲，经历过抗战和解放，养育子女辛勤操持',
    related_events: ['mem_001', 'mem_002'],
    relationships: [],
    created_at: '2024-01-10T09:00:00Z',
  },
  p002: {
    people_id: 'p002',
    name: '父亲',
    relation: '父亲',
    description: '已故。曾在纺织厂工作，沉默寡言但手艺精湛',
    related_events: ['mem_006'],
    relationships: [
      { target_id: 'p001', relation_type: '夫妻' }
    ],
    created_at: '2024-01-14T09:00:00Z',
  },
  p003: {
    people_id: 'p003',
    name: '王婆婆',
    relation: '邻居',
    description: '隔壁的王婆婆，热心肠，帮助凑学费让我陈秀英上学',
    related_events: ['mem_002'],
    relationships: [],
    created_at: '2024-01-10T09:00:00Z',
  },
  p004: {
    people_id: 'p004',
    name: '老师',
    relation: '老师',
    description: '第一位老师，老先生，教陈秀英写"人之初"',
    related_events: ['mem_002'],
    relationships: [],
    created_at: '2024-01-10T10:00:00Z',
  },
  p005: {
    people_id: 'p005',
    name: '师傅',
    relation: '师傅',
    description: '纺织厂的师傅，东北人，手艺好但人凶',
    related_events: ['mem_004'],
    relationships: [],
    created_at: '2024-01-12T11:30:00Z',
  },
  p006: {
    people_id: 'p006',
    name: '丈夫',
    relation: '丈夫',
    description: '同厂工人，经人介绍结婚，1999年突发脑溢血去世',
    related_events: ['mem_006', 'mem_007', 'mem_011'],
    relationships: [
      { target_id: 'p001', relation_type: '夫妻' },
    ],
    created_at: '2024-01-14T09:00:00Z',
  },
  p007: {
    people_id: 'p007',
    name: '大儿子',
    relation: '大儿子',
    description: '52岁，出租车司机，成都，孝顺但脾气急',
    related_events: ['mem_007'],
    relationships: [
      { target_id: 'p006', relation_type: '父子' }
    ],
    created_at: '2024-01-15T13:00:00Z',
  },
  p008: {
    people_id: 'p008',
    name: '二女儿',
    relation: '二女儿',
    description: '49岁，小学老师，重庆，贴心，经常打电话',
    related_events: [],
    relationships: [
      { target_id: 'p006', relation_type: '父女' }
    ],
    created_at: '2024-01-16T10:00:00Z',
  },
  p009: {
    people_id: 'p009',
    name: '小儿子',
    relation: '小儿子',
    description: '46岁，程序员，深圳，忙但给钱大方',
    related_events: ['mem_010'],
    relationships: [
      { target_id: 'p006', relation_type: '父子' }
    ],
    created_at: '2024-01-18T11:00:00Z',
  },
  p010: {
    people_id: 'p010',
    name: '工友',
    relation: '工友',
    description: '纺织厂的老姐妹们',
    related_events: ['mem_004', 'mem_009', 'mem_012'],
    relationships: [
      { target_id: 'p001', relation_type: '工友' }
    ],
    created_at: '2024-01-17T15:00:00Z',
  },
  p011: {
    people_id: 'p011',
    name: '车间主任',
    relation: '领导',
    description: '纺织厂车间主任，文革期间保护过陈秀英',
    related_events: ['mem_005', 'mem_009', 'mem_012'],
    relationships: [],
    created_at: '2024-01-13T16:00:00Z',
  },
}

// ==================== 主题节点 ====================
const mockThemeNodes: Record<string, ThemeNode> = {
  // ===== 人生篇章 =====
  THEME_LIFE_01: {
    theme_id: 'THEME_LIFE_01',
            domain: Domain.LIFE_CHAPTERS,
            title: '人生篇章概览',
            status: NodeStatus.EXHAUSTED,
            slots_filled: { '童年': true, '青年': true, '中年': true, '老年': true },
            seed_questions: [
                '您能把自己的人生分成几个篇章吗？',
                '每个篇章有什么主题？',
            ],
            depends_on: [],
            extracted_events: ['mem_001', 'mem_002', 'mem_004', 'mem_012'],
        },

  // ===== 关键场景 =====
  THEME_SCENE_HIGHLIGHT: {
            theme_id: 'THEME_SCENE_HIGHLIGHT',
            domain: Domain.KEY_SCENES,
            title: '人生高光时刻',
            status: NodeStatus.MENTIONED,
            slots_filled: { '事件描述': true, '时间地点': true },
            seed_questions: [
                '您人生中最自豪的时刻是什么？',
                '那天发生了什么？',
            ],
            depends_on: ['THEME_LIFE_01'],
            extracted_events: ['mem_008', 'mem_010'],
        },
  THEME_SCENE_LOWPOINT: {
            theme_id: 'THEME_SCENE_LOWPOINT',
            domain: Domain.KEY_SCENES,
            title: '人生低谷时刻',
            status: NodeStatus.MENTIONED,
            slots_filled: { '事件描述': true, '情感体验': true },
            seed_questions: [
                '您人生中最困难的时刻是什么？',
                '您是怎么熬过来的？',
            ],
            depends_on: ['THEME_LIFE_01'],
            extracted_events: ['mem_007', 'mem_011'],
        },
  THEME_SCENE_TURNING: {
            theme_id: 'THEME_SCENE_TURNING',
            domain: Domain.KEY_SCENES,
            title: '人生转折点',
            status: NodeStatus.MENTIONED,
            slots_filled: { '转折描述': true },
            seed_questions: [
                '您人生中有哪些转折点？',
                '这些转折点如何改变了您的人生？',
            ],
            depends_on: [],
            extracted_events: ['mem_004', 'mem_012'],
        },
  THEME_SCENE_CHILDHOOD: {
            theme_id: 'THEME_SCENE_CHILDHOOD',
            domain: Domain.KEY_SCENES,
            title: '童年记忆',
            status: NodeStatus.EXHAUSTED,
            slots_filled: { '事件描述': true, '时间地点': true, '参与人物': true, '情感体验': true },
            seed_questions: [
                '您还记得童年时最深刻的事情吗？',
                '那时候的生活是什么样的？',
            ],
            depends_on: [],
            extracted_events: ['mem_001', 'mem_002', 'mem_003'],
        },
  THEME_SCENE_ADULTHOOD: {
            theme_id: 'THEME_SCENE_ADULTHOOD',
            domain: Domain.KEY_SCENES,
            title: '成人记忆',
            status: NodeStatus.MENTIONED,
            slots_filled: { '事件描述': true, '情感体验': true },
            seed_questions: [
                '工作后印象最深的是什么？',
                '结婚生子时有什么特别的事？',
            ],
            depends_on: [],
            extracted_events: ['mem_005', 'mem_006'],
        },
  THEME_SCENE_WISDOM: {
            theme_id: 'THEME_SCENE_WISDOM',
            domain: Domain.KEY_SCENES,
            title: '智慧事件',
            status: NodeStatus.PENDING,
            slots_filled: {},
            seed_questions: [
                '您从什么时候开始真正理解人生？',
                '有什么事让您获得了重要的感悟？',
            ],
            depends_on: [],
            extracted_events: [],
        },

  // ===== 未来剧本 =====
          THEME_FUTURE_DREAMS: {
            theme_id: 'THEME_FUTURE_DREAMS',
            domain: Domain.FUTURE_SCRIPTS,
            title: '梦想与期望',
            status: NodeStatus.PENDING,
            slots_filled: {},
            seed_questions: [
                '您对晚年生活有什么期望？',
                '有什么想完成的心愿吗？',
            ],
            depends_on: [],
            extracted_events: [],
        },

  // ===== 挑战 =====
          THEME_CHALLENGE_HEALTH: {
            theme_id: 'THEME_CHALLENGE_HEALTH',
            domain: Domain.CHALLENGES,
            title: '健康挑战',
            status: NodeStatus.MENTIONED,
            slots_filled: { '健康状况': true, '担忧': true },
            seed_questions: [
                '您现在身体怎么样？',
                '有什么健康方面的担忧吗？',
            ],
            depends_on: [],
            extracted_events: [],
        },
  THEME_CHALLENGE_LOSS: {
            theme_id: 'THEME_CHALLENGE_LOSS',
            domain: Domain.CHALLENGES,
            title: '失落与失去',
            status: NodeStatus.MENTIONED,
            slots_filled: { '事件描述': true, '情感体验': true },
            seed_questions: [
                '您经历过的最大失落是什么？',
                '您是怎么走出来的？',
            ],
            depends_on: [],
            extracted_events: ['mem_009', 'mem_011'],
        },

  // ===== 个人思想 =====
          THEME_THOUGHT_VALUES: {
            theme_id: 'THEME_THOUGHT_VALUES',
            domain: Domain.PERSONAL_THOUGHTS,
            title: '个人价值观',
            status: NodeStatus.PENDING,
            slots_filled: {},
            seed_questions: [
                '您觉得什么对您最重要？',
                '您一生坚持的原则是什么？',
            ],
            depends_on: [],
            extracted_events: [],
        },
  THEME_THOUGHT_SOCIAL: {
            theme_id: 'THEME_THOUGHT_SOCIAL',
            domain: Domain.PERSONAL_THOUGHTS,
            title: '社会价值观',
            status: NodeStatus.PENDING,
            slots_filled: {},
            seed_questions: [
                '您怎么看现在社会的变化？',
                '您觉得现在和过去有什么不同？',
            ],
            depends_on: [],
            extracted_events: [],
        },
  THEME_THOUGHT_CHANGE: {
            theme_id: 'THEME_THOUGHT_CHANGE',
            domain: Domain.PERSONAL_THOUGHTS,
            title: '转变和发展',
            status: NodeStatus.PENDING,
            slots_filled: {},
            seed_questions: [
                '您年轻时和现在的想法有什么不同？',
                '有什么事改变了您的看法？',
            ],
            depends_on: [],
            extracted_events: [],
        },
}

// ==================== 事件节点（基于 elder_profile_example.json）====================
const mockEventNodes: Record<string, EventNode> = {
  // 童年记忆
    mem_001: {
        event_id: 'mem_001',
        theme_id: 'THEME_SCENE_CHILDHOOD',
        title: '抗战时期的躲警报',
        location: '成都',
        people_involved: ['p001', 'p002'],
        slots: {
            time: '1947年，我五六岁时',
            location: '成都，防空洞',
            people: '母亲、兄弟姐妹',
            event: '躲日本飞机的空袭警报，有一次跑得急把鞋都跑掉了一只',
            reflection: '那会儿真是造孽哦，飞机一来就吓得要死，哪像现在这么太平',
        },
        emotional_score: -0.8,
        depth_level: 4,
        typical_dialogue: '"那会儿真是造孽哦，飞机一来就吓得要死，哪像现在这么太平。"',
        tags: ['抗战', '童年', '恐惧'],
    },
  mem_002: {
        event_id: 'mem_002',
        theme_id: 'THEME_SCENE_CHILDHOOD',
        title: '第一次上学',
        location: '成都',
        people_involved: ['p002', 'p003', 'p004'],
        slots: {
            time: '1950年，8岁)',
            location: '成都',
            people: '王婆婆、老师、母亲',
            event: '第一次进学堂读书，书包是用旧衣服改的，本子是用废纸订的',
            reflection: '我八岁才第一次摸到书本，那会儿觉得学堂好大哦，女娃儿也要认字',
        },
        emotional_score: 0.3,
        depth_level: 5,
        typical_dialogue: '"我八岁才第一次摸到书本，那会儿觉得学堂好大哦。"',
        tags: ['上学', '童年', '贫困'],
    },
  mem_003: {
        event_id: 'mem_003',
        theme_id: 'THEME_SCENE_CHILDHOOD',
        title: '大跃进时期的公社食堂',
        location: '成都',
        people_involved: [],
        slots: {
            time: '1958年大跃进时期',
            location: '成都',
            people: '家人、公社社员',
            event: '吃公社食堂。开始还好后来越吃越差，稀饭清得能照人',
            reflection: '公社食堂开始还热闹，后来就不行了，还是各人家里做实在',
        },
        emotional_score: -0.5,
        depth_level: 4,
        typical_dialogue: '"公社食堂开始还热闹，后来就不行了，还是各人家里做实在。"',
        tags: ['大跃进', '饥饿', '集体'],
    },
  // 成人记忆
    mem_004: {
        event_id: 'mem_004',
        theme_id: 'THEME_SCENE_ADULTHOOD',
        title: '进纺织厂当学徒',
        location: '成都纺织厂',
        people_involved: ['p001', 'p005'],
        slots: {
            time: '1961年，19岁',
            location: '成都纺织厂',
            people: '母亲、师傅',
            event: '顶替母亲的名额进纺织厂当学徒工，第一个月18块钱',
            reflection: '车间里吵得很，说话要靠喊。师傅是个东北人，凶得很，但手艺好',
        },
        emotional_score: 0.2,
        depth_level: 3,
        typical_dialogue: '"第一天进车间，耳朵都要震聋了，后来才慢慢习惯。"',
        tags: ['工作', '纺织厂', '学徒'],
    },
  mem_005: {
        event_id: 'mem_005',
        theme_id: 'THEME_SCENE_ADULTHOOD',
        title: '文化大革命期间被贴大字报',
        location: '成都纺织厂',
        people_involved: ['p011'],
        slots: {
            time: '1968年文革期间',
            location: '纺织厂',
            people: '车间主任',
            event: '因一句话被贴大字报，差点被批斗',
            reflection: '那会儿说话要小心，一句话不对就要遭',
        },
        emotional_score: -0.7,
        depth_level: 3,
        typical_dialogue: '"那会儿说话要小心，一句话不对就要遭。"',
        tags: ['文革', '政治', '恐惧'],
    },
  mem_006: {
        event_id: 'mem_006',
        theme_id: 'THEME_SCENE_ADULTHOOD',
        title: '结婚时的"三转一响"',
        location: '成都',
        people_involved: ['p005', 'p006'],
        slots: {
            time: '1970年',
            location: '成都',
            people: '丈夫、师傅、家人',
            event: '结婚，置办"三转一响"：缝纫机、自行车、手表、收音机',
            reflection: '那会儿结婚，有"三转一响"就不得了了，现在年轻人要房要车。',
        },
        emotional_score: 0.7,
        depth_level: 4,
        typical_dialogue: '"那会儿结婚，有"三转一响"就不得了了，现在年轻人要房要车。"',
        tags: ['结婚', '嫁妆', '幸福'],
    },
  // 低谷
  mem_007: {
        event_id: 'mem_007',
        theme_id: 'THEME_SCENE_LOWPOINT',
        title: '生大儿子难产',
        location: '纺织厂卫生所',
        people_involved: ['p006', 'p004'],
        slots: {
            time: '1972年',
            location: '厂卫生所',
            people: '丈夫、医生',
            event: '生大儿子时难产，大出血差点没命',
            reflection: '生老大时折腾了两天一夜，那时候医疗条件差，差点没救过来。后来他爸说再也不生了，结果后来又生了两个',
        },
        emotional_score: -0.6,
        depth_level: 4,
        typical_dialogue: '"生老大的时候，我以为我活不成了，现在想想都后怕。',
        tags: ['生育', '危险', '母亲'],
    },
  // 高光
  mem_008: {
        event_id: 'mem_008',
        theme_id: 'THEME_SCENE_HIGHLIGHT',
        title: '第一次涨工资',
        location: '成都',
        people_involved: ['p007', 'p008', 'p009'],
        slots: {
            time: '1983年',
            location: '成都',
            people: '孩子们',
            event: '改革开放后第一次涨工资，从42块涨到68块，涨了26块，买了两斤肉包饺子',
            reflection: '那会儿涨20多块钱不得了哦，能买好多东西，孩子们吃得满嘴流油说妈今天过年啦',
        },
        emotional_score: 0.9,
        depth_level: 3,
        typical_dialogue: '"那会儿涨20多块钱不得了哦，能买好多东西。"',
        tags: ['改革开放', '涨工资', '喜悦'],
    },
  // 失落
  mem_009: {
        event_id: 'mem_009',
        theme_id: 'THEME_CHALLENGE_LOSS',
        title: '工厂改制下岗潮',
        location: '成都纺织厂',
        people_involved: ['p008', 'p010', 'p011'],
        slots: {
            time: '1995年',
            location: '纺织厂',
            people: '工友姐妹们、车间主任',
            event: '国企改制，第一批下岗三分之一。我因手艺好留下来的，心里难受',
            reflection: '看着她们哭，我心里也跟刀割一样，虽然有啥子办法嘛',
        },
        emotional_score: -0.4,
        depth_level: 3,
        typical_dialogue: '"看着她们哭，我心里也跟刀割一样，虽然有啥子办法嘛。',
        tags: ['下岗', '改制', '伤感'],
    },
  // 高光
  mem_010: {
        event_id: 'mem_010',
        theme_id: 'THEME_SCENE_HIGHLIGHT',
        title: '儿子考上大学',
        location: '成都',
        people_involved: ['p006', 'p009'],
        slots: {
            time: '1998年',
            location: '成都',
            people: '小儿子',
            event: '三个娃中老幺考上四川大学，收到通知书那天我哭了一下午',
            reflection: '他爸在的时候总说我们陈家要出个大学生，可惜他没看到，力把爸爸的相片擦了又擦，告诉他你儿子争气。',
        },
        emotional_score: 0.85,
        depth_level: 4,
        typical_dialogue: '"老幺考上大学那天，我把他爸的相片擦了又擦，告诉他你儿子争气。',
        tags: ['子女', '教育', '骄傲'],
    },
  // 低谷/失落
  mem_011: {
        event_id: 'mem_011',
        theme_id: 'THEME_SCENE_LOWPOINT',
        title: '老伴去世',
        location: '成都',
        people_involved: ['p006'],
        slots: {
            time: '1999年',
            location: '成都',
            people: '老伴',
            event: '老伴突发脑溢血去世',
            reflection: '那天早上还好好的，说去公园打太极，突然就倒下了。送到医院没抢救过来。一起过了29年，说走就走了。那段时间觉得天都塌了。',
        },
        emotional_score: -0.95,
        depth_level: 5,
        typical_dialogue: '"他走得太突然了，一句话都没留下..."',
        tags: ['丧偶', '悲痛', '转折'],
    },
  // 转折
  mem_012: {
        event_id: 'mem_012',
        theme_id: 'THEME_SCENE_TURNING',
        title: '正式退休',
        location: '成都纺织厂',
        people_involved: ['p008', 'p010', 'p011'],
        slots: {
            time: '2000年',
            location: '纺织厂',
            people: '工友们、车间主任',
            event: '正式退休，离开工作35年的工厂',
            reflection: '最后一天上班，我把机床擦了又擦。车间主任和工友们给我开了欢送会，送了条红围巾。走出厂门时回头看了好久，半辈子都在这里了。',
        },
        emotional_score: 0.3,
        depth_level: 4,
        typical_dialogue: '"在厂里35年，出来的时候觉得心里空落落的。"',
        tags: ['退休', '告别', '感慨'],
    },
}

// ==================== 图谱状态 ====================
export const mockGraphState: GraphState = {
  theme_nodes: mockThemeNodes,
  event_nodes: mockEventNodes,
  people_nodes: mockPeopleNodes,
  coverage_metrics: {
        overall_coverage: 0.48,
        domain_coverage: {
            [Domain.LIFE_CHAPTERS]: 1.0,
            [Domain.KEY_SCENES]: 0.65,
            [Domain.FUTURE_SCRIPTS]: 0,
            [Domain.CHALLENGES]: 0.35,
            [Domain.PERSONAL_THOUGHTS]: 0,
        },
        slot_coverage: {
            time: 0.85,
            location: 0.7,
            people: 0.6,
            event: 0.5,
            reflection: 0.4,
        },
        people_coverage: 0.6,
    },
    theme_count: 13,
    event_count: 12,
    people_count: 11,
    pending_themes: 5,
    mentioned_themes: 6,
    exhausted_themes: 2,
    timestamp: '2024-01-20T16:00:00Z',
    elder_info: {
        name: '陈秀英',
        age: 82,
        hometown: '四川省成都市',
    }
}

// 获取 Mock 数据的函数
export function getMockGraphState(): Promise<GraphState> {
  return new Promise((resolve) => {
    // 模拟网络延迟
    setTimeout(() => {
      resolve(mockGraphState)
    }, 500)
  })
}
