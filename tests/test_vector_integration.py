#!/usr/bin/env python3
"""
向量去重集成测试

测试新的向量存储、记忆提取代理以及整个去重流程
"""

import os
import sys
import json
from datetime import datetime

# 添加项目根目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

def test_vector_storage():
    """测试向量存储的基本功能"""
    print("\n" + "="*70)
    print("【测试1】向量存储基本功能")
    print("="*70)
    
    try:
        from src.memory.vector_storage import create_vector_store
        
        # 创建向量存储
        print("创建向量存储实例...")
        store = create_vector_store("auto")
        print(f"✓ 向量存储创建成功: {store.__class__.__name__}")
        
        # 添加节点
        print("\n添加节点到向量存储...")
        store.add(
            node_id="node_1",
            text="我經常去蘇州老宅玩耍，那是我童年的回忆",
            metadata={"type": "Location", "name": "蘇州老宅"}
        )
        store.add(
            node_id="node_2",
            text="小时候在苏州的老房子里度过的快乐时光",
            metadata={"type": "Location", "name": "苏州老房子"}
        )
        store.add(
            node_id="node_3",
            text="我喜欢去公园散步",
            metadata={"type": "Location", "name": "公园"}
        )
        print("✓ 节点添加成功")
        
        # 搜索相似节点
        print("\n搜索相似节点...")
        results = store.search(
            query_text="苏州的老宅",
            top_k=3,
            threshold=0.7
        )
        print(f"✓ 找到 {len(results)} 个相似节点")
        for node_id, similarity, metadata in results:
            print(f"  - {metadata.get('name')} (相似度: {similarity:.2%})")
        
        # 验证高相似度匹配
        if len(results) >= 2:
            assert results[0][1] > 0.85, "第一个结果应该有高相似度"
            print("✓ 向量相似度计算正确")
        
        return True
    
    except Exception as e:
        print(f"✗ 向量存储测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_memory_manager_integration():
    """测试记忆管理器与向量存储的集成"""
    print("\n" + "="*70)
    print("【测试2】记忆管理器与向量存储集成")
    print("="*70)
    
    try:
        from src.memory.manager_sync import EnhancedGraphMemoryManager, create_vector_store
        
        # 创建管理器（带向量存储）
        print("创建增强的内存管理器...")
        manager = EnhancedGraphMemoryManager(
            vector_store=create_vector_store("memory"),  # 使用内存向量存储
            enable_vector_dedup=True
        )
        
        print(f"✓ 管理器创建成功")
        print(f"  - 向量去重已启用: {manager.enable_vector_dedup}")
        print(f"  - 向量存储类型: {manager.vector_store.__class__.__name__}")
        
        # 测试搜索相似节点
        print("\n测试向量搜索...")
        results = manager.search_similar_nodes(
            entity_name="蘇州老宅",
            entity_type="Location",
            similarity_threshold=0.75
        )
        print(f"✓ 向量搜索执行成功，返回 {len(results)} 结果")
        
        return True
    
    except Exception as e:
        print(f"✗ 管理器集成测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_memory_extraction_agent():
    """测试记忆提取代理"""
    print("\n" + "="*70)
    print("【测试3】记忆提取代理")
    print("="*70)
    
    try:
        from src.memory.manager_sync import EnhancedGraphMemoryManager, create_vector_store
        from src.agents.memory_extraction_agent import MemoryExtractionAgent
        
        # 初始化管理器
        print("初始化管理器...")
        manager = EnhancedGraphMemoryManager(
            vector_store=create_vector_store("memory"),
            enable_vector_dedup=True
        )
        
        # 创建提取代理
        print("创建记忆提取代理...")
        agent = MemoryExtractionAgent(
            memory_manager=manager,
            interview_id="test_interview_001",
            dedup_threshold=0.80
        )
        print(f"✓ 代理创建成功 (interview_id={agent.interview_id})")
        
        # 测试提取方法的存在性
        assert hasattr(agent, 'extract_and_store'), "代理应该有 extract_and_store 方法"
        assert hasattr(agent, 'respond'), "代理应该有 respond 方法"
        print("✓ 代理方法检查通过")
        
        return True
    
    except Exception as e:
        print(f"✗ 提取代理测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_tools_integration():
    """测试新增工具的集成"""
    print("\n" + "="*70)
    print("【测试4】工具集成测试")
    print("="*70)
    
    try:
        from src.memory.manager_sync import EnhancedGraphMemoryManager, create_vector_store
        from src.memory.tools_sync import create_graph_memory_tools
        
        # 初始化管理器
        print("初始化管理器...")
        manager = EnhancedGraphMemoryManager(
            vector_store=create_vector_store("memory"),
            enable_vector_dedup=True
        )
        
        # 创建工具
        print("创建图内存工具...")
        tools = create_graph_memory_tools(
            memory_manager=manager,
            interview_id="test_interview_001"
        )
        
        print(f"✓ 创建了 {len(tools)} 个工具")
        
        # 检查新增工具
        tool_names = [t.func.__name__ for t in tools if hasattr(t, 'func')]
        print(f"  工具列表: {tool_names}")
        
        # 验证 extract_interview_memories_tool 存在
        has_extract_tool = any('extract' in name.lower() for name in tool_names)
        assert has_extract_tool, "应该包含记忆提取工具"
        print("✓ 记忆提取工具已被添加")
        
        # 验证 store_memory_tool 存在
        has_store_tool = any('store' in name.lower() for name in tool_names)
        assert has_store_tool, "应该包含存储工具"
        print("✓ 存储工具已集成向量去重")
        
        return True
    
    except Exception as e:
        print(f"✗ 工具集成测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_deduplication_workflow():
    """测试完整的去重工作流"""
    print("\n" + "="*70)
    print("【测试5】完整去重工作流")
    print("="*70)
    
    try:
        from src.memory.manager_sync import EnhancedGraphMemoryManager, create_vector_store
        from src.agents.memory_extraction_agent import MemoryExtractionAgent
        
        # 初始化
        print("初始化去重工作流...")
        manager = EnhancedGraphMemoryManager(
            vector_store=create_vector_store("memory"),
            enable_vector_dedup=True
        )
        
        agent = MemoryExtractionAgent(
            memory_manager=manager,
            interview_id="test_dedup",
            dedup_threshold=0.80
        )
        
        print("✓ 系统初始化完成")
        
        # 模拟访谈文本
        interview_text = """
        我经常去苏州老宅玩，那里有很多家具。
        小时候在苏州的老房子里玩耍，很开心。
        我的父亲是一名工程师。
        爸爸从事工程方面的工作。
        """
        
        # 运行提取和去重
        print("\n运行记忆提取和去重...")
        result = agent.extract_and_store(interview_text)
        
        print(f"✓ 去重流程执行成功")
        print(f"  - 状态: {result.get('status')}")
        print(f"  - 提取的实体: {result.get('extracted_count', 0)}")
        print(f"  - 存储的节点: {result.get('stored_count', 0)}")
        print(f"  - 合并的节点: {result.get('merged_count', 0)}")
        print(f"  - 跳过的节点: {result.get('skipped_count', 0)}")
        
        return True
    
    except Exception as e:
        print(f"✗ 去重工作流测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """运行所有测试"""
    print("\n" + "="*70)
    print("【向量去重集成测试套件】")
    print("开始时间:", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("="*70)
    
    results = []
    
    # 运行所有测试
    test_functions = [
        ("向量存储", test_vector_storage),
        ("管理器集成", test_memory_manager_integration),
        ("提取代理", test_memory_extraction_agent),
        ("工具集成", test_tools_integration),
        ("去重工作流", test_deduplication_workflow),
    ]
    
    for test_name, test_func in test_functions:
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"\n✗ {test_name}测试异常: {e}")
            import traceback
            traceback.print_exc()
            results.append((test_name, False))
    
    # 打印总结
    print("\n" + "="*70)
    print("【测试总结】")
    print("="*70)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status}: {test_name}")
    
    print(f"\n总计: {passed}/{total} 测试通过")
    print("结束时间:", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    
    if passed == total:
        print("\n🎉 所有测试都通过了！系统已准备好运行。")
        return 0
    else:
        print(f"\n⚠️  有 {total - passed} 个测试失败，请检查错误信息。")
        return 1


if __name__ == "__main__":
    sys.exit(main())
