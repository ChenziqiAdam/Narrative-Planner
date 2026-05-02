# GraphRAG 管线使用说明

## 概述

本项目支持两条访谈管线，通过环境变量 `GRAPH_RAG_ENABLED` 切换：

| 管线 | 特点 | 适用场景 |
|------|------|----------|
| **旧管线（默认）** | 8 槽位提取 + 合并 + MemoryCapsule 决策 | 稳定版本，无需 Neo4j |
| **GraphRAG 管线** | 自由提取 + Neo4j 图存储 + 混合检索 + 图原生决策 | 推荐，需要 Neo4j |

## 快速启动

### 1. 安装依赖

```bash
# 后端
pip install -r requirements.txt

# 前端
cd frontend
pnpm install
```

### 2. 启动 Neo4j（GraphRAG 管线需要）

```bash
docker compose up -d
```

- Neo4j 浏览器：http://localhost:7474
- 用户名：`neo4j`，密码：`narrative2026`

### 3. 配置环境变量

复制 `.env` 文件，确保以下配置正确：

**基础配置（两条管线都需要）：**
```env
OPENAI_API_KEY=你的API密钥
OPENAI_BASE_URL=https://api.moonshot.cn/v1
MODEL_NAME=kimi-k2.5
```

**旧管线（默认）：**
```env
GRAPH_RAG_ENABLED=false
NEO4J_ENABLED=false
```

**GraphRAG 管线：**
```env
GRAPH_RAG_ENABLED=true
NEO4J_ENABLED=true
NEO4J_URI=bolt://localhost:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=narrative2026
```

### 4. 启动服务

```bash
# 终端 1: 后端
python src/app.py

# 终端 2: 前端
cd frontend
pnpm dev
```

### 5. 访问应用

- 前端界面：http://localhost:3000
- 后端 API：http://localhost:5000
- Neo4j 浏览器：http://localhost:7474

## 配置项详解

### 功能开关

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `GRAPH_RAG_ENABLED` | `false` | GraphRAG 管线开关 |
| `NEO4J_ENABLED` | `false` | Neo4j 数据库开关 |
| `EMBEDDING_PROVIDER` | `local` | 嵌入模型：`local`（本地 sentence-transformers）或 `openai` |
| `ENABLE_DYNAMIC_PROFILE_UPDATE` | `true` | 动态画像异步更新 |
| `ENABLE_LLM_MERGE_HINTS` | `true` | LLM 合并提示（仅旧管线） |

### 模型配置

| 环境变量 | 说明 |
|----------|------|
| `MODEL_NAME` | 默认模型 |
| `EXTRACTOR_MODEL_NAME` | 提取模型（GraphRAG 和旧管线共用） |
| `INTERVIEWER_MODEL_NAME` | 访谈问题生成模型 |

### Neo4j 配置

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `NEO4J_URI` | `bolt://localhost:7687` | 连接地址 |
| `NEO4J_USERNAME` | `neo4j` | 用户名 |
| `NEO4J_PASSWORD` | `narrative2026` | 密码 |
| `NEO4J_DATABASE` | `neo4j` | 数据库名 |

## 管线架构对比

### 旧管线

```
用户回答
  → TurnRoutingPolicy 路由判定
  → ExtractionAgent（8槽位提取：time/location/people/event/feeling/reflection/cause/result）
  → MergeEngine（合并到 CanonicalEvent）
  → GraphProjector（更新内存图谱）
  → MemoryProjector.refresh()（更新 MemoryCapsule）
  → CoverageCalculator（计算覆盖度）
  → PlannerDecisionPolicy（计算策略信号）
  → InterviewerAgent.generate_question()（生成下一问题）
```

### GraphRAG 管线

```
用户回答
  → HybridRetriever.retrieve()
      ├── 向量搜索（FAISS）
      ├── 图遍历（Neo4j 2-hop）
      └── 全文搜索（Neo4j fulltext）
      → RRF 融合（α=0.5, β=0.3, γ=0.2）
  → GraphExtractionAgent.extract()
      → 自由提取实体（Event/Person/Location/Emotion/Insight）
      → 自由提取关系（PARTICIPATES_IN/TRIGGERS/LOCATED_AT/...）
  → GraphWriter.write_extraction()
      → 实体去重（向量 cos > 0.85）
      → 写入 Neo4j + 同步 FAISS
  → GraphRAGDecisionContextBuilder.build()
      → 主题覆盖度（Cypher 查询）
      → 焦点叙事（narrative_fragments）
      → 图间隙（可探索方向）
      → 情感状态（transcript 内联推断）
  → InterviewerAgent.generate_question_graph_rag()
  → [异步] MemoryCapsule / Coverage / SessionMetrics 更新
  → [异步] DynamicProfile / TurnEvaluation 更新
```

## 记忆架构

三层记忆系统（GraphRAG 模式）：

| 层级 | 组件 | 更新方式 | 决策作用 |
|------|------|----------|----------|
| 短期 | transcript (SessionState) | 每轮同步 | 问题生成的直接上下文 |
| 长期 | Neo4j 图谱（实体/关系/主题） | 每轮同步写入 | 覆盖度/焦点/探索方向 |
| 长期 | DynamicProfile | 每 3-5 轮异步 | 画像指导 |
| 展示 | MemoryCapsule | 异步后台 | 仅前端看板 |
| 展示 | SessionMetrics | 异步后台 | 仅 API 返回 |

## 跨会话记忆

GraphRAG 管线支持跨会话记忆。当同一老人开始新的访谈时：

1. 通过 `elder_id`（name + birth_year）查询 Neo4j 历史数据
2. 预加载 EntityVectorStore（历史实体嵌入）
3. 生成历史摘要注入开场 prompt
4. 提取历史未闭合线索作为追问方向

## 前端看板

- 旧管线：`get_graph_state()` 返回基于 canonical_events 的槽位覆盖度
- GraphRAG 管线：覆盖度从 Neo4j Cypher 实时查询（`GraphCoverageCalculator`）

## 常见问题

### Q: 启动 GraphRAG 报 Neo4j 连接错误？
确保 Docker 中的 Neo4j 容器已启动：`docker compose up -d`

### Q: 嵌入模型加载慢？
首次加载 `paraphrase-multilingual-MiniLM-L12-v2` 需要下载 ~470MB 模型文件。后续会缓存。

### Q: 如何切换回旧管线？
将 `.env` 中的 `GRAPH_RAG_ENABLED` 改为 `false`，重启后端即可。

### Q: 旧管线和 GraphRAG 管线的访谈数据能互通吗？
不能。旧管线数据存在 `canonical_events` 中，GraphRAG 数据存在 Neo4j 中。切换管线后建议开启新会话。
