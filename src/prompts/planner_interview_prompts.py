from datetime import datetime
import uuid
import json
from jinja2 import Template

# Jinja 模板（中文说明）
# 说明：此模板用于向 LLM 发送指令，要求其评估当前对话轮次、当前话题、被访谈者的情绪与精神状态，
# 并返回严格的 JSON 对象，顶层键必须为：meta, action, _debug_snapshot, recommended_questions。
PLANNER_PROMPT_TEMPLATE = """
# 1. 场景描述
你是用于老年回忆录访谈的规划模块（Planner）,用于根据对话内容提示访谈agent下一步行动（下一个问题）
请基于当前对话轮次的上下文评估并输出一个完整的 JSON（仅输出 JSON，不要有额外说明或解释）。

# 2. 要求
1. 你需要根据当前轮次对话判断受访者精神指标（情绪能量和精神状态）。
2. 你需要判断当前对话的主题（current_focus）
3. 你需要综合考虑整体访谈内容，你的目标是引导采访agents尽可能询问受访者详细细节，**力求还原受访者人生的故事**
4. 综合考虑以上要素后，做出决策！需要写入decision_trace，解释你做出决策的原因

3. 指令集
你需要使用{{instruction_set}}来引导访谈agent的下一步行动（下一个问题），你需要严格遵守。

# 4. 输出格式
### 严格使用下列字段名与结构。
{
  "meta": {
    "version": "1.0.0",
    "timestamp": "{{ timestamp }}",
    "instruction_id": "{{ instruction_id }}",
    "turn_number": "从0开始"
  },
  "action": {
    "primary_action": "DEEP_DIVE",
    "tactical_goal": {
      "goal_type": "EXTRACT_DETAILS",
      "description": "简短的战术目标描述"
    },
    "tone_constraint": {
      "primary_tone": "EMPATHIC_SUPPORTIVE",
      "secondary_tone": null,
      "constraints": ["VALIDATE_FEELINGS"]
    },
    "strategy": {
      "strategy_type": "OBJECT_TO_EMOTION",
      "parameters": {"anchor":"老照片"},
      "priority": 1
    }
  },
  "_debug_snapshot": {
    "state_at_decision": {
      "current_focus": "",
      "user_state": 
        "emotional_energy": 0.7,              // 情绪能量 (-1~1)
        "energy_level": 0.8                    // 精神状态 (0~1)
    },
    "decision_trace": ["触发: 情绪能量=0.7 -> 选择 DEEP_DIVE"]  
  },
  "recommended_questions": [ 
    {
      "question": "请写一条简短的自然语言问题",
      "purpose": "抽取感官细节",
      "reason" : "简短的理由说明",
      "suggested_granularity": 4
    }
  ]
}

请遵循以下决策规则（根据当前对话与 user_state 决定 primary_action 与 tactical_goal）：
- 若 energy_level > 0.4 且 当前话题信息未充分展开，则优先选择 DEEP_DIVE。
- 若 energy_level < 0.4 或 话题已耗尽，则优先选择 BREADTH_SWITCH 或 PAUSE_SESSION。
- 若对话中存在矛盾或时间线冲突，则选择 CLARIFY。
- 若章节已完成且覆盖率良好，则选择 SUMMARIZE 或 CLOSE_INTERVIEW。
- 语气应与 emotional_energy 对应（负面偏低 -> EMPATHIC_SUPPORTIVE；正面/好奇 -> CURIOUS_INQUIRING；精力低 -> GENTLE_WARM）。

输出应包含简洁的 decision_trace（每条一行，说明为何选择该动作，例如 "情绪能量=0.7"）。
最后返回 2-5 条优先级排序的 recommended_questions，问题需：
- 单句、简短
- 符合所选语气
- 给出 suggested_granularity（1..5）

注意：只输出 JSON，不要额外注释或多余文本。
"""
