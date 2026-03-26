#!/usr/bin/env python3
"""
Planner Agent 访谈仿真脚本

在此脚本中：
- BaselineAgent（启用 planner 模式）充当访谈者
- PlannerAgent 充当规划器，基于对话内容提供访谈策略和建议
- IntervieweeAgent 充当被访谈者
三个 Agent 协作进行多轮对话，最终生成访谈记录。

访谈流程：
1. 被访谈者回答上一个问题
2. Planner Agent 分析回答并生成下一步行动指令
3. Baseline Agent 根据 Planner 指令调整提问策略
4. Baseline Agent 生成下一个问题
5. 循环...
"""

import os
import sys
import json
import logging
from datetime import datetime
from typing import Optional, Dict, Any

# 添加项目根目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from dotenv import load_dotenv
from src.agents.baseline_agent import BaselineAgent
from src.agents.interviewee_agent import IntervieweeAgent
from src.agents.planner_agents import PlannerAgent
from src.config import Config

# 加载环境变量
load_dotenv()

# 设置日志
logging.basicConfig(
    level=Config.LOG_LEVEL,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/planner_simulation.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class PlannerInterviewSimulation:
    """访谈仿真：BaselineAgent + PlannerAgent + IntervieweeAgent 的协同对话"""

    def __init__(self,
                 interviewee_profile_path: str = "prompts/roles/elder_profile_example.json",
                 max_turns: int = 20,
                 planner_instruction_path: Optional[str] = None,
                 model_type: str = None,
                 model_base_url: str = None,
                 api_key: str = None):
        """
        初始化 Planner 模式的访谈仿真

        Args:
            interviewee_profile_path: 被访谈者的角色配置文件路径
            max_turns: 最多对话轮数
            planner_instruction_path: Planner 的指令文件路径
            model_type: 使用的模型类型
            model_base_url: 模型服务 URL
            api_key: API 密钥
        """
        self.interviewee_profile_path = interviewee_profile_path
        self.max_turns = max_turns
        self.planner_instruction_path = planner_instruction_path
        self.model_type = model_type or os.getenv("MODEL_TYPE")
        self.model_base_url = model_base_url or os.getenv("MODEL_BASE_URL")
        self.api_key = api_key or os.getenv("API_KEY")
        
        self.conversation_log = []
        self.planner_decisions = []  # 记录 Planner 的每次决策
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        logger.info(f"初始化 Planner 模式访谈仿真 (Session: {self.session_id})")

    def initialize_agents(self, basic_info: str = ""):
        """初始化三个 Agent"""
        logger.info("初始化 Baseline Agent（启用 Planner 模式）...")
        self.interviewer = BaselineAgent(
            session_id=self.session_id,
            model_type=self.model_type,
            model_base_url=self.model_base_url,
            api_key=self.api_key,
            planner=True  # 启用 Planner 模式
        )
        
        logger.info("初始化 Planner Agent（规划器）...")
        self.planner = PlannerAgent(
            instruction_path=self.planner_instruction_path,
            test=False
        )
        
        logger.info("初始化 Interviewee Agent（被访谈者）...")
        self.interviewee = IntervieweeAgent(
            profile_path=self.interviewee_profile_path,
            model_type=self.model_type,
            model_base_url=self.model_base_url,
            api_key=self.api_key,
            save_path=f"data/raw/interviewee_answers_planner_{self.session_id}.txt"
        )
        
        # 使用被访谈者的信息初始化访谈者
        if not basic_info:
            basic_info = self._extract_basic_info_from_profile()
        
        self.interviewer.initialize_conversation(basic_info)
        logger.info(f"三个 Agent 已初始化，基本信息: {basic_info}")

    def _extract_basic_info_from_profile(self) -> str:
        """从被访谈者的配置文件中提取基本信息"""
        try:
            with open(self.interviewee_profile_path, 'r', encoding='utf-8') as f:
                profile = json.load(f)
            
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

    def parse_interviewee_response(self, response: str) -> tuple[str, Dict[str, Any]]:
        """
        解析被访谈者的响应（JSON 格式，来自 elderly_agent）
        
        Returns:
            (reply_text, thoughts_dict) - 实际回答文本和完整的 thoughts 对象
        """
        try:
            parsed = self.interviewee.parse_json_response(response)
            reply = parsed.get("reply", response)
            thoughts = parsed.get("thoughts", {})
            return reply, thoughts
        except Exception as e:
            logger.error(f"解析被访谈者响应失败: {e}")
            return response, {}

    def parse_planner_response(self, response: str) -> Dict[str, Any]:
        """
        解析 Planner Agent 的响应（JSON 格式）
        
        Returns:
            包含 action、meta 等信息的字典
        """
        try:
            parsed = self.planner.parse_json_response(response)
            return parsed
        except Exception as e:
            logger.error(f"解析 Planner 响应失败: {e}")
            return {}

    def extract_action_from_planner(self, planner_decision: Dict[str, Any]) -> Dict[str, Any]:
        """
        从 Planner 的决策中提取 action 信息
        
        Args:
            planner_decision: Planner 返回的 JSON 决策对象
            
        Returns:
            包含 primary_action, tactical_goal, strategy 等的字典
        """
        try:
            action = planner_decision.get('action', {})
            if action:
                return {
                    "primary_action": action.get('primary_action', ''),
                    "tactical_goal": action.get('tactical_goal', {}),
                    "tone_constraint": action.get('tone_constraint', {}),
                    "strategy": action.get('strategy', '')
                }
            return {}
        except Exception as e:
            logger.error(f"提取 Planner action 时出错: {e}")
            return {}

    def extract_recommended_questions(self, planner_decision: Dict[str, Any]) -> list:
        """
        从 Planner 的决策中提取推荐的问题
        
        Args:
            planner_decision: Planner 返回的 JSON 决策对象
            
        Returns:
            推荐问题列表
        """
        try:
            questions = planner_decision.get('recommended_questions', [])
            if isinstance(questions, list) and len(questions) > 0:
                return questions
            return []
        except Exception as e:
            logger.error(f"提取推荐问题时出错: {e}")
            return []

    def format_interviewee_response_for_planner(self, answer: str) -> str:
        """
        格式化被访谈者的响应供 Planner 处理
        
        Planner.respond 期望接收被访谈者的基本响应文本
        """
        return answer

    def run_interview(self) -> str:
        """运行访谈对话"""
        print("\n" + "="*70)
        print("【传记访谈仿真 - Planner 模式】")
        print("（BaselineAgent + PlannerAgent + IntervieweeAgent）")
        print("="*70)
        
        conversation = []
        turn_count = 0
        current_question = None
        
        try:
            # 第一轮：位访谈者生成初始问题
            logger.info("生成初始问题...")
            current_question = self.interviewer.get_next_question()
            print(f"\n【访谈者】: {current_question}")
            conversation.append({
                "speaker": "interviewer",
                "content": current_question,
                "turn": turn_count + 1
            })
            self.conversation_log.append({
                "turn": turn_count + 1,
                "role": "interviewer",
                "content": current_question,
                "source": "baseline_direct"
            })
            
            # 对话循环
            while turn_count < self.max_turns:
                turn_count += 1
                
                # 被访谈者回答
                logger.info(f"第 {turn_count} 轮：被访谈者生成回答...")
                try:
                    answer = self.interviewee.agent.step(current_question)
                    raw_answer = answer.msg.content
                    # 解析被访谈者的 JSON 响应，提取 reply 字段
                    answer_text, thoughts = self.parse_interviewee_response(raw_answer)
                except Exception as e:
                    logger.error(f"被访谈者生成回答失败: {e}")
                    answer_text = "（抱歉，我没有很好地理解这个问题，可以再问一遍吗？）"
                    thoughts = {}
                
                print(f"\n【被访谈者】: {answer_text}")
                if thoughts:
                    accept_value = thoughts.get('accept_value', 20)
                    current_emotion = thoughts.get('current_emotion', '平静')
                    print(f"  [情绪: {current_emotion}, 接受度: {accept_value}]")
                
                conversation.append({
                    "speaker": "interviewee",
                    "content": answer_text,
                    "turn": turn_count,
                    "thoughts": thoughts
                })
                self.conversation_log.append({
                    "turn": turn_count,
                    "role": "interviewee",
                    "content": answer_text,
                    "thoughts": thoughts
                })
                self.interviewee.history += f"Q: {current_question}\nA: {answer_text}\n"
                
                # Planner 分析并生成指令
                logger.info(f"第 {turn_count} 轮：Planner 分析并生成指令...")
                try:
                    # 调用 Planner，传入被访谈者的回答和当前的问题
                    planner_response = self.planner.respond(answer_text, current_question)
                    planner_decision = self.parse_planner_response(planner_response)
                    
                    # 记录 Planner 的决策
                    self.planner_decisions.append({
                        "turn": turn_count,
                        "decision": planner_decision,
                        "raw_response": planner_response
                    })
                    
                    # 打印 Planner 的决策摘要
                    if planner_decision:
                        action_info = self.extract_action_from_planner(planner_decision)
                        primary_action = action_info.get('primary_action', 'UNKNOWN')
                        print(f"\n【Planner 指令】: {primary_action}")
                        
                        # 打印推荐问题
                        recommended_qs = self.extract_recommended_questions(planner_decision)
                        if recommended_qs:
                            print(f"  推荐问题数: {len(recommended_qs)}")
                            if len(recommended_qs) > 0:
                                first_q = recommended_qs[0]
                                if isinstance(first_q, dict):
                                    print(f"    - {first_q.get('question', first_q)}")
                                else:
                                    print(f"    - {first_q}")
                    
                except Exception as e:
                    logger.error(f"Planner 处理失败: {e}", exc_info=True)
                    planner_decision = {}  # 降级处理
                
                # 访谈者根据 Planner 指令和回答生成下一个问题
                logger.info(f"第 {turn_count} 轮：访谈者生成下一个问题...")
                try:
                    # 构建更丰富的上下文（包含 Planner 决策）
                    context_for_interviewer = answer_text
                    if planner_decision:
                        action_info = self.extract_action_from_planner(planner_decision)
                        if action_info:
                            primary_action = action_info.get('primary_action', '')
                            tactical_goal = action_info.get('tactical_goal', {})
                            if isinstance(tactical_goal, dict):
                                goal_desc = tactical_goal.get('name', '') or tactical_goal.get('description', '')
                            else:
                                goal_desc = str(tactical_goal)
                            
                            action_desc = f"Planner 指令: {primary_action}"
                            if goal_desc:
                                action_desc += f" ({goal_desc})"
                            context_for_interviewer = f"{action_desc}\n\n被访谈者回答：{answer_text}"
                    
                    next_question = self.interviewer.get_next_question(context_for_interviewer)
                except Exception as e:
                    logger.error(f"访谈者生成问题失败: {e}", exc_info=True)
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
                    "content": next_question,
                    "source": "baseline_planner_guided"
                })
                
                current_question = next_question
                
                # 检查是否应该继续（基于 Planner 指令或被访谈者状态）
                if planner_decision:
                    primary_action = planner_decision.get('action', {}).get('primary_action', '')
                    if primary_action in ['PAUSE_SESSION', 'CLOSE_INTERVIEW']:
                        logger.info(f"Planner 建议结束访谈: {primary_action}")
                        break
            
            logger.info(f"访谈完成，共进行 {turn_count} 轮对话")
            print(f"\n【信息】访谈已完成，共进行 {turn_count} 轮对话")
            
        except KeyboardInterrupt:
            print("\n\n【信息】访谈已被用户中断")
            logger.warning("访谈被用户中断")
        except Exception as e:
            logger.error(f"访谈过程中发生错误: {e}", exc_info=True)
            print(f"\n【错误】访谈过程中发生错误: {e}")
        
        return self.save_conversation(conversation)

    def save_conversation(self, conversation: list) -> str:
        """保存对话记录和 Planner 决策"""
        results_dir = "results/interviews"
        os.makedirs(results_dir, exist_ok=True)
        
        # 保存为文本格式
        txt_output = os.path.join(results_dir, f"planner_interview_{self.session_id}.txt")
        with open(txt_output, 'w', encoding='utf-8') as f:
            f.write("="*80 + "\n")
            f.write("【传记访谈记录 - Planner 模式】\n")
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
        
        # 保存为 JSON 格式（包含 Planner 决策）
        json_output = os.path.join(results_dir, f"planner_interview_{self.session_id}.json")
        with open(json_output, 'w', encoding='utf-8') as f:
            json.dump({
                "session_id": self.session_id,
                "timestamp": datetime.now().isoformat(),
                "mode": "planner",
                "conversation": self.conversation_log,
                "planner_decisions": self.planner_decisions
            }, f, ensure_ascii=False, indent=2)
        
        logger.info(f"JSON 格式的对话记录已保存到: {json_output}")
        
        # 保存 Planner 决策分析
        planner_output = os.path.join(results_dir, f"planner_decisions_{self.session_id}.json")
        with open(planner_output, 'w', encoding='utf-8') as f:
            json.dump({
                "session_id": self.session_id,
                "timestamp": datetime.now().isoformat(),
                "total_turns": len([d for d in self.planner_decisions]),
                "decisions": self.planner_decisions
            }, f, ensure_ascii=False, indent=2)
        
        logger.info(f"Planner 决策记录已保存到: {planner_output}")
        
        return txt_output

    def get_summary(self) -> dict:
        """获取访谈摘要"""
        return {
            "session_id": self.session_id,
            "mode": "planner",
            "total_turns": len([log for log in self.conversation_log if log['role'] == 'interviewer']),
            "planner_decisions_count": len(self.planner_decisions),
            "conversation_log": self.conversation_log,
            "planner_decisions": self.planner_decisions,
            "timestamp": datetime.now().isoformat()
        }


def main():
    """主函数：运行 Planner 模式的访谈仿真"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Planner Agent 访谈仿真")
    parser.add_argument(
        "--profile",
        default="prompts/roles/elder_profile_example.json",
        help="被访谈者的角色配置文件路径"
    )
    parser.add_argument(
        "--turns",
        type=int,
        default=1,  ### 测试2轮
        help="最多对话轮数"
    )
    parser.add_argument(
        "--planner-instruction",
        help="Planner 的指令文件路径（YAML 格式）"
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
    simulation = PlannerInterviewSimulation(
        interviewee_profile_path=args.profile,
        max_turns=args.turns,
        planner_instruction_path=args.planner_instruction,
        model_type=args.model,
        model_base_url=args.url,
        api_key=args.api_key
    )
    
    simulation.initialize_agents()
    output_file = simulation.run_interview()
    
    # 打印摘要
    summary = simulation.get_summary()
    print("\n" + "="*70)
    print("【访谈摘要】")
    print(f"会话ID: {summary['session_id']}")
    print(f"模式: {summary['mode'].upper()}")
    print(f"总问题数: {summary['total_turns']}")
    print(f"Planner 决策数: {summary['planner_decisions_count']}")
    print(f"结果文件: {output_file}")
    print("="*70)


if __name__ == "__main__":
    main()
