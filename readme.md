# Narrative Navigator - 传记访谈助手

## 项目简介

这是一个基于大语言模型的传记访谈助手，能够帮助老人回顾和记录人生故事。项目采用对话式AI技术，实现智能访谈引导和人生故事结构化整理。

### 项目目标
- 实现自然流畅的传记访谈对话
- 提供无Planner的基线对话Agent作为对比基准
- 支持多轮对话的话题引导和深度挖掘

## 功能特性

- **智能对话引导**: 基于大语言模型的智能访谈提问
- **多轮对话管理**: 支持长对话的连贯性保持
- **简易部署**: 简单的环境配置和一键启动
- **可扩展架构**: 为后续Planner模块预留接口

## 环境要求

- Python 3.8+
- macOS/Linux/Windows
- 混元API或OpenAI GPT-4 API访问权限

## 快速开始

### 1. 克隆项目
```
git clone <项目地址>
cd narrative-navigator
```

### 2. 设置虚拟环境（Mac）
创建虚拟环境
`
python3 -m venv narrative_navigator_env
`
激活虚拟环境
`
source narrative_navigator_env/bin/activate
`

### 3. 安装依赖
`pip install -r requirements.txt`

### 4. 配置API密钥
创建 `.env` 文件：
复制并重命名环境变量文件

`cp .env.example .env`

编辑 .env 文件，添加你的API密钥

`nano .env`


在 `.env` 文件中添加：
bash
OpenAI配置（示例）
```
OPENAI_API_KEY=your_api_key_here
MODEL_NAME=gpt-4
```
项目配置
```
LOG_LEVEL=INFO
MAX_RETRIES=3
REQUEST_TIMEOUT=30
```

### 5. 运行基线访谈助手
```
python baseline_agent.py
```

## 项目结构


narrative-navigator/
├── prompts/                     # 提示词模板
│   └── baseline_system_prompt.txt
├── data/                       # 数据存储
├── logs/                       # 运行日志
├── tests/                      # 测试用例
├── config.py                   # 配置文件
├── baseline_agent.py          # 基线对话Agent
├── requirements.txt           # Python依赖
├── .env.example               # 环境变量模板
├── .gitignore                 # Git忽略规则
└── README.md                  # 项目说明


## 使用方法

### 基本访谈流程
1. 启动程序：`python baseline_agent.py`
2. 输入老人的基本信息（如：出生于1960年，曾是一名教师）
3. 开始对话，系统会自动生成引导性问题
4. 输入"退出"或"exit"结束访谈

### 对话示例

= 传记访谈助手 Baseline =
请输入老人的基本信息：出生于1960年，曾是一名教师，现居上海

助手：您好！能跟我分享一下您童年时代最难忘的一件事吗？
老人：我记得小时候经常在村口的大树下听爷爷讲故事...
助手：听起来很温馨！您爷爷通常会给您讲什么类型的故事呢？
老人：他经常讲民间传说和历史故事...
助手：这些故事对您后来的成长有什么影响吗？


## 开发指南

### 代码规范
- 遵循 PEP 8 代码规范
- 使用类型注解
- 编写详细的docstring

### 运行测试
运行单元测试
`
pytest tests/
`
代码质量检查
```
flake8 .
black . --check
```

### 添加新的提示词模板
1. 在 `prompts/` 目录下创建新的提示词文件
2. 修改 `config.py` 中的配置路径
3. 在Agent中加载新的提示词模板

## 配置说明

### 环境变量
| 变量名 | 说明 | 默认值 |
|-------|------|--------|
| OPENAI_API_KEY | OpenAI API密钥 | 必填 |
| MODEL_NAME | 使用的模型名称 | gpt-4 |
| LOG_LEVEL | 日志级别 | INFO |
| MAX_RETRIES | API重试次数 | 3 |
| REQUEST_TIMEOUT | 请求超时时间 | 30 |

### 自定义访谈风格
编辑 `prompts/baseline_system_prompt.txt` 来调整访谈风格：

txt
你是一位[风格描述]的传记访谈助手...


## 故障排除

### 常见问题

**Q: 无法激活虚拟环境**
检查虚拟环境路径

`source ./narrative_navigator_env/bin/activate`


**Q: ModuleNotFoundError**
重新安装依赖
`
pip install -r requirements.txt
`

**Q: API密钥错误**
- 检查 `.env` 文件格式
- 确认API密钥有效性
- 验证API配额

### 日志查看
查看运行日志
`tail -f logs/baseline_agent.log`


## API参考

### BaselineAgent类
```
class BaselineAgent:
    def __init__(self)  # 初始化Agent
    def initialize_conversation(self, basic_info)  # 初始化对话
    def get_next_question(self, user_response)  # 获取下个问题
    def run_interview(self)  # 运行访谈循环
```

## 贡献指南

1. Fork本仓库
2. 创建特性分支：`git checkout -b feature/新功能`
3. 提交更改：`git commit -am '添加新功能'`
4. 推送分支：`git push origin feature/新功能`
5. 提交Pull Request

## 许可证

本项目采用MIT许可证。详见[LICENSE](LICENSE)文件。

## 更新日志

### v1.0.0 (2026-02-05)
- 初始版本发布
- 实现基线对话Agent
- 支持基础访谈功能

## 技术支持

- 问题反馈：[GitHub Issues](链接)
- 文档更新：[Wiki](链接)
- 联系方式：your-email@example.com

---
