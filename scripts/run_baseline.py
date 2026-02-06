#!/usr/bin/env python3
"""
Baseline Agent 测试入口

用于评估对比，不带 Planner 的纯对话 Agent。
"""

import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.agents.baseline_agent import BaselineAgent


def main():
    print("=== 叙事导航者 - Baseline Agent ===")
    print("这是不带 Planner 的纯对话 Agent，用于评估对比。")
    print()

    agent = BaselineAgent()
    agent.run_interview()


if __name__ == "__main__":
    main()
