# Planner 指令集标准 (Planner Instruction Standard)

> **版本**: v1.4.0
> **状态**: Draft
> **更新日期**: 2026-02-06

---

## 1. 概述

### 1.1 设计目标

Planner 是"叙事导航者"系统的核心决策模块，其职责是：

1. **解耦规划与生成**：Planner 只输出结构化战术指令，不直接生成对话文本
2. **动态图谱驱动**：基于实时构建的人生事件图谱进行决策
3. **智能导航博弈**：在深度挖掘（Depth-expansion）与广度跳转（Breadth-switching）间动态平衡

### 1.2 指令流转

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Planner 指令流转                              │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│   输入                      Planner 内部             输出           │
│ ┌──────────┐           ┌──────────────┐        ┌──────────┐       │
│ │  用户    │────────▶  │              │────────▶│ NLG模块  │       │
│ │  回答    │           │   决策引擎   │        │ 对话生成 │       │
│ └──────────┘           │              │        └──────────┘       │
│                        │  ┌────────┐  │             │              │
│   ┌──────────┐         │  │ state  │  │             ▼              │
│   │ 事件图谱  │────────▶  │ (内部) │  │      JSON 指令            │
│   │ 当前状态  │           │  └────────┘  │   ┌─────────────────┐  │
│   └──────────┘           │              │   │ meta (元数据)    │  │
│                        └──────────────┘   │ action (战术动作) │  │
│                                            │ context (上下文)  │  │
│                                            │ _debug (可选)     │  │
│                                            └─────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘

说明：
• state 是 Planner 的内部处理变量，用于决策依据
• 输出 JSON 只包含"做什么"，不包含"当前是什么"
• _debug_snapshot 为可选字段，仅调试模式包含 state 快照
```

### 1.3 设计原则

| 原则 | 说明 |
|:---|:---|
| **指令纯粹** | 输出只包含"做什么"，不包含"当前是什么"（state 作为内部变量） |
| **单一职责** | 每个指令只描述一个战术动作 |
| **机器可读** | JSON 格式，字段类型明确，便于解析 |
| **人类可读** | 字段命名语义化，便于调试与日志审查 |
| **可扩展性** | 预留扩展字段，支持未来新增策略 |

---

## 2. 指令格式定义

### 2.1 顶层结构

```json
{
  "meta": { ... },
  "action": { ... },
  "context": { ... },
  "_debug_snapshot": { ... }  // 可选，仅调试模式
}
```

> **注意**：`state` 是 Planner 的**内部处理变量**，用于决策依据，不包含在输出指令中。如需调试信息，可使用 `_debug_snapshot` 字段。

### 2.2 完整 Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "Planner Instruction",
  "description": "Narrative Navigator Planner 决策指令标准格式",
  "type": "object",
  "required": ["meta", "action"],
  "properties": {
    "meta": {
      "type": "object",
      "description": "指令元数据",
      "required": ["version", "timestamp", "instruction_id"],
      "properties": {
        "version": {
          "type": "string",
          "description": "指令集版本号",
          "example": "1.0.0"
        },
        "timestamp": {
          "type": "string",
          "description": "指令生成时间 (ISO 8601)",
          "example": "2026-02-06T10:30:00Z"
        },
        "instruction_id": {
          "type": "string",
          "description": "指令唯一标识符 (UUID)",
          "example": "550e8400-e29b-41d4-a716-446655440000"
        },
        "turn_number": {
          "type": "integer",
          "description": "当前对话轮次（从1开始）",
          "minimum": 1,
          "example": 5
        }
      }
    },
    "action": {
      "type": "object",
      "description": "核心战术动作",
      "required": ["primary_action", "tactical_goal"],
      "properties": {
        "primary_action": {
          "$ref": "#/definitions/PrimaryAction"
        },
        "tactical_goal": {
          "$ref": "#/definitions/TacticalGoal"
        },
        "tone_constraint": {
          "$ref": "#/definitions/ToneConstraint"
        },
        "strategy": {
          "$ref": "#/definitions/Strategy"
        },
        "target_node": {
          "$ref": "#/definitions/NodeReference"
        }
      }
    },
    "context": {
      "type": "object",
      "description": "上下文桥接信息",
      "properties": {
        "bridge_type": {
          "$ref": "#/definitions/BridgeType"
        },
        "entities": {
          "type": "array",
          "description": "当前上下文中的关键实体",
          "items": {
            "$ref": "#/definitions/Entity"
          }
        },
        "suggested_opening": {
          "type": "string",
          "description": "建议的对话开场方式（已包含上下文信息，无需额外的 context_bridge 字段）",
          "example": "先对用户表达的困难表示理解，然后用温和的方式引导描述当时的感受"
        }
      }
    },
    "_debug_snapshot": {
      "type": "object",
      "description": "调试快照（仅调试模式包含，生产环境省略）",
      "properties": {
        "state_at_decision": {
          "type": "object",
          "description": "决策时的图谱状态快照",
          "properties": {
            "current_focus": {
              "$ref": "#/definitions/NodeReference"
            },
            "coverage_metrics": {
              "$ref": "#/definitions/CoverageMetrics"
            },
            "user_state": {
              "$ref": "#/definitions/UserState"
            }
          }
        },
        "decision_trace": {
          "type": "array",
          "description": "决策轨迹（可选）",
          "items": {
            "type": "string"
          }
        }
      }
    }
  },
  "definitions": {
    "NodeReference": {
      "type": "object",
      "description": "事件节点引用",
      "required": ["node_id"],
      "properties": {
        "node_id": {
          "type": "string",
          "description": "节点唯一标识",
          "example": "1992_startup_phase"
        },
        "node_type": {
          "type": "string",
          "enum": ["life_chapter", "key_event", "relationship", "theme"],
          "description": "节点类型"
        },
        "label": {
          "type": "string",
          "description": "节点显示标签",
          "example": "1992年创业初期"
        }
      }
    },
    "CoverageMetrics": {
      "type": "object",
      "description": "覆盖率指标",
      "properties": {
        "overall_coverage": {
          "type": "number",
          "minimum": 0,
          "maximum": 1,
          "description": "总体覆盖率 (0-1)"
        },
        "dimension_coverage": {
          "type": "object",
          "description": "各维度覆盖率",
          "properties": {
            "time": { "type": "number", "minimum": 0, "maximum": 1 },
            "space": { "type": "number", "minimum": 0, "maximum": 1 },
            "people": { "type": "number", "minimum": 0, "maximum": 1 },
            "emotion": { "type": "number", "minimum": 0, "maximum": 1 },
            "reflection": { "type": "number", "minimum": 0, "maximum": 1 }
          }
        },
        "current_depth": {
          "type": "integer",
          "minimum": 0,
          "maximum": 5,
          "description": "当前节点挖掘深度 (0-5)"
        }
      }
    },
    "UserState": {
      "type": "object",
      "description": "用户状态评估（两维度模型）",
      "properties": {
        "emotional_energy": {
          "type": "number",
          "minimum": -1,
          "maximum": 1,
          "description": "情绪能量 (-1=负面/低落, 0=平静, 1=正面/高昂)，用于选择语气"
        },
        "energy_level": {
          "type": "number",
          "minimum": 0,
          "maximum": 1,
          "description": "精神状态 (0=疲惫/低能量, 1=充沛/高能量)，用于决定继续/暂停"
        }
      }
    },
    "PrimaryAction": {
      "type": "string",
      "description": "主要动作类型",
      "enum": [
        "DEEP_DIVE",
        "BREADTH_SWITCH",
        "CLARIFY",
        "SUMMARIZE",
        "PAUSE_SESSION",
        "CLOSE_INTERVIEW"
      ]
    },
    "TacticalGoal": {
      "type": "object",
      "description": "战术目标",
      "required": ["goal_type", "description"],
      "properties": {
        "goal_type": {
          "type": "string",
          "description": "目标类型",
          "enum": [
            // 深度挖掘类
            "EXTRACT_DETAILS",
            "EXTRACT_EMOTIONS",
            "EXTRACT_REFLECTIONS",
            "EXTRACT_SENSORY",
            "EXTRACT_CAUSALITY",
            // 广度跳转类
            "EXPLORE_PERIOD",
            "EXPLORE_PERSON",
            "EXPLORE_LOCATION",
            "EXPLORE_THEME",
            // 纠偏类
            "RESOLVE_CONFLICT",
            "CONFIRM_UNDERSTANDING",
            // 总结类
            "REVIEW_PERIOD",
            "SYNTHESIZE_THEME",
            // 结束类
            "SESSION_FAREWELL",
            "FINAL_CLOSURE"
          ]
        },
        "description": {
          "type": "string",
          "description": "目标自然语言描述",
          "example": "提取用户在创业失败时的情绪体验"
        },
        "target_slots": {
          "type": "array",
          "description": "待填充的槽位清单",
          "items": {
            "type": "string"
          },
          "example": ["时间", "地点", "起因", "结果", "感受"]
        }
      }
    },
    "ToneConstraint": {
      "type": "object",
      "description": "语气约束",
      "required": ["primary_tone"],
      "properties": {
        "primary_tone": {
          "type": "string",
          "description": "主要语气",
          "enum": [
            "EMPATHIC_SUPPORTIVE",
            "CURIOUS_INQUIRING",
            "RESPECTFUL_REVERENT",
            "CASUAL_CONVERSATIONAL",
            "PROFESSIONAL_NEUTRAL",
            "GENTLE_WARM",
            "ENCOURAGING"
          ]
        },
        "secondary_tone": {
          "type": "string",
          "description": "次要语气（可选）",
          "enum": [
            "HUMOROUS",
            "NOSTALGIC",
            "THOUGHTFUL",
            "ENERGETIC",
            "CALM"
          ]
        },
        "constraints": {
          "type": "array",
          "description": "额外约束",
          "items": {
            "type": "string",
            "enum": [
              "NO_LEADING_QUESTIONS",
              "NO_JUDGMENT",
              "ALLOW_SILENCE",
              "VALIDATE_FEELINGS",
              "AVOID_TECHNICAL_TERMS"
            ]
          }
        }
      }
    },
    "Strategy": {
      "type": "object",
      "description": "执行策略",
      "required": ["strategy_type"],
      "properties": {
        "strategy_type": {
          "type": "string",
          "description": "策略类型",
          "enum": [
            // 深度扩展路径
            "EVENT_TO_PERSON",
            "OBJECT_TO_EMOTION",
            "ERA_TO_INDIVIDUAL",
            // 广度跳转路径
            "SPATIAL_JUMP",
            "SOCIAL_NETWORK_JUMP",
            "HISTORICAL_SNAPSHOT",
            "AFFECTIVE_ASSOCIATION",
            "TASK_RESUME"
          ]
        },
        "parameters": {
          "type": "object",
          "description": "策略参数",
          "additionalProperties": true
        },
        "priority": {
          "type": "integer",
          "minimum": 1,
          "maximum": 3,
          "description": "优先级 (1=最高, 3=最低)"
        }
      }
    },
    "BridgeType": {
      "type": "string",
      "description": "桥接类型",
      "enum": [
        "NONE",
        "SUMMARY_BRIDGE",
        "EMOTIONAL_BRIDGE",
        "THEMATIC_BRIDGE",
        "TEMPORAL_BRIDGE",
        "CONTRAST_BRIDGE",
        "ACKNOWLEDGMENT_BRIDGE"
      ]
    },
    "Entity": {
      "type": "object",
      "description": "实体信息",
      "required": ["entity_type", "text"],
      "properties": {
        "entity_type": {
          "type": "string",
          "enum": ["PERSON", "LOCATION", "TIME", "ORGANIZATION", "EVENT", "OBJECT"]
        },
        "text": {
          "type": "string",
          "description": "实体文本"
        },
        "normalized": {
          "type": "string",
          "description": "规范化后的实体值"
        },
        "confidence": {
          "type": "number",
          "minimum": 0,
          "maximum": 1,
          "description": "识别置信度"
        }
      }
    }
  }
}
```

---

## 3. 动作类型详解

### 3.1 DEEP_DIVE（深度挖掘）

**意图**：在当前事件/主题上深入挖掘，获取更多细节、情感和反思。

**触发条件**：
- 当前节点槽位填充率 < 80%
- 情绪能量评分 > 0.5（用户情绪饱满，适合深挖）
- 精神状态 > 0.4（用户还有精力）

**Tactical Goal 类型**：
| goal_type | 描述 | 示例问题方向 |
|:---|:---|:---|
| `EXTRACT_DETAILS` | 提取事实细节 | "具体是什么时间？还有谁在场？" |
| `EXTRACT_EMOTIONS` | 提取情绪体验 | "当时您是什么心情？" |
| `EXTRACT_REFLECTIONS` | 提取反思感悟 | "现在回头看，您有什么感悟？" |
| `EXTRACT_SENSORY` | 提取感官细节 | "那天天气怎么样？有什么声音或气味？" |
| `EXTRACT_CAUSALITY` | 提取因果关系 | "是什么原因导致这个结果？" |

**Strategy 类型**：
| strategy_type | 描述 | 使用场景 |
|:---|:---|:---|
| `EVENT_TO_PERSON` | 由事及人，归纳性格特质 | 访谈早期，建立信任 |
| `OBJECT_TO_EMOTION` | 由物及情，感官触发法 | 记忆模糊时，用物品作为锚点 |
| `ERA_TO_INDIVIDUAL` | 由时代及个体，演绎法 | 提升回忆录社会学价值 |

**示例指令**：

```json
{
  "meta": {
    "version": "1.0.0",
    "timestamp": "2026-02-06T10:30:00Z",
    "instruction_id": "550e8400-e29b-41d4-a716-446655440001",
    "turn_number": 8
  },
  "action": {
    "primary_action": "DEEP_DIVE",
    "tactical_goal": {
      "goal_type": "EXTRACT_EMOTIONS",
      "description": "提取用户在创业失败时的情绪体验",
      "target_slots": ["起因", "感受", "后续影响"]
    },
    "tone_constraint": {
      "primary_tone": "EMPATHIC_SUPPORTIVE",
      "secondary_tone": "THOUGHTFUL",
      "constraints": ["VALIDATE_FEELINGS", "ALLOW_SILENCE"]
    },
    "strategy": {
      "strategy_type": "OBJECT_TO_EMOTION",
      "parameters": {
        "anchor": "那年冬天租住的小屋"
      },
      "priority": 1
    },
    "target_node": {
      "node_id": "1992_startup_failure",
      "node_type": "key_event"
    }
  },
  "context": {
    "bridge_type": "EMOTIONAL_BRIDGE",
    "entities": [
      {
        "entity_type": "TIME",
        "text": "1992年冬天",
        "normalized": "1992-winter",
        "confidence": 0.95
      },
      {
        "entity_type": "LOCATION",
        "text": "深圳",
        "normalized": "Shenzhen",
        "confidence": 0.9
      }
    ],
    "suggested_opening": "先对用户表达的困难表示理解，然后用温和的方式引导描述当时的感受"
  }
}
```

> **调试模式输出**（可选）：
>
```json
{
  // ... 以上字段不变 ...
  "_debug_snapshot": {
    "state_at_decision": {
      "current_focus": {
        "node_id": "1992_startup_failure",
        "node_type": "key_event",
        "label": "1992年创业失败"
      },
      "coverage_metrics": {
        "overall_coverage": 0.35,
        "current_depth": 2
      },
      "user_state": {
        "emotional_energy": 0.7,
        "energy_level": 0.8
      }
    },
    "decision_trace": [
      "触发: User_mentioned_difficult_winter",
      "槽位填充率 < 80%",
      "情绪能量 > 0.5",
      "精神状态 > 0.4",
      "选择 DEEP_DIVE + EMPATHIC_SUPPORTIVE"
    ]
  }
}
```

---

### 3.2 BREADTH_SWITCH（广度跳转）

**意图**：切换到新的人生阶段、人物或主题，确保访谈覆盖完整。

**触发条件**：
- 当前节点信息密度衰减
- 精神状态 < 0.4（用户累了）
- 当前节点槽位填充率 > 80%（已挖透）
- 某维度覆盖率严重不足（< 30%）

**Tactical Goal 类型**：
| goal_type | 描述 | 示例问题方向 |
|:---|:---|:---|
| `EXPLORE_PERIOD` | 探索新的人生阶段 | "让我们聊聊您大学时代..." |
| `EXPLORE_PERSON` | 探索关键人物 | "您多次提到爱人，还没讲怎么认识的..." |
| `EXPLORE_LOCATION` | 探索地点 | "您后来去了西安，那次搬家..." |
| `EXPLORE_THEME` | 探索主题 | "说到坚持，您年轻时有类似经历吗？" |

**Strategy 类型（跳转路径优先级）**：

| 优先级 | strategy_type | 描述 | 体验 |
|:---:|:---|:---|:---|
| 1 | `AFFECTIVE_ASSOCIATION` | 情感/动机共振跳转 | 最佳 |
| 1 | `SOCIAL_NETWORK_JUMP` | 人物社交网络跳转 | 最佳 |
| 2 | `SPATIAL_JUMP` | 物理/地理跳转 | 稳健 |
| 2 | `TASK_RESUME` | 挂起任务回溯 | 稳健 |
| 3 | `HISTORICAL_SNAPSHOT` | 时代快照跳转 | 补充 |

**示例指令**：

```json
{
  "meta": {
    "version": "1.0.0",
    "timestamp": "2026-02-06T10:45:00Z",
    "instruction_id": "550e8400-e29b-41d4-a716-446655440002",
    "turn_number": 15
  },
  "action": {
    "primary_action": "BREADTH_SWITCH",
    "tactical_goal": {
      "goal_type": "EXPLORE_PERSON",
      "description": "探索用户爱人的相关故事，补充人物维度覆盖"
    },
    "tone_constraint": {
      "primary_tone": "GENTLE_WARM",
      "constraints": ["NO_JUDGMENT"]
    },
    "strategy": {
      "strategy_type": "SOCIAL_NETWORK_JUMP",
      "parameters": {
        "person_name": "爱人",
        "connection_count": 5,
        "mention_frequency": "high"
      },
      "priority": 1
    },
    "target_node": {
      "node_id": "spouse_relationship",
      "node_type": "relationship",
      "label": "与爱人的相识相知"
    }
  },
  "context": {
    "bridge_type": "THEMATIC_BRIDGE",
    "entities": [
      {
        "entity_type": "PERSON",
        "text": "爱人",
        "confidence": 0.98
      }
    ],
    "suggested_opening": "肯定用户刚才讲述的奋斗经历，自然过渡到爱人在其中的角色"
  }
}
```

---

### 3.3 CLARIFY（纠偏澄清）

**意图**：检测并解决叙事中的矛盾、时间冲突或逻辑不一致。

**触发条件**：
- 新事件与图谱中已有节点产生时间/逻辑冲突
- 用户表述存在明显矛盾
- 时间锚定发现异常

**Tactical Goal 类型**：
| goal_type | 描述 |
|:---|:---|
| `RESOLVE_CONFLICT` | 解决叙事矛盾 |
| `CONFIRM_UNDERSTANDING` | 确认理解正确 |

**示例指令**：

```json
{
  "meta": {
    "version": "1.0.0",
    "timestamp": "2026-02-06T11:00:00Z",
    "instruction_id": "550e8400-e29b-41d4-a716-446655440003",
    "turn_number": 12
  },
  "action": {
    "primary_action": "CLARIFY",
    "tactical_goal": {
      "goal_type": "RESOLVE_CONFLICT",
      "description": "用户提到1980年在上大学，但之前说1978年已毕业，需要澄清时间线"
    },
    "tone_constraint": {
      "primary_tone": "RESPECTFUL_REVERENT",
      "constraints": ["NO_JUDGMENT", "ALLOW_SILENCE"]
    }
  },
  "context": {
    "bridge_type": "ACKNOWLEDGMENT_BRIDGE",
    "suggested_opening": "温和地请用户帮助确认时间线，表达是自己的理解可能有问题"
  }
}
```

---

### 3.4 SUMMARIZE（阶段性总结）

**意图**：在完成一个较大人生阶段（如青年时期）的访谈后，进行阶段性总结，承上启下。

**触发条件**：
- 完成一个人生篇章的所有关键节点
- 用户话题自然结束，适合过渡到下一阶段
- 需要在阶段间进行主题提炼

**Tactical Goal 类型**：
| goal_type | 描述 | NLG 输出意图 |
|:---|:---|:---|
| `REVIEW_PERIOD` | 回顾刚完成的人生阶段 | "咱们回顾一下刚聊的青年时代...接下来聊聊您的成家立业..." |
| `SYNTHESIZE_THEME` | 综合提炼阶段主题 | "这一时期的主题是'奋斗与成长'..." |

**示例指令**：

```json
{
  "meta": {
    "version": "1.0.0",
    "timestamp": "2026-02-06T12:00:00Z",
    "instruction_id": "550e8400-e29b-41d4-a716-446655440004",
    "turn_number": 25
  },
  "action": {
    "primary_action": "SUMMARIZE",
    "tactical_goal": {
      "goal_type": "REVIEW_PERIOD",
      "description": "总结刚完成的青年时期（求学到第一份工作）的几件关键事件",
      "completed_period": "青年时期",
      "next_period": "成家立业时期"
    },
    "tone_constraint": {
      "primary_tone": "THOUGHTFUL",
      "secondary_tone": "ENCOURAGING"
    },
    "target_node": {
      "node_id": "family_career_period",
      "node_type": "life_chapter",
      "label": "成家立业时期"
    }
  },
  "context": {
    "bridge_type": "TEMPORAL_BRIDGE",
    "suggested_opening": "简要总结刚聊的青年时代的关键事件，自然过渡到下一个人生阶段"
  }
}
```

---

### 3.5 PAUSE_SESSION（当天结束，断点续传）

**意图**：识别用户告别意图或精神状态过低，优雅地结束当天访谈，保存断点以便下次继续。

**触发条件**：
- 用户明确表达告别意图（如"今天就到这吧"、"我有点累了"）
- 精神状态 < 0.2（用户明显疲惫）
- 对话轮次超过预设上限（如单次超过50轮）

**Tactical Goal 类型**：
| goal_type | 描述 |
|:---|:---|
| `SESSION_FAREWELL` | 简单回顾当前成果，告知下次继续位置，感谢并收集反馈 |

**NLG 输出意图**：
```
"今天咱们聊了您的童年、求学和第一份工作，收获很大！
下次咱们可以从您结婚的时候接着聊。
今天辛苦您了，还有什么想补充的吗？感谢您的分享！"
```

**示例指令**：

```json
{
  "meta": {
    "version": "1.0.0",
    "timestamp": "2026-02-06T13:00:00Z",
    "instruction_id": "550e8400-e29b-41d4-a716-446655440005",
    "turn_number": 42
  },
  "action": {
    "primary_action": "PAUSE_SESSION",
    "tactical_goal": {
      "goal_type": "SESSION_FAREWELL",
      "description": "简单回顾当前访谈成果，告知下次会从断点继续，感谢并收集反馈"
    },
    "tone_constraint": {
      "primary_tone": "GENTLE_WARM",
      "secondary_tone": "GRATEFUL"
    }
  },
  "checkpoint": {
    "last_discussed_node": "1992_first_job",
    "next_resume_node": "1993_marriage",
    "topics_covered_today": ["童年", "求学", "第一份工作"],
    "coverage_today": 0.35,
    "summary_today": "今天聊了从童年到第一份工作的经历，涵盖了用户早期的成长轨迹"
  },
  "context": {
    "bridge_type": "SUMMARY_BRIDGE",
    "suggested_opening": "表达对本次分享的感谢，说明下次继续的断点位置，询问是否需要补充"
  }
}
```

---

### 3.6 CLOSE_INTERVIEW（全局结束，访谈完成）

**意图**：在访谈完整度足够高后，进行完整总结，询问用户是否需要补充，确认后正式结束整个访谈项目。

**触发条件**：
- 总体覆盖率 ≥ 85%
- 各维度覆盖率均衡（无维度低于 60%）
- 用户明确表示访谈已完成

**Tactical Goal 类型**：
| goal_type | 描述 |
|:---|:---|
| `FINAL_CLOSURE` | 完整总结整个人生访谈，询问是否需要补充，用户同意后结束 |

**NLG 输出意图**：
```
"经过这些访谈，咱们完整走完了您的人生旅程。
我提炼出您的主题是'在漂泊中寻找安宁，在困难中坚持'，
童年、求学、创业、成家...都记录下来了。

请问还有什么想补充的吗？
...（用户确认后）...
感谢您愿意把这些珍贵的回忆留下来，这些故事会很有意义！期待未来能看到它成书。"
```

**示例指令**：

```json
{
  "meta": {
    "version": "1.0.0",
    "timestamp": "2026-02-06T15:00:00Z",
    "instruction_id": "550e8400-e29b-41d4-a716-446655440006",
    "turn_number": 120,
    "session_count": 5
  },
  "action": {
    "primary_action": "CLOSE_INTERVIEW",
    "tactical_goal": {
      "goal_type": "FINAL_CLOSURE",
      "description": "完整总结整个人生访谈，询问是否需要补充，用户同意后结束"
    },
    "tone_constraint": {
      "primary_tone": "RESPECTFUL_REVERENT",
      "secondary_tone": "GRATEFUL"
    }
  },
  "final_state": {
    "overall_coverage": 0.88,
    "theme_summary": "在漂泊中寻找安宁，在困难中坚持",
    "life_chapters_covered": ["童年", "求学", "创业", "成家", "中年奋斗", "晚年反思"],
    "completeness_confirmation_needed": true
  },
  "context": {
    "bridge_type": "THEMATIC_BRIDGE",
    "suggested_opening": "表达完整总结，呈现人生主题，询问补充意愿，最终表达感谢和期待"
  }
}
```

---

## 4. 语气约束详解

### 4.1 Primary Tone 枚举

| tone_code | 中文描述 | 适用场景 |
|:---|:---|:---|
| `EMPATHIC_SUPPORTIVE` | 共情支持型 | 谈论困难、低谷、失败时 |
| `CURIOUS_INQUIRING` | 好奇探索型 | 挖掘新鲜故事时 |
| `RESPECTFUL_REVERENT` | 尊重敬重型 | 谈论长辈、师长、去世亲人时 |
| `CASUAL_CONVERSATIONAL` | 轻松聊天型 | 聊童年趣事、爱好时 |
| `PROFESSIONAL_NEUTRAL` | 专业中立型 | 澄清事实、确认信息时 |
| `GENTLE_WARM` | 温柔温暖型 | 老人疲劳、情绪低落时 |
| `ENCOURAGING` | 鼓励型 | 用户表达自我怀疑时 |

### 4.2 Secondary Tone 枚举

| tone_code | 中文描述 |
|:---|:---|
| `HUMOROUS` | 幽默风趣 |
| `NOSTALGIC` | 怀旧感伤 |
| `THOUGHTFUL` | 沉思反思 |
| `ENERGETIC` | 活力热情 |
| `CALM` | 平静从容 |

### 4.3 Constraints 枚举

| constraint_code | 说明 |
|:---|:---|
| `NO_LEADING_QUESTIONS` | 避免诱导性问题 |
| `NO_JUDGMENT` | 不做价值判断 |
| `ALLOW_SILENCE` | 允许沉默，给用户思考时间 |
| `VALIDATE_FEELINGS` | 肯定和接纳用户情绪 |
| `AVOID_TECHNICAL_TERMS` | 避免专业术语 |

---

## 5. 桥接类型详解

| bridge_type | 描述 | 示例 |
|:---|:---|:---|
| `NONE` | 无需桥接，直接开始 | 新会话开场 |
| `SUMMARY_BRIDGE` | 用总结过渡 | "刚才我们聊了..." |
| `EMOTIONAL_BRIDGE` | 用情绪共鸣过渡 | "我能感受到您那时的..." |
| `THEMATIC_BRIDGE` | 用主题关联过渡 | "说到坚持，您年轻时..." |
| `TEMPORAL_BRIDGE` | 用时间关联过渡 | "在那之后不久..." |
| `CONTRAST_BRIDGE` | 用对比过渡 | "与那次失败不同..." |
| `ACKNOWLEDGMENT_BRIDGE` | 用确认/道歉过渡 | "请允许我确认一下..." |

---

## 6. 实体类型详解

| entity_type | 描述 | 示例 |
|:---|:---|:---|
| `PERSON` | 人物 | "张三"、"母亲"、"王老师" |
| `LOCATION` | 地点 | "上海"、"清华大学"、"老厂房" |
| `TIME` | 时间 | "1990年代"、"那个冬天"、"18岁时" |
| `ORGANIZATION` | 组织机构 | "某部队"、"某公司" |
| `EVENT` | 事件 | "高考"、"南巡讲话"、"文革" |
| `OBJECT` | 物品 | "军功章"、"老照片"、"自行车" |

---

## 7. NLG 模块集成指南

### 7.1 解析流程

```python
def parse_planner_instruction(instruction_json: str) -> dict:
    """
    将 Planner 输出的 JSON 指令解析为 NLG 可用的 Prompt 参数
    """
    import json

    instruction = json.loads(instruction_json)

    # 提取核心信息
    action = instruction["action"]
    context = instruction.get("context", {})
    state = instruction.get("state", {})

    # 构建 Prompt 模板参数
    prompt_params = {
        "action_type": action["primary_action"],
        "goal": action["tactical_goal"]["description"],
        "tone": action["tone_constraint"]["primary_tone"],
        "target_slots": action["tactical_goal"].get("target_slots", []),
        "context_bridge": context.get("context_bridge", ""),
        "bridge_type": context.get("bridge_type", "NONE"),
        "entities": context.get("entities", []),
        "strategy": action.get("strategy", {}).get("strategy_type", ""),
        "current_depth": state.get("coverage_metrics", {}).get("current_depth", 0),
    }

    return prompt_params
```

### 7.2 Prompt 模板示例

```
你是一位专业的人生回忆录访谈者。

当前任务: {action_type}
战术目标: {goal}
语气要求: {tone}
当前挖掘深度: {current_depth}/5

上下文桥接: {context_bridge}
桥接类型: {bridge_type}

关键实体: {entities}

待填充槽位: {target_slots}

策略指引: {strategy}

要求:
1. 使用{tone}的语气进行提问
2. 遵循{bridge_type}桥接方式自然过渡
3. 一次性只问一个核心问题
4. 避免诱导性提问
5. 给用户留出充分的思考空间
```

---

## 8. 版本历史

| 版本 | 日期 | 变更 |
|:---|:---|:---|
| v1.4.0 | 2026-02-06 | 删除 context.context_bridge 字段（与 suggested_opening 重复），审计信息移入 _debug_snapshot.decision_trace |
| v1.3.0 | 2026-02-06 | state 改为内部处理变量，输出 JSON 移除 state 字段，添加可选的 _debug_snapshot |
| v1.2.0 | 2026-02-06 | 用户状态简化为两维度模型（emotional_energy + energy_level） |
| v1.1.0 | 2026-02-06 | 拆分 CLOSE_SESSION 为 PAUSE_SESSION 和 CLOSE_INTERVIEW，明确三种结束场景 |
| v1.0.0 | 2026-02-06 | 初始版本 |

---

## 9. 附录

### 9.1 完整示例：典型访谈流程

#### 轮次1：开场
```json
{
  "action": {
    "primary_action": "DEEP_DIVE",
    "tactical_goal": {
      "goal_type": "EXPLORE_PERIOD",
      "description": "探索用户的童年时期"
    },
    "tone_constraint": {
      "primary_tone": "GENTLE_WARM"
    }
  }
}
```

#### 轮次5-8：深度挖掘童年趣事
```json
{
  "action": {
    "primary_action": "DEEP_DIVE",
    "tactical_goal": {
      "goal_type": "EXTRACT_DETAILS",
      "target_slots": ["时间", "地点", "玩伴", "游戏内容"]
    },
    "strategy": {
      "strategy_type": "EVENT_TO_PERSON"
    }
  }
}
```

#### 轮次9：切换到求学阶段
```json
{
  "action": {
    "primary_action": "BREADTH_SWITCH",
    "tactical_goal": {
      "goal_type": "EXPLORE_PERIOD",
      "description": "探索求学阶段"
    },
    "strategy": {
      "strategy_type": "TEMPORAL_BRIDGE",
      "priority": 2
    }
  },
  "context": {
    "bridge_type": "SUMMARY_BRIDGE"
  }
}
```

#### 轮次25：阶段性总结（青年时期结束）
```json
{
  "action": {
    "primary_action": "SUMMARIZE",
    "tactical_goal": {
      "goal_type": "REVIEW_PERIOD",
      "description": "总结青年时期，准备过渡到成家立业"
    }
  }
}
```

#### 轮次42：当天结束（断点续传）
```json
{
  "action": {
    "primary_action": "PAUSE_SESSION",
    "tactical_goal": {
      "goal_type": "SESSION_FAREWELL",
      "description": "保存断点，告知下次继续"
    }
  },
  "checkpoint": {
    "next_resume_node": "1993_marriage",
    "topics_covered_today": ["童年", "求学", "第一份工作"]
  }
}
```

#### 轮次120：全局结束（访谈完成）
```json
{
  "action": {
    "primary_action": "CLOSE_INTERVIEW",
    "tactical_goal": {
      "goal_type": "FINAL_CLOSURE",
      "description": "完整总结，确认结束"
    }
  },
  "final_state": {
    "overall_coverage": 0.88,
    "theme_summary": "在漂泊中寻找安宁，在困难中坚持"
  }
}
```

### 9.2 错误处理

| 错误场景 | 处理方式 |
|:---|:---|
| JSON 解析失败 | 返回默认指令：DEEP_DIVE + CURIOUS_INQUIRING |
| 必填字段缺失 | 使用默认值填充，记录警告日志 |
| 枚举值无效 | 回退到最保守的选项（如 PROFESSIONAL_NEUTRAL） |
| node_id 不存在 | 清空 target_node，触发 BREADTH_SWITCH |

### 9.3 扩展预留

以下字段预留用于未来扩展：
- `action.experimental_strategy`: 实验性策略
- `_debug_snapshot.predicted_next_topic`: 预测的下一话题
- `meta.experiment_id`: A/B 测试实验标识
