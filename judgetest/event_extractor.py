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


class EventExtractor:
    def __init__(self, provider: str = "hunyuan"):
        """
        初始化事件提取器

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
            print(">>> 混元事件提取器客户端已就绪")

        elif self.provider == "moonshot":
            self.moonshot_api_key = os.getenv("MOONSHOT_API_KEY")
            if not self.moonshot_api_key:
                raise ValueError("MOONSHOT_API_KEY 环境变量未设置，请检查 .env 文件")

            # 实例化 Moonshot (OpenAI 兼容) 客户端
            self.client = OpenAI(
                api_key=self.moonshot_api_key,
                base_url="https://api.moonshot.cn/v1"
            )
            print(">>> Moonshot (Kimi) 事件提取器客户端已就绪")

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
                    temperature=0.0,
                    max_tokens=8000
                )
                return response.choices[0].message.content

            except Exception as err:
                raise Exception(f"Moonshot API 报错: {err}")

    def _parse_llm_json(self, content):
        """
        辅助函数：从 LLM 的回复中提取 JSON。
        防止 LLM 输出 Markdown 格式导致解析失败。
        """
        try:
            # 清理 Markdown 标记
            cleaned_content = content.replace("```json", "").replace("```", "").strip()
            print(f">>> JSON 清理前长度: {len(content)}, 清理后长度: {len(cleaned_content)}")
            result = json.loads(cleaned_content)
            print(f">>> JSON 解析成功")
            return result
        except json.JSONDecodeError as e:
            print(f"❌ JSON 解析失败: {e}")
            print(f"❌ 清理后的内容: {cleaned_content[:500]}...")
            return []

    def extract_events(self, dialogue_history):
        """
        从访谈对话历史中提取关键事件

        参数:
            dialogue_history: 包含多轮对话的字符串，每轮对话用换行分隔

        返回:
            list: 事件列表，每个事件包含日期、主题、人、描述
        """
        # --- 1. 构建 System Prompt ---
        system_prompt = """你是一个专业、严谨的“回忆录传记整理专家”与“数据标注员”。你的任务是从老人漫长、口语化、可能带有大量废话的对话历史中，精准提取出核心的【人生事件】。

        请严格按照以下规则提取，并输出 JSON 数组格式，每个事件必须包含以下 5 个严格定义的字段：
        1. 【时间】：提取具体年份或相对时间（如“1998年”、“初二那年”、“90年代初”）。如果完全没提到时间，填“未提及”。
        2. 【地点】：提取事件发生的具体或相对空间场景（如“生产队地瓜地”、“陕北乡下”）。如果完全没提到地点，填“未提及”。
        3. 【事件】：⚠️ 宏观概括核心骨架！用第三人称客观、简练地总结事件的起因、经过、结果。**必须摒弃细枝末节的文学性动作描写（如“跑丢了鞋”、“拿着卡尺量”）**。过滤掉情绪宣泄、抱怨和无关的废话。
        4. 【人物】：提取所有参与或影响该事件的关键人物（包括主角互动的所有配角）。
           ⚠️ 核心规范（非常重要）：必须将人物名称规范化为“身份/头衔 + 姓名”的简练名词短语。绝不能照抄含有动词的原句短语！
           - 错误示范：“车间主任姓王”、“他妈”、“我同桌”
           - 正确示范：“车间王主任”、“小明妈妈”、“同桌小明”
           如果没有提到其他人，填“未提及”。多个人物之间严格用顿号（、）分隔。
        5. 【感受】：提取受访者当时的主观情绪（如“绝望”、“惊喜”），或者受访者如今提到这件事时的感慨与反思。

        【示例演示】
        输入样例：
        "我上高中的时候，班里规矩特别严。班主任是个姓李的老头，凶得很。有次我前桌李雷上课睡觉，被他拿粉笔头直接砸醒了，后来连李雷他爸都被叫到学校挨训，现在的老师哪敢这样啊。"
        输出样例：
        [
            {
                "时间": "高中时期",
                "地点": "学校班级",
                "事件": "前桌李雷上课睡觉被班主任李老师抓到，并叫家长到校挨训。",
                "人物": "班主任李老师、前桌李雷、李雷爸爸",
                "感受": "觉得当时的老师极其严厉，感慨现在的老师不敢这样管学生。"
            }
        ]

        警告：你输出的结果必须且只能是合法的 JSON 数组，不要包含任何多余的解释、Markdown 标记或客套话。
        """

        user_prompt = f"""
        【访谈对话历史】:
        {dialogue_history}

        请提取其中的关键事件：
        """

        try:
            # --- 2. 调用统一的 LLM 接口 ---
            print(f">>> 正在调用 {self.provider} API...")
            content = self._call_llm(system_prompt, user_prompt)
            print(f">>> API 返回内容长度: {len(content)} 字符")
            print(f">>> API 返回前 200 字符: {content[:200]}...")

            # --- 3. 解析结果 ---
            result_json = self._parse_llm_json(content)
            print(f">>> JSON 解析成功，提取到 {len(result_json)} 个事件")
            return result_json

        except Exception as e:
            print(f"❌ LLM 调用错误: {e}")
            import traceback
            traceback.print_exc()
            return []

    def extract_from_file(self, input_path: str, output_path: str):
        """
        从文本文件读取对话历史并提取事件到 JSON 文件

        参数:
            input_path: 输入文本文件路径
            output_path: 输出 JSON 文件路径
        """
        try:
            # 检查输入文件是否存在
            if not os.path.exists(input_path):
                print(f"❌ 错误: 输入文件不存在: {input_path}")
                return []

            # 读取输入文件
            print(f">>> 正在读取文件: {input_path}")
            with open(input_path, 'r', encoding='utf-8') as f:
                dialogue_text = f.read()
            print(f">>> 文件读取成功，共 {len(dialogue_text)} 字符")

            # 提取事件
            print(">>> 正在调用 LLM 提取事件...")
            events = self.extract_events(dialogue_text)

            if not events:
                print("⚠️ 警告: 未提取到任何事件（返回空列表）")
            else:
                print(f">>> 成功提取 {len(events)} 个事件")

            # 确保输出目录存在
            output_dir = os.path.dirname(output_path)
            if output_dir and not os.path.exists(output_dir):
                os.makedirs(output_dir)
                print(f">>> 创建输出目录: {output_dir}")

            # 写入输出文件
            print(f">>> 正在写入文件: {output_path}")
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(events, f, ensure_ascii=False, indent=4)

            # 验证文件是否写入成功
            if os.path.exists(output_path):
                file_size = os.path.getsize(output_path)
                abs_path = os.path.abspath(output_path)
                print(f"✅ 事件提取完成，已保存到: {abs_path} ({file_size} 字节)")
            else:
                print(f"❌ 错误: 文件写入失败，文件不存在: {output_path}")

            return events

        except Exception as e:
            print(f"❌ extract_from_file 发生错误: {e}")
            import traceback
            traceback.print_exc()
            return []


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

    print(f"\n{'='*20} 初始化事件提取器 (Provider: {provider}) {'='*20}")
    extractor = EventExtractor(provider=provider)

    # 选择运行模式
    print("\n请选择运行模式:")
    print("  1. 使用内置测试样例")
    print("  2. 使用文件 I/O 功能")
    mode_choice = input("请输入选项 (1/2): ").strip()

    if mode_choice == "1":
        # ========== 模式 1：内置测试样例 ==========
        # 基础测试对话（保留原有示例）
        dialogue_history_basic = """
        访谈者：您能跟我讲讲您年轻时的故事吗？

        用户：我记得那是1995年的夏天，我刚大专毕业。那年夏天特别热，我一个人背着行李，坐了20多个小时的火车去深圳打工。

        访谈者：当时为什么选择去深圳呢？

        用户：那时候改革开放，深圳发展特别快。我学的是计算机相关专业，觉得那边机会多。我爸妈一开始不同意，觉得一个女孩子跑那么远不安全。但我还是想出去闯一闯。

        访谈者：第一次去深圳有什么印象深刻的事情吗？

        用户：到了深圳站是凌晨三点，人生地不熟的。我记得那天晚上月亮特别圆，我坐在火车站广场的石凳上，看着天上的月亮，又紧张又兴奋。那时候我随身带了一个小包，里面有我奶奶给我做的布鞋，她说外面的鞋子不透气，让我带着。

        访谈者：您奶奶对您影响一定很大吧？

        用户：是啊，我奶奶是老教师，退休前一直在小学教书。她从小就教育我要独立、要自强。虽然她2010年走了，但她的教诲我一直记在心里。
        """

        # 新增测试用例
        test_cases = [
            {
                "name": "Case 1: 时间隐晦 + 多人互动",
                "dialogue": "我记得是我上初二那年吧，那时候农村也没啥玩的，我和我同桌小明每天放学就去村东头的水沟抓蛐蛐。有一天他一脚踩空掉水沟里了，糊了满身泥，还是我费了九牛二虎之力把他拉上来的，哈哈，后来他妈还来我家送了几个鸡蛋感谢我。",
                "expected": [
                    {
                        "日期": "初二那年",
                        "主题": "抓蛐蛐救同桌",
                        "人": "同桌小明、小明妈妈",
                        "描述": "初二时和同桌去抓蛐蛐，同桌掉进水沟被我救起，对方母亲送鸡蛋答谢。"
                    }
                ]
            },
            {
                "name": "Case 2: 噪音极大 + 单一事件",
                "dialogue": "现在的年轻人啊，动不动就辞职，真的是太吃不了苦了。哪像我们那时候，干一份工作就是一辈子。我记得90年代初我在一棉厂当女工，那时候车间主任姓王，是个母老虎，对我们可严格了，迟到一分钟都要扣半天工资，大家干活都拼了命一样。现在的厂长哪敢这么管工人啊。",
                "expected": [
                    {
                        "日期": "90年代初",
                        "主题": "一棉厂当女工",
                        "人": "车间王主任",
                        "描述": "在一棉厂当女工，车间王主任管理极其严格，工人工作非常拼命。"
                    }
                ]
            },
            {
                "name": "Case 3: 信息缺失 (纯情绪宣泄)",
                "dialogue": "唉，别提了。其实那次真的挺伤心的，我一个人在屋里关着门哭了很久很久。那时候感觉天都要塌下来了，也没有人能理解我，现在想起来心里都不好受，心脏直跳。",
                "expected": [
                    {
                        "日期": "未提及",
                        "主题": "一次极度伤心的经历",
                        "人": "未提及",
                        "描述": "经历了一次极其伤心的事情，独自关在屋里哭泣，感到无人理解。"
                    }
                ]
            }
        ]

        print(f"\n{'='*20} 事件提取测试 {'='*20}")

        # 测试基础示例
        print("\n>>> 基础示例测试 <<<")
        print("输入对话历史：")
        print(dialogue_history_basic[:200] + "...")

        events = extractor.extract_events(dialogue_history_basic)

        print(f"\n提取的事件数量: {len(events)}")
        print("\n提取结果:")
        for i, event in enumerate(events):
            print(f"\n事件 {i+1}:")
            print(f"  日期: {event.get('日期', '未知')}")
            print(f"  主题: {event.get('主题', '未知')}")
            print(f"  人: {event.get('人', '未提及')}")
            print(f"  描述: {event.get('描述', '无')}")

        # 循环测试新增用例
        for case in test_cases:
            print(f"\n\n{'='*20}")
            print(f">>> Case: {case['name']} <<<")
            print(f"\n输入对话历史：")
            print(case['dialogue'][:200] + "...")

            events = extractor.extract_events(case['dialogue'])

            print(f"\n提取的事件数量: {len(events)}")

            # 打印实际输出 (Actual)
            print("\n" + "-" * 15)
            print("【实际输出 Actual】:")
            if not events:
                print("  (无事件提取)")
            for i, event in enumerate(events):
                print(f"\n  事件 {i+1}:")
                print(f"    日期: {event.get('日期', '未知')}")
                print(f"    主题: {event.get('主题', '未知')}")
                print(f"    人: {event.get('人', '未提及')}")
                print(f"    描述: {event.get('描述', '无')}")

            # 打印预期结果 (Expected)
            print("\n" + "-" * 15)
            print("【预期结果 Expected】:")
            expected = case.get("expected", [])
            if not expected:
                print("  (无预期)")
            for i, exp in enumerate(expected):
                print(f"\n  事件 {i+1}:")
                print(f"    日期: {exp.get('日期', '未知')}")
                print(f"    主题: {exp.get('主题', '未知')}")
                print(f"    人: {exp.get('人', '未提及')}")
                print(f"    描述: {exp.get('描述', '无')}")

    elif mode_choice == "2":
        # ========== 模式 2：文件 I/O 功能 ==========
        print(f"\n{'='*20} 文件 I/O 功能 {'='*20}")

        # 检查并创建 sample_dialogue.txt
        if not os.path.exists("sample_dialogue.txt"):
            print(">>> 创建 sample_dialogue.txt...")
            sample_content = """访谈者：您能跟我讲讲您年轻时的故事吗？

            用户：我记得那是1995年的夏天，我刚大专毕业。那年夏天特别热，我一个人背着行李，坐了20多个小时的火车去深圳打工。

            访谈者：当时为什么选择去深圳呢？

            用户：那时候改革开放，深圳发展特别快。我学的是计算机相关专业，觉得那边机会多。我爸妈一开始不同意，觉得一个女孩子跑那么远不安全。但我还是想出去闯一闯。
            """
            with open("sample_dialogue.txt", "w", encoding="utf-8") as f:
                f.write(sample_content)
            print("✅ sample_dialogue.txt 已创建")

        # 调用文件提取功能
        print(">>> 从文件提取事件...")
        extractor.extract_from_file("sample_dialogue.txt", "extracted_events.json")

    else:
        print("无效选择，默认使用内置测试样例")
        # 默认执行模式1的代码（简化版）
        dialogue_history_basic = """
    访谈者：您能跟我讲讲您年轻时的故事吗？

    用户：我记得那是1995年的夏天，我刚大专毕业。那年夏天特别热，我一个人背着行李，坐了20多个小时的火车去深圳打工。
    """
        print(f"\n{'='*20} 事件提取测试 {'='*20}")
        print("\n>>> 基础示例测试 <<<")
        events = extractor.extract_events(dialogue_history_basic)
        print(f"\n提取的事件数量: {len(events)}")
        for i, event in enumerate(events):
            print(f"\n事件 {i+1}:")
            print(f"  日期: {event.get('日期', '未知')}")
            print(f"  主题: {event.get('主题', '未知')}")
            print(f"  人: {event.get('人', '未提及')}")
            print(f"  描述: {event.get('描述', '无')}")
