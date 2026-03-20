# Planner 多 Agent 工程落地路线图

状态: draft v0.1

关联文档:

- [planner-multi-agent-architecture.md](planner-multi-agent-architecture.md)
- [planner-instruction-standard.md](planner-instruction-standard.md)

## 1. 文档目标

本路线图用于把多 Agent 架构草案落成可执行工程方案，覆盖:

- 模块拆分与代码边界
- 开发阶段与里程碑
- 团队分工与协作接口
- 测试与效果评估方案
- 风险控制与上线策略

## 2. 当前现状判断

结合当前代码库，现阶段有三个重要现实约束:

### 2.1 compare 模式里的 planner 还不是完整 planner

当前 compare 主链路中，planner 模式本质仍然是:

- 同步事件提取
- 同步图谱更新
- 最后调用 baseline interviewer 继续提问

这意味着:

- 图谱尚未真正驱动下一问
- planner 还未形成独立决策层
- 提取流程仍占用关键路径延迟

### 2.2 已存在两个方向不同的实现分支

- `PlannerInterviewAgent` 路线:
  - 适合 compare 模式快速验证
  - 但耦合较高
- `StreamingInterviewEngine` 路线:
  - 更接近长期可维护架构
  - 已具备异步提取思路

工程上建议:

- 短期保留 compare UI
- 中期逐步把主编排迁移到 `StreamingInterviewEngine` 风格的 orchestrator

### 2.3 图谱存在，记忆层缺失，评测层尚未独立

当前已有:

- `ThemeNode`
- `EventNode`
- `GraphManager`
- `EventExtractor`

当前缺失:

- `SessionState` 统一状态层
- `MemoryCapsule` 规划上下文层
- `TurnEvaluation` 与 `SessionEvaluation`
- `PeopleNode` 真正写入链路
- 归并与冲突消解代码路径

## 3. 目标架构与落地原则

## 3.1 目标运行形态

一轮对话的标准链路应为:

1. 用户回答进入 `SessionState`
2. 读取上一轮已提交的 `memory capsule + graph summary`
3. `PlannerAgent` 输出结构化 `QuestionPlan`
4. `InterviewerAgent` 把计划转成自然问题
5. 立刻返回问题给前端
6. 后台异步执行:
   - `ExtractionAgent`
   - `MergeEngine`
   - `GraphProjector`
   - `MemoryProjector`
   - `EvaluatorAgent`

## 3.2 工程原则

- 同步主路径最多保留 `1-2` 次 LLM 调用
- 结构化归并优先走代码，不优先走 LLM
- 基线版和 planner 版共享同一 interviewee simulator 与 evaluator
- 数据结构先冻结，再做多模块改造
- 每个阶段都要可运行、可回滚、可测量

## 4. 模块落地拆分

## 4.1 状态层

建议新增目录:

```text
src/state/
  models.py
  session_state.py
  planner_context.py
  evaluation_models.py
```

职责:

- 冻结 `SessionState`
- 定义 `TurnRecord`
- 定义 `MemoryCapsule`
- 定义 `QuestionPlan`
- 定义 `ExtractionResult`
- 定义 `TurnEvaluation`

验收标准:

- 所有上层服务只通过状态模型传递核心数据
- compare、planner、evaluator 不再各自定义一套临时 dict

## 4.2 编排层

建议新增目录:

```text
src/orchestration/
  session_orchestrator.py
  state_store.py
  background_jobs.py
```

职责:

- 管一轮对话的主顺序
- 管异步任务提交与状态回写
- 保证热路径和冷路径边界稳定

验收标准:

- `PlannerInterviewAgent` 不再直接承担所有职责
- 能单测一轮编排，不依赖前端

## 4.3 Agent 层

建议新增目录:

```text
src/agents/
  planner_agent.py
  interviewer_agent.py
  extraction_agent.py
  evaluator_agent.py
```

职责边界:

- `planner_agent.py`: 输入 `PlannerContext`，输出 `QuestionPlan`
- `interviewer_agent.py`: 输入 `QuestionPlan`，输出最终问题
- `extraction_agent.py`: 输入 turn 和上下文，输出三层提取结果
- `evaluator_agent.py`: 输出回合分与会话分

验收标准:

- Agent 输出必须结构化
- 每个 Agent 都可以单独回放测试

## 4.4 服务层

建议新增目录:

```text
src/services/
  merge_engine.py
  graph_projector.py
  memory_projector.py
  coverage_calculator.py
  summarizer.py
```

职责:

- `merge_engine.py`: 事件归并、人物归并、冲突检测
- `graph_projector.py`: 写入 Theme/Event/People 图谱
- `memory_projector.py`: 生成 memory capsule
- `coverage_calculator.py`: 统一覆盖率与完成度指标

验收标准:

- 核心指标不再分散在多个 agent 内部随意计算
- 图谱和记忆来自同一 canonical state

## 4.5 适配层

建议新增目录:

```text
src/adapters/
  llm_client.py
  persistence.py
  websocket_broadcaster.py
```

职责:

- 隔离 OpenAI SDK
- 隔离存储方案
- 隔离 compare UI 和 dashboard 推送

验收标准:

- 上层逻辑不直接散落调用 OpenAI client
- 后续切模型、切缓存、切持久化不需要改业务核心

## 5. 推荐开发组织方式

## 5.1 建议工作流

采用四条并行工作流，但以状态契约先行:

### 工作流 A: 状态与编排

负责人:

- 总工/后端主程

交付:

- `SessionState`
- `Orchestrator`
- `StateStore`

依赖:

- 无，优先开始

### 工作流 B: 提取与归并

负责人:

- LLM 工程 + 算法工程

交付:

- `ExtractionAgent`
- `MergeEngine`
- `People merge`
- `existing_events` 回注 extractor

依赖:

- 依赖工作流 A 的状态结构

### 工作流 C: Planner 与 Interviewer

负责人:

- Prompt/Agent 工程

交付:

- `PlannerContext`
- `QuestionPlan`
- `PlannerAgent`
- `InterviewerAgent`

依赖:

- 依赖工作流 A 的状态结构
- 可先用 mock graph summary 开发

### 工作流 D: Evaluator 与实验框架

负责人:

- 评测工程 + 数据分析

交付:

- `TurnEvaluation`
- `SessionEvaluation`
- compare 实验协议
- A/B 报告模板

依赖:

- 依赖工作流 A 的 turn/session schema

## 5.2 推荐分支策略

- `main`: 稳定主线
- `feat/session-state`
- `feat/extraction-merge`
- `feat/planner-runtime`
- `feat/evaluator`
- `feat/compare-harness`

合并顺序:

1. `session-state`
2. `extraction-merge`
3. `planner-runtime`
4. `evaluator`
5. `compare-harness`

## 6. 分阶段工程里程碑

## 6.1 M0: 契约冻结

目标:

- 冻结状态模型和接口边界

产出:

- `src/state/models.py`
- `src/state/evaluation_models.py`
- `docs/planner-engineering-roadmap.md`

验收:

- 所有核心对象有明确字段定义
- 团队不再新增随意格式 dict

## 6.2 M1: SessionState 与 Orchestrator 骨架

目标:

- 建立统一状态层和最小可运行编排

产出:

- `SessionStateStore`
- `SessionOrchestrator`
- compare 模式能跑通 transcript 和 state 写入

验收:

- 单轮对话不丢 turn 数据
- 同一 session 可重放

## 6.3 M2: PlannerContext 与问题生成重构

目标:

- planner 模式不再直接复用 baseline 提问

产出:

- `PlannerAgent`
- `InterviewerAgent`
- `QuestionPlan`

验收:

- planner 模式下一问来自 planner runtime
- baseline 模式仍然可运行

## 6.4 M3: 异步提取与归并

目标:

- 事件提取离开关键路径
- 建立 canonical event merge

产出:

- `ExtractionAgent`
- `MergeEngine`
- `GraphProjector`
- `MemoryProjector`

验收:

- 同步路径不等待图谱提取完成
- 图谱可在下一轮前完成更新
- 可区分 create/update/merge

## 6.5 M4: Evaluator 上线

目标:

- 建立每轮与整局评测能力

产出:

- `EvaluatorAgent`
- `TurnEvaluation`
- `SessionMetrics`
- compare 报告生成

验收:

- 每轮都有 question quality score
- 会话结束能产出覆盖率与效果总评

## 6.6 M5: 实验化 compare

目标:

- baseline vs planner 做公平对比

产出:

- 统一 simulator
- 统一 evaluator
- 自动批量跑样本集

验收:

- 可批量跑 A/B
- 有稳定的 latency、coverage、quality 对比结果

## 7. 效果测试方案

## 7.1 测试分层

### A. 单元测试

测试对象:

- `CoverageCalculator`
- `MergeEngine`
- `MemoryProjector`
- `GraphProjector`

重点:

- 事件更新是否正确
- people merge 是否稳定
- slot coverage 计算是否一致

### B. 契约测试

测试对象:

- `PlannerContext`
- `QuestionPlan`
- `ExtractionResult`
- `TurnEvaluation`

重点:

- schema 不漂移
- 关键字段不会缺失

### C. Agent 回放测试

测试对象:

- `PlannerAgent`
- `InterviewerAgent`
- `ExtractionAgent`
- `EvaluatorAgent`

重点:

- 输入固定时输出结构稳定
- planner 动作是否符合预期

### D. 编排集成测试

测试对象:

- `SessionOrchestrator`

重点:

- 一轮热路径是否稳定
- 后台任务是否能正确回写状态
- state 是否可恢复

### E. compare 仿真测试

测试对象:

- baseline 与 planner 整体流程

重点:

- 相同受访者配置下，两边是否公平
- planner 是否真正提升信息增益与覆盖率

## 7.2 效果指标

### 每轮指标

- `question_quality_score`
- `information_gain_score`
- `non_redundancy_score`
- `slot_targeting_score`
- `emotional_alignment_score`
- `planner_alignment_score`

### 会话指标

- `theme_coverage`
- `slot_coverage`
- `people_coverage`
- `open_loop_closure_rate`
- `contradiction_resolution_rate`
- `avg_turn_quality`

### 工程指标

- `p50_turn_latency`
- `p95_turn_latency`
- `background_job_delay`
- `graph_update_lag`
- `failed_extraction_rate`

## 7.3 验证样本设计

至少建立三类样本:

### 样本 A: 高结构化受访者

特点:

- 时间线明确
- 回答完整

目标:

- 验证 planner 能否有效深挖

### 样本 B: 低结构化受访者

特点:

- 跳时空
- 省略主语
- 事件碎片化

目标:

- 验证 merge、clarify、memory capsule 是否工作

### 样本 C: 高情绪负载受访者

特点:

- 有创伤、损失、遗憾

目标:

- 验证 tone control 和 pause/clarify/summarize 策略

## 7.4 A/B 实验设计

固定:

- 同一 elder profile
- 同一 interviewee simulator
- 同一 evaluator
- 同一最大轮数

变化:

- baseline: 只读 transcript
- planner: 读 transcript + memory capsule + graph summary

成功标准:

- planner 平均信息增益高于 baseline
- planner 覆盖率高于 baseline
- planner 的重复问法低于 baseline
- planner 延迟增长控制在可接受预算内

## 8. 延迟预算与性能策略

## 8.1 建议延迟预算

用户可感知主路径建议目标:

- `p50 <= 2.5s`
- `p95 <= 5.0s`

后台任务建议目标:

- extraction 完成: `<= 6s`
- merge + projection: `<= 500ms`
- evaluation 完成: `<= 6s`

## 8.2 优化策略

- planner 优先读取上一次已提交状态，而不是等待本轮抽取结果
- 提取结果统一批处理回写
- 归并优先使用规则和相似度，不默认二次 LLM 判断
- question generation 与 extraction 分离

## 9. 风险清单

## 9.1 架构风险

风险:

- Agent 过多导致延迟过高

应对:

- 逻辑 Agent 和物理 LLM 调用解耦
- 允许 planner + interviewer 融合为一次调用

## 9.2 数据风险

风险:

- 图谱、记忆、评测各自维护状态，最终不一致

应对:

- 强制统一 `SessionState`
- graph 和 memory 只做投影，不做独立真相

## 9.3 评测风险

风险:

- baseline 和 planner 的 interviewee simulator 不同，导致结论失真

应对:

- compare 实验时强制共享同一 simulator 和 evaluator

## 9.4 Prompt 风险

风险:

- planner 输出不稳定，导致 interviewer 无法消费

应对:

- 强制结构化输出
- 加 schema 校验与回退机制

## 10. Definition of Done

达到以下条件，认为多 Agent 架构完成第一阶段落地:

- planner 模式已不再调用 baseline 生成下一问
- `SessionState` 成为唯一状态源
- extraction/merge/evaluation 已脱离关键路径
- compare 模式支持统一仿真与统一评测
- dashboard 展示 graph summary 与核心 coverage
- 可生成 baseline vs planner 的实验报告

## 11. 推荐近期执行顺序

如果只做最近两周的高价值推进，建议按以下顺序:

1. 冻结 `SessionState` 和 `QuestionPlan` schema
2. 实现 `SessionOrchestrator` 骨架
3. 把 planner 模式的“下一问”从 baseline 中剥离
4. 给 extractor 补上 `existing_events` 输入
5. 接入 `MergeEngine` 最小版
6. 增加 `MemoryCapsule`
7. 接入 `TurnEvaluation`
8. 最后再补 PeopleNode 和更复杂图谱关系

## 12. 推荐向团队同步的话术

可直接对内同步为:

"我们这次不是做一个更复杂的 prompt，而是把访谈系统拆成统一状态驱动的多 Agent 运行时。图谱负责全局结构，记忆负责局部可读上下文，评测负责判断每一轮提问是否真正提高了信息增益。工程上我们会先冻结状态契约，再把 planner 从 baseline interviewer 中剥离，最后把提取和评测移到异步后台，确保质量提升的同时不把交互延迟做坏。"
