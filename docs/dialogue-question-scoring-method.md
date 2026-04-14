# 对话与提问打分方法说明

## 1. 范围与入口

当前系统里有三类“评分”：

1. **单轮提问质量评分（TurnEvaluation）**
- 代码入口：`src/agents/evaluator_agent.py`
- 数据结构：`src/state/evaluation_models.py`

2. **会话级评分与统计（SessionMetrics）**
- 代码入口：`src/services/coverage_calculator.py`
- 数据结构：`src/state/models.py` 中 `SessionMetrics`

3. **Planner 决策评分（用于决定 continue/next_phase/end 等）**
- 代码入口：`src/orchestration/planner_decision_policy.py`
- 这不是“质量分”，而是“动作选择分”

---

## 2. 单轮提问质量评分（EvaluatorAgent）

每轮在 `EvaluatorAgent.evaluate_turn(...)` 中计算：

- `information_gain_score`
- `non_redundancy_score`
- `slot_targeting_score`
- `emotional_alignment_score`
- `planner_alignment_score`
- 最终 `question_quality_score`

### 2.1 information_gain_score（信息增益）

由两部分构成：

1. 覆盖率增益：
- `coverage_gain = max(post_overall_coverage - pre_overall_coverage, 0.0)`

2. 事件增益：`_event_gain(turn_record)`
- 若无 extraction 或无候选事件，记 0
- 若有候选事件：
  - `average_completeness = 候选事件 completeness_score 的平均`
  - `event_gain = min((候选事件数 * 0.15) + average_completeness * 0.5, 1.0)`

合成：
- `information_gain_score = min(coverage_gain * 4.0 + event_gain, 1.0)`

### 2.2 non_redundancy_score（非重复性）

- 取当前问题与最近最多 2 条历史问题（`recent_transcript(3)[:-1]`）做 `SequenceMatcher` 文本相似度
- `max_similarity = 最大相似度`
- `non_redundancy_score = clamp(1 - max_similarity, 0, 1)`

含义：越像旧问题，分越低。

### 2.3 slot_targeting_score（槽位命中）

- 若本轮没有 target slots，固定返回 `0.7`
- 若有 target slots 但无抽取候选事件，返回 `0.0`
- 否则统计每个目标槽位是否在任意候选事件中“有值”：
  - `people` 槽位判定 `event.people_ids or event.people_names`
  - 其他槽位判定属性值不在 `(None, "", [])`
- `slot_targeting_score = 命中槽位数 / 目标槽位数`

### 2.4 emotional_alignment_score（情绪对齐）

基于 `memory_capsule.emotional_state` 与本轮语气（tone）规则打分：

- 无情绪状态：`0.7`
- 低认知精力（`cognitive_energy < 0.4`）：
  - tone 为 `GENTLE_WARM` => `1.0`，否则 `0.6`
- 负向情绪（`valence < -0.2`）：
  - tone 为 `EMPATHIC_SUPPORTIVE` => `1.0`，否则 `0.55`
- 正向情绪（`valence > 0.2`）：
  - tone 为 `CURIOUS_INQUIRING` => `1.0`，否则 `0.7`
- 其他：
  - tone 在 `{EMPATHIC_SUPPORTIVE, CURIOUS_INQUIRING}` => `0.85`，否则 `0.7`

### 2.5 planner_alignment_score（策略一致性）

用于比较 Planner 计划动作与实际 interviewer action 的一致性。

映射关系：
- `DEEP_DIVE`, `CLARIFY` -> `continue`
- `BREADTH_SWITCH`, `SUMMARIZE`, `PAUSE_SESSION` -> `next_phase`
- `CLOSE_INTERVIEW` -> `end`

打分：
- 一致 => `1.0`
- 不一致 => `0.55`
- 无 planner action => `0.7`

### 2.6 question_quality_score（最终提问质量分）

加权合成：

- `0.30 * information_gain_score`
- `0.25 * non_redundancy_score`
- `0.20 * slot_targeting_score`
- `0.15 * emotional_alignment_score`
- `0.10 * planner_alignment_score`

即：

```text
question_quality_score =
  0.30*information_gain
+ 0.25*non_redundancy
+ 0.20*slot_targeting
+ 0.15*emotional_alignment
+ 0.10*planner_alignment
```

并附加 notes：
- `information_gain_score < 0.4` -> 低信息增益
- `non_redundancy_score < 0.5` -> 可能重复
- 有目标槽位且 `slot_targeting_score < 0.5` -> 槽位推进不足

---

## 3. 会话级评分（CoverageCalculator）

`CoverageCalculator.calculate_session_metrics(...)` 输出 `SessionMetrics`。

### 3.1 平均质量与平均信息增益

- `average_turn_quality = mean(evaluation_trace.question_quality_score)`
- `average_information_gain = mean(evaluation_trace.information_gain_score)`

### 3.2 覆盖类指标

- `overall_theme_coverage`：来自 `graph_manager.calculate_coverage().overall`
- `overall_slot_coverage`：对所有 canonical events 逐槽位统计覆盖率
  - 槽位集合：`time/location/people/event/reflection/cause/result`
- `people_coverage`：
  - `events_with_people_ratio * 0.7 + unique_people_bonus * 0.3`
  - 其中 `unique_people_bonus = min(people_registry数 / event数, 1.0)`

### 3.3 闭环类指标

- `open_loop_closure_rate = resolved_open_loop_count / open_loop_history_total`
- `contradiction_resolution_rate = resolved_contradiction_count / contradiction_history_total`
- 若 total<=0，默认记 `1.0`

---

## 4. Planner 决策评分（与质量评分的关系）

`planner_decision_policy.py` 里的分数用于**控制下一步动作**，不是直接等价于质量分：

- Action 分：`continue / next_phase / end`
- Focus 分：`stay_current_event / switch_new_event / move_to_key_person`
- Slot 排序分：`slot_rankings`
- Theme 排序分：`theme_rankings`

这些分数会影响下一问策略，并写入 `debug_trace.planning`，再由后续轮次通过 `EvaluatorAgent` 间接体现到质量分。

---

## 5. 结果查看位置

1. 单轮评分：
- `turn.turn_evaluation`（接口返回与会话状态里都可见）

2. 会话评分：
- `session_metrics`（包含平均提问质量、平均信息增益）

3. 决策评分追踪：
- `turn.debug_trace.planning`（含 decision_signals/decision_scores/weights）
- `get_evaluation_state()` 的 `planner_decision_metrics`

---

## 6. 注意事项

1. `slot_targeting_score` 在当前统一架构下可能偏保守：
- 因为 `planner_plan` 常为 `None`，没有显式 target slots 时默认 `0.7`

2. `non_redundancy_score` 是字符串相似度，不是语义相似度：
- 对“同义改写”重复的识别能力有限

3. `information_gain_score` 对覆盖率增量与抽取质量敏感：
- extraction 质量会直接影响该分数

