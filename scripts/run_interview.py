#!/usr/bin/env python3
"""
实时用户访谈入口

Usage:
    python scripts/run_interview.py --agent baseline
    python scripts/run_interview.py --agent planner
"""

import sys
import os
import argparse
from datetime import datetime

# 添加项目根目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.agents.baseline_agent import BaselineAgent
# from src.agents.planner_agent import PlannerAgent  # 待实现


def main():
    parser = argparse.ArgumentParser(description="运行访谈系统")
    parser.add_argument(
        "--agent",
        choices=["baseline", "planner"],
        default="baseline",
        help="选择 Agent 类型"
    )
    parser.add_argument(
        "--session-id",
        default=datetime.now().strftime("%Y%m%d_%H%M%S"),
        help="会话 ID（默认为当前时间）"
    )

    args = parser.parse_args()

    print(f"=== 叙事导航者 - 访谈系统 ===")
    print(f"Agent 类型: {args.agent}")
    print(f"会话 ID: {args.session_id}")
    print()

    if args.agent == "baseline":
        agent = BaselineAgent(session_id=args.session_id)
    # else:
    #     agent = PlannerAgent(session_id=args.session_id)

    agent.run_interview()


if __name__ == "__main__":
    main()
