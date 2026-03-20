# Narrative Planner - 运行指南

## 项目简介

叙事规划器（Narrative Planner）是一个动态事件图谱可视化工具，用于实时访谈和事件图谱管理。

## 技术栈

- **前端**: React + TypeScript + Vite
- **后端**: Python Flask
- **包管理**: pnpm（前端）、pip（后端）

---

## 快速开始

### 1. 克隆代码

```bash
git clone <repository-url>
cd narrative-planner
```

---

## 后端运行

### 环境要求

- Python 3.8+
- 建议使用虚拟环境

### 安装步骤

```bash
# 1. 创建并激活虚拟环境（推荐）
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS/Linux
source .venv/bin/activate

# 2. 安装依赖
pip install -r requirements.txt
```

### 启动后端服务

```bash
# 方式1：直接使用 Python 运行
python src/app.py

# 方式2：通过 Makefile
make install    # 安装依赖
python src/app.py
```

后端服务默认运行在 `http://localhost:5000`

---

## 前端运行

### 环境要求

- Node.js 16+
- pnpm（必须）

### 安装步骤

```bash
# 1. 进入前端目录
cd frontend

# 2. 安装 pnpm（如果尚未安装）
npm install -g pnpm

# 3. 安装依赖
pnpm install
```

### 启动前端开发服务器

```bash
# 在 frontend 目录下执行
pnpm dev
```

前端服务默认运行在 `http://localhost:5173`

### 构建生产版本

```bash
pnpm build
```

---

## 常用命令速查

### 后端命令

```bash
# 安装依赖
pip install -r requirements.txt

# 运行 Flask 服务
python src/app.py

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

1. **必须先启动后端，再启动前端**
2. **前端必须使用 pnpm**，不要使用 npm 或 yarn
3. **Python 依赖建议使用虚拟环境隔离**
4. 默认端口：
   - 后端：`http://localhost:5000`
   - 前端：`http://localhost:5173`

---

## 故障排除

### 后端问题

**Q: 提示缺少模块？**
```bash
# 确保已激活虚拟环境并安装依赖
.venv\Scripts\activate  # Windows
pip install -r requirements.txt
```

**Q: 端口被占用？**
```bash
# 修改 app.py 中的端口，或使用环境变量
FLASK_RUN_PORT=5001 python src/app.py
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
