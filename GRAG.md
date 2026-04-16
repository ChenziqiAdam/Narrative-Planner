# Graph RAG 记忆系统 - 完整系统分析

## 目录
1. [系统概览](#系统概览)
2. [架构设计](#架构设计)
3. [核心组件详解](#核心组件详解)
4. [数据模型](#数据模型)
5. [查询机制](#查询机制)
6. [工具层接口](#工具层接口)
7. [数据流与隔离](#数据流与隔离)
8. [关系网络](#关系网络)
9. [核心算法](#核心算法)
10. [性能考虑](#性能考虑)

---

## 1. 系统概览

### 目的
Graph RAG（Retrieval-Augmented Generation）记忆系统是一个为**老年回忆录访谈**设计的知识图实现，旨在：
1. **即时存储**被访者的讲述内容（事件、人物、地点、情感、主题等）
2. **自动建立关系**在不同概念之间（例如：事件→参与人 → 情感）
3. **支持智能查询**通过多种方式检索已有的记忆（相似度、跳数、模式）
4. **辅助访谈决策**为 Planner Agent 提供背景信息，优化下一步的提问
5. **完整隔离**多采访数据，避免不同采访间的数据污染

### 整体架构
```
                 CAMEL Agent
                    (Planner)
                      |
        ┌─────────────┼─────────────┐
        ↓             ↓             ↓
   query_memory   store_memory  get_entity_context
   tool           tool          tool (+ 3 others)
        |             |             |
        └─────────────┴─────────────┘
                      ↓
            tools_sync.py
        (5 个工具的定义和包装)
                      ↓
            manager_sync.py
      (业务逻辑与工具实现)
                      ↓
       neo4j_driver_sync.py
      (底层数据库操作)
                      ↓
            Neo4j 5.x Graph DB
          (持久化存储)
```

**关键特点**：
- ✅ **同步 API**：无 asyncio 复杂度，直接使用 neo4j 官方同步驱动
- ✅ **多层隔离**：采访 ID 贯穿全调用链，数据库层面过滤
- ✅ **丰富节点模型**：Event、Person、Location、Emotion、Topic、Insight 共6种
- ✅ **自动关系创建**：存储事件时自动为参与者、位置、情感创建节点和边
- ✅ **Hop 查询**：支持 N 跳范围的邻域探索（1-5 跳）

---

## 2. 架构设计

### 2.1 四层架构

```
┌─────────────────────────────────────────────────────┐
│  应用层 (Application Layer)                         │
│  - Agent Tools 接口                                 │
│  - 为 LLM/Agent 提供的 5 个工具函数                 │
└────────────────┬────────────────────────────────────┘
                 │
┌────────────────▼────────────────────────────────────┐
│  业务逻辑层 (Manager Layer)                         │
│  - EnhancedGraphMemoryManager                       │
│  - 节点创建、查询、模式检测                         │
│  - 采访 ID 隔离逻辑                                 │
└────────────────┬────────────────────────────────────┘
                 │
┌────────────────▼────────────────────────────────────┐
│  数据访问层 (Driver Layer)                          │
│  - Neo4jGraphDriver                                 │
│  - 原生 Cypher 查询、关系创建、索引管理            │
│  - 连接池、事务管理                                 │
└────────────────┬────────────────────────────────────┘
                 │
┌────────────────▼────────────────────────────────────┐
│  存储层 (Storage Layer)                             │
│  - Neo4j 5.x 图数据库                              │
│  - Bolt 协议 (bolt://localhost:7687)               │
└─────────────────────────────────────────────────────┘
```

### 2.2 设计原则

| 原则 | 实现 | 优势 |
|-----|------|------|
| **单标签设计** | 所有节点都是 `:Entity`，用 `type` 属性区分 | 统一的查询接口，灵活的过滤 |
| **采访隔离** | 每个节点都有 `source_interview_id` 字段 | 多采访零污染，数据库层面保证 |
| **自动关系** | 创建 Event 时自动为参数创建相应节点和关系 | 减少 Agent 认知负担，保证数据完整 |
| **Hop 查询** | 统一的 N 跳邻域查询机制 | 清晰的分层结构，易于理解关联 |
| **富文本模型** | 每种实体有专门的 dataclass，属性完整 | 捕捉访谈的丰富细节 |
| **同步 API** | 使用官方 neo4j 同步驱动，无 asyncio | 实现简单，易于调试，无死锁风险 |

---

## 3. 核心组件详解

### 3.1 Neo4jGraphDriver (neo4j_driver_sync.py)

#### 初始化与连接
```python
class Neo4jGraphDriver:
    def __init__(self, uri="bolt://localhost:7687", username="neo4j", password="password", database="neo4j"):
        """
        初始化 Neo4j 驱动
        
        参数说明：
        - uri: Bolt 协议连接字符串，格式为 bolt://host:port
        - username/password: 认证凭据
        - database: 目标数据库名
        
        关键变量：
        - self.driver: neo4j.GraphDatabase.driver 实例，维护连接池
        - self._connection_attempted: 防止重复连接尝试的标志
        """
```

**代码详解**：
```python
def connect(self):
    """建立同步连接"""
    from neo4j import GraphDatabase
    
    # 创建驱动，自动管理连接池（最多50个连接）
    self.driver = GraphDatabase.driver(
        self.uri,
        auth=(self.username, self.password),
        max_connection_pool_size=50  # 池大小优化
    )
    
    # 验证连接可用性
    with self.driver.session(database=self.database) as session:
        result = session.run("RETURN 1")
        result.consume()  # 强制执行以触发网络往返
```

#### 核心查询方法
```python
def _execute_query(self, query: str, params: Dict = None):
    """执行单个 Cypher 查询"""
    
    # 关键步骤：
    # 1. 确保连接已建立（自动连接）
    self._ensure_connected()
    
    # 2. 创建会话并执行查询
    with self.driver.session(database=self.database) as session:
        result = session.run(query, params or {})
        
        # 3. 转换结果为列表（Record → Dict）
        records = [dict(record) for record in result]
        
    return records
```

**关键点**：
- 使用上下文管理器自动管理会话生命周期
- 将 `Record` 对象转换为字典以便返回
- 参数化查询防止 Cypher 注入

#### 节点插入：单标签策略
```python
def insert_node(self, node_dict: Dict[str, Any]) -> bool:
    """
    插入或更新节点
    
    设计特点：
    - 所有节点都标记为 :Entity 标签（统一）
    - 通过 type 属性区分实体类型（Event、Person、Location 等）
    - 使用 MERGE 避免重复
    - 完整属性 SET 确保覆盖旧值
    """
    
    query = """
    MERGE (n:Entity {id: $id})           # 唯一标识符是 id
    SET n += $properties                  # 合并所有属性
    RETURN n
    """
    
    params = {
        "id": node_dict.get("id"),
        "properties": node_dict              # 包含 type、name、description 等
    }
```

**为什么选择单标签**？
- ❌ 坏方案：每个节点用不同标签 (`:Event`, `:Person`, `:Location`)
  - 问题：查询时必须 `MATCH (n:Event | :Person | :Location)` 很繁琐
  - 问题：新增节点类型需要修改所有查询
  
- ✅ 好方案：所有用 `:Entity` 标签，用属性区分
  - 优点：统一的 `MATCH (n:Entity)` 查询接口
  - 优点：灵活可扩展，新增类型无需改查询
  - 优点：可以轻松过滤：`WHERE n.type = "Event"`

#### 关系创建
```python
def insert_edge(self, source_id: str, target_id: str, relation_type: str, properties: Dict = None):
    """
    创建关系
    
    设计：
    - relation_type 直接成为关系的类型 (INVOLVES、OCCURS_AT、HAS_EMOTIONAL_TONE)
    - properties 存储关系的额外属性 (role、 weight 等)
    """
    
    query = f"""
    MATCH (source {{id: $source_id}})
    MATCH (target {{id: $target_id}})
    MERGE (source)-[r:{relation_type}]->(target)
    SET r += $properties
    RETURN r
    """
```

**自动关系类型**（在 Manager 层创建）：
- `Event --INVOLVES--> Person`：事件涉及的人物
- `Event --OCCURS_AT--> Location`：事件发生的地点
- `Event --HAS_EMOTIONAL_TONE--> Emotion`：事件的情感基调

#### Hop 查询（核心算法）
```python
def query_by_hop(self, node_id: str, hop_count: int = 1, interview_id = None, max_nodes: int = 100):
    """
    查询 N 跳范围的邻域
    
    返回结构：
    {
        "center": {...},                     # 中心节点
        "neighbors_by_hop": {
            1: [节点...],                   # 1跳邻域
            2: [节点...],                   # 2跳邻域
            ...
        },
        "relationships": [关系列表],         # 所有关系
        "total_nodes": 总数,
        "total_relations": 总数
    }
    """
    
    # 步骤 1：获取中心节点
    center_query = "MATCH (center:Entity {id: $node_id}) RETURN center"
    center_result = self._execute_query(center_query, {"node_id": node_id})
    
    # 步骤 2：为每个 hop 获取邻域（距离恰好为 hop 的节点）
    for hop in range(1, hop_count + 1):
        neighbor_query = f"""
        MATCH (center:Entity {{id: $node_id}})
        MATCH (center)-[*{hop}]-(neighbor:Entity)      # 恰好 hop 步的路径
        WHERE neighbor.id <> $node_id
        {f"AND neighbor.source_interview_id = $interview_id" if interview_id else ""}
        WITH DISTINCT neighbor LIMIT $max_nodes
        RETURN 
            neighbor.id, neighbor.type, neighbor.name, 
            neighbor.description, neighbor.confidence
        """
        hop_result = self._execute_query(neighbor_query, params)
        result["neighbors_by_hop"][hop] = hop_result
    
    # 步骤 3：获取所有关系
    relation_query = f"""
    MATCH (center:Entity {{id: $node_id}})
    MATCH path = (center)-[*1..{hop_count}]-(neighbor)
    WHERE neighbor.id <> $node_id
    {f"AND neighbor.source_interview_id = $interview_id" if interview_id else ""}
    UNWIND relationships(path) as rel
    WITH DISTINCT 
        startNode(rel).id as source_id,
        type(rel) as relation_type,
        endNode(rel).id as target_id
    RETURN source_id, relation_type, target_id
    LIMIT 1000
    """
```

**Hop 查询的妙处**：
- 使用 `*1..n` 符号（可变长度路径）高效地匹配 N 跳路径
- `DISTINCT neighbor` 防止同一节点在多条路径上重复
- 采访隔离通过 `WHERE` 子句在关系中也生效
- 分层返回（按 hop 分组）使得可视化和理解更清晰

---

### 3.2 EnhancedGraphMemoryManager (manager_sync.py)

#### 初始化
```python
class EnhancedGraphMemoryManager:
    def __init__(self, neo4j_uri="bolt://localhost:7687", neo4j_user="neo4j", 
                 neo4j_password="capstone2024", max_cache_size=1000):
        """
        初始化记忆管理器
        
        特点：
        - self.driver: Neo4jGraphDriver 实例
        - self.node_cache: 本地缓存，加快重复查询
        - self.max_cache_size: 缓存上限
        """
        self.driver = Neo4jGraphDriver(uri, user, password)
        self.node_cache = {}              # 本地缓存（ID → Node）
        self._initialized = False
```

#### 节点创建的核心逻辑：create_event_node
```python
def create_event_node(
    self,
    name: str,
    description: str,
    category="",
    locations=None,              # 地点列表
    participants=None,           # 参与者列表
    emotional_tone=None,         # 情感列表
    time_frame="",
    significance_level="medium",
    interview_id="",
    turn=0,
    **extra_attributes
) -> models.EventNode:
    """
    创建事件节点，并自动为相关实体创建子节点和关系
    
    流程：
    1. 创建 EventNode dataclass 实例
    2. 将其序列化为字典，清理不可序列化字段
    3. 插入到 Neo4j
    4. 遍历 participants，为每个创建 Person 节点 + INVOLVES 关系
    5. 遍历 locations，为每个创建 Location 节点 + OCCURS_AT 关系
    6. 遍历 emotional_tone，为每个创建 Emotion 节点 + HAS_EMOTIONAL_TONE 关系
    """
    
    # 步骤 1：创建 EventNode 实例
    event = models.EventNode(
        id=f"evt_{uuid.uuid4().hex[:8]}",        # 生成唯一 ID
        name=name,
        description=description,
        event_category=category,
        locations=locations or [],                # 地点 ID 列表
        participants=participants or [],          # 参与者 ID 列表
        emotional_tone=emotional_tone or [],      # 情感 ID 列表
        source_interview_id=interview_id,         # 采访隔离关键字段
        source_turn=turn,                         # 轮次
        confidence=0.8                            # 默认置信度
    )
    
    # 步骤 2：序列化并清理
    from dataclasses import asdict
    node_dict = asdict(event)                     # EventNode → Dict
    node_dict = self._sanitize_node_dict(node_dict)  # 处理复杂对象
    
    # 步骤 3：插入事件节点到 Neo4j
    if self.driver:
        self.driver.insert_node(node_dict)
    
    # 步骤 4-6：自动创建相关节点和关系
    if participants:
        for participant_name in participants:
            person = self.create_person_node(
                name=participant_name,
                description=f"Participant in event: {event.name}",
                interview_id=interview_id,
                turn=turn
            )
            # 创建 Event --INVOLVES--> Person 关系
            self.driver.insert_edge(
                source_id=event.id,
                target_id=person.id,
                relation_type="INVOLVES",
                properties={"role": "participant"}
            )
    
    if locations:
        for location_name in locations:
            location = self.create_location_node(
                name=location_name,
                description=f"Location of event: {event.name}",
                interview_id=interview_id
            )
            # 创建 Event --OCCURS_AT--> Location 关系
            self.driver.insert_edge(
                source_id=event.id,
                target_id=location.id,
                relation_type="OCCURS_AT",
                properties={"role": "primary_location"}
            )
    
    if emotional_tone:
        for emotion_name in emotional_tone:
            emotion = self.create_emotion_node(
                name=emotion_name,
                description=f"Emotional tone in event: {event.name}",
                interview_id=interview_id
            )
            # 创建 Event --HAS_EMOTIONAL_TONE--> Emotion 关系
            self.driver.insert_edge(
                source_id=event.id,
                target_id=emotion.id,
                relation_type="HAS_EMOTIONAL_TONE",
                properties={}
            )
    
    return event
```

**关键设计**：
- ✅ **自动关系创建**：Agent 只需指定参与者列表，Manager 自动建立所有关系
- ✅ **递归初始化**：每个参与者、地点、情感都被创建为独立节点
- ✅ **采访隔离**：每个子节点都继承父节点的 `source_interview_id`
- ✅ **无 Agent 负担**：Agent 无需显式调用多个 tool，一个 store_memory_tool 搞定

#### 数据清理：_sanitize_node_dict
```python
def _sanitize_node_dict(self, node_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    清理节点字典，确保所有值都能被 Neo4j 序列化
    
    Neo4j 支持的基本类型：str, int, float, bool, None, list
    其他复杂类型（datetime, dict, 自定义对象）需要序列化
    """
    
    sanitized = {}
    
    for key, value in node_dict.items():
        if value is None:
            sanitized[key] = None
        elif isinstance(value, (str, int, float, bool)):
            # 基本类型直接保留
            sanitized[key] = value
        elif isinstance(value, (list, tuple)):
            # 列表：检查是否全是基本类型
            if all(isinstance(x, (str, int, float, bool, type(None))) for x in value):
                sanitized[key] = list(value)
            else:
                # 包含复杂对象，序列化为 JSON
                sanitized[f"{key}_json"] = json.dumps(value, default=str)
        elif isinstance(value, dict):
            # 字典成列化为 JSON
            sanitized[key] = json.dumps(value)
        elif isinstance(value, datetime):
            # datetime 转 ISO 格式字符串
            sanitized[key] = value.isoformat()
        else:
            # 其他类型尝试 JSON 序列化（包括 dataclass 等）
            try:
                sanitized[f"{key}_json"] = json.dumps(value, default=str)
            except:
                sanitized[f"{key}_str"] = str(value)
    
    return sanitized
```

#### 查询接口：三种方式
```python
# 方式 1：文本相似度查询
def query_by_text_similarity(self, text: str, entity_type=None, top_k=10, interview_id=None):
    """
    基于文本相似度查询
    委托给 driver 层实现
    """
    return self.driver.query_by_text_similarity(
        text=text,
        entity_type=entity_type,
        max_results=top_k,
        interview_id=interview_id
    )

# 方式 2：邻域查询（旧方式，已弃用）
def get_entity_neighbors(self, entity_id: str, max_depth: int = 2, relation_types=None):
    """获取邻域（简单版本）"""
    return self.driver.get_neighbors(
        node_id=entity_id,
        max_depth=max_depth,
        relation_types=relation_types
    )

# 方式 3：Hop 查询（新方式，推荐）
def get_entity_by_hop(self, entity_id: str, hop_count: int = 2, interview_id=None, max_nodes: int = 100):
    """
    获取 N 跳范围的邻域（分层结构）
    
    优点：
    - 清晰的分层结构（neighbors_by_hop[1]、neighbors_by_hop[2]等）
    - 自动生成关系统计
    - 支持采访隔离
    """
    return self.driver.query_by_hop(
        node_id=entity_id,
        hop_count=hop_count,
        interview_id=interview_id,
        max_nodes=max_nodes
    )
```

#### 模式检测：detect_patterns
```python
def detect_patterns(self, interview_id="", pattern_type="all"):
    """
    检测访谈中的行为模式
    
    实现逻辑（伪代码）：
    1. 查询该采访的所有事件节点
    2. 提取共同的参与者、地点、情感、话题
    3. 识别重复出现的组合
    4. 返回模式列表
    """
    
    # 实际需要额外的 Cypher 查询来实现
    # 这里是框架，具体实现可选
    patterns = []
    
    # 获取该采访的所有事件
    query = """
    MATCH (e:Entity {source_interview_id: $interview_id, type: "Event"})
    WITH e
    SET e.mention_count = CASE WHEN e.mention_count IS NULL THEN 1 ELSE e.mention_count + 1 END
    RETURN e
    """
    
    return patterns  # 返回检测到的模式
```

---

### 3.3 Tools Layer (tools_sync.py)

#### 五个工具的详解

**工具 1：query_memory_tool**
```python
def query_memory_tool(query_text: str, entity_type: str = "all", max_results: int = 5) -> str:
    """
    功能：根据关键词查询已有的记忆
    
    参数：
    - query_text: 查询关键词（如"童年"、"父亲"）
    - entity_type: 限定实体类型（"Event"、"Person" 等，"all" 为不限制）
    - max_results: 最多返回多少个结果
    
    流程：
    1. 调用 manager.query_by_text_similarity()
    2. 格式化结果为可读的文本
    3. 返回给 Agent
    
    返回格式：
    "以下是匹配的记忆信息：
    【结果 1】
    类型: Event
    名称: 童年在山东
    描述: 与小伙伴在河边玩耍...
    
    【结果 2】
    ..."
    
    使用场景：
    - Agent 想检查是否讨论过某个话题
    - Agent 想找到相关的过去讲述来支撑当前决策
    """
```

**工具 2：store_memory_tool**
```python
def store_memory_tool(
    event_name: str,
    description: str,
    entity_type: str = "Event",
    key_details: Optional[str] = None  # JSON 字符串
) -> str:
    """
    功能：显式存储新的讲述到知识图谱
    
    参数：
    - event_name: 事件/概念的名称
    - description: 详细描述
    - entity_type: 节点类型（"Event"、"Person"、"Location"、"Emotion"、"Topic"）
    - key_details: 额外属性（JSON 字符串，如 '{"emotion_tone": ["sad"], "location": "京城"}'）
    
    流程：
    1. 解析 key_details JSON（如果提供）
    2. 根据 entity_type 调用对应的 create_XXX_node()
    3. 返回创建成功的消息和 ID
    
    返回格式：
    "✓ 已成功存储记忆:
      类型: Event
      名称: 高中时期的阁楼抄写
      ID: evt_abc12345"
    
    使用场景：
    - **最重要的工具**：每轮对话都要调用
    - Agent 识别到关键讲述时（事件、人物重现、话题新见解）
    - 即时入库，后续可通过 hop 查询找到关联
    """
```

**工具 3：get_interview_summary_tool**
```python
def get_interview_summary_tool() -> str:
    """
    功能：获取当前采访的统计摘要
    
    无参数：使用当前采访 ID（来自闭包）
    
    流程：
    1. 调用 manager.get_graph_statistics(interview_id)
    2. 返回节点总数、类型分布、关系总数等
    
    返回格式：
    "【访谈摘要】(采访ID: interview_abc123)
    
    统计信息:
      - total_nodes: 18
      - entities_by_type: {'Event': 8, 'Person': 5, 'Location': 3, 'Emotion': 2}
      - relations_by_type: {'INVOLVES': 10, 'OCCURS_AT': 8}"
    
    使用场景：
    - 对话开始时，快速评估已收集的信息量
    - 中期检查，了解覆盖了哪些话题领域
    - 决策：如果覆盖率足够，考虑 CLOSE_INTERVIEW；如果太片面，选择 BREADTH_SWITCH
    """
```

**工具 4：detect_patterns_tool**
```python
def detect_patterns_tool(pattern_type: str = "all") -> str:
    """
    功能：检测已存储讲述中的行为模式
    
    参数：
    - pattern_type: 模式类型（可选值待定义）
    
    流程：
    1. 调用 manager.detect_patterns(interview_id, pattern_type)
    2. 分析：
       - 重复出现的人物
       - 常见的情感组合
       - 跨时期的相似事件
       - 价值观的表现
    3. 格式化返回
    
    返回格式：
    "【检测到的行为模式】:
    
    1. 父权式权威陷阱
       类型: behavioral
       原因: 在家庭场景、工作场景都提到被父亲/领导压制的感受
    
    2. 乐观克服困难
       类型: emotional
       原因: 虽然经历贫困和战乱，总是用前进的态度面对"
    
    使用场景：
    - 了解被访者的深层性格特质
    - 发现重复的人生主题
    - 决策：若发现重要模式未充分探索，选择 DEEP_DIVE；若模式已清晰，可考虑其他话题
    """
```

**工具 5：get_entity_context_tool**  ⭐ 最重要
```python
def get_entity_context_tool(entity_id: str, hop_count: int = 2) -> str:
    """
    功能：查询某个实体的 N 跳邻域关联网络
    
    参数：
    - entity_id: 实体 ID（如 "evt_xyz"、"person_abc"）
    - hop_count: 跳数（1-5），决定邻域深度
    
    流程：
    1. 调用 manager.get_entity_by_hop(entity_id, hop_count, interview_id)
    2. 获得中心节点和分层邻域
    3. 精美格式化输出
    
    返回格式：
    "【中心实体】
      ID: evt_abc123
      类型: Event
      名称: 高中时期在阁楼钞写赚钱
      描述: 为了减轻家里负担，在阁楼里...
    
    【1跳邻域节点】(3个)
      1. 父亲 (Person)
      2. 阁楼 (Location)
      3. 困难援助 (Emotion)
    
    【2跳邻域节点】(5个)
      1. 母亲 (Person)
      2. 贫困时期 (Topic)
      3. 责任感 (Emotion)
      4. 学习能力 (Topic)
      5. 高中 (Location)
    
    【关系统计】
      - INVOLVES: 4 条
      - OCCURS_AT: 2 条
      - HAS_EMOTIONAL_TONE: 1 条
    
    【统计信息】
      总节点数: 9
      总关系数: 7"
    
    使用场景：
    - **核心工具**：完整理解一个讲述的背景
    - 需要探索话题关联时
    - 构建知识图谱的关键工具
    - 决策：根据邻域关联决定下一步提问方向
    """
```

#### 工具创建与返回
```python
def create_graph_memory_tools(memory_manager, interview_id: str = "default_interview"):
    """
    创建工具集
    
    关键特点：
    1. 闭包：每个工具都可以访问 memory_manager 和 interview_id
    2. interview_id 自动传递到所有工具，无需 Agent 重复指定
    3. FunctionTool 包装：将 Python 函数转换为 CAMEL 工具
    
    返回：
    tools = [
        FunctionTool(query_memory_tool),
        FunctionTool(store_memory_tool),
        FunctionTool(get_interview_summary_tool),
        FunctionTool(detect_patterns_tool),
        FunctionTool(get_entity_context_tool),
    ]
    """
    
    # 所有工具都通过闭包访问 memory_manager 和 interview_id
    # 不需要作为工具参数
    
    tools = [
        FunctionTool(query_memory_tool),
        # ... 其他工具
    ]
    
    return tools
```

---

## 4. 数据模型

### 4.1 核心 Dataclass（models.py）

整个系统定义了 6 种实体类型，每种都有详细的属性：

#### EnhancedGraphNode（基类）
```python
@dataclass
class EnhancedGraphNode:
    """所有实体的基类"""
    
    # 唯一标识
    id: str                                    # 全局唯一，格式：type_xxxxx
    type: str                                  # Event、Person、Location 等
    name: str                                  # 实体名称
    description: str                           # 实体描述
    
    # 元数据
    confidence: float = 0.8                    # 信息置信度
    source_type: str = "extraction"            # 来源类型
    source_interview_id: str = ""              # ⭐ 采访隔离关键字段
    source_turn: int = 0                       # 来自哪一轮
    
    # 时间戳
    created_at: str                            # ISO 格式创建时间
    first_mentioned: str                       # 首次提及时间
    last_updated: str                          # 最后更新时间
    
    # 使用统计
    mention_count: int = 1                     # 被提及几次
    reference_count: int = 0                   # 被引用几次
    
    # 质量指标
    is_conflicted: bool = False                # 是否存在冲突信息
    is_verified: bool = False                  # 是否已验证
    
    # 关系（指向其他实体 ID）
    parent_entity_id: Optional[str] = None     # 父实体
    related_entity_ids: List[str] = []         # 相关实体
```

#### EventNode（事件）
```python
@dataclass
class EventNode(EnhancedGraphNode):
    """事件/故事片段"""
    
    type: str = "Event"                        # 固定值
    
    event_category: str = ""                   # childhood、career、family
    time_frame: str = ""                       # "1960-1970"、"1980s"
    time_precision: str = "approximate"        # exact、approximate、range
    
    locations: List[str] = []                  # 涉及的地点 ID（自动创建和建立 OCCURS_AT）
    participants: List[str] = []               # 参与者 ID（自动创建和建立 INVOLVES）
    emotional_tone: List[str] = []             # 情感 ID（自动创建和建立 HAS_EMOTIONAL_TONE）
    
    primary_location: str = ""                 # 主要地点
    primary_actor: str = ""                    # 主角
    
    significance_level: str = "medium"         # low、medium、high、critical
    significance_reason: str = ""              # 重要性原因
    
    key_details: Dict[str, Any] = {}           # 关键细节（灵活的、补充的）
    
    # 事件间关系
    is_elaboration_of: Optional[str] = None    # 补充了某个事件
    has_elaborations: List[str] = []           # 被补充的列表
    contradicts: List[str] = []                # 与哪些事件矛盾
    
    trigger_event: Optional[str] = None        # 原因事件
    consequence_events: List[str] = []         # 结果事件
```

**EventNode 示例**：
```json
{
  "id": "evt_abc12345",
  "type": "Event",
  "name": "高中时期在阁楼钞写赚钱",
  "description": "我高中时期为了减轻家庭负担，每天在顶楼的阁楼里钞写字帖，卖给别人赚钱...",
  "event_category": "adolescence",
  "time_frame": "1965-1967",
  "locations": ["loc_xyz789"],                 # 指向"阁楼"节点
  "participants": ["person_father"],           # 指向"父亲"节点
  "emotional_tone": ["emotion_responsibility", "emotion_pride"],  # 指向情感节点
  "source_interview_id": "interview_elder_001",
  "source_turn": 5,
  "significance_level": "high"
}
```

#### PersonNode（人物）
```python
@dataclass
class PersonNode(EnhancedGraphNode):
    """人物/角色"""
    
    type: str = "Person"
    
    gender: Optional[str] = None               # male、female
    age_mentioned: Optional[str] = None        # "around 70"
    
    role_in_story: str = ""                    # friend、family、colleague
    relationship_to_elder: str = ""            # 与受访者的关系
    
    traits: List[str] = []                     # kind、hardworking、intelligent
    
    knows_people: List[str] = []               # 认识的其他人物 ID
    family_relations: Dict[str, List[str]] = {}  # {relation_type: [person_ids]}
    
    locations_lived: List[str] = []            # 住过的地点 ID
    occupations: List[str] = []                # 职业列表
    
    memorable_stories: List[Dict] = []         # [{title, description}]
    key_quotes: List[Dict] = []                # [{quote, context}]
    
    current_status: Optional[str] = None       # alive、deceased
    last_contact: Optional[str] = None         # "5 years ago"
    
    first_mentioned_in_turn: int = 0           # 首次提及的轮次
    mention_sentiment: str = "neutral"         # positive、negative、mixed
```

#### LocationNode（地点）
```python
@dataclass
class LocationNode(EnhancedGraphNode):
    """地点/场所"""
    
    type: str = "Location"
    
    location_type: str = ""                    # province、city、building、room
    country: str = ""                          # 国家
    
    time_periods_lived: List[str] = []         # 在这里生活的时期
    
    characteristics: List[str] = []            # rural、urban、poor、developed
    cultural_significance: str = ""            # 文化意义
    emotional_significance: str = ""           # 情感意义（nostalgia、hardship）
    
    landmark_features: Dict[str, str] = {}     # {feature: description}
    notable_places: List[str] = []             # 子地点
    
    life_events_here: List[str] = []           # 发生在此的事件 ID
    daily_activities: List[str] = []           # 日常活动
    
    frequency_of_visits: str = ""              # daily、weekly、occasionally
    last_visit: Optional[str] = None           # "10 years ago"
    still_connected: bool = False              # 现在是否还有联系
```

#### EmotionNode（情感）
```python
@dataclass
class EmotionNode(EnhancedGraphNode):
    """情感/心理状态"""
    
    type: str = "Emotion"
    
    emotion_category: str = ""                 # joy、sadness、nostalgia、gratitude
    emotion_subcategory: Optional[str] = None  # 细粒度分类
    valence: str = "neutral"                   # positive、negative、neutral
    
    intensity: float = 0.5                     # 强度 (0-1)
    persistence: str = "temporary"             # temporary、persistent、cyclical
    
    triggered_by: List[str] = []               # 触发实体 ID
    manifest_behaviors: List[str] = []         # 表现行为（cried、laughed）
    
    related_emotions: List[str] = []           # 关联情感 ID
    contrasting_emotions: List[str] = []       # 对立情感 ID
```

#### TopicNode（话题）
```python
@dataclass
class TopicNode(EnhancedGraphNode):
    """话题/主题（缩写版本）"""
    
    type: str = "Topic"
    
    topic_category: str = ""                   # education、family、work
    topic_priority: str = "medium"             # high、medium、low
    
    core_message: str = ""                     # 核心观点
    key_beliefs: List[str] = []                # 信念
    values_expressed: List[str] = []           # 价值观
    
    related_events: List[str] = []             # 相关事件 ID
    related_people: List[str] = []             # 相关人物 ID
    related_locations: List[str] = []          # 相关地点 ID
```

#### InsightNode（洞察）
```python
@dataclass
class InsightNode(EnhancedGraphNode):
    """AI 提取的高级发现/模式"""
    
    type: str = "Insight"
    
    insight_type: str = ""                     # pattern、contradiction、theme
    insight_category: str = ""                 # behavioral、emotional、relational
    
    title: str = ""                            # 洞察标题
    detailed_description: str = ""             # 详细解释
    evidence_level: str = "medium"             # weak、medium、strong
    
    supporting_events: List[str] = []          # 支持的事件 ID
    supporting_quotes: List[Dict] = []         # 引用
    
    confidence_score: float = 0.7              # 置信度
    validation_status: str = "unverified"      # unverified、confirmed
```

---

## 5. 查询机制

### 5.1 查询层级与策略

| 查询方式 | 实现位置 | 适用场景 | 采访隔离 |
|---------|--------|--------|--------|
| **文本相似度** | driver.query_by_text_similarity() | 快速找到相关的过去讲述 | ✅ |
| **邻域查询（旧）** | driver.get_neighbors() | 简单的邻域探索 | ❌ |
| **Hop 查询（推荐）** | driver.query_by_hop() | 完整的分层关联网络 | ✅ |
| **图统计** | manager.get_graph_statistics() | 了解已收集的信息量 | ✅ |
| **模式检测** | manager.detect_patterns() | 识别行为规律 | ✅ |

### 5.2 文本相似度查询（Neo4j 5.x 向量能力）

```python
# 实现位置：neo4j_driver_sync.py (lines ~500)
def query_by_text_similarity(self, text, entity_type=None, max_results=10, interview_id=None):
    """
    基于向量相似度查询
    
    原理：
    1. 计算输入 text 的向量表示
    2. 查询 Neo4j 中所有节点，计算相似度
    3. 按相似度排序，返回 top-k
    4. 如指定 interview_id，额外过滤
    
    Cypher 示例（简化）：
    MATCH (n:Entity)
    WHERE n.source_interview_id = $interview_id  # 采访隔离
    AND (n.type = $entity_type OR $entity_type IS NULL)  # 类型过滤
    WITH n, gds.similarity.cosine(
        gds.ml.hashgnn.encode($text),              # 用户输入向量
        gds.ml.hashgnn.encode(n.name + ' ' + n.description)  # 节点向量
    ) as similarity
    RETURN n, similarity
    ORDER BY similarity DESC
    LIMIT $max_results
    """
    
    # 实际实现可能使用 Cypher 函数或 Python embedding
```

### 5.3 Hop 查询的详细 Cypher

```cypher
# 步骤 1：获取中心节点
MATCH (center:Entity {id: 'evt_abc123'})
RETURN center

# 步骤 2：获取 1 跳邻域（直接相邻）
MATCH (center:Entity {id: 'evt_abc123'})
MATCH (center)-[*1]-(neighbor:Entity)
WHERE neighbor.id <> 'evt_abc123'
AND neighbor.source_interview_id = 'interview_001'  # 采访隔离
WITH DISTINCT neighbor LIMIT 100
RETURN neighbor

# 步骤 3：获取 2 跳邻域
MATCH (center:Entity {id: 'evt_abc123'})
MATCH (center)-[*2]-(neighbor:Entity)
WHERE neighbor.id <> 'evt_abc123'
AND neighbor.source_interview_id = 'interview_001'
WITH DISTINCT neighbor LIMIT 100
RETURN neighbor

# 步骤 4：获取所有关系（在 hop 范围内）
MATCH (center:Entity {id: 'evt_abc123'})
MATCH path = (center)-[*1..2]-(neighbor)
WHERE neighbor.id <> 'evt_abc123'
AND neighbor.source_interview_id = 'interview_001'
UNWIND relationships(path) as rel
WITH DISTINCT 
    startNode(rel).id as source_id,
    type(rel) as relation_type,
    endNode(rel).id as target_id
RETURN source_id, relation_type, target_id
LIMIT 1000
```

---

## 6. 工具层接口

### 6.1 五个工具的完整接口参考

```python
# 工具 1：查询记忆
query_memory_tool(
    query_text: str,           # 查询文本（如"童年"）
    entity_type: str = "all",  # 限定类型：all、Event、Person 等
    max_results: int = 5       # 最多返回多少个结果
) -> str                       # 返回格式化的文本结果

# 工具 2：存储记忆 ⭐ 最常用
store_memory_tool(
    event_name: str,           # 事件/实体名称
    description: str,          # 详细描述
    entity_type: str = "Event",  # Event、Person、Location、Emotion、Topic
    key_details: Optional[str] = None  # JSON 字符串，额外属性
) -> str                       # 返回存储结果和 ID

# 工具 3：获取访谈摘要
get_interview_summary_tool() -> str  # 无参数，返回统计信息

# 工具 4：检测模式
detect_patterns_tool(
    pattern_type: str = "all"  # 模式类型（待定）
) -> str

# 工具 5：获取实体上下文 ⭐ 最重要
get_entity_context_tool(
    entity_id: str,           # 实体 ID（如 evt_abc、person_xyz）
    hop_count: int = 2        # 跳数（通常 1-3 最有用）
) -> str                      # 返回格式化的邻域网络
```

### 6.2 工具使用流程（最佳实践）

```
每轮对话时的标准工作流：

┌─────────────────────────────────────────────┐
│ 步骤 1：快速上下文获取                       │
├─────────────────────────────────────────────┤
│                                             │
│ store_memory_tool(                          │
│   event_name="被访者讲的内容",              │
│   description="详细描述",                   │
│   entity_type="Event",                      │
│   key_details='{"emotion": ["nostalgia"}' │
│ )                                           │
│ → 返回：✓ 已存储，ID: evt_xxxx             │
│                                             │
└─────────────────────────────────────────────┘
              ↓
┌─────────────────────────────────────────────┐
│ 步骤 2：理解关联关系                        │
├─────────────────────────────────────────────┤
│                                             │
│ get_entity_context_tool(                    │
│   entity_id="evt_xxxx",                     │
│   hop_count=2                               │
│ )                                           │
│ → 返回：中心节点、1跳、2跳邻域、关系统计   │
│                                             │
└─────────────────────────────────────────────┘
              ↓
┌─────────────────────────────────────────────┐
│ 步骤 3：检测模式/学习规律                   │
├─────────────────────────────────────────────┤
│                                             │
│ detect_patterns_tool()                      │
│ → 返回：已提取的行为模式、话题重复性      │
│                                             │
└─────────────────────────────────────────────┘
              ↓
┌─────────────────────────────────────────────┐
│ 步骤 4：决策下一步                         │
├─────────────────────────────────────────────┤
│                                             │
│ 基于以上信息，规划 Agent 决定：           │
│ - DEEP_DIVE：继续深入某个话题               │
│ - BREADTH_SWITCH：切换到新话题             │
│ - CLARIFY：澄清矛盾                        │
│ - SUMMARIZE：阶段性总结                    │
│                                             │
└─────────────────────────────────────────────┘
```

---

## 7. 数据流与隔离

### 7.1 采访隔离的三个层级

```
┌─────────────────────────────────────────────────────────┐
│ 应用层（Agent）                                         │
│ - planner_mode.py 为每个采访创建唯一的 interview_id   │
│ - 例如：interview_id = f"planner_interview_{timestamp}" │
└────────────────┬────────────────────────────────────────┘
                 │ interview_id 作为参数传递
                 ↓
┌────────────────────────────────────────────────────────┐
│ 工具层（Tools）                                        │
│ - create_graph_memory_tools() 通过闭包捕获 interview_id
│ - 所有工具都自动传递该 ID 到 Manager 层               │
│ - Agent 无需显式管理 ID                                │
└────────────────┬───────────────────────────────────────┘
                 │
┌────────────────▼───────────────────────────────────────┐
│ Manager 层（业务逻辑）                                 │
│ - create_event_node() 接收 interview_id               │
│ - 所有创建的子节点都继承该 interview_id             │
│ - 所有查询都通过 interview_id 过滤结果               │
└────────────────┬───────────────────────────────────────┘
                 │
┌────────────────▼───────────────────────────────────────┐
│ Driver 层（数据库操作）                               │
│ - insert_node() 保存 source_interview_id 字段        │
│ - query_by_hop() WHERE 子句中过滤：                   │
│   "WHERE neighbor.source_interview_id = $interview_id"└────────────────┬───────────────────────────────────────┘
                 │
┌────────────────▼───────────────────────────────────────┐
│ Neo4j 数据库                                           │
│ - 节点物理隔离：不同采访的节点有不同的 interview_id   │
│ - 查询结果隔离：数据库层保证不会跨采访返回数据       │
└─────────────────────────────────────────────────────────┘
```

### 7.2 隔离的保证机制

**节点级隔离**：
```python
# 创建事件时
event = models.EventNode(
    ...
    source_interview_id=interview_id,  # 👈 关键：标记所属采访
    ...
)
# 存储时
node_dict = asdict(event)
driver.insert_node(node_dict)  # 👈 source_interview_id 被保存

# 存储子节点时
person = self.create_person_node(
    ...
    interview_id=interview_id  # 👈 子节点继承相同的 interview_id
)
```

**查询级隔离**：
```python
# Hop 查询中的过滤
neighbor_query = f"""
    MATCH (center:Entity {{id: $node_id}})
    MATCH (center)-[*{hop}]-(neighbor:Entity)
    WHERE neighbor.id <> $node_id
    AND neighbor.source_interview_id = $interview_id  # 👈 WHERE 子句过滤
    ...
"""
```

**验证隔离**：
```python
# 示例：采访 1 创建了 4 个节点
# 采访 2 创建了 4 个节点
# 查询采访 1 的所有节点

query = "MATCH (n:Entity {source_interview_id: 'interview_1'}) RETURN n"
# 结果：只返回 4 个节点（采访 1 的）

# 若遗漏了 WHERE source_interview_id 子句
query = "MATCH (n:Entity) RETURN n"  # ❌ 错误！
# 结果：返回 8 个节点（全部）✗ 数据污染！
```

---

## 8. 关系网络

### 8.1 自动创建的关系类型

| 关系类型 | 方向 | 含义 | 创建时机 | 示例 |
|---------|------|------|--------|------|
| **INVOLVES** | Event → Person | 事件涉及的人物 | 创建 Event 时，为参与者创建 | 高中赚钱事件 --INVOLVES--> 父亲 |
| **OCCURS_AT** | Event → Location | 事件发生的地点 | 创建 Event 时，为位置创建 | 赚钱事件 --OCCURS_AT--> 阁楼 |
| **HAS_EMOTIONAL_TONE** | Event → Emotion | 事件的情感基调 | 创建 Event 时，为情感创建 | 赚钱事件 --HAS_EMOTIONAL_TONE--> 责任感 |
| **RELATED_TO** | 任意 → 任意 | 通用相关性 | 手动创建或推理 | 父亲 --RELATED_TO--> 教育价值观 |
| **CONTRADICTS** | Event → Event | 事件间矛盾 | 识别到矛盾时手动记录 | 早期说家里很穷 --CONTRADICTS--> 后来说有仆人 |

### 8.2 关系图示例

```
事件：高中在阁楼钞写赚钱
  ├── INVOLVES --> 父亲
  ├── OCCURS_AT --> 阁楼
  ├── HAS_EMOTIONAL_TONE --> 责任感
  └── HAS_EMOTIONAL_TONE --> 骄傲

人物：父亲
  ├── 出现在事件：高中钞写赚钱
  ├── 出现在事件：童年在河边玩
  ├── 出现在事件：工作时的教导
  └── RELATED_TO --> 权威式教学方式（Topic）

位置：阁楼
  ├── 所在更大位置：北京住宅
  ├── 发生过事件：高中钞写赚钱
  ├── 发生过事件：青年时期的思考
  └── RELATED_TO --> 童年贫困 (Topic)

情感：责任感
  ├── 出现在事件：高中钞写赚钱
  ├── 出现在人物：父亲（教导特质）
  ├── RELATED_TO --> 家庭价值观 (Topic)
  └── CONTRASTS_WITH --> 无忧无虑
```

### 8.3 关系的作用

**对访谈决策的影响**：
```
场景：Agent 想了解 "父亲" 这个人物

步骤 1：调用 get_entity_context_tool(entity_id='person_father', hop_count=2)

返回：
【中心实体】父亲

【1跳邻域】
  - 高中钞写赚钱 (Event)  ← INVOLVES 反向
  - 童年河边玩 (Event)    ← INVOLVES 反向
  - 工作教导 (Event)      ← INVOLVES 反向

【2跳邻域】
  - 北京住宅 (Location)   ← Event --OCCURS_AT--> Location
  - 阁楼 (Location)
  - 责任感 (Emotion)      ← Event --HAS_EMOTIONAL_TONE--> Emotion
  - 权威式教学 (Topic)

步骤 2：Agent 分析关系，发现：
  - 父亲在 3 个关键事件中出现
  - 多个事件都发生在北京
  - 多次关联到"责任感"和"教学"

步骤 3：Agent 做出决策：
  "父亲是塑造被访者人生观的关键人物，选择 DEEP_DIVE 进一步探索父亲的教学理念"
```

---

## 9. 核心算法

### 9.1 Hop 查询算法

```python
def query_by_hop(node_id, hop_count, interview_id):
    """
    目标：找出中心节点周围 N 跳范围内的所有节点，并按 hop 层级分组
    
    算法流程：
    
    1. 初始化结果结构
       result = {
           "center": None,
           "neighbors_by_hop": {},    # {1: [], 2: [], ...}
           "relationships": [],
           "total_nodes": 0,
           "total_relations": 0
       }
    
    2. 获取中心节点
       MATCH (center {id: node_id})
       IF not found: RETURN empty result
       ELSE: result["center"] = center
    
    3. 对每个 hop (1 到 hop_count)
       // 核心查询：距离恰好为 hop 的节点
       MATCH (center)-[*hop]-(neighbor)
       WHERE neighbor != center AND neighbor.interview_id == interview_id
       FOREACH neighbor:
           result["neighbors_by_hop"][hop].append(neighbor)
           result["total_nodes"] += 1
    
    4. 获取所有关系
       // 在 hop_count 范围内的所有路径
       MATCH (center)-[*1..hop_count]-(neighbor)
       FOREACH path:
           FOREACH rel in relationships(path):
               result["relationships"].append({
                   source: startNode(rel).id,
                   edge: type(rel),
                   target: endNode(rel).id
               })
       result["total_relations"] = len(relationships)
    
    5. 返回结果
    """
```

**时间复杂度分析**：
- 中心节点查询：O(1)（索引查询）
- N 跳邻域查询：O(k^n)，其中 k 是平均度数，n 是跳数
  - 1 跳：O(k)
  - 2 跳：O(k²)
  - 3 跳：O(k³)
  - 通常 k~5，所以 3 跳 = O(125)，可接受

**空间复杂度**：O(hop_count * k^hop_count)

### 9.2 自动关系创建算法

```python
def create_event_node(name, description, locations, participants, emotional_tone, interview_id):
    """
    目标：一次调用创建事件及其所有相关节点和关系
    
    算法：
    
    1. 创建主节点
       event = EventNode(id=gen_id(), name, description, interview_id)
       driver.insert_node(event)
    
    2. 处理参与者 participants = ["父亲", "小明"]
       FOREACH participant:
           person = PersonNode(id=gen_id(), name=participant, interview_id)
           driver.insert_node(person)
           driver.insert_edge(event, person, "INVOLVES")
    
    3. 处理位置 locations = ["阁楼", "北京"]
       FOREACH location:
           loc = LocationNode(id=gen_id(), name=location, interview_id)
           driver.insert_node(loc)
           driver.insert_edge(event, loc, "OCCURS_AT")
    
    4. 处理情感 emotional_tone = ["责任感", "骄傲"]
       FOREACH emotion:
           emo = EmotionNode(id=gen_id(), name=emotion, interview_id)
           driver.insert_node(emo)
           driver.insert_edge(event, emo, "HAS_EMOTIONAL_TONE")
    
    5. 返回 event
    """
    
    # 代码实现见 manager_sync.py#L100-L180
```

**关键优化**：
- ✅ 一次工具调用处理多个子节点创建（3-6 个节点 + 3-6 个关系）
- ✅ Agent 无需关心底层细节，只提供列表参数
- ✅ 自动处理采访隔离（所有子节点继承 interview_id）

### 9.3 数据清理算法

```python
def _sanitize_node_dict(node_dict):
    """
    目标：将 Python 对象转换为 Neo4j 兼容的类型
    
    Neo4j 支持的基本类型：
    - str、int、float、bool、None
    - List （元素必须是基本类型）
    
    不支持的类型需要序列化：
    - datetime → ISO 字符串
    - dict → JSON 字符串
    - dataclass → JSON 字符串
    - 其他复杂对象 → JSON 字符串或 str()
    
    算法：
    FOR EACH field in node_dict:
        IF type in (str, int, float, bool, None):
            sanitized[field] = value
        ELIF type is list AND all elements are basic:
            sanitized[field] = value
        ELIF type is dict:
            sanitized[field] = json.dumps(value)
        ELIF type is datetime:
            sanitized[field] = value.isoformat()
        ELSE:
            sanitized[field + "_json"] = json.dumps(value, default=str)
            OR sanitized[field + "_str"] = str(value)
    
    RETURN sanitized
    """
```

**字段重命名规则**：
- 原字段 `attributes` (dict) → `attributes` (JSON 字符串) 或 `attributes_json`
- 原字段 `created_at` (datetime) → `created_at` (ISO 字符串)
- 原字段 `complex_obj` → `complex_obj_json` 或 `complex_obj_str`

---

## 10. 性能考虑

### 10.1 Neo4j 连接管理

```python
# 连接池配置（neo4j_driver_sync.py)
driver = GraphDatabase.driver(
    uri,
    auth=(username, password),
    max_connection_pool_size=50  # 最多维持 50 个连接
)

# 优势：
# - 复用连接，避免频繁的 TCP 握手
# - 自动超时和清理空闲连接
# - 线程安全（官方驱动已处理）

# 缺点：
# - 长时间空闲时连接可能断开
# - 应定期检查（通过 _ensure_connected()）
```

### 10.2 查询优化

**索引**（application)：
```cypher
# 推荐创建的索引
CREATE INDEX node_id ON (:Entity): (id)
CREATE INDEX interview_id ON (:Entity) FOR (source_interview_id)
CREATE INDEX type ON (:Entity) FOR (type)
```

**Hop 查询的优化技巧**：
```cypher
# ❌ 低效：不限制节点数
MATCH (center)-[*2]-(neighbor)
RETURN neighbor

# ✅ 高效：限制返回数量（早期终止）
MATCH (center)-[*2]-(neighbor)
WITH DISTINCT neighbor LIMIT 100
RETURN neighbor

# ✅ 采访隔离也是优化（减少扫描）
MATCH (center)-[*2]-(neighbor)
WHERE neighbor.source_interview_id = $interview_id
...
```

### 10.3 缓存策略

```python
# 本地缓存（manager_sync.py)
self.node_cache = {}  # {node_id: node_object}
self.max_cache_size = 1000

# 缓存最近创建的节点，加快重复查询
# 但不缓存复杂查询结果（Hop 查询等）

# 缓存失效：
# - 手动调用 clear_cache()
# - 超过 max_cache_size（FIFO 淘汰）
```

### 10.4 批量操作建议

```python
# ❌ 单个操作太慢
for participant in participants:
    person = create_person_node(participant)
    insert_edge(event, person, "INVOLVES")  # N 次数据库往返

# ✅ Auto-batch（当前实现）
def create_event_node(...participants...):
    # 内部批量创建相关节点
    for participant:
        create_person_node(participant)  # ← 仍是 N 次往返
    # 但从 Agent 角度看是原子操作

# 理想方案（未实现）：使用 Cypher UNWIND 批量操作
query = """
MERGE (e:Entity {id: $event_id})
WITH e
UNWIND $participants as participant
MERGE (p:Entity {name: participant})
MERGE (e)-[:INVOLVES]->(p)
"""
```

### 10.5 并发性

```python
# 同步 API 不能直接并发多个查询
# 但可以通过不同的会话并发

# ❌ 串行（当前）
result1 = driver.query(q1)  # 阻塞
result2 = driver.query(q2)  # 阻塞

# ✅ 潜在并发（使用 ThreadPoolExecutor）
from concurrent.futures import ThreadPoolExecutor
executor = ThreadPoolExecutor(max_workers=5)
future1 = executor.submit(driver.query, q1)
future2 = executor.submit(driver.query, q2)
result1 = future1.result()
result2 = future2.result()
```

---

## 总结

### 系统优势
1. **完整性**：6 种丰富的实体模型，捕捉访谈的每个细节
2. **隔离性**：多采访零污染，采访 ID 贯穿全调用链
3. **自动化**：一个工具调用创建多个节点和关系，Agent 无负担
4. **可探索性**：Hop 查询提供清晰的分层邻域网络
5. **简洁性**：同步 API，无 asyncio 复杂度，易于调试

### 核心文件导航
- `neo4j_driver_sync.py`：底层数据库操作（~500 行）
- `manager_sync.py`：业务逻辑和节点创建（~600 行）
- `models.py`：丰富的数据模型（~800 行）
- `tools_sync.py`：Agent 工具接口（~300 行）

### 使用流程（Agent 视角）
```
1. store_memory_tool()           ← 存储讲述
2. get_entity_context_tool()     ← 了解关联
3. detect_patterns_tool()        ← 识别规律
4. 根据知识图谱做出决策 ← 下一步提问
5. 循环回到步骤 1
```

---

*文档最后更新：2026-04-08*
*系统版本：Graph RAG 1.0（同步实现）*
