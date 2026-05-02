# GraphRAG 叙事访谈系统 — 启动与使用说明

## 系统架构

```
用户回答
  → HybridRetriever.retrieve()
      ├── 向量搜索（FAISS）
      ├── 图遍历（Neo4j 2-hop）
      └── 全文搜索（Neo4j fulltext）
      → RRF 融合（α=0.5, β=0.3, γ=0.2）
  → GraphExtractionAgent.extract()
      → 自由提取实体（Event / Person / Location / Emotion / Insight）
      → 自由提取关系（PARTICIPATES_IN / TRIGGERS / LOCATED_AT / ...）
  → GraphWriter.write_extraction()
      → 实体去重（向量 cos > 0.85）
      → 写入 Neo4j + 同步 FAISS
  → GraphRAGDecisionContextBuilder.build()
      → 主题覆盖度（Cypher 查询）
      → 焦点叙事（narrative_fragments）
      → 图间隙（可探索方向）
      → 情感状态（transcript 内联推断）
  → InterviewerAgent.generate_question()
  → [异步] DynamicProfile / TurnEvaluation 更新
```

---

## 快速启动

### 前提条件

- Python 3.11+
- Node.js 18+ & pnpm
- Docker（用于 Neo4j）

### 1. 安装依赖

```bash
# 后端
pip install -r requirements.txt

# 前端
cd frontend
pnpm install
```

### 2. 启动 Neo4j

```bash
docker compose up -d
```

- Neo4j 浏览器：http://localhost:7474
- 用户名：`neo4j`，密码：`narrative2026`

首次启动后 Neo4j 会自动创建 schema（程序初始化时处理）。

### 3. 配置环境变量

复制 `.env` 文件，按实际情况修改：

```env
# LLM API 配置
OPENAI_API_KEY=你的API密钥
OPENAI_BASE_URL=https://api.moonshot.cn/v1
MODEL_NAME=kimi-k2.5

# Neo4j（必需）
NEO4J_URI=bolt://localhost:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=narrative2026
NEO4J_DATABASE=neo4j

# 嵌入模型
EMBEDDING_PROVIDER=local

# 可选：动态画像
ENABLE_DYNAMIC_PROFILE_UPDATE=true
```

### 4. 启动服务

```bash
# 终端 1: 后端 API（FastAPI）
python -m uvicorn src.api.server:app --host 0.0.0.0 --port 8000 --reload

# 终端 2: 前端
cd frontend
pnpm dev
```

### 5. 访问应用

| 服务 | 地址 |
|------|------|
| 前端界面 | http://localhost:5173 |
| 后端 API 文档 | http://localhost:8000/docs |
| Neo4j 浏览器 | http://localhost:7474 |
| 健康检查 | http://localhost:8000/health |

---

## API 端点

### 创建会话

```bash
curl -X POST http://localhost:8000/api/session \
  -H "Content-Type: application/json" \
  -d '{"basic_info": "陈秀英，1945年出生，浙江绍兴人，退休纺织工人"}'
```

### WebSocket 实时访谈

连接地址：`ws://localhost:8000/ws/interview/{session_id}`

消息格式：
```json
// 客户端 → 服务器
{"type": "message", "content": "我当时在纺织厂上班..."}

// 服务器 → 客户端（流式 token）
{"type": "token", "token": "您", "is_final": false}

// 服务器 → 客户端（完成）
{"type": "token", "token": "", "is_final": true}

// 服务器 → 客户端（图谱更新）
{"type": "graph_update", "update_type": "fragment_added", "data": {...}}
```

### 获取图谱状态

```bash
curl http://localhost:8000/api/graph/{session_id}
```

---

## 配置项参考

### LLM 模型

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `MODEL_NAME` | `moonshot-v1-8k` | 默认模型 |
| `EXTRACTOR_MODEL_NAME` | 同 MODEL_NAME | 图谱提取模型 |
| `INTERVIEWER_MODEL_NAME` | 同 CHAT_MODEL_NAME | 访谈问题生成模型 |
| `CHAT_MODEL_NAME` | `kimi-latest` | 对话模型 |

### Neo4j

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `NEO4J_URI` | `bolt://localhost:7687` | 连接地址 |
| `NEO4J_USERNAME` | `neo4j` | 用户名 |
| `NEO4J_PASSWORD` | `narrative2026` | 密码 |
| `NEO4J_DATABASE` | `neo4j` | 数据库名 |

### 嵌入模型

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `EMBEDDING_PROVIDER` | `local` | `local`（sentence-transformers）或 `openai` |
| `EMBEDDING_MODEL_LOCAL` | `paraphrase-multilingual-MiniLM-L12-v2` | 本地嵌入模型 |

### 动态画像

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `ENABLE_DYNAMIC_PROFILE_UPDATE` | `true` | 异步更新开关 |
| `DYNAMIC_PROFILE_MIN_TURNS_BETWEEN_UPDATES` | `3` | 最小更新间隔轮数 |
| `DYNAMIC_PROFILE_MAX_TURNS_BETWEEN_UPDATES` | `5` | 最大更新间隔轮数 |

---

## 记忆架构

| 层级 | 组件 | 更新方式 | 作用 |
|------|------|----------|------|
| 短期 | transcript（SessionState） | 每轮同步 | 问题生成的直接上下文 |
| 长期 | Neo4j 图谱（实体/关系/主题） | 每轮同步写入 | 覆盖度/焦点/探索方向 |
| 长期 | DynamicProfile | 每 3-5 轮异步 | 画像指导 |

## 跨会话记忆

同一老人开始新访谈时：

1. 通过 `elder_id`（name + birth_year）查询 Neo4j 历史数据
2. 预加载 EntityVectorStore（历史实体嵌入）
3. 生成历史摘要注入开场 prompt
4. 提取历史未闭合线索作为追问方向

---

## 项目结构

```
src/
├── agents/
│   ├── graph_extraction_agent.py   # 自由格式图谱提取
│   ├── interviewer_agent.py        # 访谈问题生成
│   └── evaluator_agent.py          # 轮次评估
├── orchestration/
│   └── session_orchestrator.py     # 会话编排（GraphRAG only）
├── services/
│   ├── graph_rag_decision_context.py  # 图原生决策上下文
│   ├── graph_writer.py                # Neo4j 写入
│   ├── hybrid_retriever.py            # 混合检索（向量+图+全文）
│   ├── entity_vector_store.py         # 多类型实体向量索引
│   ├── embedding_service.py           # 嵌入服务
│   ├── graph_coverage.py              # 图覆盖率计算
│   ├── narrative_richness.py          # 叙事丰富度评分
│   ├── session_graph_bridge.py        # 跨会话记忆桥接
│   └── profile_projector.py           # 动态画像
├── storage/neo4j/
│   ├── driver.py                   # Neo4j 驱动
│   └── manager.py                  # 图谱管理器
├── state/
│   ├── models.py                   # 核心数据模型
│   ├── narrative_models.py         # 叙事/实体/关系模型
│   └── evaluation_models.py        # 评估模型
├── api/
│   └── server.py                   # FastAPI 服务
└── config.py                       # 配置

frontend/src/
├── types/
│   ├── index.ts                    # 数据类型（GraphRAG）
│   └── websocket.ts                # WebSocket 类型
├── components/
│   ├── GraphCanvas.tsx             # 图谱可视化（Cytoscape）
│   ├── ThemeView.tsx               # 主题视图
│   ├── TimelineCanvas.tsx          # 叙事时间轴
│   ├── CoverageDashboard.tsx       # 覆盖率仪表盘
│   ├── NodeDetailPanel.tsx         # 节点详情面板
│   └── LiveInterviewPanel.tsx      # 实时访谈面板
└── App.tsx                         # 主应用
```

---

## 常见问题

### Q: 启动报 Neo4j 连接错误？
确保 Docker 中的 Neo4j 容器已启动：`docker compose up -d`

### Q: 嵌入模型加载慢？
首次加载 `paraphrase-multilingual-MiniLM-L12-v2` 需要下载 ~470MB 模型文件。后续会缓存到本地。

### Q: 如何使用 OpenAI 嵌入模型？
```env
EMBEDDING_PROVIDER=openai
```
确保 `OPENAI_API_KEY` 已配置。

### Q: 前端如何连接后端？
前端通过 URL 参数指定 session：`http://localhost:5173?session=<session_id>`
后端 WebSocket 地址可通过 `VITE_BACKEND_URL` 环境变量配置（默认 `http://localhost:9999`）。

### Q: 如何查看 Neo4j 中的图谱数据？
打开 http://localhost:7474，运行 Cypher 查询：
```cypher
// 查看所有实体
MATCH (n) RETURN n LIMIT 50

// 查看关系
MATCH (a)-[r]->(b) RETURN a, r, b LIMIT 50

// 查看主题覆盖度
MATCH (t:Topic)
OPTIONAL MATCH (t)-[:INCLUDES]->(e:Event)
RETURN t.title, count(e) AS event_count
```
