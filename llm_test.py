import os
import json
from dotenv import load_dotenv

# 腾讯云 SDK
from tencentcloud.common import credential
from tencentcloud.common.profile.client_profile import ClientProfile
from tencentcloud.common.profile.http_profile import HttpProfile
from tencentcloud.common.exception.tencent_cloud_sdk_exception import TencentCloudSDKException
from tencentcloud.hunyuan.v20230901 import hunyuan_client, models

# 加载密钥
load_dotenv()

class LLMJudgeEvaluator:
    def __init__(self):
        self.secret_id = os.getenv("TENCENT_SECRET_ID")
        self.secret_key = os.getenv("TENCENT_SECRET_KEY")
        
        cred = credential.Credential(self.secret_id, self.secret_key)
        httpProfile = HttpProfile()
        httpProfile.endpoint = "hunyuan.tencentcloudapi.com"
        clientProfile = ClientProfile()
        clientProfile.httpProfile = httpProfile
        
        # 实例化客户端
        self.client = hunyuan_client.HunyuanClient(cred, "ap-guangzhou", clientProfile)
        print(">>> 混元 LLM Judge 客户端已就绪")

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
        system_prompt = """你是一个严苛的“回忆录访谈语义审计员”。你的任务是判断【用户的回答】在语义上和【Planner的目标】是否匹配。

        判定规则：
        1. 【核心事件一致性】：必须描述同一个核心事件。用户是否有提到Planner所预期的核心事件？
        2. 【忽略噪音】：若回答包含大量废话（如具体的年份、吐槽），但核心情节符合，判定为 TRUE。
        3. 【忽略乱序】：叙述顺序不同不影响判定。
        4. 【情感/意图】：若目标是询问情感，回答必须包含相关情感描述。
        5. 【忽略语言细节】：语言的正式与否和用语习惯不影响判定，仅判断两个文段意思是否相同。

        请输出严格的 JSON 格式：
        {
            "reason": "简短的判定理由",
            "is_pass": true 或 false
        }
        """

        user_prompt = f"""
        【Planner的目标】: {goal}
        【用户的回答】: {response}
        
        请根据上述规则进行 JSON 判定：
        """

        try:
            # --- 2. 构造请求参数 ---
            req = models.ChatCompletionsRequest()
            
            # 使用官方推荐的 json dumps 方式传参
            params = {
                "Model": "hunyuan-lite",  # 或 "hunyuan-pro", standard 够用且便宜
                "Messages": [
                    {"Role": "system", "Content": system_prompt},
                    {"Role": "user", "Content": user_prompt}
                ],
                "Temperature": 0.0  # 设置为 0 确保评判标准稳定
            }
            req.from_json_string(json.dumps(params))

            # --- 3. 发送请求 ---
            resp = self.client.ChatCompletions(req)
            
            # --- 4. 解析结果 ---
            # 混元 Chat 接口返回的内容在 resp.Choices[0].Message.Content
            if hasattr(resp, "Choices") and len(resp.Choices) > 0:
                content = resp.Choices[0].Message.Content
                result_json = self._parse_llm_json(content)
                return result_json.get("is_pass", False), result_json.get("reason", "无理由")
            
            return False, "API 返回结构异常"

        except TencentCloudSDKException as err:
            print(f"腾讯云 API 报错: {err}")
            return False, str(err)
        except Exception as e:
            print(f"未知错误: {e}")
            return False, str(e)

# --- 复用之前的测试用例 ---
if __name__ == "__main__":
    judge = LLMJudgeEvaluator()
    
    # 同样的测试集
    test_cases = [
        # Case 1: 完美等价
        ("我记得那是一个夏天的傍晚，爸爸在公园教我骑自行车。刚开始我总是摔倒，膝盖都磕破了，想放弃。但在爸爸的鼓励下，我最终掌握了平衡，那种风吹过脸庞的感觉让我至今难忘。", 
         "那时候是夏天，天快黑了。我和我爸在楼下的公园里练车。前面几次我根本骑不稳，摔了好几个狗吃屎，腿疼死了，我当时气得把车都扔了。后来我爸一直劝我再试一次，结果我真的学会了！骑起来的时候感觉风呼呼地吹，太爽了，这事我记一辈子。", 
         "✅ 预期: TRUE"),
        
        # Case 2: Noisy (噪音干扰)
       ("大学毕业那年，我决定去北京闯荡。找工作非常不顺利，住地下室，吃了两个月泡面。最后终于在一家互联网公司拿到offer，虽然工资不高，但那是梦想开始的地方。", 
         "那是2015年吧，具体的日子我忘了。当时其实我妈想让我回老家考公务员，但我不想过一眼望到头的日子，就买了张票去了北京。刚去的时候住的那个地下室，哎哟全是霉味，隔壁还住着一对吵架的情侣。我那两个月天天吃红烧牛肉面，现在闻到那个味都想吐。不过好在最后运气不错，有个互联网小公司录用我了。虽然钱少，好像才给四千块吧，但毕竟能留下来了。", 
         "✅ 预期: TRUE（虽然有废话）"),
        
        # Case 3: 核心冲突 (这是 LLM Judge 最该发挥作用的地方！)
        ("高中最遗憾的事情是没有坚持练钢琴。当时为了高考，把学了六年的钢琴停掉了。现在听到别人弹琴，心里总是空落落的。", 
         "高中最遗憾的是没有向那个女生表白。当时为了高考，家里管得严，我把这份喜欢藏在心里。现在看到她结婚的朋友圈，心里总是空落落的。", 
         "❌ 预期: FALSE (Embedding 可能会判高分，但 LLM 必须判 False)"),
        
        # Case 4: 乱序
        ("过年的时候，全家人围在一起包饺子。奶奶负责擀皮，妈妈负责调馅，我们几个小孩负责捣乱。等到热腾腾的饺子出锅，窗外正好响起了鞭炮声。", 
         "窗外放鞭炮的时候，饺子刚好出锅了，特别香。记得那时候主要是奶奶擀皮，妈妈弄馅儿。我们小孩子啥也不会，就在那瞎玩。反正每年过年全家都会这样围在一起，特别温馨。", 
         "✅ 预期: TRUE"),
        
        # Case 5: 无关答案
        ("我最喜欢的旅行是去云南大理。那里的苍山洱海非常美，生活节奏很慢，让我彻底放松了身心。", 
         "我觉得现在的手机游戏太氪金了。特别是那个新出的皮肤，死贵死贵的，完全是在割韭菜。以后我再也不充钱了，没意思。", 
         "❌ 预期: FALSE")
    ]

    print(f"\n{'='*20} 开始 LLM Judge 测试 {'='*20}")
    for i, (goal, resp, expected) in enumerate(test_cases):
        print(f"\nCase {i+1} Testing...")
        
        # 截断一下显示，不然太长
        print(f"  [目标] {goal[:20]}...")
        print(f"  [回答] {resp[:20]}...")
        
        is_pass, reason = judge.check_semantic_equivalence(goal, resp)
        
        # 结果展示
        icon = "✅ PASS" if is_pass else "❌ REJECT"
        print(f"  [AI 判决] {icon}")
        print(f"  [AI 理由] {reason}")
        print(f"  [预期结果] {expected}") 