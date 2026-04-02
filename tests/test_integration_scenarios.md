# Extraction-Merge 统一化集成测试用例

**版本**: v1.0  
**目的**: 验证新方案的端到端效果，对比新旧系统的差异

---

## 测试方法论

### 测试数据准备

1. **人工标注数据集**: 100组真实访谈对话，人工标注：
   - 应提取的事件
   - 事件是否应该合并
   - 合并的理由

2. **A/B测试框架**:
   ```python
   # 并行运行新旧系统
   old_result = merge_with_legacy(events, state)
   new_result = merge_with_llm_hints(events, state)

   # 对比差异
   diff = compare_merge_decisions(old_result, new_result)
   ```

---

## 核心测试场景

### 场景1：语义相同，措辞不同（核心收益场景）

**对话历史**:
```
第一轮:
问: 您年轻时在哪里工作？
答: 我1968年进了上海纺织厂，做挡车工。
```

**已提取事件**:
```json
{
  "event_id": "evt_001",
  "title": "纺织厂工作",
  "summary": "1968年进上海纺织厂做挡车工",
  "time": "1968年",
  "location": "上海纺织厂"
}
```

**新对话**:
```
第二轮:
问: 那时候工作辛苦吗？
答: 在工厂上班挺辛苦的，三班倒，但那时候年轻不觉得累。
```

**期望行为**:
- **旧系统**: 创建新事件（"工厂上班" vs "纺织厂工作"字面相似度低）❌
- **新系统**: 识别为同一事件，更新属性 ✅

**验证指标**:
- LLM给出的similarity_hints中，confidence应 > 0.8
- merge_status应为"updated_by_llm_hint"

---

### 场景2：时间表达不同

**对话历史**:
```
已提取: time="1968年"
```

**新对话**:
```
答: 那是六八年的事了，我才18岁。
```

**期望行为**:
- LLM应识别"六八年" = "1968年"
- similarity_hints.confidence > 0.7
- 如果birth_year=1950，应识别"18岁那年"也等于1968年

---

### 场景3：不同事件应区分

**对话历史**:
```
已提取:
- evt_001: "纺织厂工作" (1968年, 上海)
- evt_002: "结婚" (1970年, 北京)
```

**新对话**:
```
答: 我70年在北京成了家。
```

**期望行为**:
- 与evt_001: confidence < 0.5（时间地点都不同）
- 与evt_002: confidence > 0.8（时间地点人物匹配）
- 决策: UPDATE evt_002

---

### 场景4：模糊情况需要验证

**对话历史**:
```
已提取:
- evt_001: "童年上学" (1955年, 家乡小学)
```

**新对话**:
```
答: 那时候在村里读书。
```

**期望行为**:
- LLM给出中等置信度 (0.5-0.7)
- 触发硬编码验证
- SequenceMatcher验证通过则合并，否则新建

---

### 场景5：多事件同时提取

**新对话**:
```
答: 1968年进了纺织厂，两年后又调到车间当组长。
```

**期望行为**:
- 提取2个事件
- 事件1: 与已有"纺织厂工作"匹配 (confidence > 0.8)
- 事件2: 无匹配 (confidence < 0.5或no hints)
- 结果: 事件1更新，事件2新建

---

## 边界测试

### 边界1：空候选事件

**条件**: 第一轮对话，无已有事件

**期望**: 正常提取，similarity_hints为空

---

### 边界2：大量已有事件

**条件**: 已有50个事件

**期望**:
- _select_candidate_events 只选TOP-3
- Prompt长度可控
- 响应时间在可接受范围

---

### 边界3：LLM响应格式错误

**条件**: LLM返回非JSON格式

**期望**:
- 不抛出异常
- 降级到旧版解析器或返回空列表
- 记录错误日志

---

### 边界4：候选事件不存在

**条件**: LLM建议的candidate_id在state中不存在

**期望**:
- 决策为CREATE_NEW
- 不抛出异常
- 记录警告日志

---

## 性能测试

### 测试1：延迟基准

```python
# 测量各阶段耗时
with timer("select_candidates"):
    candidates = extractor._select_candidate_events(turn, events)

with timer("build_prompt"):
    prompt = extractor._build_unified_prompt(turn, context, candidates)

with timer("llm_call"):
    response = await extractor._call_llm(prompt)

with timer("parse_response"):
    events = extractor._parse_unified_llm_response(response)

with timer("merge_decision"):
    result = merge_engine.merge(state, events, turn_id)
```

**期望指标**:
- select_candidates: < 50ms
- build_prompt: < 10ms
- llm_call: 500-1500ms（主要耗时）
- parse_response: < 20ms
- merge_decision: < 10ms

---

### 测试2：Token使用量

**测量**: Prompt和Response的token数

**期望**:
- 旧系统: ~1500 tokens/调用
- 新系统: ~2500 tokens/调用（增加候选事件描述）
- 增加量: ~1000 tokens（可接受）

---

## 回滚测试

### 测试开关有效性

```python
# 测试1: 开关关闭时走旧逻辑
Config.ENABLE_LLM_MERGE_HINTS = False
result = await extractor.extract_with_existing_events(...)
# 验证: 使用旧版prompt，无视similarity_hints

# 测试2: 开关打开时走新逻辑
Config.ENABLE_LLM_MERGE_HINTS = True
result = await extractor.extract_with_existing_events(...)
# 验证: 使用统一prompt，解析similarity_hints
```

---

## 人工评估流程

### 抽样检查清单

每100轮对话，人工检查10个合并决策：

1. **决策正确性**: 是否合并且应该合并？
2. **置信度合理性**: confidence值是否符合直观判断？
3. **理由清晰性**: reason字段是否解释了判断依据？

### 评分标准

| 维度 | 优秀(>90%) | 良好(70-90%) | 待改进(<70%) |
|------|-----------|-------------|-------------|
| 合并准确率 | >90% | 70-90% | <70% |
| 误合并率 | <5% | 5-15% | >15% |
| 漏合并率 | <10% | 10-25% | >25% |

---

## 自动化测试脚本

```python
# tests/run_integration_tests.py

import asyncio
import json
from pathlib import Path

from src.orchestration.session_orchestrator import SessionOrchestrator

async def run_scenario_test(scenario_file: str):
    """运行单个场景测试"""
    with open(scenario_file) as f:
        scenario = json.load(f)

    orchestrator = SessionOrchestrator(
        session_id=f"test_{scenario['id']}"
    )

    # 初始化
    state = orchestrator.initialize_session(scenario['elder_info'])

    # 模拟历史对话
    for turn in scenario['history_turns']:
        # 手动注入已有事件
        for event in turn.get('existing_events', []):
            state.canonical_events[event['event_id']] = event

    # 执行提取+合并
    result = await orchestrator.process_user_response(
        scenario['current_answer']
    )

    # 验证结果
    expected = scenario['expected']
    actual = {
        'new_event_count': len(result.get('extracted_events', [])),
        'merge_decisions': extract_merge_decisions(state)
    }

    return compare_with_tolerance(expected, actual)

async def main():
    """运行所有集成测试"""
    scenario_dir = Path("tests/integration_scenarios")

    results = []
    for scenario_file in scenario_dir.glob("*.json"):
        result = await run_scenario_test(scenario_file)
        results.append({
            'scenario': scenario_file.stem,
            'passed': result['passed'],
            'diff': result['diff']
        })

    # 生成报告
    generate_report(results)

if __name__ == "__main__":
    asyncio.run(main())
```

---

## 测试数据样本

### sample_scenario_01.json

```json
{
  "id": "semantic_similarity",
  "description": "语义相同但措辞不同",
  "elder_info": {
    "name": "王奶奶",
    "birth_year": 1950
  },
  "history_turns": [
    {
      "question": "您年轻时在哪里工作？",
      "answer": "我1968年进了上海纺织厂，做挡车工。",
      "existing_events": [
        {
          "event_id": "evt_001",
          "title": "纺织厂工作",
          "summary": "1968年进上海纺织厂做挡车工",
          "time": "1968年",
          "location": "上海纺织厂",
          "people_names": [],
          "theme_id": "career"
        }
      ]
    }
  ],
  "current_answer": "在工厂上班挺辛苦的，三班倒，但那时候年轻不觉得累。",
  "expected": {
    "extracted_events_count": 1,
    "merge_decisions": [
      {
        "action": "UPDATE",
        "target_event_id": "evt_001",
        "confidence_range": [0.75, 1.0]
      }
    ]
  }
}
```

---

## 总结

这些集成测试用例覆盖：
1. **核心场景**: 语义理解、时间匹配、事件区分
2. **边界情况**: 空数据、大量数据、错误处理
3. **性能指标**: 延迟、token用量
4. **回滚验证**: 开关有效性

通过这套测试，可以全面验证方案B的效果，并决定是否全量上线。
