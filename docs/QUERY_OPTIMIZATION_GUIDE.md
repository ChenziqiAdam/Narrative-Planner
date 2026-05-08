# 查询优化功能指南

## 功能概述

查询优化功能允许将 GraphRAG 记忆查询的工作委托给**记忆提取 Agent (GraphExtractionAgent)**，而不是直接通过 HybridRetriever 进行查询。这可以带来以下好处：

1. **统一的查询逻辑**：所有记忆查询均由提取 Agent 管理，便于集中控制和优化
2. **扩展性更强**：记忆提取 Agent 可以在未来添加更复杂的查询逻辑
3. **可观测性更好**：便于跟踪和调试查询流程

## 架构变化

### 原有流程
```
process_user_response()
  ↓
HybridRetriever.retrieve()  [直接查询]
  ↓
GraphRAGDecisionContextBuilder.build()
```

### 优化后流程（启用时）
```
process_user_response()
  ↓
GraphRAGDecisionContextBuilder.build()
  ↓
GraphExtractionAgent.query_memory()  [代理查询]
  ↓
HybridRetriever.retrieve()
```

## 使用方法

### 1. 环境配置

在 `.env` 文件中添加配置选项：

```bash
# 启用查询优化功能
QUERY_OPTIMIZATION_ENABLED=true
```

**默认值**：`false`（保持向后兼容）

### 2. 代码集成

#### 选项 A：通过环境变量（推荐）

无需修改代码，仅通过 `.env` 配置：

```python
# src/config.py 中已自动读取
Config.QUERY_OPTIMIZATION_ENABLED  # True/False
```

#### 选项 B：编程方式（用于特定会话）

```python
from src.orchestration import SessionOrchestrator

# 使用默认配置
orchestrator = SessionOrchestrator(session_id="test_session")

# 或者可通过会话初始化时传入配置
# (如果需要针对特定会话的配置调整)
```

### 3. 验证配置

在您的日志中查看以下信息：

**启用时**（在 decision_context 构建时）：
```
Memory query succeeded: N entities, X.X ms
```

**禁用时**（在 process_user_response 时）：
```
Hybrid retrieval: N entities, N tokens, X.X ms
```

## 技术细节

### GraphExtractionAgent.query_memory()

新增方法签名：

```python
def query_memory(
    self,
    query: str,
    session_id: str,
    neo4j_manager: Optional[Any] = None,
    entity_vector_store: Optional[Any] = None,
) -> str:
    """Query graph RAG memory for retrieval context."""
    # 内部调用 HybridRetriever 进行实际查询
    # 返回格式化的提示文本
```

### GraphRAGDecisionContextBuilder 变化

**新增参数**：

```python
def build(
    self,
    state: Any,
    graph_extraction: Optional[Any] = None,
    graph_rag_context: Optional[str] = None,
    bridge_result: Optional[Any] = None,
    session_id: Optional[str] = None,           # 新增
    user_response: Optional[str] = None,        # 新增
    enable_query_optimization: bool = False,    # 新增
) -> GraphRAGDecisionContext:
```

- `session_id`：当前会话 ID，用于 HybridRetriever
- `user_response`：用户最新回答，作为查询文本
- `enable_query_optimization`：是否启用优化模式

**行为**：

- 当 `enable_query_optimization=True` 且其他必要参数可用时，调用 `extraction_agent.query_memory()`
- 否则使用提供的 `graph_rag_context` 或空字符串

### SessionOrchestrator 变化

**在 prepare 阶段**：

```python
decision_ctx = self._get_decision_context_builder().build(
    state,
    graph_extraction,
    _graph_rag_context,
    session_id=self.session_id,
    user_response=user_response,
    enable_query_optimization=Config.QUERY_OPTIMIZATION_ENABLED,
)
```

**流程控制**：

- 当 `QUERY_OPTIMIZATION_ENABLED=False`：保持原有行为，HybridRetriever 直接在 process_user_response 中调用
- 当 `QUERY_OPTIMIZATION_ENABLED=True`：HybridRetriever 调用延迟到 decision context 构建时

## 配置项总结

| 参数 | 位置 | 默认值 | 说明 |
|------|------|--------|------|
| `QUERY_OPTIMIZATION_ENABLED` | `.env` / `config.py` | `false` | 启用查询优化 |

## 影响范围

### 受影响的文件

1. **src/config.py**
   - 新增配置选项 `QUERY_OPTIMIZATION_ENABLED`

2. **src/agents/graph_extraction_agent.py**
   - 新增方法 `query_memory()`

3. **src/services/graph_rag_decision_context.py**
   - 构造器新增参数 `extraction_agent`
   - `build()` 方法新增参数
   - 新增查询优化逻辑

4. **src/orchestration/session_orchestrator.py**
   - `_get_decision_context_builder()` 传递 extraction_agent
   - `initialize_session()` 传递优化选项
   - `process_user_response()` 支持两种查询路径

### 向后兼容性

✅ **完全向后兼容**

- 默认禁用优化（`QUERY_OPTIMIZATION_ENABLED=false`）
- 当禁用时，行为完全相同于之前版本
- 所有新参数都有默认值

## 调试与监控

### 日志位置

查看以下日志输出来验证功能状态：

```python
# 在 GraphExtractionAgent.query_memory() 中
logger.info("Memory query succeeded: %d entities, %.1f ms", ...)
logger.warning("Memory query failed for session %s: %s", ...)

# 在 HybridRetriever.retrieve() 中
logger.info("Hybrid retrieval: %d entities, %d tokens, %.1f ms", ...)
```

### 性能指标

注意以下指标的变化：

- **Decision context 构建时间**：可能会增加（因为查询逻辑被纳入）
- **Plan 生成时间**：应保持相同（使用相同的输入）
- **总体流程时间**：理论上接近，因为只是改变了调用顺序

## 故障排除

### 问题 1：Query 返回空结果

**原因**：Neo4j 连接问题或向量存储不可用

**解决**：
1. 检查日志中的错误信息
2. 验证 Neo4j 是否运行（`docker ps | grep neo4j`）
3. 检查向量存储初始化

### 问题 2：性能下降

**原因**：可能的 N+1 查询问题

**解决**：
1. 查看查询延迟指标
2. 使用 `Neo4j Browser` 分析 Cypher 查询
3. 考虑添加适用的缓存

### 问题 3：配置不生效

**原因**：`.env` 变更后需要重启服务

**解决**：
```bash
# 重新加载配置
python -m uvicorn src.api.server:app --reload
```

## 未来扩展

在 `GraphExtractionAgent.query_memory()` 中可以添加：

1. **智能查询改写**：基于提取的实体优化查询
2. **缓存策略**：减少重复查询
3. **查询路由**：根据上下文选择不同的检索通道
4. **结果过滤**：基于相关性阈值的结果筛选

## 示例：启用查询优化

### 步骤 1：配置环境

```bash
# .env
QUERY_OPTIMIZATION_ENABLED=true
```

### 步骤 2：运行系统

```bash
# 启动后端
python -m uvicorn src.api.server:app --reload

# 查看日志输出
# [INFO] Memory query succeeded: 8 entities, 145.3 ms
```

### 步骤 3：对比结果

在 Flask 对比界面或日志中查看决策流程，观察记忆查询的表现。

---

**最后修改**：2026-05-08
