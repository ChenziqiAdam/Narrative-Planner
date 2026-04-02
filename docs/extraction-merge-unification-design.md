# Extraction-Merge 统一化改造设计文档

**方案**: B - 混合智能方案（大模型语义提示 + 硬编码规则兜底）  
**日期**: 2026-04-02  
**状态**: 设计阶段  

---

## 1. 设计目标

### 1.1 当前痛点
- **硬编码合并僵化**: `SequenceMatcher` 无法识别语义相似（如"纺织厂工作" vs "在工厂上班"）
- **误判成本高**: 同一事件被重复创建，导致图谱碎片化、主题完成度计算失真
- **调试困难**: 合并决策无解释性，无法追踪为什么两个事件没被合并

### 1.2 目标
- 用**最小成本**获得大模型的**语义理解能力**
- 保留硬编码规则作为**兜底和验证**
- 系统可**回滚**、可**调试**、可**灰度**

---

## 2. 架构变更概览

### 2.1 变更类型判定

| 模块 | 变更方式 | 原因 |
|------|----------|------|
| `EventExtractor` | **修改** | 在现有提取逻辑上增加相似度提示输出 |
| `ExtractionAgent` | **修改** | 解析新的 `similarity_hints` 字段 |
| `MergeEngine` | **修改** | 新增基于 confidence 的分支逻辑，保留原有方法 |
| `ExtractedEvent` | **新增字段** | 向后兼容，旧数据默认为空列表 |
| Prompt 模板 | **新增** | 新增 `unified_extraction_prompt_v2.txt` |

### 2.2 核心原则：**增量式修改，非替换**

```
旧流程: 提取 → 简单事件对象 → 硬编码合并
            ↓
新流程: 提取 → 增强事件对象(带相似度提示) → 智能合并(优先用大模型建议)
            ↓                              ↓
            └──────────────────► 硬编码合并兜底(原有逻辑保留)
```

---

## 3. 详细设计

### 3.1 数据结构变更

#### 3.1.1 新增 SimilarityHint 数据类

```python
# src/core/interfaces.py

@dataclass
class SimilarityHint:
    """大模型给出的相似度建议"""
    candidate_id: str          # 候选事件ID
    confidence: float          # 置信度 0.0-1.0
    reason: str                # 判断理由（用于调试）
    matched_slots: List[str]   # 匹配的槽位（time/location/people等）
```

#### 3.1.2 ExtractedEvent 扩展

```python
# src/core/interfaces.py

@dataclass
class ExtractedEvent:
    event_id: str
    extracted_at: datetime
    slots: EventSlots
    confidence: float
    theme_id: Optional[str]
    source_turns: List[str]
    is_update: bool = False
    updated_event_id: Optional[str] = None
    
    # ⭐ 新增字段（向后兼容，默认为空）
    similarity_hints: List[SimilarityHint] = field(default_factory=list)
```

### 3.2 Prompt 设计

#### 3.2.1 新建 Prompt 文件

**文件**: `prompts/unified_extraction_prompt_v2.txt`

```
# 角色
你是专门从老年回忆录访谈中提取结构化事件的信息专家。
你同时具备"提取"和"合并判断"两种能力。

# 任务说明
从受访者的回答中提取具体人生事件，并判断是否与已有事件重复。

# 输入数据

## 当前对话
提问者问：{{ interviewer_question }}
受访者答：{{ interviewee_answer }}

## 历史上下文（最近3轮）
{{ transcript_context }}

## 已有事件候选（按字面相似度选出的TOP-3，可能无关）
{{ candidate_events }}

# 提取要求

## 8个维度槽位
1. time: 时间（如"1968年春天"、"我18岁那年"）
2. location: 地点（如"上海纺织厂"、"北京"）
3. people: 涉及人物列表（如["母亲", "师傅"]）
4. event: 事件核心内容（一句话描述发生了什么）
5. feeling: 当时的感受（如"紧张又期待"）
6. reflection: 现在的反思（如"那是我人生的转折点"）
7. cause: 事件起因
8. result: 事件结果/影响

## unexpanded_clues
列出受访者提到但未详细说明的线索（用分号分隔），如"提到有个同事但没问名字;说后来发生了变故但没细说"

# 合并判断要求

对每个提取出的事件，判断是否与【已有事件候选】中的某一条描述的是**同一件具体事情**：

**判断标准**（按优先级）：
1. 时间+地点+核心事件三重匹配 → 极可能是同一事件
2. 人物+核心事件双重匹配+时间相近 → 可能是同一事件
3. 只有措辞相似但时间/地点矛盾 → 不是同一事件

**注意事项**：
- 措辞不同不代表不同事件（"纺织厂"="工厂"="车间"）
- 时间表达不同需转换后比较（"1968年"="六八年"="我18岁那年"如果出生1950）
- 置信度>0.8: 高度确信是同一事件
- 置信度0.5-0.8: 可能是，建议人工/规则二次确认
- 置信度<0.5: 视为新事件

# 输出格式

```json
{
  "events": [
    {
      "event_id": "evt_new_xxx",
      "slots": {
        "time": "...",
        "location": "...",
        "people": ["..."],
        "event": "...",
        "feeling": "...",
        "reflection": "...",
        "cause": "...",
        "result": "...",
        "unexpanded_clues": "..."
      },
      "confidence": 0.85,
      "theme_id": "career",
      "similarity_hints": [
        {
          "candidate_id": "evt_003",
          "confidence": 0.88,
          "reason": "同一件纺织厂工作事件，时间地点匹配",
          "matched_slots": ["time", "location", "event"]
        }
      ]
    }
  ],
  "open_loops": [
    {
      "description": "...",
      "priority": 0.8
    }
  ],
  "emotional_state": {
    "valence": 0.2,
    "energy": 0.7
  }
}
```

# 约束
1. 只输出合法JSON，不要Markdown、解释、前缀
2. 如果没有匹配候选事件，similarity_hints为空数组
3. 如果槽位未提及，填null而非空字符串
4. 时间地点人物是判断同一性的关键，务必准确提取
```

### 3.3 EventExtractor 修改

#### 3.3.1 新增方法：事件预选

```python
# src/core/event_extractor.py

class EventExtractor:
    def _select_candidate_events(
        self, 
        current_turn: DialogueTurn, 
        existing_events: List[Dict]
    ) -> List[Dict]:
        """
        用轻量级规则预选TOP-3候选事件供大模型参考
        策略：标题相似度 + 主题匹配 + 时间关键词匹配
        """
        candidates = []
        answer = current_turn.interviewee_raw_reply or ""
        
        for event in existing_events:
            score = 0.0
            
            # 标题相似度 (0-0.4)
            title = event.get("title", "")
            summary = event.get("summary", "")
            title_score = SequenceMatcher(None, answer[:50], title).ratio() * 0.4
            score += title_score
            
            # 主题匹配 (0-0.3)
            theme_id = event.get("theme_id", "")
            if theme_id and self._theme_matches_answer(theme_id, answer):
                score += 0.3
            
            # 时间关键词匹配 (0-0.3)
            event_time = event.get("time", "")
            if event_time and self._time_matches_answer(event_time, answer):
                score += 0.3
            
            if score > 0.2:  # 阈值过滤
                candidates.append({"event": event, "score": score})
        
        # 按分数排序取TOP-3
        candidates.sort(key=lambda x: x["score"], reverse=True)
        return [c["event"] for c in candidates[:3]]
```

#### 3.3.2 修改提取方法

```python
async def extract_with_existing_events(
    self,
    current_turn: DialogueTurn,
    context: List[DialogueTurn],
    existing_events: List[Dict],
) -> List[ExtractedEvent]:
    # ⭐ 新增：预选候选事件
    candidate_events = self._select_candidate_events(current_turn, existing_events)
    
    # ⭐ 修改：使用新的 unified prompt
    prompt = self._build_unified_prompt_v2(
        current_turn=current_turn,
        context=context,
        candidate_events=candidate_events
    )
    
    response = await self._call_llm(prompt)
    return self._parse_unified_response_v2(response)
```

### 3.4 MergeEngine 智能合并逻辑

#### 3.4.1 新增分层决策

```python
# src/services/merge_engine.py

class MergeEngine:
    # ⭐ 新增：大模型建议置信度阈值
    HIGH_CONFIDENCE_THRESHOLD = 0.80
    MEDIUM_CONFIDENCE_THRESHOLD = 0.50
    
    def merge(
        self,
        state: SessionState,
        extracted_events: List[ExtractedEvent],
        turn_id: str,
    ) -> MergeResult:
        result = MergeResult()
        
        for extracted in extracted_events:
            # 处理人物（不变）
            person_ids, new_person_ids = self._upsert_people(state, extracted, turn_id)
            result.new_person_ids.extend(new_person_ids)
            result.touched_person_ids.extend(person_ids)
            
            # ⭐ 新增：优先使用大模型建议
            merge_action = self._decide_merge_action(state, extracted)
            
            if merge_action.action_type == "UPDATE" and merge_action.target_event:
                # 高置信度：直接使用大模型建议
                self._update_event(
                    merge_action.target_event, extracted, person_ids, turn_id
                )
                merge_action.target_event.merge_status = "updated_by_llm_hint"
                result.updated_event_ids.append(merge_action.target_event.event_id)
                result.touched_event_ids.append(merge_action.target_event.event_id)
                
            elif merge_action.action_type == "VERIFY_THEN_UPDATE":
                # 中等置信度：大模型建议 + 硬编码验证
                if self._verify_with_rules(merge_action.target_event, extracted):
                    self._update_event(
                        merge_action.target_event, extracted, person_ids, turn_id
                    )
                    merge_action.target_event.merge_status = "updated_verified"
                    result.updated_event_ids.append(merge_action.target_event.event_id)
                else:
                    # 验证失败，创建新事件
                    canonical_event = self._create_event(extracted, person_ids, turn_id)
                    state.canonical_events[canonical_event.event_id] = canonical_event
                    result.new_event_ids.append(canonical_event.event_id)
                    result.touched_event_ids.append(canonical_event.event_id)
                    
            else:
                # 低置信度或无建议：走原有硬编码流程
                matched_event = self._find_match_with_legacy_rules(state, extracted)
                if matched_event:
                    self._update_event(matched_event, extracted, person_ids, turn_id)
                    matched_event.merge_status = "updated_legacy"
                    result.updated_event_ids.append(matched_event.event_id)
                    result.touched_event_ids.append(matched_event.event_id)
                else:
                    canonical_event = self._create_event(extracted, person_ids, turn_id)
                    state.canonical_events[canonical_event.event_id] = canonical_event
                    result.new_event_ids.append(canonical_event.event_id)
                    result.touched_event_ids.append(canonical_event.event_id)
            
            self._link_people(state, person_ids, result.touched_event_ids[-1])
            
            # ⭐ 调试日志：记录决策原因
            logger.debug(
                "Merge decision for %s: %s (confidence=%.2f, reason=%s)",
                extracted.event_id,
                merge_action.action_type,
                merge_action.confidence,
                merge_action.reason
            )
        
        return result
```

#### 3.4.2 新增决策类

```python
@dataclass
class MergeAction:
    action_type: Literal["UPDATE", "VERIFY_THEN_UPDATE", "CREATE_NEW"]
    target_event: Optional[CanonicalEvent]
    confidence: float
    reason: str

class MergeEngine:
    def _decide_merge_action(
        self, 
        state: SessionState, 
        extracted: ExtractedEvent
    ) -> MergeAction:
        """
        基于大模型建议决定合并动作
        """
        hints = extracted.similarity_hints
        
        if not hints:
            return MergeAction(
                action_type="CREATE_NEW",
                target_event=None,
                confidence=0.0,
                reason="no_llm_hints"
            )
        
        # 取最高置信度的建议
        best_hint = max(hints, key=lambda h: h.confidence)
        target_event = state.canonical_events.get(best_hint.candidate_id)
        
        if not target_event:
            return MergeAction(
                action_type="CREATE_NEW",
                target_event=None,
                confidence=0.0,
                reason="candidate_not_found"
            )
        
        # 分层决策
        if best_hint.confidence >= self.HIGH_CONFIDENCE_THRESHOLD:
            return MergeAction(
                action_type="UPDATE",
                target_event=target_event,
                confidence=best_hint.confidence,
                reason=f"high_confidence_llm_hint: {best_hint.reason}"
            )
        
        elif best_hint.confidence >= self.MEDIUM_CONFIDENCE_THRESHOLD:
            return MergeAction(
                action_type="VERIFY_THEN_UPDATE",
                target_event=target_event,
                confidence=best_hint.confidence,
                reason=f"medium_confidence_llm_hint: {best_hint.reason}"
            )
        
        else:
            return MergeAction(
                action_type="CREATE_NEW",
                target_event=None,
                confidence=best_hint.confidence,
                reason="low_confidence_llm_hints"
            )
```

### 3.5 回滚与降级策略

#### 3.5.1 功能开关

```python
# src/config.py

class Config:
    # 功能开关
    ENABLE_LLM_MERGE_HINTS = True  # 是否启用大模型合并建议
    LLM_MERGE_HIGH_THRESHOLD = 0.80
    LLM_MERGE_MEDIUM_THRESHOLD = 0.50
    LLM_MERGE_MAX_CANDIDATES = 3
```

#### 3.5.2 降级逻辑

```python
class EventExtractor:
    async def extract_with_existing_events(self, ...):
        if not Config.ENABLE_LLM_MERGE_HINTS:
            # 降级：使用旧版提取逻辑
            return await self._legacy_extract(...)
        
        # 正常流程
        ...

class MergeEngine:
    def merge(self, ...):
        if not Config.ENABLE_LLM_MERGE_HINTS:
            # 降级：使用旧版合并逻辑
            return self._legacy_merge(...)
        
        # 正常流程
        ...
```

---

## 4. 数据流变更

### 4.1 修改前数据流

```
老人回复
  │
  ▼
EventExtractor.extract()
  ├── 输入: 当前对话 + 历史3轮
  ├── Prompt: 简单提取任务
  └── 输出: ExtractedEvent[] (无相似度信息)
  │
  ▼
MergeEngine.merge()
  ├── 输入: ExtractedEvent[] + 全部已有事件
  ├── 算法: SequenceMatcher 相似度计算
  └── 输出: MergeResult
```

### 4.2 修改后数据流

```
老人回复
  │
  ▼
EventExtractor._select_candidate_events() (硬编码预选TOP-3)
  │
  ▼
EventExtractor.extract_with_existing_events()
  ├── 输入: 当前对话 + 历史3轮 + TOP-3候选事件
  ├── Prompt: unified_extraction_prompt_v2 (提取+合并判断)
  └── 输出: ExtractedEvent[] (带 similarity_hints)
  │
  ▼
MergeEngine.merge()
  ├── 输入: ExtractedEvent[] (带相似度提示)
  ├── 算法:
  │   ├── confidence >= 0.8 → 直接用LLM建议
  │   ├── 0.5 <= confidence < 0.8 → LLM建议 + 规则验证
  │   └── confidence < 0.5 → 原有SequenceMatcher兜底
  └── 输出: MergeResult
```

---

## 5. 测试策略

### 5.1 单元测试

```python
# tests/test_merge_engine_with_llm_hints.py

class TestMergeEngineWithLLMHints:
    def test_high_confidence_hint_direct_update(self):
        """高置信度建议应直接合并"""
        extracted = create_extracted_event(
            similarity_hints=[
                SimilarityHint(candidate_id="evt_001", confidence=0.90, ...)
            ]
        )
        action = merge_engine._decide_merge_action(state, extracted)
        assert action.action_type == "UPDATE"
    
    def test_medium_confidence_hint_with_verification(self):
        """中等置信度建议需规则验证"""
        extracted = create_extracted_event(
            similarity_hints=[
                SimilarityHint(candidate_id="evt_001", confidence=0.65, ...)
            ]
        )
        action = merge_engine._decide_merge_action(state, extracted)
        assert action.action_type == "VERIFY_THEN_UPDATE"
    
    def test_low_confidence_hint_fallback_to_legacy(self):
        """低置信度建议回退到硬编码"""
        extracted = create_extracted_event(
            similarity_hints=[
                SimilarityHint(candidate_id="evt_001", confidence=0.30, ...)
            ]
        )
        action = merge_engine._decide_merge_action(state, extracted)
        assert action.action_type == "CREATE_NEW"
```

### 5.2 集成测试用例

| 用例 | 输入 | 期望行为 |
|------|------|----------|
| 语义相同 | 新提取"在纺织厂上班" vs 已有"纺织厂工作" | LLM给出高置信度，直接合并 |
| 时间相近 | 新提取"1968年" vs 已有"六八年" | LLM识别为同一时间，建议合并 |
| 不同事件 | 新提取"结婚" vs 已有"工作" | LLM给出低置信度，创建新事件 |
| 模糊情况 | 新提取"那时候" vs 已有"年轻时" | 中等置信度，需规则二次验证 |

### 5.3 灰度发布

```python
# 按会话ID灰度
def should_use_new_extraction(session_id: str) -> bool:
    import hashlib
    hash_val = int(hashlib.md5(session_id.encode()).hexdigest(), 16)
    return hash_val % 100 < 20  # 20%流量
```

---

## 6. 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| LLM给出错误高置信度 | 不同事件被错误合并 | 保留硬编码验证作为二次检查；可配置开关快速回滚 |
| Prompt过长导致token暴增 | 成本上升 | 限制候选事件为TOP-3；预选逻辑轻量级 |
| LLM响应格式错误 | 解析失败 | try-catch兜底；失败时降级到旧版逻辑 |
| 延迟增加 | 响应变慢 | 预选逻辑<50ms；LLM调用本身已存在，增量成本小 |

---

## 7. 实施计划

### Phase 1: 基础设施（1天）
- [ ] 新增 `SimilarityHint` 数据类
- [ ] 修改 `ExtractedEvent` 添加 `similarity_hints` 字段
- [ ] 新建 `unified_extraction_prompt_v2.txt`
- [ ] 添加功能开关配置

### Phase 2: 核心逻辑（2天）
- [ ] 实现 `EventExtractor._select_candidate_events()`
- [ ] 修改 `EventExtractor` 使用新Prompt
- [ ] 实现 `MergeEngine._decide_merge_action()`
- [ ] 修改 `MergeEngine.merge()` 分层逻辑

### Phase 3: 测试与灰度（2天）
- [ ] 编写单元测试
- [ ] 准备集成测试用例
- [ ] 20%流量灰度观察
- [ ] 全量发布

---

## 8. 验证指标

### 8.1 业务指标
- **事件重复率**: 改造前 vs 改造后（预期下降50%+）
- **主题完成度准确性**: 避免因重复事件导致的虚高

### 8.2 技术指标
- **合并准确率**: 人工抽样检查100个合并决策
- **降级率**: 因LLM失败回退到旧逻辑的比例（目标<5%）
- **延迟增量**: P99延迟增加（目标<100ms）

---

## 9. 附录

### 9.1 新旧逻辑对比示例

**场景**: 第一轮提到"1968年进纺织厂"，第二轮说"那年在工厂上班"

| 维度 | 旧逻辑 | 新逻辑 |
|------|--------|--------|
| 字面相似度 | "纺织厂" vs "工厂" = 低 | LLM理解为同一概念 |
| 合并决策 | 创建两个独立事件 | 识别为同一事件，更新属性 |
| 结果 | 图谱碎片化，主题完成度虚高 | 事件聚合，准确反映进度 |

### 9.2 Prompt Token 估算

```
新Prompt增加内容:
- 3个候选事件 × 平均200字 = 600字 ≈ 800 tokens
- 相似度判断指令 ≈ 200 tokens
- 总计增加: ~1000 tokens/调用

成本影响:
- 假设1000 tokens = $0.002
- 单会话20轮 = $0.04额外成本
- 可接受范围内
```
