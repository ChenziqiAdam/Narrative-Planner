# v2 Narrative-Planner - 查询优化功能

## 快速概览 (30秒了解)

✨ **新功能**：将 GraphRAG 记忆查询委托给记忆提取 Agent

- **正常模式**（默认）：HybridRetriever 直接查询
- **优化模式**（可选）：GraphExtractionAgent 代理查询

## 启用方法

### 方式 1：环境变量
```bash
export QUERY_OPTIMIZATION_ENABLED=true
python -m uvicorn src.api.server:app --reload
```

### 方式 2：修改 .env
```bash
# 在 .env 中添加
QUERY_OPTIMIZATION_ENABLED=true
```

### 默认行为
✓ 无需任何配置，系统自动使用直接查询（backward compatible）

## 核心变更

| 组件 | 说明 |
|------|------|
| `src/config.py` | 新增 `QUERY_OPTIMIZATION_ENABLED` 配置 |
| `src/agents/graph_extraction_agent.py` | 新增 `query_memory()` 方法 |
| `src/services/graph_rag_decision_context.py` | `build()` 支持代理查询 |
| `src/orchestration/session_orchestrator.py` | 实现双路径查询 |

## 日志标志

### 禁用时（默认）
```
[src.services.hybrid_retriever] INFO: Hybrid retrieval: 8 entities, 400 tokens, 145.3 ms
```

### 启用时
```
[src.agents.graph_extraction_agent] INFO: Memory query succeeded: 8 entities, 145.3 ms
```

## 代码示例

### 配置读取
```python
from src.config import Config

if Config.QUERY_OPTIMIZATION_ENABLED:
    print("查询优化已启用")
else:
    print("查询优化已禁用（默认）")
```

### 自动应用
```python
# 无需修改现有代码，系统自动根据配置切换

# SessionOrchestrator 内部会自动使用正确的查询路径
orchestrator = SessionOrchestrator(session_id="test")
orchestrator.initialize_session(elder_info)
result = await orchestrator.process_user_response(user_response)  # 自动适配
```

## 文件清单

### 核心功能
- ✅ `src/config.py` - 配置项
- ✅ `src/agents/graph_extraction_agent.py` - query_memory() 方法
- ✅ `src/services/graph_rag_decision_context.py` - 决策上下文
- ✅ `src/orchestration/session_orchestrator.py` - 编排器

### 文档
- 📄 `docs/QUERY_OPTIMIZATION_GUIDE.md` - 完整使用指南
- 📄 `docs/QUERY_OPTIMIZATION_IMPLEMENTATION.md` - 实现详情
- 📄 `.env.query_optimization_example` - 配置示例

### 测试
- 🧪 `scripts/test_query_optimization.py` - 演示脚本

## 验证功能

### 检查配置
```bash
grep QUERY_OPTIMIZATION_ENABLED .env
# 输出应为：QUERY_OPTIMIZATION_ENABLED=true
```

### 运行测试
```bash
python scripts/test_query_optimization.py
# 显示两种模式的对比演示
```

### 查看日志
```bash
# 启用时
docker logs narrative-planner | grep "Memory query"

# 禁用时  
docker logs narrative-planner | grep "Hybrid retrieval"
```

## 架构对比

### 原有流程（保持不变）
```
process_user_response()
  └─ HybridRetriever.retrieve() [直接查询]
    └─ build() [决策上下文]
```

### 优化流程（启用时）
```
process_user_response()
  └─ build() [决策上下文]
    └─ GraphExtractionAgent.query_memory() [代理查询]
      └─ HybridRetriever.retrieve()
```

## 性能

- ✅ **理论延迟**：相同（仅改变调用顺序）
- ✅ **实际延迟**：预计相同
- 🎯 **优化目标**：代码结构和可扩展性，非性能

## 故障排除

| 问题 | 解决 |
|------|------|
| 配置不生效 | 重启服务后生效，检查 `.env` 加载 |
| 查询返回空 | 检查 Neo4j 和向量存储可用性 |
| 看不到日志 | 确认日志级别设置为 INFO |

## 向后兼容性

✅ **100% 向后兼容**
- 默认禁用
- 现有代码无需修改
- 所有新参数可选
- 任何时间点可切换

## 下一步

1. **了解细节**：阅读 [docs/QUERY_OPTIMIZATION_GUIDE.md](docs/QUERY_OPTIMIZATION_GUIDE.md)
2. **尝试功能**：运行 `python scripts/test_query_optimization.py`
3. **启用功能**：修改 `.env` 文件或环境变量
4. **监控性能**：查看日志验证功能运行

## 联系方式

有问题或建议？
- 查看 [完整实现文档](docs/QUERY_OPTIMIZATION_IMPLEMENTATION.md)
- 检查测试脚本中的使用示例
- 参考日志输出进行调试

---

**状态**：✅ 实现完成，无错误，已验证向后兼容性
