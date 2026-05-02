# Narrative Planner - 安装与运行指南

## 项目简介

叙事规划器（Narrative Planner）是一个面向传记访谈的 Planner 系统，用于实时访谈、Planner 决策实验和动态事件图谱展示。

## 技术栈

- **前端**: React + TypeScript + Vite
- **后端**: Python Flask + FastAPI
- **包管理**: pnpm（前端）、pip（后端）

---

## 快速开始（推荐）

### 1. 准备代码

```bash
git clone <repository-url>
cd Narrative-Planner
```

### 2. 安装 Python 依赖

```bash
python3 -m venv .venv

# Windows
.venv\Scripts\activate

# macOS/Linux
source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 3. 安装前端依赖

```bash
cd frontend
pnpm install
```

如果本机还没有 pnpm：

```bash
npm install -g pnpm
```

---

## 后端运行

### Flask 访谈演示服务

根目录下执行：

```bash
source .venv/bin/activate
python start_flask.py
```

服务默认运行在 `http://localhost:9999`。

也可以直接运行 Flask 入口：

```bash
python src/app.py
```

直接运行 `src/app.py` 时，端口以文件中的 `app.run(...)` 配置为准。

### 动态图谱 API 服务（FastAPI）

如果需要 WebSocket 图谱 API：

```bash
source .venv/bin/activate
uvicorn src.api.server:app --host 127.0.0.1 --port 8000 --reload
```

API 文档地址：`http://127.0.0.1:8000/docs`

### 环境要求

- Python 3.10+
- 建议使用虚拟环境
- 可选：Neo4j（仅在启用 Neo4j 图谱存储时需要）

---

## 前端运行

### 环境要求

- Node.js 18+
- pnpm

### 开发展示

```bash
cd frontend
pnpm install
pnpm dev
```

前端开发服务器默认运行在 `http://localhost:3000`。

默认不带 `session` 参数时，前端会加载 Mock 图谱数据，适合独立展示人物视图、主题视图、时间轴和覆盖率仪表盘。

### 构建生产版本

```bash
pnpm build
```

---

## 常用命令速查

### 后端命令

```bash
# 安装依赖
python -m pip install -r requirements.txt

# 运行 Flask 访谈演示
python start_flask.py

# 运行动态图谱 API
uvicorn src.api.server:app --host 127.0.0.1 --port 8000 --reload

# 运行测试
make test

# 清理缓存文件
make clean
```

### 前端命令

```bash
# 进入前端目录
cd frontend

# 安装依赖
pnpm install

# 启动开发服务器
pnpm dev

# 构建生产版本
pnpm build

# 预览生产构建
pnpm preview

# 代码检查
pnpm lint
```

---

## 项目结构

```
narrative-planner/
├── frontend/           # 前端代码
│   ├── src/           # 源代码
│   ├── package.json   # 前端依赖
│   └── vite.config.ts # Vite 配置
├── src/               # 后端代码
│   ├── app.py         # Flask 入口
│   ├── api/           # API 接口
│   ├── agents/        # AI Agent
│   ├── core/          # 核心逻辑
│   └── prompts/       # 提示词模板
├── requirements.txt   # Python 依赖
└── Makefile          # 自动化脚本
```

---

## 注意事项

1. **Mock 展示只需要启动前端**；联调实时会话时再启动后端。
2. **前端使用 pnpm**，锁文件为 `frontend/pnpm-lock.yaml`。
3. **Python 依赖建议使用虚拟环境隔离**，避免影响系统 Python。
4. 默认端口：
   - Flask 访谈演示：`http://localhost:9999`
   - FastAPI 图谱 API：`http://127.0.0.1:8000`
   - 前端 Vite：`http://localhost:3000`

---

## 故障排除

### 后端问题

**Q: 提示缺少模块？**
```bash
# 确保已激活虚拟环境并安装依赖
source .venv/bin/activate  # macOS/Linux
python -m pip install -r requirements.txt
```

**Q: 端口被占用？**
```bash
# Flask 演示服务可修改 start_flask.py 中的 port
# FastAPI 服务可换端口
uvicorn src.api.server:app --host 127.0.0.1 --port 8001 --reload
```

### 前端问题

**Q: pnpm 命令不存在？**
```bash
npm install -g pnpm
```

**Q: 依赖安装失败？**
```bash
# 删除 node_modules 重新安装
rm -rf node_modules pnpm-lock.yaml
pnpm install
```

---

## 开发团队

如有问题，请联系项目维护者。
