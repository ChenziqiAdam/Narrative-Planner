# Narrative Planner - 运行指南

## 项目简介

叙事规划器（Narrative Planner）是一个基于 GraphRAG 的智能访谈系统，通过实时图谱构建和语义检索辅助深度叙事访谈。

## 技术栈

- **前端**: React + TypeScript + Vite (port 3000)
- **后端 API**: FastAPI + WebSocket (port 8000)
- **对比调试**: Flask + SSE (port 9999)
- **图数据库**: Neo4j 5 Community (Docker, port 7687)
- **嵌入模型**: 智谱 GLM Embedding-3 (云端 API)
- **LLM**: Kimi / Moonshot (OpenAI 兼容格式)
- **包管理**: pnpm（前端）、pip（后端）

---

## 快速开始

### 1. 克隆代码

```bash
git clone <repository-url>
cd narrative-planner
```

### 2. 配置环境变量

复制 `.env` 文件并填入你的 API Key：

```bash
# LLM API 配置
OPENAI_API_KEY=your-moonshot-api-key
OPENAI_BASE_URL=https://api.moonshot.cn/v1
MODEL_NAME=kimi-k2.5
CHAT_MODEL_NAME=moonshot-v1-8k
STRUCTURED_MODEL_NAME=moonshot-v1-8k

# 嵌入模型（智谱 Embedding-3）
EMBEDDING_PROVIDER=openai
EMBEDDING_OPENAI_API_KEY=your-zhipu-api-key
EMBEDDING_OPENAI_BASE_URL=https://open.bigmodel.cn/api/paas/v4
EMBEDDING_OPENAI_MODEL=embedding-3

# Neo4j 图数据库
NEO4J_URI=bolt://localhost:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=narrative2026
NEO4J_DATABASE=neo4j
```

> **注意**: `.env` 中包含敏感信息，已在 `.gitignore` 中排除。

### 3. 启动服务

```bash
# (1) 启动 Neo4j（需要 Docker Desktop）
make neo4j

# (2) 安装后端依赖 + 启动 FastAPI
pip install -r requirements.txt
python -m uvicorn src.api.server:app --host 0.0.0.0 --port 8000 --reload

# (3) 启动 Flask 对比调试界面（新终端）
python src/app.py

# (4) 启动前端（新终端）
cd frontend && pnpm install && pnpm dev
```

---

## 服务端口

| 服务 | 端口 | 用途 |
|------|------|------|
| FastAPI | `http://localhost:8000` | 主 API + WebSocket |
| Flask | `http://localhost:9999/compare` | 对比调试界面 | (不加compare只有baseline agent)
| React | `http://localhost:3000` | 前端主界面 |
| Neo4j Browser | `http://localhost:7474` | 图数据库管理 |
| Neo4j Bolt | `bolt://localhost:7687` | 图数据库连接 |

---

## Neo4j 图数据库（Docker 本地运行）

本项目使用 Neo4j 5 Community Edition 作为图数据库，通过 Docker 容器在本地运行。

### 前提条件

- 已安装 [Docker Desktop](https://www.docker.com/products/docker-desktop/) 并启动
- Docker Desktop 状态栏图标显示为运行中（绿色）

### 启动 Neo4j

```bash
make neo4j
# 或直接使用 docker compose
docker compose up -d
```

首次运行会拉取 `neo4j:5-community` 镜像（约 300MB），后续启动只需数秒。

### 访问 Neo4j

| 入口 | 地址 | 说明 |
|------|------|------|
| Neo4j Browser（可视化界面） | `http://localhost:7474` | 在浏览器中打开，可执行 Cypher 查询、浏览图谱 |
| Bolt 协议（应用连接） | `bolt://localhost:7687` | 后端通过此端口连接数据库 |

Neo4j Browser 登录凭据：

- 用户名: `neo4j`
- 密码: `narrative2026`

### 容器配置说明

[docker-compose.yml](docker-compose.yml) 中的关键配置：

| 配置项 | 值 | 说明 |
|--------|----|------|
| 镜像 | `neo4j:5-community` | 社区版，免费使用 |
| 容器名 | `narrative-neo4j` | 方便通过 `docker ps` 识别 |
| 内存堆 | 512MB ~ 1GB | 根据本地机器配置自动调整 |
| 页缓存 | 256MB | 提升查询性能 |
| 插件 | APOC | 扩展 Cypher 功能（如路径遍历、文本处理） |
| 数据持久化 | `./data/neo4j` | 数据存储在项目目录下，容器重建不丢失 |
| 重启策略 | `unless-stopped` | Docker 重启后自动恢复运行 |

### 启用 Neo4j 功能

在 `.env` 文件中设置：

```env
NEO4J_ENABLED=true
```

> 未设置或设为 `false` 时，系统跳过图谱功能正常运行，不依赖 Neo4j。

### 停止 Neo4j

```bash
make neo4j-down
# 或
docker compose down
```

> 停止容器不会删除数据（数据持久化在 `./data/neo4j` 目录）。

### 清除所有数据

如需完全重置 Neo4j 数据：

```bash
docker compose down -v
# 或手动删除数据目录
rm -rf data/neo4j
```

> **警告**: 此操作不可恢复，图谱中的所有实体和关系将被删除。

### 常见问题

**Q: Docker Desktop 未启动？**

确保 Docker Desktop 应用已打开且状态为运行中。可在终端执行 `docker ps` 验证。

**Q: 端口 7474 或 7687 被占用？**

```bash
# Windows 查看端口占用
netstat -ano | findstr :7474
netstat -ano | findstr :7687

# 修改 docker-compose.yml 中的端口映射，如改为 7475:7474
```

**Q: 容器启动后立即退出？**

```bash
# 查看容器日志
docker logs narrative-neo4j

# 常见原因：内存不足，尝试减少 docker-compose.yml 中的内存配置
```

---

## Makefile 命令

```bash
make help        # 显示帮助信息
make install     # 安装后端依赖
make dev         # 启动 FastAPI 开发服务器
make frontend    # 安装前端依赖并启动
make test        # 运行测试
make neo4j       # 启动 Neo4j
make neo4j-down  # 停止 Neo4j
make clean       # 清理生成文件
```

---

## 嵌入模型配置

系统使用嵌入向量进行实体去重、语义搜索和主题匹配。支持两种 Provider：

### 方式 A：云端 Embedding API（推荐）

在 `.env` 中配置：

```env
EMBEDDING_PROVIDER=openai
EMBEDDING_OPENAI_API_KEY=your-api-key
EMBEDDING_OPENAI_BASE_URL=https://open.bigmodel.cn/api/paas/v4
EMBEDDING_OPENAI_MODEL=embedding-3
```

支持的云端 Provider（均为 OpenAI 兼容格式）：

| Provider | base_url | 模型名 | 维度 |
|----------|----------|--------|------|
| 智谱 GLM | `https://open.bigmodel.cn/api/paas/v4` | `embedding-3` | 2048 |
| OpenAI | `https://api.openai.com/v1` | `text-embedding-3-small` | 1536 |

> **注意**: Kimi (Moonshot) 和 DeepSeek 不提供 Embedding API。

### 方式 B：本地模型

```env
EMBEDDING_PROVIDER=local
EMBEDDING_MODEL_LOCAL=paraphrase-multilingual-MiniLM-L12-v2
```

首次使用会从 HuggingFace 下载模型（约 420MB）。国内网络需配置镜像：

```bash
HF_ENDPOINT=https://hf-mirror.com python -c "
from sentence_transformers import SentenceTransformer
SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
"
```

---

## 项目结构

```
narrative-planner/
├── frontend/                # 前端代码 (React + Vite)
│   ├── src/
│   │   ├── components/     # UI 组件
│   │   ├── hooks/          # WebSocket hooks
│   │   ├── types/          # TypeScript 类型定义
│   │   └── App.tsx         # 入口组件
│   └── package.json
├── src/                     # 后端代码 (Python)
│   ├── api/                # FastAPI 路由
│   ├── agents/             # AI Agent (访谈者、受访者、提取器)
│   ├── orchestration/      # 会话编排器
│   ├── services/           # 业务服务 (GraphRAG、检索、嵌入)
│   ├── state/              # 数据模型
│   ├── storage/            # Neo4j 存储
│   ├── tools/              # 受访者工具 (记忆系统)
│   ├── prompts/            # 提示词模板
│   ├── app.py              # Flask 对比调试界面
│   └── config.py           # 配置管理
├── tests/                   # 测试
├── docker-compose.yml       # Neo4j Docker 配置
├── requirements.txt         # Python 依赖
├── Makefile                 # 自动化脚本
└── .env                     # 环境变量（不纳入版本控制）
```

---

## 故障排除

### 后端问题

**Q: HuggingFace 连接失败？**

系统已配置 `TRANSFORMERS_OFFLINE=1`，使用云端 Embedding 时不会触发 HuggingFace 下载。如需使用本地模型，参考上方"嵌入模型配置 - 方式 B"。

**Q: Neo4j 连接失败？**

```bash
# 确认 Docker Desktop 已启动
docker ps | grep neo4j

# 重启 Neo4j
make neo4j-down && make neo4j
```

**Q: 端口被占用？**

```bash
# Windows 查看端口占用
netstat -ano | findstr :8000
netstat -ano | findstr :9999
```

### 前端问题

**Q: pnpm 命令不存在？**

```bash
npm install -g pnpm
```

**Q: 依赖安装失败？**

```bash
rm -rf frontend/node_modules frontend/pnpm-lock.yaml
cd frontend && pnpm install
```
