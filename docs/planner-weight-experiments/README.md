# Planner 信息权重实验配置

这些配置用于 `SessionOrchestrator(..., decision_weights=...)` 的可重复实验。

每个 JSON 文件包含：
- `experiment_id`: 实验编号
- `goal`: 目标
- `variants`: 权重变体列表（可直接注入 orchestrator）

核心可调字段：
- `new_info_weight`
- `missing_slot_weight`
- `theme_coverage_weight`
- `emotion_energy_weight`
- `memory_stability_weight`
- `conflict_clarification_weight`
- `information_quality_weight`
- `low_gain_penalty`
- `reflection_slot_weight`
- `factual_slot_weight`

示例：

```python
from src.orchestration import SessionOrchestrator

variant = {...}  # 从实验 JSON 读取某组 variants[i]["weights"]
orchestrator = SessionOrchestrator("exp_run_001", decision_weights=variant)
```

也支持向量输入（固定顺序）：

```python
vector = [1.0, 1.15, 1.0, 0.9, 0.85, 1.0, 0.95, 1.1, 0.75, 1.0]
orchestrator = SessionOrchestrator("exp_run_002", decision_weights=vector)
```

批量跑多组向量：

```bash
python scripts/run_planner_weight_vector_batch.py \
  --vectors-file docs/planner-weight-experiments/vector_groups.sample.json \
  --turns 20
```
