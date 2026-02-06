import os
import numpy as np
from dotenv import load_dotenv
from sklearn.metrics.pairwise import cosine_similarity

# 腾讯云 SDK
from tencentcloud.common import credential
from tencentcloud.common.profile.client_profile import ClientProfile
from tencentcloud.common.profile.http_profile import HttpProfile
from tencentcloud.hunyuan.v20230901 import hunyuan_client, models

# 加载密钥
load_dotenv()

class SimpleEvaluator:
    def __init__(self):
        # 1. 简化的初始化，只连腾讯混元
        self.secret_id = os.getenv("TENCENT_SECRET_ID")
        self.secret_key = os.getenv("TENCENT_SECRET_KEY")
        
        # 鉴权
        cred = credential.Credential(self.secret_id, self.secret_key)
        httpProfile = HttpProfile()
        httpProfile.endpoint = "hunyuan.tencentcloudapi.com"
        clientProfile = ClientProfile()
        clientProfile.httpProfile = httpProfile
        
        # 实例化客户端
        self.client = hunyuan_client.HunyuanClient(cred, "ap-guangzhou", clientProfile)
        print(">>> 混元 Embedding 客户端已就绪")

    def _get_embedding(self, text):
        """调用腾讯 API 获取向量 (修正版)"""
        try:
            req = models.GetEmbeddingRequest()
            
            req.Input = text 
            
            resp = self.client.GetEmbedding(req)
            
            if hasattr(resp, "Data") and len(resp.Data) > 0:
                return resp.Data[0].Embedding
            
            print("API 返回了空的 Data 列表")
            return [0.0] * 1024
            
        except Exception as e:
            print(f"API 调用失败: {e}")
            # 打印详细结构方便调试（如果再报错的话）
            # try:
            #     print("Debug Resp:", resp.to_json_string())
            # except:
            #     pass
            return [0.0] * 1024

    def check_semantic_equivalence(self, goal, response, threshold):
        """
        核心函数：判断是否等价
        """
        # 1. 取向量
        v_goal = self._get_embedding(goal)
        v_resp = self._get_embedding(response)
        
        # 2. 算余弦相似度
        sim_score = cosine_similarity([v_goal], [v_resp])[0][0]

        # 3. 计算长度比率 (Length Ratio)判断完整程度
        # 这代表“量”的匹配。如果标准答案 100 字，用户只回 20 字，比率就是 0.2
        # 我们设置一个上限 1.0，防止用户废话太多导致分数爆表
        len_ratio = min(len(goal) / len(response), 1.0)

        sim_score = sim_score * (len_ratio ** 0.9)
        
        # 3. 判分 (0 或 1)
        result = 1 if sim_score >= threshold else 0
        
        return result, sim_score

# --- 5 对测试样例 ---
if __name__ == "__main__":
    evaluator = SimpleEvaluator()
    
    # 定义测试集：(Planner目标, Agent实际回答, 预期结果)
    test_cases = [
        # Case 1: 完美等价（用词不同，意思一样）
        ("我记得那是一个夏天的傍晚，爸爸在公园教我骑自行车。刚开始我总是摔倒，膝盖都磕破了，想放弃。但在爸爸的鼓励下，我最终掌握了平衡，那种风吹过脸庞的感觉让我至今难忘。", 
         "那时候是夏天，天快黑了。我和我爸在楼下的公园里练车。前面几次我根本骑不稳，摔了好几个狗吃屎，腿疼死了，我当时气得把车都扔了。后来我爸一直劝我再试一次，结果我真的学会了！骑起来的时候感觉风呼呼地吹，太爽了，这事我记一辈子。", 
         "高匹配"),
        
        # Case 2: noisy
        ("大学毕业那年，我决定去北京闯荡。找工作非常不顺利，住地下室，吃了两个月泡面。最后终于在一家互联网公司拿到offer，虽然工资不高，但那是梦想开始的地方。", 
         "那是2015年吧，具体的日子我忘了。当时其实我妈想让我回老家考公务员，但我不想过一眼望到头的日子，就买了张票去了北京。刚去的时候住的那个地下室，哎哟全是霉味，隔壁还住着一对吵架的情侣。我那两个月天天吃红烧牛肉面，现在闻到那个味都想吐。不过好在最后运气不错，有个互联网小公司录用我了。虽然钱少，好像才给四千块吧，但毕竟能留下来了。", 
         "noisy test"),
        
        # Case 3: 偏题
        ("高中最遗憾的事情是没有坚持练钢琴。当时为了高考，把学了六年的钢琴停掉了。现在听到别人弹琴，心里总是空落落的。", 
         "高中最遗憾的是没有向那个女生表白。当时为了高考，家里管得严，我把这份喜欢藏在心里。现在看到她结婚的朋友圈，心里总是空落落的。", 
         "结构&情感区别"),
        
        # Case 4: 乱序
        ("过年的时候，全家人围在一起包饺子。奶奶负责擀皮，妈妈负责调馅，我们几个小孩负责捣乱。等到热腾腾的饺子出锅，窗外正好响起了鞭炮声。", 
         "窗外放鞭炮的时候，饺子刚好出锅了，特别香。记得那时候主要是奶奶擀皮，妈妈弄馅儿。我们小孩子啥也不会，就在那瞎玩。反正每年过年全家都会这样围在一起，特别温馨。", 
         "乱序判定"),
        
        # Case 5: 无关答案
        ("我最喜欢的旅行是去云南大理。那里的苍山洱海非常美，生活节奏很慢，让我彻底放松了身心。", 
         "我觉得现在的手机游戏太氪金了。特别是那个新出的皮肤，死贵死贵的，完全是在割韭菜。以后我再也不充钱了，没意思。", 
         "完全无关")
    ]

    print(f"\n{'='*20} 开始测试 {'='*20}")
    for i, (goal, resp, expected) in enumerate(test_cases):
        threshold = 0.70
        is_pass, score = evaluator.check_semantic_equivalence(goal, resp, threshold)
        
        # 打印结果
        status = "✅ PASS" if is_pass == 1 else "❌ FAIL"
        print(f"\nCase {i+1}:")
        print(f"  [目标] {goal}")
        print(f"  [回答] {resp}")
        print(f"  [得分] {score:.4f}  ->  {status} (测试样例: {expected})")
        print(f"  [阈值] {threshold}")