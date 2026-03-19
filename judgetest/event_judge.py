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


class EventJudge:
    """
    事件提取评测裁判类
    用于对比 Ground Truth 和 Extracted 事件集合，输出详细的评测报告
    """

    def __init__(self, provider: str = "hunyuan"):
        """
        初始化事件评测裁判

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
            print(">>> 混元事件评测裁判客户端已就绪")

        elif self.provider == "moonshot":
            self.moonshot_api_key = os.getenv("MOONSHOT_API_KEY")
            if not self.moonshot_api_key:
                raise ValueError("MOONSHOT_API_KEY 环境变量未设置，请检查 .env 文件")

            # 实例化 Moonshot (OpenAI 兼容) 客户端
            self.client = OpenAI(
                api_key=self.moonshot_api_key,
                base_url="https://api.moonshot.cn/v1"
            )
            print(">>> Moonshot (Kimi) 事件评测裁判客户端已就绪")

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

    def evaluate_extraction(self, ground_truth_json: list, extracted_json: list) -> dict:
        """
        评测事件提取的准确性

        参数:
            ground_truth_json: Ground Truth 事件列表
            extracted_json: 实际提取的事件列表

        返回:
            dict: 包含评测报告的字典
        """
        system_prompt = """你是一个严苛但具备宏观视野的数据提取评测专家。你的任务是对比两组回忆录事件数据：
        - 【Ground Truth (GT)】：人工标注的标准核心事件集合
        - 【Extracted】：大模型实际提取的事件集合

        请进行全局交叉比对。为了保证准确无误，你必须先在草稿区进行逐一思考，然后再输出最终的分类数组。

        【评估标准与匹配逻辑】（非常重要）：
        - 核心判定基于【事件】的宏观语义相似度。
        - ⚠️ 细节宽容原则：只要提取的事件抓住了 GT 的核心骨架（主线一致），即使缺失了原话中的微小细节，也必须算作匹配成功！
        - ⚠️ 互斥绝对原则：一个事件如果已经匹配成功放入 `matched_events`，就【绝对不能】再出现在 `missed_events` 或 `hallucinated_events` 中！这三个集合必须是完全互斥的。

        【Match Quality (匹配质量) 严格分级标准】：
        - "高"：核心事件完全一致，且时间、地点、人物要素基本正确提取。允许丢失无关紧要的细枝末节。
        - "中"：核心事件一致，但在“时间”、“关键人物”或“核心感受”上出现了明显的遗漏或张冠李戴。
        - "低"：核心语义发生偏移，或者把多个无关事件强行缝合，导致事件面目全非。

        必须输出以下严格的 JSON 结构（不要有任何额外说明或Markdown标记）：
        {
            "step_by_step_matching": "请在这里一步步写出你的比对草稿。例如：1. GT事件1与Extracted事件1对应，属于匹配；2. GT事件2没有找到对应，属于遗漏；3. Extracted事件3多余，属于幻觉...",
            "matched_events": [
                {
                    "gt_event_summary": "GT中的核心事件简述", 
                    "extracted_event_summary": "提取出来的对应事件简述", 
                    "match_quality": "高/中/低", 
                    "reason": "匹配原因，请解释为何给出该评级"
                }
            ],
            "missed_events": ["仅列出真正在 matching 过程中没找到对应的 GT 事件简述"],
            "hallucinated_events": ["仅列出真正在 matching 过程中没被用到的 Extracted 事件简述"],
            "metrics": {
                "completeness_score": 0.0, // 必须根据公式精确计算：匹配成功的GT事件数 / GT总事件数
                "accuracy_score": 0.0,    // 必须根据公式精确计算：匹配成功的Extracted事件数 / Extracted总事件数
                "overall_score": 0.0
            },
            "final_evaluation": "不超过50字的总体评价"
        }
        """

        user_prompt = f"""【Ground Truth (标准答案)】:
            {json.dumps(ground_truth_json, ensure_ascii=False, indent=2)}

            【Extracted (实际提取)】:
            {json.dumps(extracted_json, ensure_ascii=False, indent=2)}

            请进行评测并返回JSON格式的报告："""

        try:
            print(f">>> 正在调用 {self.provider} API 进行评测...")
            content = self._call_llm(system_prompt, user_prompt)
            print(f">>> API 返回内容长度: {len(content)} 字符")
            print(f">>> API 返回前 300 字符: {content[:300]}...")

            # 解析结果
            result_json = self._parse_llm_json(content)
            if result_json is None:
                # 返回一个默认的失败报告
                return {
                    "error": "JSON 解析失败",
                    "raw_content": content[:1000],
                    "matched_events": [],
                    "missed_events": [],
                    "hallucinated_events": [],
                    "metrics": {
                        "completeness_score": 0.0,
                        "accuracy_score": 0.0,
                        "overall_score": 0.0
                    },
                    "final_evaluation": "评测失败，无法解析 LLM 返回结果"
                }
            return result_json

        except Exception as e:
            print(f"❌ LLM 调用错误: {e}")
            import traceback
            traceback.print_exc()
            return {
                "error": str(e),
                "matched_events": [],
                "missed_events": [],
                "hallucinated_events": [],
                "metrics": {
                    "completeness_score": 0.0,
                    "accuracy_score": 0.0,
                    "overall_score": 0.0
                },
                "final_evaluation": "评测失败，发生异常"
            }

    def evaluate_files(self, gt_file_path: str, extracted_file_path: str, report_output_path: str) -> dict:
        """
        从文件读取 Ground Truth 和 Extracted 事件，进行评测并输出报告

        参数:
            gt_file_path: Ground Truth JSON 文件路径
            extracted_file_path: Extracted JSON 文件路径
            report_output_path: 评测报告输出文件路径

        返回:
            dict: 评测报告字典
        """
        try:
            # 读取 Ground Truth 文件
            print(f">>> 正在读取 Ground Truth 文件: {gt_file_path}")
            with open(gt_file_path, 'r', encoding='utf-8') as f:
                ground_truth = json.load(f)
            print(f">>> 读取成功，共 {len(ground_truth)} 个 GT 事件")

            # 读取 Extracted 文件
            print(f">>> 正在读取 Extracted 文件: {extracted_file_path}")
            with open(extracted_file_path, 'r', encoding='utf-8') as f:
                extracted = json.load(f)
            print(f">>> 读取成功，共 {len(extracted)} 个提取事件")

            # 执行评测
            print(">>> 开始执行事件提取评测...")
            report = self.evaluate_extraction(ground_truth, extracted)

            # 确保输出目录存在
            output_dir = os.path.dirname(report_output_path)
            if output_dir and not os.path.exists(output_dir):
                os.makedirs(output_dir)
                print(f">>> 创建输出目录: {output_dir}")

            # 写入报告文件
            print(f">>> 正在写入评测报告: {report_output_path}")
            with open(report_output_path, 'w', encoding='utf-8') as f:
                json.dump(report, f, ensure_ascii=False, indent=4)

            # 验证文件是否写入成功
            if os.path.exists(report_output_path):
                file_size = os.path.getsize(report_output_path)
                abs_path = os.path.abspath(report_output_path)
                print(f"✅ 评测报告已保存到: {abs_path} ({file_size} 字节)")
            else:
                print(f"❌ 错误: 文件写入失败，文件不存在: {report_output_path}")

            return report

        except FileNotFoundError as e:
            print(f"❌ 文件未找到错误: {e}")
            raise
        except json.JSONDecodeError as e:
            print(f"❌ JSON 解析错误: {e}")
            raise
        except Exception as e:
            print(f"❌ evaluate_files 发生错误: {e}")
            import traceback
            traceback.print_exc()
            raise


def create_mock_data():
    """
    创建 Mock 测试数据
    GT: 2个标准事件
    Extracted: 3个事件（1个正确匹配，1个幻觉，1个缺少关键人物）
    """
    ground_truth = [
        {
            "日期": "1995年夏天",
            "主题": "大专毕业去深圳",
            "人": "父母",
            "描述": "1995年大专毕业后独自坐火车去深圳打工，父母起初不同意。"
        },
        {
            "日期": "1996年",
            "主题": "第一份工作",
            "人": "部门经理张总、同事小李",
            "描述": "在深圳一家电子厂找到第一份工作，受到部门经理张总和同事小李的帮助。"
        }
    ]

    extracted = [
        {
            "日期": "1995年",
            "主题": "毕业去深圳打工",
            "人": "父母",
            "描述": "大专毕业后去深圳打工，父母一开始不同意。"
        },
        {
            "日期": "1996年初",
            "主题": "找到电子厂工作",
            "人": "张总",
            "描述": "在深圳找到电子厂工作，部门经理张总给予了帮助。"  # 缺少同事小李
        },
        {
            "日期": "1997年",
            "主题": "升职加薪",
            "人": "老板",
            "描述": "因为工作表现优秀，被老板升职加薪。"  # 幻觉事件
        }
    ]

    return ground_truth, extracted


# --- 测试用例 ---
if __name__ == "__main__":
    import sys

    # 检查必要的文件是否存在
    gt_file = "sample_events.json"
    extracted_file = "extracted_events.json"
    report_output = "evaluation_report.json"

    # 如果文件不存在，创建 mock 数据
    if not os.path.exists(gt_file) or not os.path.exists(extracted_file):
        print(">>> 数据文件不存在，正在生成 Mock 测试数据...")
        gt_data, extracted_data = create_mock_data()

        # 写入 Mock 数据
        with open(gt_file, 'w', encoding='utf-8') as f:
            json.dump(gt_data, f, ensure_ascii=False, indent=4)
        print(f"✅ Mock Ground Truth 已写入: {gt_file}")

        with open(extracted_file, 'w', encoding='utf-8') as f:
            json.dump(extracted_data, f, ensure_ascii=False, indent=4)
        print(f"✅ Mock Extracted 已写入: {extracted_file}")

    # 运行时让用户选择模型
    print("\n请选择模型提供商:")
    print("  1. hunyuan (腾讯混元)")
    print("  2. moonshot (月之暗面 Kimi)")

    # 尝试从命令行参数获取选择
    if len(sys.argv) > 1 and sys.argv[1] in ["1", "2"]:
        choice = sys.argv[1]
    else:
        choice = input("请输入选项 (1/2): ").strip()

    if choice == "1":
        provider = "hunyuan"
    elif choice == "2":
        provider = "moonshot"
    else:
        print("无效选择，默认使用 moonshot")
        provider = "moonshot"

    print(f"\n{'='*20} 初始化事件评测裁判 (Provider: {provider}) {'='*20}")

    try:
        # 实例化评测裁判
        judge = EventJudge(provider=provider)

        # 执行文件评测
        print(f"\n{'='*20} 开始事件提取评测 {'='*20}")
        report = judge.evaluate_files(gt_file, extracted_file, report_output)

        # 打印评测摘要
        print(f"\n{'='*20} 评测摘要 {'='*20}")
        metrics = report.get("metrics", {})
        print(f"完整性得分 (Completeness): {metrics.get('completeness_score', 0.0):.2f}")
        print(f"准确性得分 (Accuracy): {metrics.get('accuracy_score', 0.0):.2f}")
        print(f"综合得分 (Overall): {metrics.get('overall_score', 0.0):.2f}")
        print(f"\n总体评价: {report.get('final_evaluation', 'N/A')}")

        matched = report.get("matched_events", [])
        missed = report.get("missed_events", [])
        hallucinated = report.get("hallucinated_events", [])

        print(f"\n匹配事件数: {len(matched)}")
        print(f"遗漏事件数: {len(missed)}")
        print(f"幻觉事件数: {len(hallucinated)}")

        print(f"\n✅ 评测完成，报告已生成: {os.path.abspath(report_output)}")

    except Exception as e:
        print(f"\n❌ 评测失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
