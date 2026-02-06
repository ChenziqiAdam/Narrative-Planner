# docs/ 目录说明

本目录包含指导所有 Planner 变量和指令集的规范文档。

## 设计原则

根据项目架构文档划分：

| 目录层级 | 职责 | 说明 |
|:---|:---|:---|
| **根目录文档** | 指导项目全局 | `prd.md`、`CLAUDE.md`、`项目介绍.md`、`参考文献.md` |
| **docs/** | 指导 Planner 变量和指令集 | 本目录下的规范文档 |

## 文档清单

| 文件 | 说明 | 状态 |
|:---|:---|:---|
| [planner-instruction-standard.md](planner-instruction-standard.md) | Planner 指令集标准规范 | v1.4.0 |
| [planner-instruction-config.json](planner-instruction-config.json) | Planner 指令集 JSON Schema | v1.0.0 |

## 文档结构关系

```
根目录文档（全局指导）
    ├── prd.md              # 产品需求文档
    ├── CLAUDE.md           # 项目开发规范
    ├── 项目介绍.md          # 项目愿景与架构
    └── 参考文献.md          # 学术参考与技术调研
            │
            ▼
docs/（Planner 变量与指令集规范）
    ├── planner-instruction-standard.md    # 指令集标准
    └── planner-instruction-config.json    # JSON Schema
            │
            ▼
src/planner/（实现代码）
    ├── event_extractor.py     # 事件抽取器
    ├── navigation_decider.py  # 导航决策器
    └── instruction_builder.py # 指令构建器
```

## 使用指南

### 新增 Planner 策略

1. 更新 `planner-instruction-standard.md` 中的定义
2. 同步更新 `planner-instruction-config.json` 的 Schema
3. 在 `src/planner/` 中实现对应逻辑

### 新增指令字段

1. 在 `planner-instruction-standard.md` 中添加字段说明
2. 在 `planner-instruction-config.json` 中更新 Schema 定义
3. 更新 `src/planner/instruction_builder.py` 中的构建逻辑

---

*最后更新：2026-02-06*
