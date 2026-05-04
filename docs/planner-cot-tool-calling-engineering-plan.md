# Planner COT Workflow and Tool Calling Engineering Plan

## 1. 背景

当前 Planner 版访谈已经具备 GraphRAG 上下文、图谱抽取、主题覆盖度、动态画像和评价指标，但下一问的核心决策仍主要发生在 `InterviewerAgent` 的一次 LLM 调用内部。

现状可以概括为：

```text
受访者回答
  -> HybridRetriever 检索
  -> GraphExtractionAgent 抽取事件/人物/地点/情绪
  -> GraphWriter 写入 Neo4j
  -> GraphRAGDecisionContextBuilder 构造决策上下文
  -> InterviewerAgent 直接生成 action + question
```

问题是：系统给了 LLM 一些上下文，但没有明确规范 LLM 的 Planner 工作流，也没有把关键决策依据结构化记录下来。因此调试时很难判断：

- 为什么这一轮深挖，而不是跳转？
- 为什么突然进入工作主题？
- 当前事件到底是否完整？
- 信息增益、情绪能量、主题覆盖和图谱缺口分别对决策产生了多大影响？

本方案目标是：不恢复旧的硬编码槽位决策机制，而是在保留 LLM 自主权的前提下，规范它的内部分析流程、允许它按需调用工具，并输出可观测的结构化决策摘要。

## 2. 设计原则

1. 不把深挖、跳转、澄清写成死规则。
2. 不要求模型输出完整自由文本思维链。
3. 允许模型在内部按步骤分析，但只保存结构化的 `planner_plan`。
4. 工具提供证据，LLM 负责综合判断。
5. 工程层负责限制工具范围、调用轮数、输出 schema 和日志记录。
6. 优先控制延迟，第一阶段不拆成两个 LLM agent。
7. 保留未来拆分 `PlannerDecisionAgent` 的接口空间。

## 3. 分支经验对比

### 3.1 anoversion 的工具调用

`anoversion` 分支主要使用 CAMEL：

- `tools/elder_tools.py` 使用 `FunctionTool` 包装老人记忆工具。
- `BaseAgent` 初始化 `ChatAgent(system_message, model, tools=tools)`。
- `IntervieweeAgent` 把记忆工具交给 CAMEL，由 CAMEL 内部处理工具调用。
- `PlannerAgent` 架构上支持传入 `tools`，但仿真脚本里实际初始化 Planner 时没有接入工具。
- Planner prompt 要求输出 `action`、`_debug_snapshot.decision_trace` 和 `recommended_questions`。

可借鉴点：

- Planner 输出结构化决策对象，而不是直接只输出问题。
- action / tactical_goal / tone / strategy 的分层设计有助于调试。
- `decision_trace` 的想法是正确的，但应改成简短决策摘要，而不是暴露完整链式推理。

不足：

- CAMEL 封装较黑箱，不利于精确记录工具调用过程。
- Planner 工具调用没有真正落地。
- Planner 和 Interviewer 两次 LLM 调用会带来明显延迟。

### 3.2 当前分支的工具调用

当前分支的 `IntervieweeAgent` 已经实现了更透明的 OpenAI function-calling loop：

```text
发送 messages + tools
  -> 模型返回 tool_calls
  -> 代码执行本地 callable
  -> 追加 role=tool 的结果
  -> 再次请求模型
  -> 直到模型输出最终文本
```

可借鉴点：

- 工具 schema 和 callable 分离，便于维护。
- 每次工具调用可以记录 `tool_calls_log`。
- 工具失败可以降级，不必打断整轮对话。
- 适合迁移到 `InterviewerAgent`。

因此，推荐基于当前分支的 OpenAI function-calling 实现继续扩展，而不是回到 CAMEL。

## 4. 是否单独建立 PlannerDecisionAgent

### 4.1 两个 agent 的延迟问题

如果拆成：

```text
PlannerDecisionAgent 生成 QuestionPlan
InterviewerAgent 根据 QuestionPlan 生成自然问题
```

每轮至少增加一次 LLM 调用。当前自动访谈窗口中，这通常会让延迟接近 1.7-2.5 倍。如果 Planner 再调用工具，延迟会进一步增加。

### 4.2 第一阶段推荐：一体化 InterviewerAgent

第一阶段建议保持单 LLM agent：

```text
InterviewerAgent
  -> 内部按 Planner 工作流分析
  -> 必要时调用工具
  -> 输出 planner_plan + action + question
```

这样可以：

- 不增加固定的第二次 LLM 调用。
- 保留 LLM 对深挖/跳转/澄清的自主判断。
- 通过 `planner_plan` 暴露结构化决策摘要。
- 未来如果效果需要，再把 `planner_plan` 生成逻辑拆成独立 `PlannerDecisionAgent`。

### 4.3 何时再拆 agent

满足以下情况时，再考虑拆分：

- 需要固定同一个 Interviewer 表达层，对比不同 Planner 策略。
- Planner 工具调用变复杂，需要独立调试。
- 需要让 Planner 输出多个候选计划，再由 Interviewer 润色。
- 发现一体化 agent 经常违背自己的计划。
- 研究上需要严格区分“决策质量”和“语言表达质量”。

## 5. COT 工作流设计

这里的 COT 不指输出完整思维链，而是指系统提示词中明确要求模型在内部按步骤完成规划。

建议在 `InterviewerAgent` 的 system prompt 中加入：

```text
在生成下一问前，你需要在内部完成以下规划流程：

1. 语义理解
   判断受访者刚才主要讲了什么，属于人生阶段、事件、人物、地点、价值观还是情绪表达。

2. 访谈阶段判断
   判断当前是否仍处于前 5-10 轮的人生脉络梳理阶段。
   如果是，不要因为背景信息或单个关键词过早深挖具体职业/家庭/地点。

3. 当前事件完整度判断
   评估当前叙事是否具备时间、地点、人物、经过、原因、结果、感受、反思。
   识别缺失或较弱的维度。

4. 情绪与精力判断
   判断情绪能量、认知负担、是否需要先共情承接。

5. 图谱和主题判断
   必要时查询主题覆盖、当前焦点、关联人物/地点、开放线索或冲突。

6. 候选动作比较
   比较 continue_life_overview、deep_dive_event、clarify、confirm_summary、
   switch_theme、move_to_person、move_to_period、gentle_reflection、end。

7. 下一问计划
   选择 action、focus、slot_or_angle、tone、question_intent。

不要输出完整分析过程。
只输出结构化 planner_plan、action 和 question。
```

## 6. 输出结构

建议把当前输出从：

```json
{
  "action": "continue",
  "question": "..."
}
```

扩展为：

```json
{
  "planner_plan": {
    "stage": "life_overview",
    "selected_action": "continue_life_overview",
    "focus": {
      "type": "life_period",
      "label": "早年经历"
    },
    "event_completeness": {
      "score": 0.35,
      "missing_dimensions": ["people", "daily_scene", "feeling"],
      "reason_summary": "目前只有粗略时间和地点线索，人生阶段还未铺开"
    },
    "theme_pressure": [
      {
        "theme_id": "childhood",
        "coverage": 0.12,
        "priority": 0.8
      }
    ],
    "emotion_signal": {
      "energy": 0.5,
      "valence": "neutral",
      "support_needed": false
    },
    "candidate_actions": [
      {
        "action": "continue_life_overview",
        "score": 0.84,
        "reason_summary": "访谈早期，应先建立人生脉络"
      },
      {
        "action": "deep_dive_event",
        "score": 0.42,
        "reason_summary": "当前事件有细节空间，但过早深挖会缩窄范围"
      }
    ],
    "selected_slot_or_angle": "life_timeline",
    "tone": "respectful_warm",
    "question_intent": "邀请老人继续铺开早年生活脉络"
  },
  "action": "continue",
  "question": "您小时候家里和周围的生活，大概是什么样子的？"
}
```

说明：

- `planner_plan` 用于调试、评估和前端展示。
- `question` 是真正发给受访者的问题。
- `reason_summary` 只保存简短依据，不保存完整思维链。
- `selected_action` 是研究用细粒度动作。
- 顶层 `action` 保留兼容当前 UI 和后端流程。

## 7. 工具调用设计

### 7.1 工具调用策略

工具调用放在同一个 `InterviewerAgent` 内部，不需要单独 agent。

```text
InterviewerAgent 第一次请求模型
  -> 模型决定是否调用工具
  -> 后端执行工具
  -> 工具结果回灌给模型
  -> 模型输出 planner_plan + question
```

约束：

- `tool_choice="auto"`
- `max_tool_rounds=2`
- 每轮最多接受 2 个工具调用
- 工具失败返回 `{ "error": "..." }`，不直接中断
- 所有工具调用进入 `tool_trace`
- 对比实验中可以关闭工具调用，形成 ablation

### 7.2 第一批工具

建议第一批工具控制在 6 个以内：

#### get_theme_coverage

返回整体主题覆盖和欠覆盖主题。

用途：

- 判断是否需要跳转。
- 判断当前是否仍应做人生脉络梳理。

#### get_current_focus_snapshot

返回当前焦点事件/人物/地点/人生阶段，以及最近几轮摘要。

用途：

- 防止突然跳题。
- 帮助判断当前事件是否还值得追问。

#### assess_event_completeness

返回当前事件完整度：

```json
{
  "score": 0.48,
  "filled_dimensions": ["time", "people"],
  "missing_dimensions": ["location", "result", "emotion"],
  "weak_dimensions": ["cause"],
  "recommended_probe_dimensions": ["emotion", "result"]
}
```

用途：

- 帮助 LLM 判断深挖、澄清还是总结确认。
- 不是硬规则，只是证据。

#### retrieve_related_context

基于自然语言 query 检索相关记忆、图谱片段和历史上下文。

用途：

- 当 LLM 想确认某个人物、地点、主题或早前线索时使用。

#### get_entity_context

查询某个图谱实体的 N-hop 邻域。

用途：

- 从事件跳到人物。
- 从地点跳到另一段经历。
- 查询关联主题。

#### detect_open_loops_and_conflicts

返回未展开线索、潜在矛盾、时间冲突或人物混淆。

用途：

- 触发 `clarify` 或 `confirm_summary`。

### 7.3 可后置的工具

以下工具可以第二阶段再补：

- `estimate_emotion_state`
- `get_recent_question_quality`
- `get_dynamic_profile_hint`
- `get_cross_session_open_loops`

## 8. 工程实施阶段

### Phase 1: COT 提示词 + planner_plan

目标：不接工具，先让 LLM 输出结构化决策摘要。

改动：

- 更新 `InterviewerAgent` system prompt 和 user prompt。
- 扩展 `_parse_response`，兼容 `planner_plan`。
- 在 `SessionOrchestrator.process_user_response` 中把 `planner_plan` 写入 `debug_trace`。
- 保持顶层 `action` 和 `question` 兼容。

验收：

- 自动对话正常运行。
- 前 5-10 轮更倾向人生脉络梳理。
- 每轮可以看到 `planner_plan`。
- 没有额外 LLM 调用。

### Phase 2: 工具调用循环

目标：把 `IntervieweeAgent` 的 tool loop 思路迁移到 `InterviewerAgent`。

改动：

- 新增 `_create_completion_with_tools` 或通用 `ToolCallingLoop`。
- 给 `InterviewerAgent` 注册 Planner 工具 schemas 和 callables。
- 记录 `tool_trace`。
- 加入最大调用轮数和工具失败降级。

验收：

- 模型可以主动调用工具。
- 工具结果能影响最终 `planner_plan`。
- 工具调用日志可在 `debug_trace` 查看。
- 工具不可用时仍能生成问题。

### Phase 3: Planner 专用工具

目标：补齐事件完整度、焦点快照、主题覆盖、开放线索工具。

优先实现：

- `src/tools/planner_tools.py`
- `PlannerToolSystem`
- `get_planner_tool_schemas()`
- `get_planner_tool_callables()`

验收：

- 工具返回结构稳定、短小、适合 LLM 消化。
- 不暴露大量原始图谱数据。
- Neo4j 不可用时返回 fallback。

### Phase 4: 前端展示和实验

目标：在对比调试窗口展示决策摘要。

改动：

- `planner_plan` 展示为 tooltip 或折叠面板。
- 显示 `selected_action`、`stage`、`event_completeness.score`、`selected_slot_or_angle`。
- `tool_trace` 显示工具名称、参数和简短结果。

实验组：

```text
A. 当前 GraphRAG prompt-only
B. COT 工作流 + planner_plan，无工具
C. COT 工作流 + planner_plan + 工具调用
D. 工具调用关闭/开启的 ablation
```

## 9. 延迟控制

第一阶段不增加固定 LLM 调用。

第二阶段工具调用可能增加延迟，因此需要：

- 默认最多 2 轮工具调用。
- 默认最多 2 个工具/轮。
- 工具结果严格截断。
- 工具 schema 描述保持简短，减少 token。
- 对低价值轮次允许模型不调用工具。
- 在 debug trace 中记录：

```text
planner_llm_ms
planner_tool_ms
planner_tool_rounds
planner_tool_count
```

如果工具调用导致交互明显变慢，可以增加配置：

```text
PLANNER_TOOLS_ENABLED=true|false
PLANNER_MAX_TOOL_ROUNDS=0|1|2
PLANNER_TOOL_MODE=off|light|full
```

## 10. 评估指标

需要重点检查：

- 前 5-10 轮人生脉络梳理完成度
- 过早深挖率
- 跳转突兀率
- 事件完整度提升
- 主题覆盖提升
- 平均信息增益
- 问题重复率
- 问题自然度
- 情绪承接质量
- 工具调用次数
- 工具调用是否改变最终 action
- 工具调用延迟

建议新增派生指标：

```text
life_overview_progress
premature_deep_dive_rate
abrupt_switch_rate
event_completeness_delta
tool_influence_rate
planner_plan_parse_success_rate
```

## 11. 风险与缓解

### 风险 1: 模型输出 planner_plan 但问题不遵守 plan

缓解：

- 在 prompt 中明确 `question` 必须服务于 `planner_plan.question_intent`。
- 在 evaluator 中检查 plan-question alignment。

### 风险 2: planner_plan 变成空泛解释

缓解：

- 限制 `reason_summary` 长度。
- 要求 candidate_actions 至少两个。
- 要求每个 score 必须是 0-1 数字。

### 风险 3: 工具调用过多导致延迟

缓解：

- 限制工具轮数。
- 默认 light mode。
- 在早期人生脉络阶段只开放主题覆盖和焦点快照工具。

### 风险 4: 模型依赖工具但工具不可用

缓解：

- 工具失败返回结构化错误。
- prompt 要求工具不可用时基于已有上下文继续。

### 风险 5: 重新滑向硬编码槽位

缓解：

- `assess_event_completeness` 只返回证据，不直接返回 action。
- action 仍由 LLM 选择。
- 保留 candidate action score，便于分析而非强制。

## 12. 推荐落地顺序

推荐最小可行路径：

```text
1. 扩展 InterviewerAgent 输出 planner_plan
2. debug_trace 记录 planner_plan
3. 前端显示 planner_plan
4. 加入工具调用循环，但先只接 get_theme_coverage / get_current_focus_snapshot
5. 再补 assess_event_completeness
6. 做 prompt-only vs tool-calling 对比实验
```

第一版不要立即拆 `PlannerDecisionAgent`。等一体化方案验证有效后，再根据延迟、可解释性和实验需求决定是否拆分。

## 13. 外部最佳实践参考

OpenAI 官方文档建议：

- 工具调用适合让模型连接应用提供的数据和动作；调用流程是模型请求工具、应用执行工具、再把工具结果回传给模型。
- 结构化输出适合约束模型最终响应符合 JSON Schema。
- 工具 schema 会计入上下文 token，应控制工具数量和参数描述长度。

参考：

- Function calling: https://platform.openai.com/docs/guides/function-calling?api-mode=chat
- Structured Outputs: https://platform.openai.com/docs/guides/structured-outputs?api-mode=chat

