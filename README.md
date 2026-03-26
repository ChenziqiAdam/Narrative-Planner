**Narrative-Planner — main.ipynb 说明**

- 本文件说明 `main.ipynb` 中构建的仿真流程、所依赖的文件/模块、运行方法和输出位置，方便复现与二次开发。

**概述**
- `main.ipynb` 演示并运行两个访谈仿真模式：基础 baseline 模式和带 Planner 决策的 planner 模式。
- baseline 模式由 `src/simulation/baseline.py` 中的 `InterviewSimulation` 实现；planner 模式由 `src/simulation/planner_mode.py` 中的 `PlannerInterviewSimulation` 实现。
- 仿真会驱动若干 agent（见 `src/agents/`），并把访谈结果与日志保存到 `results/interviews/` 下的输出文件，同时在控制台打印会话摘要。

**Notebook 里主要构建的内容**
- 加载访谈者配置（示例文件：prompts/roles/elder_profile_example.json）。
- 通过环境变量或 `.env` 提供模型相关配置：`MODEL_TYPE`、`MODEL_BASE_URL`、`API_KEY`（`main.ipynb` 使用 `python-dotenv` 加载环境）。
- 提供两种运行函数：
  - `baseline_mode_simulate()`：初始化 `InterviewSimulation`，运行 `run_interview()`，打印并返回结果文件路径。
  - `planner_mode_simulate()`：初始化 `PlannerInterviewSimulation`（注意 notebook 中会把 `max_turns` 扩展为 `(max_turns)*2+1`），运行并打印包含 `planner_decisions_count` 的摘要。
- 最终会分别调用并执行 baseline 和 planner 两种仿真。

**关键文件与位置**
- Notebook： [main.ipynb](main.ipynb)
- 仿真实现： [src/simulation/baseline.py](src/simulation/baseline.py), [src/simulation/planner_mode.py](src/simulation/planner_mode.py)
- Agent 实现与角色： [src/agents/](src/agents/)
- 核心图/节点逻辑： [src/core/](src/core/)
- 访谈角色示例： [prompts/roles/elder_profile_example.json](prompts/roles/elder_profile_example.json)
- Planner 指令配置： [docs/planner-instruction.yaml](docs/planner-instruction.yaml)
- 仓库依赖： [requirements.txt](requirements.txt)
- 输出目录： `results/interviews/`（仿真运行后在此目录下生成 `.json` / `.txt` 等结果文件）

**运行前准备（先决条件）**
- 建议在虚拟环境中运行：
  - `python -m venv .venv`
  - `& .venv\\Scripts\\Activate.ps1`（Windows PowerShell）或 `source .venv/bin/activate`（Unix）
  - `pip install -r requirements.txt`
- 在项目根目录放置 `.env`，或在系统环境中设置以下变量：
  - `MODEL_TYPE`：模型类型标识（项目中用于选择模型适配逻辑）
  - `MODEL_BASE_URL`：模型服务的 base URL（若使用私有/本地模型服务）
  - `API_KEY`：模型服务的 API Key（如果需要授权）

**如何运行**
- 在 Jupyter 中打开并运行 [main.ipynb](main.ipynb)。Notebook 中提供两个函数：`baseline_mode_simulate()` 和 `planner_mode_simulate()`，最后会顺序执行两个仿真。
- 也可以使用仓库中的脚本运行部分流程：`scripts/run_baseline.py`、`scripts/run_interview.py`（视脚本具体参数而定）。

**输出与摘要字段**
- 仿真结束后会返回一个输出文件路径（`output_file`），通常落在 `results/interviews/` 下。
- 控制台会打印摘要（summary），常见字段包括：
  - `session_id`：会话唯一标识
  - `total_turns`：访谈总回合数
  - `mode`：运行模式（planner 模式会显示）
  - `planner_decisions_count`：仅 planner 模式存在，表示 Planner 做出的决策数

**设计注意与可配置点**
- `planner_mode_simulate()` 中对 `max_turns` 的处理为 `(max_turns)*2+1`，若需要不同节奏请在 notebook 中调整或直接在 `PlannerInterviewSimulation` 构造时传入期望的 `max_turns`。
- 访谈角色、Prompts 和 Planner 指令均为可替换文件（参见 `prompts/` 与 `docs/`），方便做 AB 测试或不同人物设定。

**快速故障排查**
- 若无法调用模型服务，请检查 `.env` 中 `MODEL_BASE_URL` 与 `API_KEY` 是否正确，或在网络/防火墙中放行对应端口。
- 若依赖缺失导致导入失败，确认已在虚拟环境中安装 `requirements.txt`。

**后续建议**
- 如需记录更多元的评估指标，可在 `run_interview()` 或仿真类中扩展输出结构并保存到 `results/`。
- 若要并行跑大批量评估，考虑将仿真改为可 CLI 控制并在外层脚本中并发调度。

如果你希望，我可以：
- 把 README.md 中的运行命令补成 Windows PowerShell 的完整示例；
- 或者根据你指定的模型服务细化 `.env` 示例内容。
