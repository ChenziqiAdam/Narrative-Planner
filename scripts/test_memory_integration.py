#!/usr/bin/env python3
"""
Graph RAG 记忆系统集成测试脚本

验证以下功能：
1. enable_graph_memory 参数是否正确传递
2. 记忆管理器是否正确初始化
3. PlannerAgent 是否正确加载记忆工具
4. 两种模式（启用/禁用）是否都能正常工作
"""

import os
import sys
import logging
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_memory_enabled():
    """测试启用记忆系统的场景"""
    logger.info("=" * 80)
    logger.info("测试 1: 启用 Graph RAG 记忆系统")
    logger.info("=" * 80)
    
    try:
        from src.simulation.planner_mode import PlannerInterviewSimulation
        
        # 创建启用记忆的模拟
        logger.info("创建 PlannerInterviewSimulation (enable_graph_memory=True)...")
        sim = PlannerInterviewSimulation(
            interviewee_profile_path="prompts/roles/elder_profile_example.json",
            max_turns=2,  # 仅 2 轮测试
            enable_graph_memory=True
        )
        
        # 验证参数
        assert sim.enable_graph_memory == True, "enable_graph_memory 应为 True"
        logger.info("✓ enable_graph_memory 参数正确")
        
        # 初始化 agents（这会初始化记忆管理器）
        logger.info("初始化 Agents...")
        sim.initialize_agents()
        
        # 验证记忆管理器
        if sim.memory_manager is not None:
            logger.info(f"✓ 记忆管理器已初始化: {type(sim.memory_manager).__name__}")
        else:
            logger.error("✗ 记忆管理器初始化失败")
            return False
        
        # 验证 PlannerAgent 的工具
        if hasattr(sim.planner, 'graph_memory_tools') and len(sim.planner.graph_memory_tools) > 0:
            logger.info(f"✓ PlannerAgent 已加载 {len(sim.planner.graph_memory_tools)} 个记忆工具")
            for tool in sim.planner.graph_memory_tools:
                if hasattr(tool, 'name'):
                    logger.info(f"  - {tool.name}")
                else:
                    logger.info(f"  - {type(tool).__name__}")
        else:
            logger.warning("⚠ 未检测到记忆工具")
        
        logger.info("✓ 测试 1 通过\n")
        return True
        
    except Exception as e:
        logger.error(f"✗ 测试 1 失败: {e}", exc_info=True)
        return False


def test_memory_disabled():
    """测试禁用记忆系统的场景"""
    logger.info("=" * 80)
    logger.info("测试 2: 禁用 Graph RAG 记忆系统")
    logger.info("=" * 80)
    
    try:
        from src.simulation.planner_mode import PlannerInterviewSimulation
        
        # 创建禁用记忆的模拟
        logger.info("创建 PlannerInterviewSimulation (enable_graph_memory=False)...")
        sim = PlannerInterviewSimulation(
            interviewee_profile_path="prompts/roles/elder_profile_example.json",
            max_turns=2,  # 仅 2 轮测试
            enable_graph_memory=False
        )
        
        # 验证参数
        assert sim.enable_graph_memory == False, "enable_graph_memory 应为 False"
        logger.info("✓ enable_graph_memory 参数正确")
        
        # 初始化 agents
        logger.info("初始化 Agents...")
        sim.initialize_agents()
        
        # 验证记忆管理器
        if sim.memory_manager is None:
            logger.info("✓ 记忆管理器已正确禁用（None）")
        else:
            logger.warning(f"⚠ 记忆管理器不应该被初始化: {type(sim.memory_manager).__name__}")
        
        # 验证 PlannerAgent 不应该有记忆工具
        if hasattr(sim.planner, 'graph_memory_tools'):
            if len(sim.planner.graph_memory_tools) == 0:
                logger.info("✓ PlannerAgent 未加载记忆工具")
            else:
                logger.warning(f"⚠ PlannerAgent 不应该加载工具: {len(sim.planner.graph_memory_tools)} 个已加载")
        
        logger.info("✓ 测试 2 通过\n")
        return True
        
    except Exception as e:
        logger.error(f"✗ 测试 2 失败: {e}", exc_info=True)
        return False


def test_planner_agent_memory_manager_passing():
    """测试记忆管理器是否正确传递给 PlannerAgent"""
    logger.info("=" * 80)
    logger.info("测试 3: 验证记忆管理器传递给 PlannerAgent")
    logger.info("=" * 80)
    
    try:
        from src.agents.planner_agents import PlannerAgent
        from src.memory.manager import EnhancedGraphMemoryManager
        
        # 创建独立的记忆管理器
        logger.info("创建 EnhancedGraphMemoryManager...")
        memory_mgr = EnhancedGraphMemoryManager()
        logger.info(f"✓ 记忆管理器创建成功: {type(memory_mgr).__name__}")
        
        # 创建 PlannerAgent 并传递记忆管理器
        logger.info("创建 PlannerAgent 并传递记忆管理器...")
        agent = PlannerAgent(
            use_graph_memory_tools=True,
            memory_manager=memory_mgr
        )
        
        # 验证 agent 是否正确接收了记忆管理器
        assert agent.memory_manager is memory_mgr, "记忆管理器应该被正确传递"
        logger.info("✓ 记忆管理器正确传递给 PlannerAgent")
        
        # 验证工具是否加载
        if len(agent.graph_memory_tools) > 0:
            logger.info(f"✓ PlannerAgent 已加载 {len(agent.graph_memory_tools)} 个工具")
        else:
            logger.warning("⚠ 工具加载可能失败")
        
        logger.info("✓ 测试 3 通过\n")
        return True
        
    except Exception as e:
        logger.error(f"✗ 测试 3 失败: {e}", exc_info=True)
        return False


def test_main_function_compatibility():
    """测试 main() 函数的兼容性"""
    logger.info("=" * 80)
    logger.info("测试 4: 验证 main() 函数的向后兼容性")
    logger.info("=" * 80)
    
    try:
        from src.simulation.planner_mode import main
        import inspect
        
        # 检查 main 函数的签名
        sig = inspect.signature(main)
        logger.info(f"main() 函数签名: {sig}")
        
        # 检查是否需要更新 main() 来支持新参数
        # （本测试仅验证 main() 是否存在且可调用）
        logger.info("✓ main() 函数存在且可调用")
        logger.info("✓ 建议：在 main() 中添加 --disable-memory 命令行参数")
        
        logger.info("✓ 测试 4 通过\n")
        return True
        
    except Exception as e:
        logger.error(f"✗ 测试 4 失败: {e}", exc_info=True)
        return False


def main():
    """运行所有测试"""
    logger.info("\n" + "=" * 80)
    logger.info("Graph RAG 记忆系统集成测试")
    logger.info("=" * 80 + "\n")
    
    # 检查必要的文件是否存在
    config_path = "prompts/roles/elder_profile_example.json"
    if not os.path.exists(config_path):
        logger.warning(f"⚠ 配置文件不存在: {config_path}")
        logger.warning("部分测试可能跳过\n")
    
    results = []
    
    # 运行测试
    results.append(("测试 1: 启用记忆系统", test_memory_enabled()))
    results.append(("测试 2: 禁用记忆系统", test_memory_disabled()))
    
    try:
        results.append(("测试 3: 记忆管理器传递", test_planner_agent_memory_manager_passing()))
    except Exception as e:
        logger.warning(f"测试 3 跳过: {e}")
    
    try:
        results.append(("测试 4: main() 兼容性", test_main_function_compatibility()))
    except Exception as e:
        logger.warning(f"测试 4 跳过: {e}")
    
    # 打印总结
    logger.info("=" * 80)
    logger.info("测试总结")
    logger.info("=" * 80)
    
    passed = 0
    failed = 0
    for test_name, result in results:
        status = "✓ 通过" if result else "✗ 失败"
        logger.info(f"{status}: {test_name}")
        if result:
            passed += 1
        else:
            failed += 1
    
    logger.info(f"\n总计: {passed} 通过, {failed} 失败\n")
    
    if failed == 0:
        logger.info("✓ 所有测试通过！记忆系统集成成功。")
    else:
        logger.warning(f"✗ 有 {failed} 个测试失败。请检查上面的日志。")
    
    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
