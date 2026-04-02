# 延迟合并 + 前端可控事件提取设计文档

## 当前架构问题

```
用户回答 → 提取事件 → 立即自动合并 → 返回结果
                    ↓
              无法干预，没有机会调整
```

**问题**：
1. 合并是即时的，一轮结束后就完成
2. 用户/前端无法调整合并决策
3. 无法跨轮次关联事件（第3轮和第5轮提到的事件）
4. 提取错误无法修正

## 目标架构

```
用户回答 → 提取事件 → 生成候选+合并建议 → 前端显示 → 用户确认 → 执行合并
                    ↓                          ↓
              返回候选列表和建议            可调整：
                                         - 接受建议合并
                                         - 创建新事件
                                         - 手动选择目标
                                         - 修改事件内容
```

## 核心变更

### 1. 新增数据结构

```python
# src/state/models.py

@dataclass
class MergeProposal:
    """合并建议"""
    target_event_id: str           # 建议合并到的目标事件ID
    target_event_title: str        # 目标事件标题（用于显示）
    confidence: float              # 置信度 0-1
    reason: str                    # 建议理由
    matched_slots: List[str]       # 匹配的槽位
    action: str  # "merge" | "create_new" | "manual_select"

@dataclass
class ExtractionCandidate:
    """提取的候选事件（待确认）"""
    candidate_id: str              # 候选ID
    extracted_event: ExtractedEvent # 提取的事件内容
    merge_proposals: List[MergeProposal]  # 合并建议列表（按置信度排序）
    status: str  # "pending" | "confirmed" | "rejected" | "modified"
    source_turn_id: str            # 来源轮次
    created_at: datetime

@dataclass
class SessionState:
    # ... 现有字段 ...
    pending_candidates: List[ExtractionCandidate] = field(default_factory=list)  # 待确认的候选
```

### 2. 新流程

**Step 1: 提取（保持不变）**
```python
extracted_events = await extraction_agent.extract(state, turn_record)
# 但现在不立即合并，而是生成候选
```

**Step 2: 生成候选+建议（新增）**
```python
# 不调用 merge_engine.merge()
# 而是调用 merge_engine.propose_merge()
candidates = merge_engine.propose_candidates(state, extracted_events, turn_id)
state.pending_candidates.extend(candidates)
```

**Step 3: 前端显示候选**
```json
{
  "question": "下一个问题...",
  "pending_candidates": [
    {
      "candidate_id": "cand_001",
      "extracted_event": { /* 事件内容 */ },
      "merge_proposals": [
        {
          "target_event_id": "evt_001",
          "target_event_title": "纺织厂工作",
          "confidence": 0.88,
          "reason": "同一件纺织厂工作事件",
          "action": "merge"
        },
        {
          "target_event_id": null,
          "confidence": 0.0,
          "reason": "创建为新事件",
          "action": "create_new"
        }
      ]
    }
  ]
}
```

**Step 4: 用户确认（新增API）**
```python
# POST /api/extraction/confirm
{
  "candidate_id": "cand_001",
  "decision": "merge",  # "merge" | "create_new" | "modify"
  "target_event_id": "evt_001",  # 如果 decision="merge"
  "modified_event": null  # 如果 decision="modify"
}
```

**Step 5: 执行合并**
```python
# 根据用户决策执行实际合并
merge_engine.execute_decision(state, candidate, decision)
```

### 3. 前端交互设计

**候选事件卡片**：
```
┌─────────────────────────────────────┐
│ 📌 提取的事件                        │
│ "在工厂上班挺辛苦的，三班倒"          │
│ 时间: 未提及 | 地点: 工厂            │
├─────────────────────────────────────┤
│ 建议操作:                            │
│ ○ 合并到 "纺织厂工作" (置信度88%)    │
│ ○ 创建为新事件                       │
│ ○ 手动选择其他事件...                │
│ ○ 修改内容...                        │
├─────────────────────────────────────┤
│ [确认] [暂时跳过]                    │
└─────────────────────────────────────┘
```

### 4. 跨轮次关联

**问题**：第3轮说"工厂"，第5轮说"纺织厂"，应该关联

**方案**：
```python
# 提取时不仅比较已有事件，还比较 pending_candidates
# 这样第5轮提取时，可以和第3轮的 pending 候选比较

# 在 propose_candidates 中：
all_reference_events = list(state.canonical_events.values()) + [
    c.extracted_event for c in state.pending_candidates 
    if c.status == "pending"
]
```

### 5. API 变更

**新增端点**：

```python
# 获取待确认的候选
@app.route("/api/extraction/candidates/<session_id>")
def get_pending_candidates(session_id):
    return {
        "candidates": [c.to_dict() for c in state.pending_candidates if c.status == "pending"]
    }

# 确认候选
@app.route("/api/extraction/confirm", methods=["POST"])
def confirm_candidate():
    data = request.json
    candidate_id = data["candidate_id"]
    decision = data["decision"]  # "merge", "create_new", "modify"
    
    # 执行决策
    candidate = find_candidate(state, candidate_id)
    merge_engine.execute_decision(state, candidate, decision, data)
    
    return {"success": True, "graph_state": get_graph_state()}

# 批量确认
@app.route("/api/extraction/confirm_batch", methods=["POST"])
def confirm_candidates_batch():
    """一键确认所有候选（接受最高置信度建议）"""
    for candidate in state.pending_candidates:
        if candidate.status == "pending":
            best_proposal = candidate.merge_proposals[0]
            merge_engine.execute_decision(state, candidate, best_proposal.action, {})
    return {"success": True}

# 修改候选内容
@app.route("/api/extraction/modify", methods=["POST"])
def modify_candidate():
    """修改提取的事件内容"""
    candidate_id = request.json["candidate_id"]
    modified_slots = request.json["slots"]  # 新的槽位内容
    
    candidate = find_candidate(state, candidate_id)
    candidate.extracted_event.slots = EventSlots(**modified_slots)
    candidate.status = "modified"
    
    # 重新生成合并建议
    candidate.merge_proposals = merge_engine.regenerate_proposals(state, candidate)
    
    return {"success": True, "candidate": candidate.to_dict()}
```

### 6. 配置选项

```python
# src/config.py

class Config:
    # 自动合并模式
    AUTO_MERGE_MODE = "manual"  # "manual" | "auto_high_confidence" | "auto_all"
    
    # 高置信度自动合并阈值（仅在 auto_high_confidence 模式下）
    AUTO_MERGE_THRESHOLD = 0.85
    
    # 是否显示低置信度建议
    SHOW_LOW_CONFIDENCE_PROPOSALS = True
    LOW_CONFIDENCE_THRESHOLD = 0.5
```

## 实施步骤

### Phase 1: 数据结构（1天）
- [ ] 新增 `MergeProposal`, `ExtractionCandidate` 数据类
- [ ] 修改 `SessionState` 添加 `pending_candidates`
- [ ] 更新数据库/序列化逻辑

### Phase 2: MergeEngine 改造（2天）
- [ ] 新增 `propose_candidates()` 方法
- [ ] 新增 `execute_decision()` 方法
- [ ] 新增 `regenerate_proposals()` 方法
- [ ] 修改 `merge()` 为包装方法（向后兼容）

### Phase 3: API 开发（1天）
- [ ] `/api/extraction/candidates/<session_id>`
- [ ] `/api/extraction/confirm`
- [ ] `/api/extraction/confirm_batch`
- [ ] `/api/extraction/modify`

### Phase 4: 前端开发（2天）
- [ ] 候选事件卡片组件
- [ ] 合并建议选择UI
- [ ] 事件编辑弹窗
- [ ] 批量确认按钮

### Phase 5: 集成测试（1天）
- [ ] 单轮单事件确认
- [ ] 单轮多事件确认
- [ ] 跨轮次关联
- [ ] 修改后重新建议

## 向后兼容

```python
# 保持旧的 merge() 方法作为快捷方式
def merge(self, state, extracted_events, turn_id):
    """向后兼容：立即合并（自动接受最高置信度建议）"""
    candidates = self.propose_candidates(state, extracted_events, turn_id)
    for candidate in candidates:
        best_proposal = candidate.merge_proposals[0]
        self.execute_decision(state, candidate, best_proposal.action, {})
    return self._build_merge_result(candidates)
```

## 预期效果

1. **用户可控**：前端显示候选，用户决定如何合并
2. **错误可修正**：提取错误可以修改后再确认
3. **跨轮次关联**：可以和之前未确认的候选比较
4. **灵活性**：支持批量确认或逐个确认

## 风险评估

| 风险 | 影响 | 缓解 |
|------|------|------|
| 增加用户操作负担 | 中 | 提供"一键确认"选项 |
| 候选积压 | 低 | 提醒用户确认，自动确认阈值 |
| 复杂度上升 | 中 | 保持向后兼容，渐进式升级 |
