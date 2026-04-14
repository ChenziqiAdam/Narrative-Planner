# 信息权重如何影响 Planner 决策（实现说明）

## 1. 目标与方法

本项目不是仅靠 prompt 调参，而是把 Planner 决策拆解成**可配置、可观测、可实验**的显式评分流程：

1. 从状态中提取信息信号（signals）
2. 用权重对信号做组合评分（scores）
3. 产出四类决策建议（action / focus / slot / theme）
4. 将中间分数写入 debug trace 与评估接口

核心实现文件：
- `src/orchestration/planner_decision_policy.py`
- `src/orchestration/session_orchestrator.py`
- `src/agents/interviewer_agent.py`
- `src/config.py`

---

## 2. 决策入口与执行链路

### 2.1 Orchestrator 中的决策入口

`SessionOrchestrator.process_user_response(...)` 在每轮提问前调用：

- `_build_focus_event_payload(state)`：构建当前焦点事件及缺失槽位
- `_build_generation_hints(...)`：调用 `PlannerDecisionPolicy.evaluate(...)` 计算权重决策结果
- `InterviewerAgent.generate_question(..., generation_hints=...)`：把决策建议注入问句生成

另外，在 action 上做了最小约束：
- 若策略偏向 `next_phase` 且当前无缺槽，允许将模型返回 `continue` 修正为 `next_phase`
- 若策略偏向 `end` 且满足 close 条件，允许收尾

### 2.2 Decision Policy 模块职责

`PlannerDecisionPolicy` 负责：
- 计算信息信号（signals）
- 打分并选择：
  - `preferred_action`（continue / next_phase / end）
  - `preferred_focus`（stay_current_event / switch_new_event / move_to_key_person）
  - `slot_rankings`
  - `theme_rankings`

---

## 3. 权重配置如何注入

### 3.1 默认配置来源

在 `src/config.py` 通过环境变量提供默认值：

- `PLANNER_NEW_INFO_WEIGHT`
- `PLANNER_MISSING_SLOT_WEIGHT`
- `PLANNER_THEME_COVERAGE_WEIGHT`
- `PLANNER_EMOTION_ENERGY_WEIGHT`
- `PLANNER_MEMORY_STABILITY_WEIGHT`
- `PLANNER_CONFLICT_CLARIFICATION_WEIGHT`
- `PLANNER_INFORMATION_QUALITY_WEIGHT`
- `PLANNER_LOW_GAIN_PENALTY`
- `PLANNER_REFLECTION_SLOT_WEIGHT`
- `PLANNER_FACTUAL_SLOT_WEIGHT`

### 3.2 运行时覆盖

`SessionOrchestrator(..., decision_weights={...})` 可按实验变体覆盖默认值。

内部由：
- `PlannerDecisionWeights.from_config(overrides)` 完成默认值 + 覆盖合并

### 3.3 向量输入（外部输入）

现在支持把权重作为**向量**传入：

- `SessionOrchestrator(..., decision_weights=[...])`
- `/api/planner/start` body 传 `decision_weight_vector`

固定顺序（`weight_vector_order`）：
1. `new_info_weight`
2. `missing_slot_weight`
3. `theme_coverage_weight`
4. `emotion_energy_weight`
5. `memory_stability_weight`
6. `conflict_clarification_weight`
7. `information_quality_weight`
8. `low_gain_penalty`
9. `reflection_slot_weight`
10. `factual_slot_weight`

注意：
- 向量长度必须为 10
- 所有值必须是数字
- 系统会在返回里给出 `decision_weight_payload`，包括实际使用的 dict、vector 和顺序

---

## 4. 信息信号（signals）定义

`PlannerDecisionPolicy._compute_signals(...)` 生成以下信号（范围归一到 0~1）：

- `new_info`：新事件/新槽位/新人物信息强度
- `missing_slot`：当前焦点事件缺槽程度
- `theme_undercoverage`：低覆盖主题压力
- `emotion_energy`：低精力或负向情绪强度
- `memory_stability`：记忆主干稳定程度
- `conflict_clarification`：冲突/澄清压力
- `information_quality`：最新信息质量
- `low_gain_penalty`：低增益连击惩罚（结合 low_info_streak 与 fallback_repeat_count）
- `overall_coverage`：会话覆盖度
- `person_gap`：人物信息缺口

关键低增益定义：
- 若 `turn_evaluation.information_gain_score <= 0.08`，判为低增益
- 或抽取事件数=0 且覆盖增量很低且回答很短，也判为低增益

### 4.1 每个信号的具体打分方法

以下实现都在 `src/orchestration/planner_decision_policy.py` 中：

1. `new_info`
- 数据来源：`latest_turn.extraction_result.graph_delta.event_candidates`
- 组成项：
  - `candidate_score = min(1.0, len(candidates) / 2.0)`
  - `slot_novelty = 平均(每个候选事件已填槽位数 / 8)`
  - `people_score = min(1.0, 新人物数 / 3.0)`
- 组合公式：
  - `new_info = clamp01(0.5*candidate_score + 0.35*slot_novelty + 0.15*people_score)`

2. `missing_slot`
- 数据来源：`focus_event_payload.missing_slots`
- 槽位基准分：`time=1.0, location=0.95, people=1.0, event=0.9, cause=0.9, result=0.9, feeling=0.72, reflection=0.72`
- 计算方式：
  - `total = 所有缺失槽位基准分求和`
  - `missing_slot = clamp01(total / max(1.0, len(missing_slots)))`

3. `theme_undercoverage`
- 数据来源：`state.theme_state` 中 `pending/mentioned` 主题
- 计算方式：
  - 按 `completion_ratio` 升序取前 3 个主题
  - `theme_undercoverage = clamp01(平均(1 - completion_ratio))`

4. `emotion_energy`
- 数据来源：`state.memory_capsule.emotional_state`
- 组成项：
  - `low_energy = clamp01(1 - cognitive_energy)`
  - `negative_valence = clamp01(max(0, -valence))`
- 组合公式：
  - `emotion_energy = clamp01(0.6*low_energy + 0.4*negative_valence)`

5. `memory_stability`
- 数据来源：`state.canonical_events`
- 单事件稳定判定：
  - `max(confidence, completeness_score, slot_filled_ratio) >= 0.6` 记为稳定事件
- 组成项：
  - `stable_ratio = 稳定事件数 / 事件总数`
  - `clue_pressure = min(1.0, 未展开线索总数 / 6.0)`
- 组合公式：
  - `memory_stability = clamp01(0.75*stable_ratio + 0.25*(1 - clue_pressure))`

6. `conflict_clarification`
- 数据来源：
  - `memory_capsule.contradictions` 数量
  - `memory_capsule.open_loops` 中 `loop_type == \"conflict\"` 数量
- 公式：
  - `conflict_clarification = clamp01((0.7*contradictions + 0.3*conflict_loops) / 3.0)`

7. `information_quality`
- 有抽取候选事件时：
  - 每个事件取 `max(confidence, completeness_score, slot_density)`
  - 全部候选取平均后 `clamp01`
- 无抽取候选事件时：
  - `information_quality = clamp01(len(answer.strip()) / 120.0)`

8. `low_gain_penalty`
- 数据来源：
  - `low_info_streak`（连续低增益轮次）
  - `fallback_repeat_count`（fallback 重复计数）
- 公式：
  - `low_gain_penalty = clamp01(0.8*(low_info_streak/3.0) + 0.2*min(1.0, fallback_repeat_count/3.0))`

9. `overall_coverage`
- 直接取 `post_overall_coverage` 后做 `clamp01`

10. `person_gap`
- 数据来源：`focus_event_payload`
- 规则：
  - 若 `missing_slots` 包含 `people`，取 `1.0`
  - 否则若 `people_names` 长度 `<=1`，取 `0.45`
  - 否则取 `0.1`

11. `low_info_streak` 判定逻辑（供 `low_gain_penalty` 使用）
- `turn.turn_evaluation.information_gain_score <= 0.08`，判低增益
- 或满足：`extracted_count == 0` 且 `coverage_delta <= 0.005` 且 `answer_len < 40`

---

## 5. 四类决策如何受权重影响

## 5.1 Action 决策（continue / next_phase / end）

通过 `_score_actions(...)` 计算三类分数并取最大值。

- `continue_score` 主要受：
  - `missing_slot_weight`
  - `information_quality_weight`
  - `memory_stability_weight`
  - `new_info_weight`（较小系数）
  - `low_gain_penalty`（负向项）

- `next_phase_score` 主要受：
  - `theme_coverage_weight`
  - `new_info_weight`
  - `conflict_clarification_weight`
  - `emotion_energy_weight`
  - `low_gain_penalty`
  - `memory_stability_weight` 的反向项（主干不稳时更倾向切换）

- `end_score` 主要受：
  - `low_gain_penalty`
  - `emotion_energy_weight`
  - `theme_coverage_weight`（覆盖度高时提高收尾倾向）

并带有 guardrail：
- 覆盖度低时压低 `end_score`
- 低增益不足时压低 `end_score`

## 5.2 Focus 决策（当前事件/新事件/关键人物）

通过 `_score_focus(...)` 计算：

- `stay_current_event`：由 `missing_slot` + `memory_stability` + `information_quality` 驱动
- `switch_new_event`：由 `new_info` + `theme_undercoverage` + `low_gain_penalty` 驱动
- `move_to_key_person`：由 `person_gap` + `new_info` + `theme_undercoverage` 驱动

## 5.3 Slot 决策（槽位排序）

通过 `_rank_slots(...)` 输出 `slot_rankings`。

核心机制：
- 先按槽位基础优先级（time/location/people/event/cause/result/feeling/reflection）
- 再叠加：
  - `missing_slot_weight`
  - 事实槽位权重 `factual_slot_weight`
  - 反思槽位权重 `reflection_slot_weight`
  - 情绪与质量信号（对 `feeling/reflection` 额外加成）
  - 新信息信号（对事实槽位加成）

`InterviewerAgent` 会优先采用 `generation_hints.recommended_slots` 作为本轮补槽顺序。

## 5.4 Theme 决策（主题切换）

通过 `_rank_themes(...)` 输出 `theme_rankings`。

主要受：
- `theme_coverage_weight` × `undercoverage`
- 主题 priority bonus
- `low_gain_penalty` 的促切题加成
- 最近主题惩罚（避免来回抖动）

最终得到 `recommended_theme_id / recommended_theme_title`。

---

## 6. 可观测性：如何解释“为什么这样决策”

每轮 `debug_trace.planning` 新增：

- `decision_weights`
- `decision_signals`
- `decision_scores`（action/focus）
- `preferred_action`
- `preferred_focus`
- `slot_rankings`
- `theme_rankings`
- `recommended_theme_id`
- `recommended_theme_title`

评估接口 `get_evaluation_state()` 新增聚合指标：
- `planner_decision_metrics.action_counts`
- `planner_decision_metrics.phase_switch_count`
- `planner_decision_metrics.repeated_question_count`
- `planner_decision_metrics.low_gain_streak_max`
- `planner_decision_metrics.early_end_count`

---

## 7. 实验配置（A/B）

实验配置目录：`docs/planner-weight-experiments/`

已覆盖四组对比：
- `exp1_missing_slot_vs_new_info.json`
- `exp2_factual_vs_reflection_slot.json`
- `exp3_low_gain_penalty_strength.json`
- `exp4_undercovered_theme_priority.json`

使用方式（示例）：

```python
from src.orchestration import SessionOrchestrator

weights = {
    "missing_slot_weight": 1.5,
    "new_info_weight": 0.8,
}
orchestrator = SessionOrchestrator("exp_run_001", decision_weights=weights)
```

---

## 8. 测试覆盖

与信息权重相关的测试文件：
- `tests/test_generation_hints.py`
- `tests/test_planner_decision_policy.py`

重点验证项：
- 缺槽权重 vs 新信息权重对 focus/action 的影响
- 事实槽位权重 vs 反思槽位权重对 slot 排序的影响
- 低增益惩罚对收尾建议的影响
- 低覆盖主题优先级对 theme 推荐的影响
- hints 中的 decision breakdown 字段存在性

---

## 9. 设计取舍

- 保留 LLM 生成问题能力：权重系统用于“决策控制与提示”，不是完全替代语言生成
- 采用轻约束而非硬覆盖：只在明确策略信号下修正 action，降低行为突变风险
- 通过 debug trace 暴露中间量，便于后续做因果分析和 ablation
