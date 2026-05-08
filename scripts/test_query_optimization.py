#!/usr/bin/env python3
"""
Demo script to test query optimization feature.

This script demonstrates:
1. Initializing planner with QUERY_OPTIMIZATION_ENABLED=false (default)
2. Processing a user response and observing direct HybridRetriever behavior
3. Switching to QUERY_OPTIMIZATION_ENABLED=true
4. Processing the same response and observing extraction-agent-delegated behavior

Usage:
    python scripts/test_query_optimization.py
"""

import asyncio
import logging
import os
import sys
from typing import Dict, Any

# Setup logging to see retrieval logs
logging.basicConfig(
    level=logging.INFO,
    format='[%(name)s] %(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)

def test_query_optimization():
    """Test query optimization with both modes."""
    from src.config import Config
    from src.orchestration import SessionOrchestrator
    
    # Test data
    elder_info = {
        "name": "李老奶奶",
        "birth_year": 1940,
        "gender": "女",
        "background": "退休教师",
        "family_size": 3,
    }
    
    first_response = "我出生在杭州，那是个很美的地方。父亲是医生，母亲是家庭主妇。我有一个哥哥。"
    second_response = "在杭州待到1958年，然后考上了浙江师范学院，学的是中文。那时候正是建国不久的时代。"
    
    print("=" * 70)
    print("查询优化功能演示")
    print("=" * 70)
    
    # ──────────────────────────────────────
    # 模式 1: 禁用优化（直接查询）
    # ──────────────────────────────────────
    print("\n【模式 1】QUERY_OPTIMIZATION_ENABLED = False (默认)")
    print("-" * 70)
    
    # 临时禁用优化
    old_optimization = Config.QUERY_OPTIMIZATION_ENABLED
    Config.QUERY_OPTIMIZATION_ENABLED = False
    
    try:
        session1 = SessionOrchestrator(session_id="demo_direct_query")
        session1.initialize_session(elder_info)
        
        logger.info("Processing first response with DIRECT query mode...")
        result1 = asyncio.run(session1.process_user_response(first_response))
        
        print("\n预期行为:")
        print("  - HybridRetriever 在 process_user_response 中直接调用")
        print("  - 查询延迟在 'Hybrid retrieval' 日志中显示")
        print(f"  - GraphRAG 上下文长度: {len(result1.get('graph_rag_context', '')) or len(result1.get('planned_question', ''))} 字符")
        
    except Exception as e:
        logger.error(f"模式 1 失败: {e}", exc_info=True)
    finally:
        asyncio.run(session1.close())
    
    # ──────────────────────────────────────
    # 模式 2: 启用优化（代理查询）
    # ──────────────────────────────────────
    print("\n【模式 2】QUERY_OPTIMIZATION_ENABLED = True")
    print("-" * 70)
    
    # 启用优化
    Config.QUERY_OPTIMIZATION_ENABLED = True
    
    try:
        session2 = SessionOrchestrator(session_id="demo_agent_query")
        session2.initialize_session(elder_info)
        
        logger.info("Processing first response with OPTIMIZED query mode...")
        result2 = asyncio.run(session2.process_user_response(first_response))
        
        print("\n预期行为:")
        print("  - GraphExtractionAgent.query_memory() 在 build() 中被调用")
        print("  - 查询延迟在 'Memory query succeeded' 日志中显示")
        print(f"  - GraphRAG 上下文长度: {len(result2.get('graph_rag_context', '')) or len(result2.get('planned_question', ''))} 字符")
        
        logger.info("Processing second response with OPTIMIZED query mode...")
        result3 = asyncio.run(session2.process_user_response(second_response))
        
        print(f"\n第二次查询完成")
        print(f"  - 累积转数: {result3.get('turn_count', '?')}")
        
    except Exception as e:
        logger.error(f"模式 2 失败: {e}", exc_info=True)
    finally:
        asyncio.run(session2.close())
    
    # 恢复原始状态
    Config.QUERY_OPTIMIZATION_ENABLED = old_optimization
    
    # ──────────────────────────────────────
    # 总结
    # ──────────────────────────────────────
    print("\n" + "=" * 70)
    print("演示完成。关键观察点：")
    print("-" * 70)
    print("1. 直接查询模式：")
    print("   - HybridRetriever 在 process_user_response 中被调用")
    print("   - 演讲问题生成前完成检索")
    print("\n2. 优化查询模式：")
    print("   - GraphExtractionAgent.query_memory() 在 build() 中被调用")
    print("   - 检索作为决策上下文构建的一部分")
    print("\n3. 功能对比：")
    print("   - 结果应相同或非常相似（因为同一算法）")
    print("   - 时序不同（查询点不同）")
    print("   - 便于统一管理和扩展")
    print("=" * 70)


def test_config_loading():
    """Verify that configuration loading works correctly."""
    print("\n配置加载验证")
    print("-" * 70)
    
    from src.config import Config
    
    optimization_enabled = Config.QUERY_OPTIMIZATION_ENABLED
    print(f"QUERY_OPTIMIZATION_ENABLED = {optimization_enabled}")
    print(f"类型: {type(optimization_enabled).__name__}")
    print(f"来源: 环境变量或 .env 文件")
    
    if optimization_enabled:
        print("✓ 查询优化已启用")
    else:
        print("✓ 查询优化已禁用（默认）")


if __name__ == "__main__":
    print("\n开始测试查询优化功能...\n")
    
    # First verify config
    test_config_loading()
    
    # Then run main test
    try:
        test_query_optimization()
    except Exception as e:
        logger.error(f"测试失败: {e}", exc_info=True)
        sys.exit(1)
    
    print("\n✓ 测试完成")
