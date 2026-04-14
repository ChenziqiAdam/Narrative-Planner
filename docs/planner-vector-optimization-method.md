# Planner 向量优化：评分与分析方法

## 1. 目标

给定 `M` 组权重向量，每组运行 `N` 轮对话（可重复 `R` 次），得到每组评分分布，最终选出最优向量。

## 2. 文件与脚本

- 批量优化脚本：`scripts/run_planner_vector_optimization.py`
- 历史结果打分脚本：`scripts/score_conversation_results.py`
- 结果评分器：`src/services/conversation_result_scorer.py`
- LLM 总评分 Agent：`src/agents/conversation_scorer_agent.py`
- 向量样例：`docs/planner-weight-experiments/vector_groups.sample.json`

## 3. 输入格式

`vectors-file` 结构：

```json
{
  "elder_info": {...},
  "vectors": [
    {"name": "v1", "vector": [ ... 10维 ... ]},
    {"name": "v2", "vector": [ ... 10维 ... ]}
  ]
}
```

10维顺序：
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

## 4. 评分方法（每次 run）

### 4.1 确定性评分（Deterministic）

从 `planner_state_*.json` 提取：
- `average_turn_quality`
- `average_information_gain`
- `overall_theme_coverage`
- 平均槽位覆盖率
- `people_coverage`
- `evaluation_trace` 的 `non_redundancy_score`
- 低增益比例（`information_gain_score <= 0.08`）
- action 分布（continue/next_phase/end）

子分项：
- `information_effectiveness`
- `structure_coverage`
- `action_balance`
- `efficiency`

合成：

```text
deterministic =
  0.40*information_effectiveness
+ 0.35*structure_coverage
+ 0.15*action_balance
+ 0.10*efficiency
```

### 4.2 LLM 总体评分（可选）

`ConversationScorerAgent` 读取对话文本 + 确定性上下文，输出：
- `narrative_coherence`
- `emotional_depth`
- `question_effectiveness`
- `non_redundancy`
- `topic_coverage_quality`
- `overall`

### 4.3 总分融合

```text
overall_score = (1-llm_weight)*deterministic + llm_weight*llm_overall
```

默认 `llm_weight=0.3`。

## 5. 分析方法（用于找最优向量）

脚本输出里明确记录并执行以下方法：

1. 描述统计：每个向量的 `mean/std/min/max`
2. Bootstrap 置信区间：均值的非参数置信区间
3. Pareto 前沿：在多目标上不被支配的向量集合
4. 稳定性分析：重复运行间方差对比
5. 动作分布分析：continue/next_phase/end 结构是否健康

## 6. 运行示例

```bash
python scripts/run_planner_vector_optimization.py \
  --vectors-file docs/planner-weight-experiments/vector_groups.sample.json \
  --turns 20 \
  --repeats 3 \
  --use-llm-scorer \
  --llm-weight 0.3
```

输出：
- `results/conversation/planner_vector_optimization_report_<ts>.json`
- 同步副本到 `results/conversations/`

仅对现有 `results/conversation` 结果打分：

```bash
python scripts/score_conversation_results.py \
  --dir results/conversation
```

报告包含：
- `best_vector`
- `ranking_by_overall_mean`
- `pareto_front_vectors`
- `vector_summary`（每次 run 的原始评分数据）

## 7. 如何选“最优向量”

推荐规则：
1. 先看 `overall_mean` 排名
2. 再看 `overall_std` 与 bootstrap CI（稳定性）
3. 若分数接近，优先选择 Pareto 前沿中结构覆盖与非重复性更好的向量
4. 最后人工抽查该向量对应的对话文本，避免“高分但体验差”的情况
