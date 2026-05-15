# Legacy vs Planner 对比实验

本实验用于比较 `legacy` planner（内存图谱、自适应路由校准，`src/legacy/`）与当前 GraphRAG `planner`（Neo4j 图谱检索，`src/orchestration/`）两套访谈 agent 的效果。两套 agent 共用同一组 Flask 路由 `/api/planner/*`，通过 `version` 字段区分。

## 运行命令

默认完整实验为两款 agent 各 5 组，每组 30 轮：

```bash
python scripts/run_legacy_vs_planner_experiment.py
```

快速验证流程：

```bash
python scripts/run_legacy_vs_planner_experiment.py --runs-per-agent 1 --legacy-turns 2 --planner-turns 2
```

启用 LLM 评分 agent：

```bash
python scripts/run_legacy_vs_planner_experiment.py --use-llm-scorer --llm-weight 0.3
```

两边跑相同轮数的快捷方式：

```bash
python scripts/run_legacy_vs_planner_experiment.py --turns 20
```

默认会把所有 chat/structured 角色临时切到 `moonshot-v1-8k`。若要完全使用 `.env` 中的模型配置：

```bash
python scripts/run_legacy_vs_planner_experiment.py --model ""
```

## 参数说明

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--runs-per-agent` | `5` | 每款 agent 跑的独立实验组数 |
| `--legacy-turns` | `30` | legacy agent 每组最大轮数 |
| `--planner-turns` | `30` | graphrag agent 每组最大轮数 |
| `--turns` | — | 快捷参数，同时设置两边轮数 |
| `--output-dir` | `results/legacy-vs-planner` | 输出根目录 |
| `--experiment-id` | 自动生成 | 时间戳 + UUID 短串 |
| `--elder-info-json` | — | 指定老人画像 JSON 文件路径，不填则用默认画像 |
| `--use-llm-scorer` | 关 | 启用 `ConversationScorerAgent` 评分 |
| `--llm-weight` | `0.30` | LLM 评分占最终分数的权重 |
| `--variance-penalty-weight` | `1.0` | 方差惩罚权重 |
| `--model` | `moonshot-v1-8k` | 覆盖所有角色模型；传空字符串则不覆盖 |
| `--enable-planner-tools` | 关 | 启用 planner 工具调用 |
| `--no-reset-graph-before-experiment` | 关 | 跳过实验前 Neo4j 图谱重置 |
| `--continue-on-error` | 关 | 遇到错误轮次后继续而非中断 |

## 与 baseline-vs-planner 的关键区别

| 对比维度 | baseline-vs-planner | legacy-vs-planner |
|----------|--------------------|--------------------|
| 被测 agent | baseline、planner | legacy planner、graphrag planner |
| Flask 路由 | `/api/baseline/*` vs `/api/planner/*` | 两者均走 `/api/planner/*` |
| 区分方式 | 不同端点 | `POST /api/planner/start` 中的 `version` 字段 |
| 图谱类型 | baseline 无图谱 | legacy 用内存图，graphrag 用 Neo4j |
| GraphRAG 指标 | 仅 planner 有 | 仅 graphrag 版本有 |
| 默认轮数 | baseline 20，planner 50 | 两边均 30 |
| 默认组数 | 10 | 5 |

## 输出目录

每次实验输出到：

```text
results/legacy-vs-planner/<experiment_id>/
```

关键文件：

- `summary.json`: 聚合分数、方差、稳定性惩罚分、胜出 agent
- `summary.csv`: 每组 run 的扁平指标表
- `experiment_config.json`: 运行参数、老人画像、评分权重
- `charts/mean_score.svg`: 两款 agent mean score 可视化
- `charts/mean_minus_variance_penalty.svg`: mean - variance penalty 可视化
- `docs/METHODS.md`: 当次实验的评分和方法说明
- `runs/legacy/run_XX/transcript.md`: legacy 单组访谈文本
- `runs/graphrag/run_XX/transcript.md`: graphrag 单组访谈文本
- `runs/<agent>/run_XX/turns.jsonl`: 逐轮原始 SSE 事件
- `runs/<agent>/run_XX/metrics.json`: 单组指标
- `runs/<agent>/run_XX/score.json`: 单组评分
- `runs/<agent>/run_XX/planner_report.json`: planner 会话报告（两款 agent 均有）
- `runs/<agent>/run_XX/graph_state.json`: 图谱状态（legacy 为内存图，graphrag 为 Neo4j）

## 指标来源与计算

### 共同指标（两款 agent 均适用）

两款 agent 均产生相同格式的 `turn_evaluation`（`question_quality_score`、`information_gain_score`、`non_redundancy_score`），因此以下指标直接可比：

- `completed_turns` / `completion_rate`
- `avg_question_quality`、`avg_information_gain`、`avg_non_redundancy`
- `low_gain_ratio`（`information_gain_score <= 0.08` 的轮次占比）
- `final_coverage`（优先取 `session_metrics.overall_theme_coverage`，次选 `coverage_metrics.*`）
- `action_continue_ratio` / `action_next_phase_ratio` / `action_end_ratio`
- `avg_interviewer_ms`

### GraphRAG 专属指标（仅 graphrag agent）

legacy agent 的 `debug_trace` 不含 `graph_rag_metrics` 字段（无 Neo4j），因此以下指标仅对 graphrag 有意义：

- `retrieval_nonempty_rate`
- `avg_ranked_entities`、`avg_context_chars`
- `total_new_entities`、`total_updated_entities`
- `total_relationships_written`、`total_extracted_events`

## 评分方式

确定性共同分数（两款 agent 适用同一公式）：

```text
score =
  0.28 * question_quality +
  0.24 * information_gain +
  0.20 * non_redundancy +
  0.18 * coverage +
  0.10 * completion
```

graphrag agent 额外输出 `graph_observability_score`，不计入共同分数，避免 legacy 因没有图谱字段被不公平扣分。

启用评分 agent 后：

```text
overall = (1 - llm_weight) * deterministic_score + llm_weight * llm_overall
```

## 稳定性惩罚

```text
mean_minus_variance_penalty =
  mean(overall_score) - variance_penalty_weight * population_variance(overall_score)
```

## GraphRAG 重置

脚本默认在实验开始前重置一次 Neo4j 访谈图谱（保留 Topic 节点），仅当 `NEO4J_ENABLED=true` 时生效。legacy agent 使用内存图，不受影响。

跳过重置：

```bash
python scripts/run_legacy_vs_planner_experiment.py --no-reset-graph-before-experiment
```
