#!/usr/bin/env python3
"""
Baseline Agent 访谈仿真脚本

在此脚本中，BaselineAgent 充当访谈者，IntervieweeAgent 充当被访谈者。
两个 Agent 之间进行多轮对话，最终生成访谈记录。
"""

import os
import sys
import json
import logging
from datetime import datetime

# 添加项目根目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from dotenv import load_dotenv
from src.agents.baseline_agent import BaselineAgent
from src.agents.interviewee_agent import IntervieweeAgent
from src.config import Config

# 加载环境变量
load_dotenv()

# 设置日志
logging.basicConfig(
    level=Config.LOG_LEVEL,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/baseline_simulation.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class InterviewSimulation:
    """访谈仿真：BaselineAgent 与 IntervieweeAgent 的对话"""

    def __init__(self, 
                 interviewee_profile_path: str = "prompts/roles/elder_profile_example.json",
                 max_turns: int = 20,
                 model_type: str = None,
                 model_base_url: str = None,
                 api_key: str = None):
        """
        初始化访谈仿真

        Args:
            interviewee_profile_path: 被访谈者的角色配置文件路径
            max_turns: 最多对话轮数
            model_type: 使用的模型类型
            model_base_url: 模型服务 URL
            api_key: API 密钥
        """
        self.interviewee_profile_path = interviewee_profile_path
        self.max_turns = max_turns
        self.model_type = model_type or os.getenv("MODEL_TYPE")
        self.model_base_url = model_base_url or os.getenv("MODEL_BASE_URL")
        self.api_key = api_key or os.getenv("API_KEY")
        
        self.conversation_log = []
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        logger.info(f"初始化访谈仿真 (Session: {self.session_id})")

    def initialize_agents(self, basic_info: str = ""):
        """初始化访谈者和被访谈者"""
        logger.info("初始化 Baseline Agent（访谈者）...")
        self.interviewer = BaselineAgent(
            session_id=self.session_id,
            model_type=self.model_type,
            model_base_url=self.model_base_url,
            api_key=self.api_key
        )
        
        logger.info("初始化 Interviewee Agent（被访谈者）...")
        self.interviewee = IntervieweeAgent(
            profile_path=self.interviewee_profile_path,
            model_type=self.model_type,
            model_base_url=self.model_base_url,
            api_key=self.api_key,
            save_path=f"data/raw/interviewee_answers_{self.session_id}.txt"
        )
        
        # 使用被访谈者的信息初始化访谈者
        if not basic_info:
            basic_info = self._extract_basic_info_from_profile()
        
        self.interviewer.initialize_conversation(basic_info)
        logger.info(f"两个 Agent 已初始化，基本信息: {basic_info}")

    def _extract_basic_info_from_profile(self) -> str:
        """从被访谈者的配置文件中提取基本信息"""
        try:
            import json
            with open(self.interviewee_profile_path, 'r', encoding='utf-8') as f:
                profile = json.load(f)
            
            # 尝试提取基本信息
            identity = profile.get('identity', {})
            name = identity.get('name', '老年人')
            age = identity.get('age', '未知')
            background = identity.get('background', '')
            
            basic_info = f"姓名: {name}, 年龄: {age}"
            if background:
                basic_info += f", 背景: {background}"
            
            return basic_info
        except Exception as e:
            logger.warning(f"无法从配置文件提取基本信息: {e}")
            return "一位老年人"

    def run_interview(self) -> str:
        """运行访谈对话"""
        print("\n" + "="*60)
        print("【传记访谈仿真 - Baseline Agent vs Interviewee Agent】")
        print("="*60)
        
        conversation = []
        turn_count = 0
        
        try:
            # 第一轮：访谈者获取初始问题
            logger.info("生成初始问题...")
            question = self.interviewer.get_next_question()
            print(f"\n【访谈者】: {question}")
            conversation.append({
                "speaker": "interviewer",
                "content": question,
                "turn": turn_count + 1
            })
            self.conversation_log.append({
                "turn": turn_count + 1,
                "role": "interviewer",
                "content": question
            })
            
            # 对话循环
            while turn_count < self.max_turns:
                turn_count += 1
                
                # 被访谈者回答
                logger.info(f"第 {turn_count} 轮：被访谈者生成回答...")
                try:
                    answer = self.interviewee.respond(question)
                except Exception as e:
                    logger.error(f"被访谈者生成回答失败: {e}")
                    answer = "（抱歉，我没有很好地理解这个问题，可以再问一遍吗？）"
                
                print(f"\n【被访谈者】: {answer}")
                conversation.append({
                    "speaker": "interviewee",
                    "content": answer,
                    "turn": turn_count
                })
                self.conversation_log.append({
                    "turn": turn_count,
                    "role": "interviewee",
                    "content": answer
                })
                self.interviewee.history += f"Q: {question}\nA: {answer}\n"
                
                # 访谈者根据回答生成下一个问题
                logger.info(f"第 {turn_count} 轮：访谈者生成下一个问题...")
                try:
                    next_question = self.interviewer.get_next_question(answer["reply"])
                except Exception as e:
                    logger.error(f"访谈者生成问题失败: {e}")
                    next_question = "感谢您的分享。还有其他您想说的吗？"
                
                print(f"\n【访谈者】: {next_question}")
                conversation.append({
                    "speaker": "interviewer",
                    "content": next_question,
                    "turn": turn_count + 1
                })
                self.conversation_log.append({
                    "turn": turn_count + 1,
                    "role": "interviewer",
                    "content": next_question
                })
                
                question = next_question
            
            logger.info(f"访谈完成，共进行 {turn_count} 轮对话")
            print(f"\n【信息】访谈已完成，共进行 {turn_count} 轮对话")
            
        except KeyboardInterrupt:
            print("\n\n【信息】访谈已被中断")
            logger.warning("访谈被用户中断")
        except Exception as e:
            logger.error(f"访谈过程中发生错误: {e}", exc_info=True)
            print(f"\n【错误】访谈过程中发生错误: {e}")
        
        return self.save_conversation(conversation)  

    def save_conversation(self, conversation: list) -> str:
        """保存对话记录"""
        # 创建输出目录
        results_dir = "results/interviews"
        os.makedirs(results_dir, exist_ok=True)
        
        # 保存为文本格式
        txt_output = os.path.join(results_dir, f"baseline_interview_{self.session_id}.txt")
        with open(txt_output, 'w', encoding='utf-8') as f:
            f.write("="*80 + "\n")
            f.write("【传记访谈记录】\n")
            f.write(f"会话ID: {self.session_id}\n")
            f.write(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("="*80 + "\n\n")
            
            for turn_log in self.conversation_log:
                turn = turn_log.get('turn', 0)
                role = turn_log.get('role', '')
                content = turn_log.get('content', '')
                
                role_name = "【访谈者】" if role == "interviewer" else "【被访谈者】"
                f.write(f"第 {turn} 轮 {role_name}\n")
                f.write(f"{content}\n")
                f.write("-" * 80 + "\n")
        
        logger.info(f"对话记录已保存到: {txt_output}")
        
        # 保存为 JSON 格式
        json_output = os.path.join(results_dir, f"baseline_interview_{self.session_id}.json")
        with open(json_output, 'w', encoding='utf-8') as f:
            json.dump({
                "session_id": self.session_id,
                "timestamp": datetime.now().isoformat(),
                "conversation": self.conversation_log
            }, f, ensure_ascii=False, indent=2)
        
        logger.info(f"JSON 格式的对话记录已保存到: {json_output}")
        
        return txt_output

    def get_summary(self) -> dict:
        """获取访谈摘要"""
        return {
            "session_id": self.session_id,
            "total_turns": len([log for log in self.conversation_log if log['role'] == 'interviewer']),
            "conversation_log": self.conversation_log,
            "timestamp": datetime.now().isoformat()
        }


def main():
    """主函数：运行访谈仿真"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Baseline Agent 访谈仿真")
    parser.add_argument(
        "--profile",
        default="prompts/roles/elder_profile_example.json",
        help="被访谈者的角色配置文件路径"
    )
    parser.add_argument(
        "--turns",
        type=int,
        default=2,
        help="最多对话轮数"
    )
    parser.add_argument(
        "--model",
        help="使用的模型类型（如：deepseek-chat）"
    )
    parser.add_argument(
        "--url",
        help="模型服务 URL"
    )
    parser.add_argument(
        "--api-key",
        help="API 密钥"
    )
    
    args = parser.parse_args()
    
    # 检查必要的配置
    if not os.getenv("API_KEY") and not args.api_key:
        print("错误: 请在环境变量或命令行参数中设置 API_KEY")
        sys.exit(1)
    
    if not os.path.exists(args.profile):
        print(f"错误: 找不到配置文件 {args.profile}")
        sys.exit(1)
    
    # 运行仿真
    simulation = InterviewSimulation(
        interviewee_profile_path=args.profile,
        max_turns=args.turns,
        model_type=args.model,
        model_base_url=args.url,
        api_key=args.api_key
    )
    
    simulation.initialize_agents()
    output_file = simulation.run_interview()
    
    # 打印摘要
    summary = simulation.get_summary()
    print("\n" + "="*60)
    print("【访谈摘要】")
    print(f"会话ID: {summary['session_id']}")
    print(f"总问题数: {summary['total_turns']}")
    print(f"结果文件: {output_file}")
    print("="*60)


if __name__ == "__main__":
    main()
