### 1. 模块概述

本阶段完成了**语义等价性**（Semantic Equivalence）与**话题完成度**（Completeness）的自动化评估工具链开发。针对”回忆录访谈”非标准答案、长文本叙事的特性，构建了 **Embedding 相似度** 与 **LLM-as-a-Judge** 双轨评估体系。

此外，还新增了两个重要模块：

- **Query-side Evaluation（提问质量评估）**：评估 Planner 提出的问题是否契合目标、是否与上下文自然衔接。
- **Event Extractor（事件提取器）**：从访谈对话历史中自动提取关键事件，结构化为 JSON 格式。

### 1.1 多模型支持 (Model Provider Routing)

本项目支持双模型切换，可以根据需求选择不同的 LLM 提供商：

| 提供商 | 模型 | 配置文件变量 | 说明 |
|:----|:----|:----|:----|
| 腾讯混元 | hunyuan-lite | `TENCENT_SECRET_ID`, `TENCENT_SECRET_KEY` | 默认使用 |
| 月之暗面 (Kimi) | moonshot-v1-8k | `MOONSHOT_API_KEY` | OpenAI 兼容接口 |

#### 环境配置

1. 复制 `.env.example` 为 `.env`：
```bash
cp .env.example .env
```

2. 填写对应的 API 密钥：
```bash
# 腾讯云
TENCENT_SECRET_ID=”your_tencent_secret_id”
TENCENT_SECRET_KEY=”your_tencent_secret_key”

# Moonshot (Kimi)
MOONSHOT_API_KEY=”your_moonshot_api_key”
```

#### 使用方式

运行时程序会提示选择模型：

```bash
# 运行 llm_test.py
python3 llm_test.py
# 输出：
# 请选择模型提供商:
#   1. hunyuan (腾讯混元)
#   2. moonshot (月之暗面 Kimi)
# 请输入选项 (1/2):

# 运行 event_extractor.py
python3 event_extractor.py
# 同样会提示选择模型
```

#### 架构设计

所有 LLM 调用通过统一的 `_call_llm()` 接口进行路由：

```python
def _call_llm(self, system_prompt, user_prompt, model=None):
    if self.provider == “hunyuan”:
        # 腾讯混元 SDK 调用
    elif self.provider == “moonshot”:
        # OpenAI 兼容接口调用
```

### 2. 技术演进路径 (Key Technical Iterations)

我们在开发过程中经历了从“单纯语义匹配”到“语义+完整度综合判定”的三个迭代阶段：

#### V1.0：基于 Embedding 的余弦相似度 (Baseline)

* **方案**：利用腾讯混元 Embedding API 将“Planner 目标”与“User 回答”向量化，计算 Cosine Similarity。

* **遇到问题**：Embedding 对“语义方向”敏感，但对“信息量”不敏感。

* **结论**：仅靠 Embedding 无法衡量回忆录所需的“叙事完整度”。

#### V2.0：引入长度惩罚因子的 Embedding 优化

* **改进**：在余弦相似度基础上，增加了**长度惩罚**（Length Penalty）机制，强制要求用户回答必须具备一定的信息密度。

**核心公式**：

```plain
# 完整度分数 = 基础相似度 * (长度比率 ^ 平滑系数)
final_score = base_similarity * (min(len(response)/len(standard), 1.0) ** 0.9)
```
* **效果**：成功拦截了语义相关但内容空洞的“短回复”。

#### V3.0：基于 LLM-as-a-Judge 的语义审计员 (Current Best)

* **方案**：构建了专门的 System Prompt，让 LLM 扮演“严苛的审计员”，从**语义一致性**、**核心事件匹配**、**信息完整度**三个维度进行 0/1 判定。

* **优势**：较好忽略口语噪音/对于完整度判定更灵活。

### 3. 核心代码逻辑展示

我们最终确立了以 **LLM Judge 为主，Embedding 为辅** 的评估策略。

**System Prompt 设计（完整度与语义双重校验）：**

```plain
{
  "role": "system",
  "content": "你是一个严苛的“回忆录访谈审计员”。你的任务是评估【用户的回答】对于【Planner的目标】的完成质量。

        请基于以下两个大维度进行评估：
        1. 语义相关性 (Relevance)：回答是否切题，是否在讨论目标事件。
        2. 信息完整度 (Completeness)：回答是否提供了足够的细节（如时间、地点、人物、感受、具体经过），而非简单的敷衍（如“是的”、“还行”）。

        判定逻辑（Threshold Logic）：
        - 只有当回答不仅切题，且【完整度】达到 80% 以上（即内容详实、有实质性信息增量）时，才能判定为通过。

        判定细则：
        1. 【核心事件一致性】：必须描述同一个核心事件。用户是否有提到Planner所预期的核心事件？
        2. 【事件完整性】：对于同一核心事件的描述，细节的完整程度应达到80%以上。
        2. 【忽略噪音】：若回答包含大量废话（如具体的年份、吐槽），但核心情节符合，判定为 TRUE。
        3. 【忽略乱序】：叙述顺序不同不影响判定。
        4. 【情感/意图】：若目标是询问情感，回答必须包含相关情感描述。
        5. 【忽略语言细节】：语言的正式与否和用语习惯不影响判定，仅判断两个文段意思是否相同。

        忽略项：
        - 忽略口语废话、乱序、拼写错误。
        
        请输出严格的 JSON 格式：
        {
            "reason": "详细理由，必须包含对完整度的评价（如：内容详实/回答敷衍）",
            "completeness_score": 0.0 到 1.0 的浮点数,
            "is_pass": true 或 false
        }
"
}
```
### 4. 性能对比分析 (Performance Comparison)

基于 5 组典型测试样例（完美匹配、噪音干扰、核心冲突、乱序、无关回答）的测试结果：

|**指标维度**|**Embedding 方法 (V2.0)**|**LLM Judge 方法 (V3.0)**|**结论**|
|:----|:----|:----|:----|
|**语义捕捉**|强（泛化能力好）|强（能理解隐含意图）|相似|
|**逻辑辨析**|强（足够区分事件差异）|强（精准识别主语和事件冲突）|**LLM 更优**|
|**完整度判定**|需人工设计惩罚公式，不够灵活|内置 80% 阈值逻辑，判定符合人类直觉|**LLM 更优**|
|**抗噪能力**|中（受废话长度影响）|高（能自动提取核心情节）|LLM 更优|

**当前结论：** 在回忆录质量评估中，LLM Judge 的表现显著优于 Embedding，更能反映访谈的真实有效性。

### 5. 当前局限与下一步规划 (Limitations & Roadmap)

**当前局限性：**

1. **单轮次判定**：目前仅针对“单次问答”进行切片式评估，尚未涵盖多轮对话的上下文连贯性。

2. **0/1 二元判定**：目前的输出过于绝对（Pass/Fail），无法体现“虽然没说完但值得鼓励”的中间状态。

**阶段二规划：**

1. **从 0/1 到 连续打分**：引入加权打分机制（Weighted Scoring），综合计算语义分、完整度分、情感分。

2. **多轮对话综合评价**：建立 Session 级别的评估指标，计算整个话题块（Topic Block）的完成率。

3. **新增高阶指标**：

   1. **实体密度 (Entity Density)**：统计回答中 Time/Location/Person 的提取数量。

   2. **情感唤起度 (Emotional Arousal)**：评估访谈是否触达用户情感深处。

---

### 6. Query-side Evaluation（提问质量评估）

#### 6.1 背景

传统的 Response-side Evaluation 评估用户回答的质量，但在实际访谈中，**提问的质量同样关键**。一个好的提问能够引导用户展开更多有价值的回忆，而一个突兀的提问则可能破坏访谈的流畅性。

#### 6.2 实现方案

在 `LLMJudgeEvaluator` 类中新增 `evaluate_planner_question` 方法：

```python
def evaluate_planner_question(self, dialogue_context, planner_goal, planner_question):
    """
    评估 Planner 提问的质量
    """
```

#### 6.3 System Prompt 设计

```plain
{
  "role": "system",
  "content": "你是一个专业的“回忆录访谈策略分析师”。你的任务是评估【Planner提出的问题】的质量。

        评估维度：
        1. 目标一致性：评估提问是否契合 planner_goal（深挖/跳转等）
        2. 上下文连贯性：评估提问是否与对话历史自然衔接

        判定逻辑：
        - 提问应自然承接上一轮对话内容
        - 提问应服务于 Planner 设定目标
        - 避免突兀的跳转或无关的追问
        - 优秀的提问能够引导用户展开更多细节

        请输出严格的 JSON 格式：
        {
            "reason": "简短评价（50字以内）",
            "question_score": 0.0 到 1.0 的浮点数
        }
  "
}
```

#### 6.4 测试用例

| Case | Planner目标 | Planner提问 | 预期评分 |
|:----|:----|:----|:----|
| 1 | 深挖细节 | "当时爸爸是怎么鼓励你的？具体说了什么话？" | 高分（自然深挖） |
| 2 | 跳转话题 | "你最喜欢的食物是什么？" | 低分（跳转生硬） |

---

### 7. Event Extractor（事件提取器）

#### 7.1 背景

在完成访谈后，需要对整个对话进行结构化处理。Event Extractor 能够从访谈对话历史中自动提取关键事件，生成结构化的回忆录时间线。

#### 7.2 实现方案

新建 `event_extractor.py`，实现 `EventExtractor` 类：

```python
class EventExtractor:
    def extract_events(self, dialogue_history):
        """
        从访谈对话历史中提取关键事件
        """
```

#### 7.3 输出规范

```json
[
  {
    "日期": "YYYY-MM-DD 或 '未知'/'未提及'",
    "主题": "主题名称",
    "人": "人名 或 '未提及'",
    "描述": "事件描述"
  }
]
```

#### 7.4 System Prompt 设计

```plain
{
  "role": "system",
  "content": "你是一个专业的“回忆录事件提取专家”。你的任务是从访谈对话历史中提取关键事件，并结构化为 JSON 数组。

        输出规范：
        - 日期：格式为 'YYYY-MM-DD'，如果未知则填 '未知'，如果未提及则填 '未提及'
        - 主题：简洁的主题名称（如 '学骑自行车'、'第一次离家'）
        - 人：涉及的人物姓名，如果未提及则填 '未提及'
        - 描述：事件的简要描述

        注意：
        - 只提取有明确时间或情节的事件
        - 忽略闲聊和无意义的客套话
        - 每个事件应该是有意义的回忆节点
  "
}
```

#### 7.5 测试示例

输入一段老人回忆录对话，Event Extractor 能够提取出：

- 1995年夏天：去深圳打工
- 童年时期：奶奶教诲
- 2010年：奶奶去世



