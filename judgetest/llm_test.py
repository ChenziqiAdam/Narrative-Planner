import os
import json
from dotenv import load_dotenv

# 腾讯云 SDK
from tencentcloud.common import credential
from tencentcloud.common.profile.client_profile import ClientProfile
from tencentcloud.common.profile.http_profile import HttpProfile
from tencentcloud.common.exception.tencent_cloud_sdk_exception import TencentCloudSDKException
from tencentcloud.hunyuan.v20230901 import hunyuan_client, models

# Moonshot (OpenAI-compatible) SDK
from openai import OpenAI

# 加载密钥
load_dotenv()


class LLMJudgeEvaluator:
    def __init__(self, provider: str = "hunyuan"):
        """
        初始化 LLM Judge 客户端

        参数:
            provider: 模型提供商，可选 "hunyuan" (腾讯混元) 或 "moonshot" (月之暗面 Kimi)
        """
        self.provider = provider.lower()

        if self.provider == "hunyuan":
            self.secret_id = os.getenv("TENCENT_SECRET_ID")
            self.secret_key = os.getenv("TENCENT_SECRET_KEY")

            cred = credential.Credential(self.secret_id, self.secret_key)
            httpProfile = HttpProfile()
            httpProfile.endpoint = "hunyuan.tencentcloudapi.com"
            clientProfile = ClientProfile()
            clientProfile.httpProfile = httpProfile

            # 实例化腾讯混元客户端
            self.client = hunyuan_client.HunyuanClient(cred, "ap-guangzhou", clientProfile)
            print(">>> 混元 LLM Judge 客户端已就绪")

        elif self.provider == "moonshot":
            self.moonshot_api_key = os.getenv("MOONSHOT_API_KEY")
            if not self.moonshot_api_key:
                raise ValueError("MOONSHOT_API_KEY 环境变量未设置，请检查 .env 文件")

            # 实例化 Moonshot (OpenAI 兼容) 客户端
            self.client = OpenAI(
                api_key=self.moonshot_api_key,
                base_url="https://api.moonshot.cn/v1"
            )
            print(">>> Moonshot (Kimi) LLM Judge 客户端已就绪")

        else:
            raise ValueError(f"不支持的模型提供商: {provider}，仅支持 'hunyuan' 或 'moonshot'")

    def _call_llm(self, system_prompt: str, user_prompt: str, model: str = None) -> str:
        """
        统一的大模型调用接口，根据 provider 自动路由

        参数:
            system_prompt: System Prompt
            user_prompt: User Prompt
            model: 可选的模型名称（仅 Moonshot 需要，混元默认用 hunyuan-lite）

        返回:
            str: LLM 生成的文本内容
        """
        if self.provider == "hunyuan":
            try:
                req = models.ChatCompletionsRequest()
                params = {
                    "Model": "hunyuan-lite",
                    "Messages": [
                        {"Role": "system", "Content": system_prompt},
                        {"Role": "user", "Content": user_prompt}
                    ],
                    "Temperature": 0.0
                }
                req.from_json_string(json.dumps(params))
                resp = self.client.ChatCompletions(req)

                if hasattr(resp, "Choices") and len(resp.Choices) > 0:
                    return resp.Choices[0].Message.Content

                raise Exception("API 返回结构异常")

            except TencentCloudSDKException as err:
                raise Exception(f"腾讯云 API 报错: {err}")

        elif self.provider == "moonshot":
            try:
                # Moonshot 使用 OpenAI 兼容接口
                response = self.client.chat.completions.create(
                    model=model or "moonshot-v1-8k",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    temperature=0.0
                )
                return response.choices[0].message.content

            except Exception as err:
                raise Exception(f"Moonshot API 报错: {err}")

    def _parse_llm_json(self, content):
        """
        辅助函数：从 LLM 的回复中提取 JSON。
        防止 LLM 输出 Markdown 格式 (```json ... ```) 导致解析失败。
        """
        try:
            # 清理 Markdown 标记
            content = content.replace("```json", "").replace("```", "").strip()
            return json.loads(content)
        except json.JSONDecodeError:
            print(f"JSON 解析失败，原始返回: {content}")
            return {"is_pass": False, "reason": "解析错误"}

    def check_semantic_equivalence(self, goal, response):
        """
        调用 LLM 进行语义判定
        """
        # --- 1. 构建 System Prompt ---
        # 这是 LLM Judge 的核心，我们告诉它判定规则
        system_prompt = """你是一个严苛的“回忆录访谈审计员”。你的任务是评估【用户的回答】对于【Planner的目标】的完成质量。

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
        """

        user_prompt = f"""
        【Planner的目标】: {goal}
        【用户的回答】: {response}

        请根据上述规则进行 JSON 判定：
        """

        try:
            # --- 2. 调用统一的 LLM 接口 ---
            content = self._call_llm(system_prompt, user_prompt)

            # --- 3. 解析结果 ---
            result_json = self._parse_llm_json(content)
            return result_json.get("is_pass", False), result_json.get("reason", "无理由")

        except Exception as e:
            print(f"LLM 调用错误: {e}")
            return False, str(e)

    def evaluate_planner_question(self, dialogue_context, planner_goal, planner_question):
        """
        评估 Planner 提问的质量（Query-side Evaluation）

        参数:
            dialogue_context: 对话历史上下文
            planner_goal: Planner 的目标（如 "深挖细节"、"跳转话题"）
            planner_question: Planner 提出的问题

        返回:
            dict: {
                "reason": "简短评价（50字以内）",
                "question_score": 0.0 到 1.0 的浮点数
            }
        """
        # --- 1. 构建 System Prompt ---
        system_prompt = """你是一个专业的“回忆录访谈策略评测专家”。你的任务是精准评估【Planner提出的问题】的质量。

        请牢记：回忆录访谈不仅需要完成信息收集，更需要极高的“同理心（EQ）”和“话题启发能力”。

        【精准评分量表（请严格对标以下分数段）】：
        - [0.8 - 1.0] 优秀提问：提问是开放式的（如“具体发生了什么”、“当时是什么感觉”），能完美激发细节讲述。且承上启下非常自然。
        - [0.5 - 0.7] 及格提问：基本符合目标，过渡尚可，但提问略显平庸，或者带有一点点引导性，故事挖掘潜力一般。
        - [0.3 - 0.4] 策略失误（封闭式提问）：提问并没有跑题（符合 Planner 目标），但犯了“封闭式提问”的错误（如“你觉得好吗？”、“开心吗？”）。这类问题导致受访者极易用“是/否”或单个词终结话题，缺乏启发性。
        - [0.1 - 0.2] 情感灾难（生硬跳转）：极度缺乏同理心。在用户表露悲伤、遗憾等严肃情绪时，无视对方情绪，使用诸如“我们不聊这个了”、“说说别的吧”等极其生硬的方式强行切换话题。这极大地不尊重用户体验。
        - [0.0] 完全失效：不知所云或产生严重的幻觉。

        请输出严格的 JSON 格式：
        {
            "reason": "简明扼要的判定理由（指出是开放/封闭式，以及情感承接的好坏）",
            "question_score": 0.0 到 1.0 的浮点数（请根据上述量表精确打分）
        }
        """

        user_prompt = f"""
        【对话历史】: {dialogue_context}
        【Planner目标】: {planner_goal}
        【Planner提问】: {planner_question}

        请根据上述规则进行评估：
        """

        try:
            # --- 2. 调用统一的 LLM 接口 ---
            content = self._call_llm(system_prompt, user_prompt)

            # --- 3. 解析结果 ---
            result_json = self._parse_llm_json(content)
            return result_json

        except Exception as e:
            print(f"LLM 调用错误: {e}")
            return {"reason": str(e), "question_score": 0.0}

# --- 测试用例 ---
if __name__ == "__main__":
    # 运行时让用户选择模型
    print("\n请选择模型提供商:")
    print("  1. hunyuan (腾讯混元)")
    print("  2. moonshot (月之暗面 Kimi)")
    choice = input("请输入选项 (1/2): ").strip()

    if choice == "1":
        provider = "hunyuan"
    elif choice == "2":
        provider = "moonshot"
    else:
        print("无效选择，默认使用 hunyuan")
        provider = "hunyuan"

    print(f"\n{'='*20} 初始化 LLM Judge (Provider: {provider}) {'='*20}")
    judge = LLMJudgeEvaluator(provider=provider)

    # Response-side 测试集
    response_test_cases = [
        # Case 1: 完美等价
        ("我记得那是一个夏天的傍晚，爸爸在公园教我骑自行车。刚开始我总是摔倒，膝盖都磕破了，想放弃。但在爸爸的鼓励下，我最终掌握了平衡，那种风吹过脸庞的感觉让我至今难忘。",
         "那时候是夏天，天快黑了。我和我爸在楼下的公园里练车。前面几次我根本骑不稳，摔了好几个狗吃屎，腿疼死了，我当时气得把车都扔了。后来我爸一直劝我再试一次，结果我真的学会了！骑起来的时候感觉风呼呼地吹，太爽了，这事我记一辈子。",
         "✅ 预期: TRUE"),
        # Case 2: Noisy (噪音干扰)
       ("大学毕业那年，我决定去北京闯荡。找工作非常不顺利，住地下室，吃了两个月泡面。最后终于在一家互联网公司拿到offer，虽然工资不高，但那是梦想开始的地方。",
         "那是2015年吧，具体的日子我忘了。当时其实我妈想让我回老家考公务员，但我不想过一眼望到头的日子，就买了张票去了北京。刚去的时候住的那个地下室，哎哟全是霉味，隔壁还住着一对吵架的情侣。我那两个月天天吃红烧牛肉面，现在闻到那个味都想吐。不过好在最后运气不错，有个互联网小公司录用我了。虽然钱少，好像才给四千块吧，但毕竟能留下来了。",
         "✅ 预期: TRUE（虽然有废话）"),
        # Case 3: 核心冲突
        ("高中最遗憾的事情是没有坚持练钢琴。当时为了高考，把学了六年的钢琴停掉了。现在听到别人弹琴，心里总是空落落的。",
         "高中最遗憾的是没有向那个女生表白。当时为了高考，家里管得严，我把这份喜欢藏在心里。现在看到她结婚的朋友圈，心里总是空落落的。",
         "❌ 预期: FALSE"),
        # Case 4: 乱序
        ("过年的时候，全家人围在一起包饺子。奶奶负责擀皮，妈妈负责调馅，我们几个小孩负责捣乱。等到热腾腾的饺子出锅，窗外正好响起了鞭炮声。",
         "窗外放鞭炮的时候，饺子刚好出锅了，特别香。记得那时候主要是奶奶擀皮，妈妈弄馅儿。我们小孩子啥也不会，就在那瞎玩。反正每年过年全家都会这样围在一起，特别温馨。",
         "✅ 预期: TRUE"),
        # Case 5: 无关答案
        ("我最喜欢的旅行是去云南大理。那里的苍山洱海非常美，生活节奏很慢，让我彻底放松了身心。",
         "我觉得现在的手机游戏太氪金了。特别是那个新出的皮肤，死贵死贵的，完全是在割韭菜。以后我再也不充钱了，没意思。",
         "❌ 预期: FALSE")
    ]

    # 赋值给 test_cases 供后续使用
    test_cases = response_test_cases

    # Query-side 测试集
    query_test_cases = [
        # Case 1: 优秀提问 - 承上启下（高分）
        {
            "dialogue_context": "用户：我们小时候有个叫二狗子的玩伴，天天一起上下学。那时候我们两家住得近，他家院子里有棵大枣树，一到秋天我们就一起去打枣。",
            "planner_goal": "深挖这段友谊的细节",
            "planner_question": "二狗子枣树上的枣子是什么味道的？你们有没有什么有趣的故事？",
            "expected": {
                "question_score": 0.8,
                "reason": "顺着话头追问细节，承上启下自然"
            }
        },
        # Case 2: 糟糕提问 - 生硬跳转（低分）
        {
            "dialogue_context": "用户：我母亲走的那天，我整个人都是蒙的...她辛苦了一辈子，还没享到什么福就这样走了，这是我心里永远的痛。",
            "planner_goal": "切换到工作阶段",
            "planner_question": "我们不聊这个了，说说你第一份工作吧。",
            "expected": {
                "question_score": 0.2,
                "reason": "生硬跳转，缺乏情感共鸣，不尊重用户情绪"
            }
        },
        # Case 3: 无效提问 - 封闭式问题（较低分）
        {
            "dialogue_context": "用户：那是1970年代响应国家号召，我们下乡插队到黑龙江，一晃就是三年。",
            "planner_goal": "引导老人讲述插队时的困难",
            "planner_question": "你插队的时候觉得苦吗？",
            "expected": {
                "question_score": 0.4,
                "reason": "封闭式问题容易导致简单回答'苦'，话题终结"
            }
        }
    ]

    # --- Response-side Evaluation 测试 ---
    # print(f"\n{'='*20} 开始 LLM Judge 测试 {'='*20}")
    # for i, (goal, resp, expected) in enumerate(test_cases):
    #     print(f"\nCase {i+1} Testing...")

    #     # 截断一下显示
    #     print(f"  [目标] {goal[:20]}...")
    #     print(f"  [回答] {resp[:20]}...")

    #     is_pass, reason = judge.check_semantic_equivalence(goal, resp)

    #     # 结果展示
    #     icon = "✅ PASS" if is_pass else "❌ REJECT"
    #     print(f"  [AI 判决] {icon}")
    #     print(f"  [AI 理由] {reason}")
    #     print(f"  [预期结果] {expected}")

    # --- Query-side Evaluation 测试 ---
    print(f"\n{'='*20} Planner 提问质量评估测试 {'='*20}")

    for i, test_case in enumerate(query_test_cases):
        print(f"\nCase {i+1}: Query-side Evaluation")
        print(f"  [对话历史] {test_case['dialogue_context'][:40]}...")
        print(f"  [Planner目标] {test_case['planner_goal']}")
        print(f"  [Planner提问] {test_case['planner_question']}")

        result = judge.evaluate_planner_question(
            test_case['dialogue_context'],
            test_case['planner_goal'],
            test_case['planner_question']
        )

        # 打印实际输出
        print(f"\n  --- 【实际输出 Actual】 ---")
        print(f"    [AI 评分] {result.get('question_score', 0.0)}")
        print(f"    [AI 理由] {result.get('reason', '无')}")

        # 打印预期结果
        print(f"\n  --- 【预期结果 Expected】 ---")
        expected = test_case['expected']
        print(f"    [预期评分] {expected.get('question_score', 'N/A')}")
        print(f"    [预期理由] {expected.get('reason', 'N/A')}") 