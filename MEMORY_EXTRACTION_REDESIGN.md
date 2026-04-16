# Memory Extraction Agent 重构方案

**时间**: 2026-04-09  
**状态**: ✅ 设计完成，代码已更新  
**涉及文件**: 2个  

---

## 问题诊断

### 原问题描述
用户反馈memory extraction agent效果"非常糟糕"，主要问题：

1. **去重机制不真实**
   - 只调用向量数据库搜索，没有真正查询图数据库
   - 无法了解现有图的结构和上下文
   - 容易造成错误的merge决策

2. **提取视角不对**
   - Agent没有从访谈者的视角工作
   - 对被采访者的回复没有进行细粒度的逐句分析
   - 容易遗漏重要的信息单元

3. **工具不完善**
   - 只有向量搜索，缺乏图数据库查询工具
   - 无法让Agent真正理解图数据库的现有结构

---

## 解决方案

### 1. 扩展工具集

新增3个工具，真正实现向量+图数据库的联合去重：

#### 工具4：`query_existing_entities_by_type()`
```python
def query_existing_entities_by_type(
    entity_type: str,  # Person|Event|Location|Emotion|Topic
    limit: int = 10
) -> str:
```

**作用**：
- 直接查询Neo4j图数据库中该类型的所有现存节点
- 让Agent真正了解"我们已经有哪些人物/事件/地点"
- 这是**真实的图数据库知识**，不是向量搜索

**返回示例**：
```json
{
  "status": "found",
  "entity_type": "Person",
  "total_count": 3,
  "existing_entities": [
    {
      "node_id": "person_abc123",
      "name": "父亲",
      "description": "采访对象的父亲",
      "created_at": "2026-04-09T10:00:00"
    },
    {
      "node_id": "person_def456",
      "name": "母亲",
      "description": "采访对象的母亲",
      "created_at": "2026-04-09T10:05:00"
    }
  ]
}
```

#### 工具5：`query_related_nodes()`
```python
def query_related_nodes(
    entity_id: str,
    max_depth: int = 2
) -> str:
```

**作用**：
- 查询某个节点在图中的邻域关系
- 帮助Agent理解"这个节点和谁有什么关系"
- 及时发现潜在的merge机会或关系冲突

**返回示例**：
```json
{
  "status": "found",
  "center_node_id": "person_abc123",
  "related_nodes": [
    {
      "node_id": "event_xyz789",
      "name": "在天井教认字",
      "type": "Event",
      "relation_types": ["INVOLVES"],
      "distance": 1
    },
    {
      "node_id": "location_mnp012",
      "name": "天井",
      "type": "Location",
      "relation_types": ["OCCURS_AT"],
      "distance": 1
    }
  ],
  "total_relations": 2
}
```

#### 工具6：`get_graph_overview()`
```python
def get_graph_overview() -> str:
```

**作用**：
- 获取知识图谱的全局统计信息
- 帮助Agent了解图的规模："我们已经有5个人物，8个事件..."
- 为Agent的决策提供全局背景

**返回示例**：
```json
{
  "status": "ok",
  "total_nodes": 18,
  "node_count_by_type": {
    "Person": 5,
    "Event": 8,
    "Location": 3,
    "Emotion": 2,
    "Topic": 0
  },
  "total_relations": 12,
  "relation_count_by_type": {
    "INVOLVES": 6,
    "OCCURS_AT": 4,
    "HAS_EMOTIONAL_TONE": 2
  }
}
```

---

### 2. 重新设计系统提示词 (System Prompt)

#### 核心转变
从"处理提交的文本块"转变为"像访谈记者一样聆听"

#### 新的系统提示词要点

1. **角色定义**
```
"你是一个资深的访谈记者，同时也是一个精准的知识提取员。
你的角色是：从访谈者的角度，认真聆听被采访者的每一句话，
并将其中包含的所有知识、记忆、故事、人物、地点等信息
系统地提取、组织并存入知识图谱。"
```

2. **核心职责：逐句深度提取**
```
每当被采访者说出一句话时，你应该：
1. 拆解这一句话中的语义单元
2. 逐个识别实体
3. 捕捉关系
4. 判断是否需要记录（使用图数据库检查）
```

3. **两层去重机制**
```
第1层：了解现存图结构
- 调用 query_existing_entities_by_type() 查看同类型节点
- 调用 get_graph_overview() 了解全局规模

第2层：向量+图综合判断
- 向量搜索找相似
- 图查询找关系网络
- 冲突检测确认矛盾

第3层：冲突智能处理
- 获取节点详情
- 检测冲突程度
- 决定merge还是create
```

4. **关系识别和链接**
明确每种关系类型的含义和用法：
- **INVOLVES**: 事件涉及的人物（"父亲教我认字" → 父亲 INVOLVES 教认字）
- **OCCURS_AT**: 事件发生的地点（"在天井教我认字" → 教认字 OCCURS_AT 天井）
- **HAS_EMOTIONAL_TONE**: 事件的情感色彩（"美好的回忆" → 回忆 HAS_EMOTIONAL_TONE 美好）
- **KNOWS**: 人物认知关系（"我父亲和他的朋友" → 父亲 KNOWS 朋友）
- **FAMILY_RELATION**: 家庭关系（"我的父亲" → 我 FAMILY_RELATION 父亲）

5. **操作决策树**
清晰的决策流程图：
```
新实体 
  ↓
查询现有同类型节点
  ↓
向量搜索
  ↓
  ├─ 无相似（<0.7）→ create
  ├─ 弱相似（0.7-0.8）→ 查图 + 冲突检测 → create或skip
  ├─ 中等相似（0.8-0.95）→ 查图 + 冲突检测 → merge或skip
  └─ 高度相似（>0.95）→ merge
```

---

### 3. 重新设计增量提取提示词 (Incremental Prompt)

#### 核心转变
从"快速处理每轮回答"转变为"逐句深度分析每轮回答"

#### 新的增量提取提示词要点

1. **第1步：逐句拆解分析**
```
逐句阅读被采访者的答复，找出每一句话中的：
- 人物：谁被提到了？
- 事件：发生了什么？
- 地点：在哪里？
- 情感：有什么感受？
- 观点：表达了什么观点或价值观？

对每一个可提取的信息单元都单独记录（不要笼统）。
```

2. **第2步：利用工具查询现有图结构**
明确的工具调用顺序：
- `get_graph_overview()` - 了解全局情况
- `query_existing_entities_by_type(type)` - 查看该类型已有节点
- `vector_search_similar_nodes(name, type)` - 向量搜索
- `query_related_nodes(node_id)` - 查看节点的关系网络
- `check_conflict_between_nodes()` - 冲突检测

3. **第3步：做出最终决策**
清晰的决策表格：
| 情景 | 决策 | 理由 |
|------|------|------|
| 向量和图都查不到相似 | **create** | 全新的信息 |
| 向量>0.9，图中已存在 | **merge** | 同一实体 |
| 向量0.7-0.8，关系网络不同 | **create** | 不同的实体 |
| 补充/更新现有但本质一致 | **merge** | 合并后丰富 |
| 完全重复 | **skip** | 无需重复 |

4. **第4步：识别关系和链接**

5. **第5步：严格返回JSON**
包含完整的去重上下文、分析过程、决策理由

---

### 4. 重新设计批量提取提示词 (Batch Prompt)

#### 核心转变
从"快速扫描"转变为"系统性梳理"

#### 新的批量提取提示词要点

1. **系统性扫描全文**
- 主要人物及其关系
- 关键事件/故事及其连接
- 重要地点及其关系
- 情感底色和事件情感
- 贯穿的主题和观点

2. **理解全局上下文**
- 先调用 `get_graph_overview()` 了解背景

3. **对每个实体进行去重**
- 先查该类型已有节点
- 再向量搜索
- 然后查图的邻域关系
- 最后冲突检测

4. **识别所有关系**

5. **构建操作方案**

---

## 代码变更

### 文件1：`src/tools/memory_extraction_tools.py`

**变更**：
- 添加 `query_existing_entities_by_type()` 函数
- 添加 `query_related_nodes()` 函数  
- 添加 `get_graph_overview()` 函数
- 更新工具列表，从3个工具扩展到6个

### 文件2：`prompts/memory_extraction_prompts.py`

**变更**：
- 重新设计 `get_memory_extraction_system_prompt()` - 完全重写
- 重新设计 `get_incremental_extraction_prompt()` - 完全重写
- 重新设计 `get_memory_extraction_step_prompt()` - 完全重写

---

## 预期改进

### 改进前
❌ Agent凭向量搜索判断go/no-go  
❌ 只知道"相似"但不知道"为什么相似"  
❌ 容易merge不应该merge的实体  
❌ 对被采访者的回答没有进行细粒度分析  

### 改进后
✅ Agent查询图数据库了解现有结构  
✅ Agent知道"已有5个人物，其中3个有故事关系"  
✅ Agent能基于充分的信息做出正确的merge决策  
✅ Agent对每一句话都进行逐句分析和提取  
✅ Agent能识别细粒度的信息单元  
✅ Agent的每个决策都有充分的理由  

---

## 使用方式

重构完成后，使用方式**完全相同**：

```python
# 增量提取（每轮对话后）
result = extraction_agent.incremental_extract(
    turn_number=1,
    interviewee_response="用户的回答",
    context="背景信息"
)

# 批量提取（访谈完成后）
result = extraction_agent.extract_and_store(full_interview_text)
```

Agent会自动调用全部6个工具，基于真实的图数据库知识做出决策。

---

## 验证方法

### 1. 检查工具是否正确加载
```bash
python -c "from src.tools.memory_extraction_tools import create_memory_extraction_tools; print(len(create_memory_extraction_tools(None)))"
# 应该输出6
```

### 2. 运行采访模拟
```bash
cd Narrative-Planner
python src/simulation/planner_mode.py --turns=3
```

观察日志中：
- Agent是否调用了新工具？
- 去重决策是否更合理？
- 是否有更多的关系被创建？

### 3. 检查Neo4j中的数据
```cypher
MATCH (n) RETURN labels(n), count(*) as count
# 应该看到明显的节点增加

MATCH (n)-[r]->(m) RETURN type(r), count(*) as count
# 应该看到明显的关系增加
```

---

## 下一步优化方向

1. **提示词微调**
   - 根据实际运行结果，调整置信度阈值
   - 优化关系识别的准确性

2. **工具增强**
   - 添加"查询特定关键词的节点"工具
   - 添加"检测循环关系"工具
   - 添加"图遍历"工具用于发现隐藏的关系

3. **决策优化**
   - 基于图的中心性指标优化merge决策
   - 实现more sophisticated的冲突解决策略

4. **性能优化**
   - 缓存图查询结果，避免重复查询
   - 批量工具调用而不是逐个调用

---

## 关键设计原则

**D1: 真实性**
- 去重不是凭直觉，而是基于真实的图数据库查询
- Agent了解"我们真正有什么"，而不是"我想象我们有什么"

**D2: 细粒度**
- 对每一句话都进行分析，而不是笼统处理
- 每个信息单元都单独考虑

**D3: 透明性**
- 每个决策都有充分的理由
- 包含deduplication_analysis字段，记录决策过程

**D4: 访谈者视角**
- Agent像访谈记者一样聆听被采访者
- 系统地组织和记录所有重要信息

---

## 常见问题

**Q: 为什么要同时调用向量搜索和图查询？**
A: 向量搜索和图查询是互补的：
- 向量搜索基于语义相似性，找到"名字相似"的节点
- 图查询基于结构关系，找到"在图中的位置"
- 两者结合才能做出正确的去重决策

**Q: 工具调用会不会太多，影响性能？**
A: 
- 每轮对话最多10-20个新实体，工具调用可控
- 可以通过缓存进一步优化
- 质量优先于速度

**Q: deduplication_context有什么用？**
A: 这是Agent做决策的"思考过程"：
- 供日后audit和debug
- 帮助理解为什么做了某个merge决策
- 用于系统改进和算法优化

