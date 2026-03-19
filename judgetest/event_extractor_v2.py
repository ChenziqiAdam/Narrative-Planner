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


class EventExtractorV2:
    """
    事件提取器 V2 版本
    - 支持 provider 切换（hunyuan/moonshot）
    - 从文件读取对话历史，输出到 JSON 文件
    - 继承 1.0 版本核心提取逻辑（五元组：时间、地点、事件、人物、感受）
    """

    def __init__(self, provider: str = "hunyuan"):
        """
        初始化事件提取器 V2

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
            print(">>> 混元事件提取器 V2 客户端已就绪")

        elif self.provider == "moonshot":
            self.moonshot_api_key = os.getenv("MOONSHOT_API_KEY")
            if not self.moonshot_api_key:
                raise ValueError("MOONSHOT_API_KEY 环境变量未设置，请检查 .env 文件")

            # 实例化 Moonshot (OpenAI 兼容) 客户端
            self.client = OpenAI(
                api_key=self.moonshot_api_key,
                base_url="https://api.moonshot.cn/v1"
            )
            print(">>> Moonshot (Kimi) 事件提取器 V2 客户端已就绪")

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

    def extract_events(self, dialogue_history: str) -> list:
        """
        从访谈对话历史中提取关键事件

        参数:
            dialogue_history: 包含多轮对话的字符串，每轮对话用换行分隔

        返回:
            list: 事件列表，每个事件包含时间、地点、事件、人物、感受五元组
        """
        # --- 1. 构建 System Prompt ---
        system_prompt = """你是一个专业、严谨的"回忆录传记整理专家"。你的任务是从老人漫长、口语化的对话历史中，精准提取出核心的【人生事件】。

        请严格按照以下规则提取，并输出 JSON 数组格式。为了保证提取的准确性，每个事件对象必须包含以下 7 个字段（请务必先填写 `_线索细节检验`，再填写 `未展开线索`）：

        1. 【时间】：必须进行跨轮次的“指代消解”。根据前文将“那时候”、“后来”还原为具体的时期，绝对不能填“未提及”。
        2. 【地点】：提取事件发生的具体或相对空间场景，结合上下文补全。
        3. 【事件】：客观、简练地总结起因、经过、结果。⚠️ 强制合并规则：同一个大背景、同时期的连贯回忆，必须强制合并为【一个】事件对象！将各轮次的细节汇聚于此。
        4. 【人物】：提取所有参与或影响该事件的关键人物。
        5. 【感受】：必须且只能提取老人（受访者）的主观情绪、感慨或反思！
        6. 【_线索细节检验】（⚠️极其重要，不可省略）：
           - 请提取受访者在最后几句话中抛出的新人物、新物品或转折。
           - 问自己：这个人物/事件是否只停留在“概括性动作”（如：照顾、帮衬、发生意外），还是有“具体的画面和小故事”（具体做了什么事、说了什么话）？
           - 如果受访者已经明确表示对某事“不想多说”、“没啥回忆的”，则视为死胡同，不作提取。
           - 请在这里写下你的简短检验过程。
        7. 【未展开线索】（你的信息雷达）：
           - 严格基于你在 `_线索细节检验` 中的结论！
           - 如果存在只有“概括性动作”而缺乏“具体画面”的实体，或者抛出了新人物却没讲背景，必须填写在这里。
           - 只有当细节极度丰满、或者对话完全封闭没有悬念时，才填"无"。

        【示例演示】
        输入样例：
        "访谈者：您当老师这十年真让人敬佩。
        老人：害，就是混口饭吃，其实没啥好说的。不过那时候多亏了看门的大爷老王。
        访谈者：老王怎么了？
        老人：老王当时特别关照我，帮了我大忙，其实我心里挺感激他的。"
        
        输出样例：
        [
            {
                "时间": "当老师的十年",
                "地点": "学校",
                "事件": "当老师批改作业十分劳累，觉得没什么好回忆的，但期间得到了看门老王的关照。",
                "人物": "看门大爷老王",
                "感受": "对老王心存深深的感激。",
                "_线索细节检验": "老人提到老王'特别关照我，帮了大忙'，这只是高度概括的动作结论，完全没有讲述老王具体是怎么帮忙的画面和细节。属于未展开状态。",
                "未展开线索": "看门大爷老王（具体的关照细节未展开）"
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
            # ⬇️ 新增：阅后即焚逻辑 ⬇️
            for event in result_json:
                if "_线索细节检验" in event:
                    del event["_线索细节检验"] 
            # ⬆️ 到这里，传给下游的数据就极其干净了 ⬆️
            print(f">>> JSON 解析成功，提取到 {len(result_json)} 个事件")
            return result_json

        except Exception as e:
            print(f"❌ LLM 调用错误: {e}")
            import traceback
            traceback.print_exc()
            return []

    def extract_from_file(self, input_path: str, output_path: str) -> list:
        """
        从文本文件读取对话历史并提取事件到 JSON 文件

        参数:
            input_path: 输入文本文件路径
            output_path: 输出 JSON 文件路径

        返回:
            list: 提取到的事件列表
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


if __name__ == "__main__":
    # 1. 初始化 extractor
    print(f"{'='*20} 初始化事件提取器 V2 {'='*20}")
    extractor = EventExtractorV2(provider="moonshot")

    # 2. 调用 extract_from_file 读取 dialogue_incomplete_sample.txt
    # 3. 输出到 extracted_events_v2.json
    print(f"\n{'='*20} 开始文件提取 {'='*20}")
    events = extractor.extract_from_file(
        input_path="dialogue_incomplete_sample.txt",
        output_path="extracted_events_v2.json"
    )

    print(f"\n{'='*20} 提取结果摘要 {'='*20}")
    print(f"共提取到 {len(events)} 个事件")
    for i, event in enumerate(events):
        print(f"\n事件 {i+1}:")
        print(f"  时间: {event.get('时间', '未提及')}")
        print(f"  地点: {event.get('地点', '未提及')}")
        print(f"  事件: {event.get('事件', '无')}")
        print(f"  人物: {event.get('人物', '未提及')}")
        print(f"  感受: {event.get('感受', '无')}")
        print(f"  未展开线索: {event.get('未展开线索', '无')}")
