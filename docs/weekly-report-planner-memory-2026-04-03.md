# 阶段四工作汇报（Planner + Memory 优化）

日期：2026-04-03  
负责人：Oier（协同 Codex）

## 1. 本次目标
- 完成 `Planner` 与 `Baseline` 的联调字段统一，降低前后端联调成本。
- 建立可观测链路，能在每轮对话中直接看到：
  - 候选事件（candidate）
  - similarity hints（置信度）
  - merge 决策路径
  - fallback 原因
- 修复当前回归测试失败点，确保改造后质量可控。

## 2. 已完成工作

### 2.1 联调字段契约统一（任务 4）
已在接口层统一回复字段结构，`Baseline / Planner` 在每轮回复接口中返回一致 key：

- `question`
- `action`
- `done`
- `extracted_events`
- `graph_update`
- `current_graph_state`
- `turn_evaluation`
- `session_metrics`
- `planner_plan`
- `memory_calls`
- `debug_trace`

实现方式：新增统一构造函数 `_build_aligned_turn_payload(...)`，并应用在：
- `POST /api/baseline/reply`
- `POST /api/planner/reply`
- `GET /api/baseline/auto`（interviewer SSE）
- `GET /api/planner/auto`（interviewer SSE）

### 2.2 观测面板数据落地（任务 5）
构建了从 Extraction → Merge → Orchestrator → API → 前端消息气泡的完整观测链路。

#### Extraction 侧新增观测
- prompt 模式（`unified/legacy`）
- 候选事件列表与数量
- similarity hint 数量与详情
- 提取数量、平均置信度
- 提取异常与 fallback 原因

#### Merge 侧新增观测
- 每个事件的 merge 决策：
  - `action`
  - `confidence`
  - `reason`
  - `target_event_id`
  - `final_action`
- 全局 fallback 原因聚合：
  - `llm_merge_hints_disabled`
  - `no_llm_hints`
  - `candidate_not_found`
  - `low_confidence_llm_hints`
  - `verification_failed_create_new`
  - `legacy_no_match_create_new`

#### Orchestrator/接口侧
- 每轮返回 `debug_trace`（`schema_version=planner_debug_v1`）
- 包含：`extraction / merge / coverage` 三个域

#### 前端可视化
在 interviewer 消息下新增调试 chip：
- `候选 N`
- `Hints N`
- `Merge N`
- `Fallback N`

支持 hover tooltip 查看完整 JSON 详情。

## 3. 回归问题修复

本次同时修复了两条 failing tests：

1. `test_title_similarity_scoring`
- 原因：`career` 主题关键词未覆盖“纺织厂”
- 修复：候选筛选关键词补充 `纺织厂`

2. `test_merge_with_medium_confidence_verifies_then_updates`
- 原因：中置信度路径验证仅依赖文本相似度，未利用 `matched_slots`
- 修复：`_verify_with_rules` 增加基于 `matched_slots` 的轻量加权（time/location/people/event + confidence bonus）

## 4. 验证结果

### 4.1 编译/语法
- `python -m py_compile ...` 通过

### 4.2 测试
- `OPENAI_API_KEY=dummy python -m pytest -q tests`
- 结果：`30 passed in 0.41s`

### 4.3 联调实测
- Planner `reply` 返回已包含统一字段 + `debug_trace`
- Baseline `reply` 返回字段与 Planner 对齐
- `debug_trace` 关键字段可见：
  - `extraction.candidate_events`
  - `extraction.similarity_hints`
  - `merge.decisions`
  - `merge.fallback_reasons`

## 5. 关键产出文档

1. 联调契约文档：
- `docs/planner-memory-observability-contract.md`

2. 本汇报文档：
- `docs/weekly-report-planner-memory-2026-04-03.md`

## 6. 主要改动文件
- `src/app.py`
- `src/orchestration/session_orchestrator.py`
- `src/agents/extraction_agent.py`
- `src/core/event_extractor.py`
- `src/services/merge_engine.py`
- `src/state/models.py`

## 7. 当前收益
- 前后端联调阻力显著降低：统一 key 后，渲染逻辑无需按模式分叉。
- 提取/合并问题可直接定位：不再只能看最终结果，支持看到“为什么这么决策”。
- 回归质量恢复：测试已全绿，可继续推进灰度。

## 8. 下周建议
1. 将 `debug_trace` 接入持久化（按 turn 落盘），便于离线分析。
2. 增加“错误合并样本回放”脚本，针对 `verification_failed_create_new` 做专项分析。
3. 基于真实会话统计 `fallback_reasons` 占比，作为下一轮调参依据。
4. 给前端加“仅显示异常轮次”过滤器，提升排错效率。

## 9. 追加优化记录（持续迭代）

### 9.1 低信息增益触发切题/收尾（2026-04-03）

**改动内容：**
- 在 `SessionOrchestrator` 新增低增益连续检测：
  - 连续低增益 `>=2`：建议切题（`next_phase`）
  - 连续低增益 `>=3` 且覆盖率较高：建议收尾（`end`）
- 在 `InterviewerAgent` 增加 `generation_hints` 支持，结合低增益提示调整兜底行为。
- 修复字段名错误：
  - `information_gain` -> `information_gain_score`

**作用：**
- 避免在低质量回复上反复追问同一个点；
- 对话更容易从“卡住状态”恢复为“换角度继续”或“体面收尾”。

**验证：**
- 测试：`32 passed`（新增策略测试后全绿）
- 实测：低信息回复连续输入时，`action` 从 `continue` 变为 `next_phase`。

---

### 9.2 切题兜底问题去重与轮换（2026-04-03）

**改动内容：**
- 增加切题兜底问题轮换机制，避免连续 `next_phase` 时重复同一句问题。
- 在 `SessionState.metadata` 中记录：
  - `last_fallback_question`
  - `fallback_repeat_count`
- 在 `generation_hints` 中传递重复计数，`InterviewerAgent` 按计数轮换不同问法。

**作用：**
- 降低“机械重复感”，让异常场景下的对话也更自然；
- 即使模型请求失败，系统仍能提供可用、可读、非重复的切题问题。

**验证：**
- 测试：`33 passed`
- 实测：触发 `next_phase` 后，问题文本可轮换，不再固定同一句。

---

### 9.3 策略触发可观测化（2026-04-03）

**改动内容：**
- 在每轮 `debug_trace` 中新增 `planning` 域，记录：
  - `low_info_streak`
  - `prefer_breadth_switch`
  - `suggest_close`
  - `fallback_repeat_count`
  - `next_action`

**作用：**
- 可以直接在调试数据里看到“为什么切题/为什么收尾”，减少黑盒感；
- 前端看板和回放分析可直接消费这些字段，不用再从日志反推。

**验证：**
- 测试：`33 passed`
- 接口层已可返回上述 `planning` 调试字段。

---

### 9.4 切题优先选择低覆盖主题（2026-04-03）

**改动内容：**
- 在 `generation_hints` 中新增：
  - `recommended_theme_id`
  - `recommended_theme_title`
- 切题时不再随机问，而是优先选择 `pending/mentioned` 中完成度最低的主题。
- `InterviewerAgent` 在 `next_phase` 兜底问题中使用推荐主题名，生成更有方向的切题问法。

**作用：**
- 切题从“泛化换话题”升级为“带目标的换话题”；
- 能更稳定地拉动整体主题覆盖率，减少无效跳转。

**验证：**
- 新增单测：推荐主题选择逻辑验证通过；
- 全量测试：`34 passed`。

---

### 9.5 推荐切题主题可观测化（2026-04-03）

**改动内容：**
- 在 `debug_trace.planning` 中追加：
  - `recommended_theme_id`
  - `recommended_theme_title`

**作用：**
- 数据看板和日志回放可直接看到“系统建议切到哪个主题”；
- 便于分析切题策略是否真正命中低覆盖主题。

**验证：**
- 全量测试：`34 passed`。
