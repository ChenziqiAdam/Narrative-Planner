# Baseline vs Planner 对比实验

本实验用于比较 `baseline` 与 GraphRAG-enabled `planner` 两套访谈 agent 的效果。脚本复用 9999 端口 compare UI 背后的 Flask API，因此测试路径和本地前端自动访谈一致。

## 运行命令

默认完整实验为两款 agent 各 10 组，每组 50 轮：

```bash
python scripts/run_baseline_vs_planner_experiment.py
```

快速验证流程：

```bash
python scripts/run_baseline_vs_planner_experiment.py --runs-per-agent 1 --turns 2
```

启用评分 agent：

```bash
python scripts/run_baseline_vs_planner_experiment.py --use-llm-scorer --llm-weight 0.3
```

默认会把所有 chat/structured 角色临时切到 `moonshot-v1-8k`，以避开部分 Kimi 模型与 tool calling 的兼容问题。若要完全使用 `.env` 中的模型配置：

```bash
python scripts/run_baseline_vs_planner_experiment.py --model ""
```

## 输出目录

每次实验输出到：

```text
results/baseline-vs-planner/<experiment_id>/
```

关键文件：

- `summary.json`: 聚合分数、方差、稳定性惩罚分、胜出 agent
- `summary.csv`: 每组 run 的扁平指标表
- `experiment_config.json`: 运行参数、老人画像、评分权重
- `charts/mean_score.svg`: 两款 agent mean score 可视化
- `charts/mean_minus_variance_penalty.svg`: mean - variance penalty 可视化
- `docs/METHODS.md`: 当次实验的评分和方法说明
- `runs/<agent>/run_XX/transcript.md`: 单组访谈文本
- `runs/<agent>/run_XX/turns.jsonl`: 单组逐轮原始事件
- `runs/<agent>/run_XX/metrics.json`: 单组指标
- `runs/<agent>/run_XX/score.json`: 单组评分
- `runs/planner/run_XX/planner_report.json`: planner GraphRAG 报告
- `runs/planner/run_XX/graph_state.json`: planner 图谱状态

## 指标

两款 agent 共同指标：

- `completed_turns`
- `completion_rate`
- `avg_question_quality`
- `avg_information_gain`
- `avg_non_redundancy`
- `low_gain_ratio`
- `final_coverage`
- `action_continue_ratio`
- `action_next_phase_ratio`
- `action_end_ratio`
- `avg_interviewer_ms`

Planner 额外 GraphRAG 指标：

- `retrieval_nonempty_rate`
- `avg_ranked_entities`
- `avg_context_chars`
- `total_new_entities`
- `total_updated_entities`
- `total_relationships_written`
- `total_extracted_events`

GraphRAG 指标用于判断图谱是否真正参与了 planner 决策，但默认不放进 baseline/planner 的共同质量分，避免 baseline 因没有图谱字段被不公平扣分。

## 评分方式

确定性共同分数：

```text
score =
  0.28 * question_quality +
  0.24 * information_gain +
  0.20 * non_redundancy +
  0.18 * coverage +
  0.10 * completion
```

启用评分 agent 后：

```text
overall = (1 - llm_weight) * deterministic_score + llm_weight * llm_overall
```

评分 agent 维度包括叙事连贯性、情感深度、问题有效性、非重复性、主题覆盖质量和整体质量。若评分 agent 调用失败，会自动退回确定性分数。

## 稳定性惩罚

每款 agent 的最终稳定性指标：

```text
mean_minus_variance_penalty =
  mean(overall_score) - variance_penalty_weight * population_variance(overall_score)
```

这个指标偏好平均表现高且跨 run 波动小的 agent。

## GraphRAG 重置

脚本默认在实验开始前重置一次访谈图谱，并保留 Topic 节点：

```bash
python scripts/run_baseline_vs_planner_experiment.py --no-reset-graph-before-experiment
```

重置只发生在实验开始，不会每轮或每个 API 调用重置。
