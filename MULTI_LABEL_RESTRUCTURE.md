# Graph RAG 系统重构文档 - 多标签设计

## 问题描述与解决方案

### 发现的问题
1. 大模型只创建Event类型的节点
2. 创建了过多的emotion节点（应为Emotion）
3. emotion_category数据混乱
4. 节点类型未准确区分，影响后续的查询和关联

### 根本原因
- 原系统使用统一的 `:Entity` 标签，仅通过 `type` 属性区分实体类型
- 大模型的提示词对entity_type指导不够明确，导致大模型倾向于默认使用Event
- query_by_text_similarity中必须显式指定entity_type过滤，不够便捷

### 解决方案
采用 **多标签设计**，使用不同的Cypher标签来表示不同的实体类型：
- `:Event` - 事件、故事、经历
- `:Person` - 人物、家庭成员
- `:Location` - 地点、城市、地区
- `:Emotion` - 情感、感受
- `:Topic` - 话题、观点、哲学
- `:Object` - 物品（可选）
- `:TimePeriod` - 时间周期（可选）

---

## 重构变更明细

### 1. neo4j_driver_sync.py 修改

#### 1.1 insert_node 方法
**目的**：根据node_dict中的type字段设置不同的Neo4j标签

**改变**：
```python
# 原来：所有节点都用 :Entity 标签
MERGE (n:Entity {id: $id})

# 改为：根据type自动选择标签
type_label_map = {
    "Event": "Event",
    "Person": "Person",
    "Location": "Location",
    "Emotion": "Emotion",
    "Topic": "Topic",
    ...
}
label = type_label_map.get(node_type, "Entity")
MERGE (n:{label} {id: $id})
```

**优势**：
- Graph database查询更高效（可以直接 MATCH (n:Event) 而不是 MATCH (n:Entity {type: "Event"})）
- 索引和约束更清晰
- 标签-property组合查询更快

#### 1.2 query_by_text_similarity 方法
**改变**：从 MATCH (n:Entity) 改为 MATCH (n)

```python
# 原来
MATCH (n:Entity)
WHERE ...

# 改为
MATCH (n)
WHERE ...
```

**优势**：自动支持任何标签的节点

#### 1.3 其他查询方法
- `get_neighbors()` - 从 :Entity {id: ...} 改为 {id: ...}
- `query_by_hop()` - center查询改为不指定标签
- `get_graph_statistics()` - MATCH (n:Entity) 改为 MATCH (n)

#### 1.4 initialize_schema 方法
**改变**：为每个标签创建约束和索引

```python
# 新增：为每个标签创建独立的约束和索引
label_list = ["Event", "Person", "Location", "Emotion", "Topic", ...]
for label in label_list:
    CREATE CONSTRAINT unique_{label}_id IF NOT EXISTS 
      FOR (e:{label}) REQUIRE e.id IS UNIQUE
    CREATE INDEX idx_{label}_type IF NOT EXISTS 
      FOR (e:{label}) ON (e.type)
    ...
```

**优势**：
- 数据完整性约束更细粒度
- 查询性能更好（标签特定的索引）
- 向后兼容Entity标签

### 2. tools_sync.py 修改

#### 2.1 store_memory_tool 增强
**目的**：帮助大模型正确指定entity_type

**改变**：
1. 添加了type_mapping规范化
   ```python
   entity_type_map = {
       "event": "Event",
       "Event": "Event",
       "事件": "Event",
       "person": "Person",
       "Person": "Person",
       "人物": "Person",
       ...
   }
   ```

2. 改进了文档字符串，明确说明支持的5种类型

3. 返回信息更详细
   ```python
   # 原来
   return f"✓ 已成功存储记忆:\n  类型: {entity_type}\n  ID: {node.id}"
   
   # 改为
   return f"✓ 已成功存储记忆:\n  类型: {normalized_type}\n  名称: {event_name}\n  ID: {node.id}\n  提示: 此信息已保存为{normalized_type}节点"
   ```

**优势**：
- 工具定义更清晰
- LLM能更准确地理解何时使用哪个entity_type
- 返回值更有信息量

### 3. planner_interview_prompts.py 修改

#### 3.1 添加详细的entity_type指南
添加了新的 **"4.2 store_memory_tool 的 entity_type 指南"** 部分

**内容**：
- 清晰的表格说明5种类型的用途和示例
- 常见错误和正确用法
- 4个场景示例（Location、Person、Topic、Emotion）
- 明确标注 ⚠️ 和 ✅

**关键指导**：
```
Event: "高中时在阁楼钞字帖赚钱" ← 事件
Person: "小明" ← 人物
Location: "阁楼" ← 地点
Emotion: "骄傲" ← 情感
Topic: "对教育的理解" ← 观点
```

**优势**：
- 大模型有明确的指示
- 减少类型混淆
- 示例丰富，易于理解

#### 3.2 工具调用流程优化
添加了 **场景A、B、C、D** 的详细工具调用示例

---

## 系统设计对比

### 原设计（单标签）
```
数据库中的所有节点：
├─ :Entity {id: "evt_001", type: "Event", ...}
├─ :Entity {id: "person_002", type: "Person", ...}
├─ :Entity {id: "loc_003", type: "Location", ...}
└─ :Entity {id: "emotion_004", type: "Emotion", ...}

查询方式：
MATCH (n:Entity)
WHERE n.type = "Event"  ← 需要type过滤
```

### 新设计（多标签）
```
数据库中的节点按标签组织：
:Event nodes
├─ {id: "evt_001", type: "Event", ...}
└─ {id: "evt_002", type: "Event", ...}

:Person nodes
├─ {id: "person_001", type: "Person", ...}
└─ {id: "person_002", type: "Person", ...}

:Location nodes
└─ {id: "loc_001", type: "Location", ...}

:Emotion nodes
└─ {id: "emotion_001", type: "Emotion", ...}

查询方式：
MATCH (n:Event)  ← 直接通过标签过滤，更快
```

### 性能对比
| 操作 | 原设计 | 新设计 | 改进 |
|-----|------|------|------|
| 查询特定类型 | `MATCH (n:Entity) WHERE n.type = "Event"` | `MATCH (n:Event)` | 避免全表扫描+过滤 |
| 创建约束 | 1个全局约束 | N个标签约束 | 约束更精确 |
| 创建索引 | 1个全局索引 | N个标签索引 | 索引更专用 |
| 磁盘占用 | 较少 | 略多（但查询快）| 权衡合理 |

---

## 代码示例

### 存储不同类型的节点

#### Event: 存储事件
```python
store_memory_tool(
    event_name="高中时期在阁楼钞字帖赚钱",
    description="为了减轻家庭负担，每天花4小时在阁楼钞写字帖，卖给书法爱好者",
    entity_type="Event",  ← ！明确指定Event
    key_details='{"duration": "3 years", "income": "modest", "audience": "book lovers"}'
)
```

#### Person: 存储人物
```python
store_memory_tool(
    event_name="小明",
    description="童年时期的好友，现在在北京工作，仍保持联系",
    entity_type="Person",  ← ！NOT Event，是Person
    key_details='{"relationship": "childhood friend", "current_city": "Beijing"}'
)
```

#### Location: 存储地点
```python
store_memory_tool(
    event_name="阁楼",
    description="老式房屋的顶楼，放满了旧家具和柜子，光线昏暗",
    entity_type="Location",  ← ！NOT Event，是Location
    key_details='{"type": "attic", "era": "1960s", "condition": "dusty"}'
)
```

#### Emotion: 存储情感
```python
store_memory_tool(
    event_name="对家庭责任的承诺",
    description="尽管生活困难，但心里充满了对家人的责任和保护欲",
    entity_type="Emotion",  ← ！NOT Event，是Emotion
    key_details='{"trigger_events": ["family hardship"], "intensity": "strong"}'
)
```

#### Topic: 存储话题/观点
```python
store_memory_tool(
    event_name="通过劳动实现自我价值",
    description="用自己的双手赚钱，不仅改善了经济状况，更重要的是找到了自我价值",
    entity_type="Topic",  ← ！NOT Event，是Topic/Philosophy
    key_details='{"related_life_stages": ["adolescence", "adulthood"]}'
)
```

---

## 迁移指南（如果有现存数据）

### 清理数据库
```bash
python cleanup_database.py
```

### 自动迁移现存数据（可选）
系统向后兼容，现存的 `:Entity` 节点仍可查询，但建议：
1. 清理现存数据
2. 使用新系统重新录入
3. 这样可以确保Entity节点使用新的标签

---

## 系统限制与约束

### 保留设计
1. 每个节点仍保持 `type` 属性，用于应用层区分
2. 既支持 `:Entity` 标签（向后兼容），也支持新的特定标签
3. 关系(relationships)仍保持原样，不区分源/目标的标签

### 目前不支持
1. 自动将 `:Entity` 节点转换为特定标签（需手动迁移或清理）
2. 跨标签的全局约束

---

## 测试与验证

### 运行测试脚本
```bash
python test_multi_label.py
```

### 预期输出
- ✅ Event节点创建成功，标签为 `:Event`
- ✅ Person节点创建成功，标签为 `:Person`
- ✅ Location节点创建成功，标签为 `:Location`
- ✅ Topic节点创建成功，标签为 `:Topic`
- ✅ 查询返回正确的类型统计
- ✅ 按类型查询过滤正确

---

## 后续优化建议

1. **自动类型推断**：基于entity_name和description自动推断entity_type
2. **查询优化**：为常见查询添加缓存
3. **可视化**：按标签显示不同颜色的节点
4. **数据导入**：为批量导入提供工具
5. **标签验证**：添加schema validation

---

## 重构完成状态

✅ **neo4j_driver_sync.py** - 全部更新
✅ **tools_sync.py** - store_memory_tool增强
✅ **planner_interview_prompts.py** - 详细指导添加  
✅ **向后兼容** - 系统仍支持Entity标签
⏳ **测试** - 建议运行test_multi_label.py验证

---

## 问题排除

### Q: 为什么查询返回类型错误的节点？
A: 检查storemory_tool调用时指定的entity_type或store_memory_tool中的entity_type检测逻辑

### Q: 旧数据如何处理？
A: 运行cleanup_database.py清理所有数据，然后重新创建

### Q: 能否同时支持:Entity和:Event标签？
A: 可以，但不建议，应选其一保持一致

---

更新于: 2026-04-08
作者: System Restructuring Agent
