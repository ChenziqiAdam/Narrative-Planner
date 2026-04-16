#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试脚本：验证多标签设计
"""

import sys

from src.memory.manager_sync import EnhancedGraphMemoryManager

def test_multi_label_design():
    """测试多标签设计"""
    
    print("\n" + "="*60)
    print("【测试】多标签设计验证")
    print("="*60)
    
    try:
        # 初始化管理器
        manager = EnhancedGraphMemoryManager()
        if not manager.initialize_sync():
            print("✗ 初始化失败")
            return False
        
        # 创建Event节点
        print("\n【1】创建Event节点...")
        event = manager.create_event_node(
            name="高中时期钞写赚钱",
            description="为了赚钱，每天在阁楼里钞写字帖",
            category="adolescence",
            participants=["父亲", "小伙伴"],
            locations=["阁楼"],
            emotional_tone=["骄傲", "辛苦"],
            time_frame="1965-1967",
            significance_level="high",
            interview_id="test_001",
            turn=1
        )
        print(f"✓ Event创建成功: {event.id}")
        print(f"  - participants: {event.participants}")
        print(f"  - locations: {event.locations}")
        print(f"  - emotional_tone: {event.emotional_tone}")
        
        # 创建独立的Person节点
        print("\n【2】创建独立Person节点...")
        person1 = manager.create_person_node(
            name="小明",
            description="高中时期的好友，现在在北京工作",
            role="friend",
            interview_id="test_001",
            turn=2
        )
        print(f"✓ Person创建成功: {person1.id}")
        print(f"  - 类型: {person1.type}")
        
        # 创建独立的Location节点
        print("\n【3】创建独立Location节点...")
        location1 = manager.create_location_node(
            name="北京",
            description="高中毕业后去工作的地方",
            location_type="city",
            interview_id="test_001",
            turn=3
        )
        print(f"✓ Location创建成功: {location1.id}")
        print(f"  - 类型: {location1.type}")
        
        # 创建独立的Topic节点
        print("\n【4】创建独立Topic节点...")
        topic1 = manager.create_topic_node(
            name="工作与生活的平衡",
            description="讨论如何在工作与生活之间取得平衡",
            category="life_philosophy",
            interview_id="test_001",
            turn=4
        )
        print(f"✓ Topic创建成功: {topic1.id}")
        print(f"  - 类型: {topic1.type}")
        
        # 查询统计
        print("\n【5】统计信息...")
        stats = manager.get_graph_statistics(interview_id="test_001")
        print(f"✓ 统计完成:")
        print(f"  - 总节点数: {stats.get('total_nodes', 0)}")
        print(f"  - 实体类型数: {stats.get('unique_types', 0)}")
        if "entities_by_type" in stats:
            print(f"  - 按类型统计: {stats.get('entities_by_type', {})}")
        
        # 按类型查询
        print("\n【6】按类型查询...")
        events = manager.query_by_text_similarity(
            text="钞写",
            entity_type="Event",
            top_k=5,
            interview_id="test_001"
        )
        print(f"✓ Event查询结果: 找到 {len(events)} 个")
        
        persons = manager.query_by_text_similarity(
            text="小",
            entity_type="Person",
            top_k=5,
            interview_id="test_001"
        )
        print(f"✓ Person查询结果: 找到 {len(persons)} 个")
        
        locations = manager.query_by_text_similarity(
            text="北京",
            entity_type="Location",
            top_k=5,
            interview_id="test_001"
        )
        print(f"✓ Location查询结果: 找到 {len(locations)} 个")
        
        print("\n✓ 多标签设计验证完成！")
        print("✓ 系统已支持不同类型的节点标签")
        
        return True
        
    except Exception as e:
        print(f"\n✗ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_multi_label_design()
    sys.exit(0 if success else 1)
