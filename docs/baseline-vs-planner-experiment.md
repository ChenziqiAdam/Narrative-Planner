# Baseline vs Planner 对比实验

本实验用于比较 `baseline` 与 GraphRAG-enabled `planner` 两套访谈 agent 的效果。脚本复用 9999 端口 compare UI 背后的 Flask API，因此测试路径和本地前端自动访谈一致。

## 运行命令

默认完整实验为两款 agent 各 10 组，其中 baseline 每组 20 轮，planner 每组 50 轮：

```bash
python scripts/run_baseline_vs_planner_experiment.py
```

快速验证流程：

```bash
python scripts/run_baseline_vs_planner_experiment.py --runs-per-agent 1 --baseline-turns 2 --planner-turns 2
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

## 指标来源与计算

实验脚本在 `scripts/run_baseline_vs_planner_experiment.py` 中通过 Flask `test_client()` 调用 9999 compare UI 使用的同一组接口：

- baseline: `/api/baseline/start`、`/api/baseline/auto?single_turn=1`、`/api/baseline/evaluation/<session_id>`
- planner: `/api/planner/start`、`/api/planner/auto?single_turn=1`、`/api/planner/evaluation/<session_id>`、`/api/planner/report/<session_id>`、`/api/planner/graph/<session_id>`

每一轮 `/auto?single_turn=1` 返回 SSE 事件。脚本用 `parse_sse_events()` 解析 `data: {...}` 行，并把原始事件保存在 `runs/<agent>/run_XX/turns.jsonl`。后续所有 run 级指标都由 `extract_common_metrics()` 和 `extract_graph_metrics()` 从这些事件与 evaluation/report 接口结果中计算。

### 共同指标

`completed_turns`

- 来源：当前 run 的 `turns` 列表。
- 计算：统计 `turn["status"] == "completed"` 的轮次数。
- 含义：该组访谈实际成功完成的轮数。

`completion_rate`

- 来源：`completed_turns` 与目标轮数。
- 计算：`completed_turns / target_turns`，上限为 1。
- 注意：baseline 和 planner 使用各自目标轮数；默认 baseline 是 20，planner 是 50。

`error_count`

- 来源：每轮 SSE event。
- 计算：统计 `event["role"] == "error"` 的事件数量。
- 用途：识别 API 错误、模型错误或自动访谈中断。

`avg_question_quality`

- 来源：interviewer SSE 事件里的 `turn_evaluation.question_quality_score`。
- baseline 的 `turn_evaluation` 由 `BaselineEvaluationRuntime.submit_turn()` 产生。
- planner 的 `turn_evaluation` 由 `EvaluatorAgent.evaluate_turn()` 产生，并通过 `SessionOrchestrator.process_user_response()` 返回。
- 计算：对所有轮次的 `question_quality_score` 求均值；如果事件里缺失，则回退到 evaluation state 的 `session_metrics.average_turn_quality`。

`avg_information_gain`

- 来源：interviewer SSE 事件里的 `turn_evaluation.information_gain_score`。
- baseline 来源同上，为 baseline runtime 的评估结果。
- planner 来源同上，为 evaluator 对当前问答的信息增量评估。
- 计算：对所有轮次的 `information_gain_score` 求均值；缺失时回退到 `session_metrics.average_information_gain`。

`avg_non_redundancy`

- 来源：interviewer SSE 事件里的 `turn_evaluation.non_redundancy_score`。
- 计算：对所有轮次的 `non_redundancy_score` 求均值。
- 含义：越高表示问题越少重复最近已经问过或已经获得的信息。

`low_gain_ratio`

- 来源：同一组 `information_gain_score`。
- 计算：`information_gain_score <= 0.08` 的轮次占比。
- 含义：低信息增益轮次越多，说明访谈在原地打转或受访者回答过短。

`final_coverage`

- 首选来源：evaluation state 的 `session_metrics.overall_theme_coverage`。
- 次选来源：evaluation state 的 `coverage_metrics.overall_coverage` 或 `coverage_metrics.overall_richness`。
- 最后回退：`session_metrics.average_coverage_gain`。
- 计算：取上述字段中第一个可用值，并裁剪到 0 到 1。
- 注意：baseline 的 coverage 通常来自 baseline runtime 的轻量 coverage 状态；planner 的 coverage 还可能来自 Neo4j 图谱覆盖率。

`action_continue_ratio`

- 来源：interviewer SSE 事件里的 `action`。
- 计算：`action == "continue"` 的数量 / 有 action 的 interviewer 事件数量。
- 含义：继续深挖当前阶段的比例。

`action_next_phase_ratio`

- 来源：同上。
- 计算：`action == "next_phase"` 的数量 / 有 action 的 interviewer 事件数量。
- 含义：切换阶段或主题的比例。

`action_end_ratio`

- 来源：同上。
- 计算：`action == "end"` 的数量 / 有 action 的 interviewer 事件数量。
- 含义：提前结束倾向；批量实验中若异常偏高，需要看 transcript 判断是否过早收束。

`avg_interviewer_ms`

- 来源：interviewer SSE 事件里的 `timing.interviewer_llm_ms`。
- 计算：对所有 interviewer timing 求均值。
- baseline 中该值主要是 baseline interviewer 生成问题耗时。
- planner 中该值由 route 里的 planner timing 或 debug timing 暴露，另有 extraction/write/retrieval 细项保存在 raw event/debug trace。

### Planner GraphRAG 指标

Planner 的 GraphRAG 指标来自 interviewer SSE 事件中的 `debug_trace.graph_rag_metrics`。这个字段由 `SessionOrchestrator.process_user_response()` 调用 `build_graph_rag_metrics()` 生成，包含 extraction、write、planner retrieval 和 decision context 四段。

`turns_with_graph_metrics`

- 来源：每轮 interviewer event 的 `debug_trace.graph_rag_metrics`。
- 计算：包含该字段的轮次数。
- 含义：GraphRAG instrumentation 是否贯穿了 planner 轮次。

`retrieval_nonempty_rate`

- 来源：`graph_rag_metrics.planner_retrieval.is_empty`。
- 计算：`is_empty == false` 的轮次占比。
- 含义：planner 在生成下一问前是否检索到了图谱证据。

`avg_ranked_entities`

- 来源：`graph_rag_metrics.planner_retrieval.ranked_entity_count`。
- 计算：对所有 planner 轮次求均值。
- 含义：每轮 GraphRAG 检索后进入排序结果的实体数量。

`avg_context_chars`

- 来源：`graph_rag_metrics.decision_context.context_char_count`。
- 计算：对所有 planner 轮次求均值。
- 含义：最终传给 interviewer 作为 GraphRAG 决策上下文的文本长度。

`total_new_entities`

- 来源：`graph_rag_metrics.write.new_entity_count`。
- 计算：所有 planner 轮次求和。
- 含义：本组访谈向 Neo4j 写入的新实体数量。

`total_updated_entities`

- 来源：`graph_rag_metrics.write.updated_entity_count`。
- 计算：所有 planner 轮次求和。
- 含义：本组访谈对已有实体的更新次数。

`total_relationships_written`

- 来源：`graph_rag_metrics.write.relationship_count`。
- 计算：所有 planner 轮次求和。
- 含义：图谱中新增或确认的关系数量。

`total_extracted_events`

- 来源：`graph_rag_metrics.extraction.event_count`。
- 计算：所有 planner 轮次求和。
- 含义：LLM extraction 从受访者回答中识别出的 Event 数量。

### Token 与 prompt 诊断指标

Planner 每轮 raw event 的 `debug_trace.extraction_prompt` 记录 GraphRAG 提取 prompt 的字符级统计：

- `prompt_chars`: extraction 最终 user prompt 总字符数
- `template_chars`: extraction 指令模板字符数
- `input_json_chars`: 当前输入 JSON 字符数
- `current_question_chars`: 当前问题裁剪后的长度
- `current_answer_chars`: 当前回答裁剪后的长度
- `context_turns`: extraction 带入的历史上下文轮数
- `graph_context_chars`: extraction 带入的图谱上下文长度

这些字段不直接参与质量评分，只用于解释 token 消耗和定位 prompt 膨胀。

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

## 分开设置轮数

默认参数已经是：

```bash
python scripts/run_baseline_vs_planner_experiment.py --baseline-turns 20 --planner-turns 50
```

如果临时需要两边跑相同轮数，可以用快捷参数：

```bash
python scripts/run_baseline_vs_planner_experiment.py --turns 10
```
