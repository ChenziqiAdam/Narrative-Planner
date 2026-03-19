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


class EventJudgeV2:
    """
    事件决策裁判 V2 版本 - 无监督实时决策引擎

    范式转变：彻底抛弃 Ground Truth 依赖，实现无监督实时评估
    - 基于槽位填充评估 (Slot Filling)
    - 基于情绪能量评估 (Emotional Energy)
    - 自动触发导航策略决策

    Primary Action 枚举:
    - DEEP_DIVE: 深度挖掘（槽位填充 < 80% 且情绪能量 > 0.5）
    - BREADTH_SWITCH: 广度跳转
    - CLARIFY: 纠偏澄清
    - SUMMARIZE: 阶段性总结
    - PAUSE_SESSION: 当天结束
    - CLOSE_INTERVIEW: 全局结束

    Tactical Goal 类型（深度挖掘类）:
    - EXTRACT_DETAILS: 提取事实细节
    - EXTRACT_EMOTIONS: 提取情绪体验
    - EXTRACT_REFLECTIONS: 提取反思感悟
    - EXTRACT_SENSORY: 提取感官细节
    - EXTRACT_CAUSALITY: 提取因果关系
    """

    def __init__(self, provider: str = "hunyuan"):
        """
        初始化导航决策引擎分析师

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
            print(">>> 混元导航决策引擎 V2 客户端已就绪")

        elif self.provider == "moonshot":
            self.moonshot_api_key = os.getenv("MOONSHOT_API_KEY")
            if not self.moonshot_api_key:
                raise ValueError("MOONSHOT_API_KEY 环境变量未设置，请检查 .env 文件")

            # 实例化 Moonshot (OpenAI 兼容) 客户端
            self.client = OpenAI(
                api_key=self.moonshot_api_key,
                base_url="https://api.moonshot.cn/v1"
            )
            print(">>> Moonshot (Kimi) 导航决策引擎 V2 客户端已就绪")

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
            return None

    def make_decision(self, extracted_events: list, dialogue_context: str) -> dict:
        """
        基于提取的事件和对话上下文进行无监督实时决策

        参数:
            extracted_events: 提取的五元组事件列表
            dialogue_context: 对话历史最后几轮上下文

        返回:
            dict: 决策指令，包含 evaluation 和 decision_output
        """
        # --- System Prompt: 导航决策引擎分析师 ---
        system_prompt = """你是"导航决策引擎分析师"，负责评估回忆录访谈对话状态，并做出实时的导航决策。
        
        你的任务是基于提取的事件图谱信息和最新对话上下文，进行无监督评估，并严格从预设的动作库中选择最合适的战术指令。

        【决策逻辑状态机（按优先级执行，一旦命中则终止判定）】
        
        [优先级 1] 疲劳与告别检测 (Session Control)
        - 评估：受访者是否明确表达了“累了”、“今天讲得差不多了”等结束意图？
        - 决策：如果是 ➡️ primary_action: PAUSE_SESSION, tactical_goal: SESSION_FAREWELL

        [优先级 2] 逻辑冲突检测 (Clarification)
        - 评估：对话中是否出现了明显的时间线倒错或常识性矛盾？
        - 决策：如果是 ➡️ primary_action: CLARIFY, tactical_goal: RESOLVE_CONFLICT

        [优先级 3] 新线索捕获 (Hook Exploration)
        - 评估：提取事件的【未展开线索】中，或者最新一轮对话的结尾，是否出现了一个"抛出但未解释"的新实体（如新出现的人物、地点、物品）或概括性结论？
        - 决策：如果是，进一步判断：
          - 若该线索是当前事件的必要组成部分（比如"老李帮了我"，但没说怎么帮）➡️ primary_action: DEEP_DIVE, tactical_goal: EXTRACT_DETAILS
          - 若该线索适合作为一个新的人生话题或关系网展开（比如想了解"老李"这个人的背景或两人如何相识）➡️ primary_action: BREADTH_SWITCH, tactical_goal: EXPLORE_PERSON / EXPLORE_THEME

        [优先级 4] 当前事件槽位检测 (Slot Filling)
        - 评估：当前正在讨论的事件，其时间、地点、经过、人物、感受（5W1H）是否残缺？受访者情绪是否高涨？
        - 决策：如果槽位缺失或情绪高涨且未深挖 ➡️ primary_action: DEEP_DIVE, tactical_goal: (根据缺失部分选择 EXTRACT_EMOTIONS / EXTRACT_REFLECTIONS / EXTRACT_SENSORY / EXTRACT_CAUSALITY)

        [优先级 5] 阶段性完结 (Chapter Conclusion)
        - 评估：当前事件槽位已满，且受访者做出了高度总结性发言，没有留下任何新线索。
        - 决策：如果是 ➡️ primary_action: SUMMARIZE, tactical_goal: REVIEW_PERIOD (或 SYNTHESIZE_THEME)

        【战术动作库 (必须严格从中选择)】
        - DEEP_DIVE 对应的 Tactical Goals: EXTRACT_DETAILS, EXTRACT_EMOTIONS, EXTRACT_REFLECTIONS, EXTRACT_SENSORY, EXTRACT_CAUSALITY
        - BREADTH_SWITCH 对应的 Tactical Goals: EXPLORE_PERIOD, EXPLORE_PERSON, EXPLORE_LOCATION, EXPLORE_THEME
        - CLARIFY 对应的 Tactical Goals: RESOLVE_CONFLICT, CONFIRM_UNDERSTANDING
        - SUMMARIZE 对应的 Tactical Goals: REVIEW_PERIOD, SYNTHESIZE_THEME
        - PAUSE_SESSION 对应的 Tactical Goals: SESSION_FAREWELL

        【强制 JSON 输出结构】
        {
            "evaluation": {
                "logic_conflict_detected": "是/否及理由",
                "pending_cues_status": "精准描述最新抛出且未展开的实体/线索，若无填'无'",
                "slot_filling_status": "描述核心事件5W1H信息的缺失情况",
                "slot_filling_rate": 0.0到1.0的浮点数, 
                "emotional_energy_level": "高/中/低 及理由",
                "emotional_energy_score": -1.0到1.0的浮点数
            },
            "decision_output": {
                "primary_action": "上述五大 Primary Action 之一",
                "tactical_goal": "上述严格对应的 Tactical Goal",
                "reason": "结合状态机的优先级，给出严密的逻辑链条，解释为什么选择了这个动作和目标"
            }
        }

        警告：必须且只能输出合法的 JSON 格式。
        """

        user_prompt = f"""
【提取的五元组事件】:
{json.dumps(extracted_events, ensure_ascii=False, indent=2)}

【最近对话上下文】:
{dialogue_context}

请基于槽位填充和情绪能量进行评估，并输出决策指令：
"""

        try:
            # --- 调用 LLM ---
            print(f">>> 正在调用 {self.provider} API 进行决策评估...")
            content = self._call_llm(system_prompt, user_prompt)
            print(f">>> API 返回内容长度: {len(content)} 字符")
            print(f">>> API 返回前 300 字符: {content[:300]}...")

            # --- 解析结果 ---
            result_json = self._parse_llm_json(content)
            if result_json is None:
                # 返回默认决策
                return {
                    "evaluation": {
                        "slot_filling_status": "解析失败，无法评估",
                        "emotional_energy_level": "未知",
                        "slot_filling_rate": 0.0,
                        "emotional_energy_score": 0.0
                    },
                    "decision_output": {
                        "primary_action": "DEEP_DIVE",
                        "tactical_goal": "EXTRACT_DETAILS",
                        "reason": "JSON解析失败，默认触发深度挖掘以确保信息完整性"
                    }
                }
            return result_json

        except Exception as e:
            print(f"❌ LLM 调用错误: {e}")
            import traceback
            traceback.print_exc()
            return {
                "evaluation": {
                    "slot_filling_status": f"调用错误: {str(e)}",
                    "emotional_energy_level": "未知",
                    "slot_filling_rate": 0.0,
                    "emotional_energy_score": 0.0
                },
                "decision_output": {
                    "primary_action": "DEEP_DIVE",
                    "tactical_goal": "EXTRACT_DETAILS",
                    "reason": "API调用异常，默认触发深度挖掘"
                }
            }

    def decide_from_files(self, events_file: str, dialogue_file: str, output_path: str) -> dict:
        """
        从文件读取提取的事件和对话上下文，进行决策并输出结果

        参数:
            events_file: 提取的事件 JSON 文件路径
            dialogue_file: 对话文本文件路径
            output_path: 决策指令输出 JSON 文件路径

        返回:
            dict: 决策指令字典
        """
        try:
            # 读取提取的事件文件
            print(f">>> 正在读取提取的事件文件: {events_file}")
            with open(events_file, 'r', encoding='utf-8') as f:
                extracted_events = json.load(f)
            print(f">>> 读取成功，共 {len(extracted_events)} 个事件")

            # 读取对话文件（取最后几轮作为上下文）
            print(f">>> 正在读取对话文件: {dialogue_file}")
            with open(dialogue_file, 'r', encoding='utf-8') as f:
                dialogue_full = f.read()
            print(f">>> 读取成功，共 {len(dialogue_full)} 字符")

            # 执行决策
            print(">>> 开始执行决策评估...")
            decision = self.make_decision(extracted_events, dialogue_full)

            # 确保输出目录存在
            output_dir = os.path.dirname(output_path)
            if output_dir and not os.path.exists(output_dir):
                os.makedirs(output_dir)
                print(f">>> 创建输出目录: {output_dir}")

            # 写入决策文件
            print(f">>> 正在写入决策指令: {output_path}")
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(decision, f, ensure_ascii=False, indent=4)

            # 验证文件是否写入成功
            if os.path.exists(output_path):
                file_size = os.path.getsize(output_path)
                abs_path = os.path.abspath(output_path)
                print(f"✅ 决策指令已保存到: {abs_path} ({file_size} 字节)")
            else:
                print(f"❌ 错误: 文件写入失败，文件不存在: {output_path}")

            return decision

        except FileNotFoundError as e:
            print(f"❌ 文件未找到错误: {e}")
            raise
        except json.JSONDecodeError as e:
            print(f"❌ JSON 解析错误: {e}")
            raise
        except Exception as e:
            print(f"❌ decide_from_files 发生错误: {e}")
            import traceback
            traceback.print_exc()
            raise


if __name__ == "__main__":
    # 1. 初始化 judge
    print(f"{'='*20} 初始化导航决策引擎 V2 {'='*20}")
    judge = EventJudgeV2(provider="moonshot")

    # 2. 读取 extracted_events_v2.json 和 dialogue_incomplete_sample.txt
    # 3. 调用 make_decision 生成决策
    # 4. 保存到 decision_instruction_v2.json
    print(f"\n{'='*20} 开始决策评估 {'='*20}")
    decision = judge.decide_from_files(
        events_file="extracted_events_v2.json",
        dialogue_file="dialogue_incomplete_sample.txt",
        output_path="decision_instruction_v2.json"
    )

    # 5. 控制台打印成功信息
    print(f"\n{'='*20} 决策结果摘要 {'='*20}")

    evaluation = decision.get("evaluation", {})
    decision_output = decision.get("decision_output", {})

    print("\n【评估结果】")
    print(f"  槽位填充状态: {evaluation.get('slot_filling_status', 'N/A')}")
    print(f"  槽位填充率: {evaluation.get('slot_filling_rate', 0.0):.2f}")
    print(f"  情绪能量等级: {evaluation.get('emotional_energy_level', 'N/A')}")
    print(f"  情绪能量评分: {evaluation.get('emotional_energy_score', 0.0):.2f}")

    print("\n【决策输出】")
    print(f"  Primary Action: {decision_output.get('primary_action', 'N/A')}")
    print(f"  Tactical Goal: {decision_output.get('tactical_goal', 'N/A')}")
    print(f"  决策理由: {decision_output.get('reason', 'N/A')}")

    # 验证 DEEP_DIVE 触发条件
    primary_action = decision_output.get('primary_action', '')
    tactical_goal = decision_output.get('tactical_goal', '')

    print(f"\n{'='*20} 验证结果 {'='*20}")
    # if primary_action == "DEEP_DIVE":
    #     print("✅ 正确触发 DEEP_DIVE 指令")
    # else:
    #     print(f"⚠️ Primary Action 为 {primary_action}，预期 DEEP_DIVE")
    print(f"Primary Action 为 {primary_action}")

    # if tactical_goal in ["EXTRACT_DETAILS", "EXTRACT_EMOTIONS"]:
    #     print(f"✅ Tactical Goal 正确: {tactical_goal}")
    # else:
    #     print(f"⚠️ Tactical Goal 为 {tactical_goal}，预期 EXTRACT_DETAILS 或 EXTRACT_EMOTIONS")
    print(f"Tactical Goal 为 {tactical_goal}")

    print(f"\n✅ 决策评估完成！")
