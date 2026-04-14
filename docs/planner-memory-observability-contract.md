# Planner + Memory 联调与观测字段契约

## 1. 目的
本文件用于统一 Baseline / Planner 两条链路的返回字段，减少前后端联调摩擦；并定义调试观测字段，支持定位提取与合并问题。

## 2. 适用接口
- `POST /api/baseline/reply`
- `GET /api/baseline/auto` (SSE)
- `POST /api/planner/reply`
- `GET /api/planner/auto` (SSE)

说明：`/api/baseline/start` 和 `/api/planner/start` 的启动返回结构保持原样，联调统一主要发生在“每轮回复”接口。

## 3. 每轮回复统一字段（HTTP）
以下字段在 Baseline / Planner 的 `reply` 接口中保持同名同语义：

```json
{
  "question": "string",
  "action": "continue|next_phase|end",
  "done": true,
  "extracted_events": [],
  "graph_update": {},
  "current_graph_state": {},
  "turn_evaluation": {},
  "session_metrics": {},
  "planner_plan": {},
  "memory_calls": [],
  "debug_trace": {}
}
```

### 字段说明
- `question`: 下一轮问题文本。
- `action`: 本轮动作标签。
- `done`: 访谈是否结束。
- `extracted_events`: 本轮提取出的事件列表。
- `graph_update`: 本轮图谱增量变更。
- `current_graph_state`: 本轮后的完整图谱状态。
- `turn_evaluation`: 该轮评估状态或评估结果。
- `session_metrics`: 会话级指标快照。
- `planner_plan`: 预留字段，统一架构下通常为空对象。
- `memory_calls`: 记忆工具调用日志（Baseline 多为空，Planner/Interviewee 可用）。
- `debug_trace`: 本轮调试观测信息（见第 5 节）。

## 4. SSE 事件字段（auto 模式）

### 4.1 Interviewee 事件
```json
{
  "role": "interviewee",
  "text": "string",
  "action": "answer",
  "memory_calls": []
}
```

### 4.2 Interviewer 事件
```json
{
  "role": "interviewer",
  "text": "string",
  "action": "continue|next_phase|end",
  "extracted_events": [],
  "graph_delta": {},
  "turn_evaluation": {},
  "session_metrics": {},
  "planner_plan": {},
  "debug_trace": {}
}
```

### 4.3 结束事件
```json
{ "role": "done" }
```

## 5. `debug_trace` 结构定义

```json
{
  "schema_version": "planner_debug_v1",
  "turn_id": "turn_xxx",
  "extraction": {
    "prompt_mode": "unified|legacy",
    "llm_merge_hints_enabled": true,
    "candidate_count": 3,
    "candidate_events": [],
    "similarity_hint_count": 1,
    "similarity_hints": [],
    "extracted_event_count": 1,
    "avg_confidence": 0.87,
    "fallback_reason": "optional",
    "error": "optional"
  },
  "merge": {
    "decisions": [
      {
        "event_id": "evt_new_001",
        "action": "UPDATE|VERIFY_THEN_UPDATE|CREATE_NEW",
        "confidence": 0.88,
        "reason": "high_confidence_llm_hint: ...",
        "target_event_id": "evt_001",
        "similarity_hints": [],
        "verification_passed": true,
        "final_action": "updated_by_llm_hint|updated_verified|created_new_after_verification|updated_legacy|created_new_legacy"
      }
    ],
    "fallback_reasons": [
      "llm_merge_hints_disabled",
      "no_llm_hints",
      "candidate_not_found",
      "low_confidence_llm_hints",
      "verification_failed_create_new",
      "legacy_no_match_create_new"
    ],
    "new_event_ids": [],
    "updated_event_ids": []
  },
  "coverage": {
    "before": 0.31,
    "after": 0.36,
    "delta": 0.05
  }
}
```

## 6. 前端展示建议（对比页）
建议 interviewer 消息下展示 4 类调试 chip：
- `候选 N`：显示 `extraction.candidate_events`
- `Hints N`：显示 `extraction.similarity_hints`
- `Merge N`：显示 `merge.decisions`
- `Fallback N`：显示 `merge.fallback_reasons`

## 7. 向后兼容约束
- 若某链路暂无该能力，字段必须返回空结构：
  - 列表字段返回 `[]`
  - 对象字段返回 `{}`
- 禁止返回 `null` 破坏前端既有渲染逻辑。

## 8. 调试定位优先级
当出现“重复事件”或“未正确合并”时，建议按顺序排查：
1. `extraction.candidate_events` 是否包含正确候选
2. `extraction.similarity_hints` 是否存在且置信度合理
3. `merge.decisions[*].action/reason/final_action`
4. `merge.fallback_reasons` 是否触发了降级路径

## 9. 版本记录
- `planner_debug_v1`: 初版统一契约，覆盖回复接口、SSE 事件与提取/合并观测字段。
