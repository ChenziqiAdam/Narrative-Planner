# 动态事件图谱可视化工具

基于 React + TypeScript 的动态事件图谱可视化前端。

## 功能特性

- **👤 人物视图**: 以人物为主键的树状结构，展示人物关系和相关事件
- **🌳 主题视图**: 思维导图风格，按 5 个领域（人生篇章、关键场景、未来剧本、挑战、个人思想）展示主题层级
- **⏱ 时间轴视图**: 按时间排序的事件列表，包含 5 个核心槽位和情绪能量指标
- **📊 覆盖率仪表盘**: 实时展示访谈进度和各维度覆盖率
- **📋 节点详情面板**: 点击节点查看详细信息
- **🔍 状态筛选**: 按节点状态（待触达/已提及/已挖透）筛选

## 技术栈

- React 18
- TypeScript
- Cytoscape.js（可选，用于图谱视图）
- Vite

## 数据模型

### 三种核心节点

| 节点类型 | 主键 | 说明 |
|---------|------|------|
| **ThemeNode** | `theme_id` | 主题节点，属于 5 个领域之一 |
| **EventNode** | `event_id` | 事件节点，包含 5 个核心槽位 |
| **PeopleNode** | `people_id` | 人物节点，记录与老人的关系 |

### EventNode 5 个核心槽位

| 槽位 | 说明 |
|-----|------|
| `time` | 时间 |
| `location` | 地点 |
| `people` | 人物 |
| `event` | 事件描述 |
| `reflection` | 感悟/反思 |

### 节点状态

- `pending` - 待触达
- `mentioned` - 已提及
- `exhausted` - 已挖透

## 快速开始

### 安装依赖

```bash
pnpm install
```

### 启动开发服务器

```bash
pnpm dev
```

### 构建生产版本

```bash
pnpm build
```

## 项目结构

```
frontend/src/
├── App.tsx                    # 主应用组件
├── main.tsx                   # 入口文件
│
├── components/               # UI 组件
│   ├── PersonView.tsx        # 人物视图（树状结构）
│   ├── PersonView.css
│   ├── ThemeView.tsx         # 主题视图（思维导图）
│   ├── ThemeView.css
│   ├── TimelineCanvas.tsx    # 时间轴视图
│   ├── TimelineCanvas.css
│   ├── CoverageDashboard.tsx # 覆盖率仪表盘
│   ├── CoverageDashboard.css
│   ├── NodeDetailPanel.tsx   # 节点详情面板
│   └── NodeDetailPanel.css
│
├── data/
│   └── mockData.ts            # Mock 数据
│
├── types/
│   └── index.ts               # 类型定义
│
├── utils/
│   └── graphTransformer.ts    # 图谱数据转换
│
└── styles/
    ├── App.css
    └── index.css
```

## 与后端集成

当前使用 Mock 数据进行开发。与后端集成时，需要：

1. 修改 `src/data/mockData.ts` 中的数据获取逻辑
2. 替换为实际的 API 调用

```typescript
// 示例：从后端 API 获取数据
export async function getGraphState(): Promise<GraphState> {
  const response = await fetch('/api/graph/state')
  return response.json()
}
```

## License

MIT
