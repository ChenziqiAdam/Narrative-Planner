# Graph RAG 记忆系统演示脚本
# 展示如何使用增强的节点模型和Neo4j驱动

import asyncio
import json
from datetime import datetime
import os
import sys

# 添加项目路径
sys.path.insert(0, os.path.dirname(__file__))

from src.memory.models import (
    EventNode, PersonNode, LocationNode, EmotionNode,
    TopicNode, InsightNode, EnhancedGraphNode
)
from src.memory.manager import EnhancedGraphMemoryManager


async def demo_scenario_1_create_rich_nodes():
    """演示场景1：创建包含丰富详节的节点"""
    
    print("\n" + "="*60)
    print("演示场景1：创建包含丰富细节的节点")
    print("="*60 + "\n")
    
    # 连接到Neo4j
    manager = EnhancedGraphMemoryManager(
        neo4j_uri="bolt://localhost:7687",
        neo4j_user="neo4j",
        neo4j_password="capstone2026"
    )
    
    try:
        await manager.initialize()
        print("✓ 已连接到Neo4j数据库\n")
        
        # 创建丰富的事件节点
        print("1. 创建事件节点（包含时间、地点、参与者、情感等）")
        event = await manager.create_event_node(
            name="山东河边的童年时光",
            description="与朋友小明一起在河边游泳、捉鱼、讲故事",
            category="childhood",
            time_frame="1952-1956",
            time_precision="approximate",
            locations=["shandong_village"],
            participants=["person_xiaoming"],
            primary_actor="person_xiaoming",
            emotional_tone=["nostalgia", "joy", "fondness"],
            significance_level="high",
            significance_reason="这段友谊塑造了我对真挚人情的理解",
            key_details={
                "frequency": "经常去（几乎每个周末）",
                "activities": ["swimming", "fishing", "storytelling"],
                "physical_conditions": "穷困但快乐",
                "weather": "春夏季节"
            },
            detailed_description="""
            那时候我们家很穷，但小明和我经常一起去河边玩。
            河水很清凉，我们会游泳、捉鱼、跳石头。
            那时没有现在这么多消遣，但却有最纯真的快乐。
            直到现在，我还能闻到那时的河水味道。
            """,
            interview_id="interview_20260403_elder001",
            turn=5
        )
        print(f"   ✓ 创建了事件: {event.name}")
        print(f"   - ID: {event.id}")
        print(f"   - 时间: {event.time_frame}")
        print(f"   - 情感: {event.emotional_tone}")
        print(f"   - 重要程度: {event.significance_level}\n")
        
        # 创建丰富的人物节点
        print("2. 创建人物节点（包含特征、关系、职业等）")
        person = await manager.create_person_node(
            name="小明",
            description="我的童年好友，后来一起去了北京工作",
            role="childhood_friend",
            relationship="lifelong friend and colleague",
            relationship_duration="65+ years",
            gender="male",
            age_mentioned="around 70",
            traits=["intelligent", "kind-hearted", "ambitious", "loyal"],
            role_characteristics={
                "intelligence": "聪明活泼",
                "kindness": "关心他人",
                "ambition": "渴望改变生活"
            },
            occupations=["farmer", "factory_worker", "engineer"],
            occupations_timeline={
                "1950-1965": "farmer",
                "1965-1978": "factory_worker", 
                "1978-2005": "engineer"
            },
            education_level="high_school",
            current_status="alive",
            last_contact="still in touch",
            interview_id="interview_20260403_elder001",
            turn=5
        )
        print(f"   ✓ 创建了人物: {person.name}")
        print(f"   - ID: {person.id}")
        print(f"   - 关系: {person.relationship}")
        print(f"   - 特征: {person.traits}")
        print(f"   - 职业: {person.occupations}\n")
        
        # 创建地点节点
        print("3. 创建地点节点（包含地理、时间、生活事件等）")
        location = await manager.create_location_node(
            name="山东",
            description="长者的故乡，充满了美好的童年记忆",
            location_type="province",
            country="China",
            administrative_division="Shandong Province",
            era_descriptions=["1950s rural China", "pre-industrial era", "agricultural period"],
            characteristics=["rural", "poor", "tight-knit community", "agricultural"],
            cultural_significance="农业文明中心，传统家族观念浓厚",
            emotional_significance="nostalgia, longing for simplicity, roots",
            life_events_here=[event.id],  # 关联事件
            daily_activities=[
                "farming with father",
                "attending school",
                "playing by the river"
            ],
            time_periods_lived=["1950-1966"],
            frequency_of_visits="rarely (moved away in 1966)",
            still_connected=True,
            interview_id="interview_20260403_elder001",
            turn=5
        )
        print(f"   ✓ 创建了地点: {location.name}")
        print(f"   - ID: {location.id}")
        print(f"   - 类型: {location.location_type}")
        print(f"   - 特征: {location.characteristics}")
        print(f"   - 生活事件: {len(location.life_events_here)} 个\n")
        
        # 创建情感节点
        print("4. 创建情感节点（包含强度、持续性、表现等）")
        emotion = await manager.create_emotion_node(
            name="怀旧与追忆",
            description="对失去的童年和青年的怀念",
            emotion_category="nostalgia",
            emotion_subcategory="longing_for_past",
            valence="positive",
            intensity=0.85,
            persistence="persistent",
            duration_description="throughout the 60+ years",
            triggered_by=[event.id, person.id, location.id],
            present_in_events=[event.id],
            manifest_behaviors=[
                "wistful sighs",
                "detailed memory recall",
                "emotional voice tone"
            ],
            emotion_arc="stable but intensified during interviews",
            related_emotions=["joy", "gratitude", "regret"],
            interview_id="interview_20260403_elder001",
            turn=5
        )
        print(f"   ✓ 创建了情感: {emotion.name}")
        print(f"   - ID: {emotion.id}")
        print(f"   - 类别: {emotion.emotion_category}")
        print(f"   - 强度: {emotion.intensity}")
        print(f"   - 持续性: {emotion.persistence}\n")
        
        return manager, event, person, location, emotion
        
    except Exception as e:
        print(f"✗ 错误：{e}")
        raise


async def demo_scenario_2_create_relationships():
    """演示场景2：创建和查询节点间的关系"""
    
    print("\n" + "="*60)
    print("演示场景2：创建和查询关系")
    print("="*60 + "\n")
    
    manager, event, person, location, emotion = (
        await demo_scenario_1_create_rich_nodes()
    )
    
    try:
        # 创建关系
        print("1. 创建不同类型的关系\n")
        
        # 事件-地点关系
        await manager.create_relationship(
            source_id=event.id,
            target_id=location.id,
            relation_type="happened_in",
            description="事件发生的地点",
            confidence=0.95,
            metadata={"primary_location": True}
        )
        print(f"   ✓ 关系: 事件 -[happened_in]-> 地点")
        
        # 事件-人物关系
        await manager.create_relationship(
            source_id=event.id,
            target_id=person.id,
            relation_type="involves",
            description="主要参与者",
            confidence=0.95,
            metadata={"role": "primary_participant"}
        )
        print(f"   ✓ 关系: 事件 -[involves]-> 人物")
        
        # 事件-情感关系
        await manager.create_relationship(
            source_id=event.id,
            target_id=emotion.id,
            relation_type="evokes",
            description="诱发的情感",
            confidence=0.90
        )
        print(f"   ✓ 关系: 事件 -[evokes]-> 情感\n")
        
        # 查询关系
        print("2. 查询关系\n")
        
        relationships = await manager.query_relationships(
            source_id=event.id
        )
        print(f"   从事件出发的关系: {len(relationships)} 个")
        for rel in relationships:
            print(f"   - {rel.get('source')}-[{rel.get('type')}]->{rel.get('target')}")
        
        return manager, event, person, location, emotion
        
    except Exception as e:
        print(f"✗ 错误：{e}")
        raise
    finally:
        await manager.close()


async def demo_scenario_3_advanced_queries():
    """演示场景3：高级查询功能"""
    
    print("\n" + "="*60)
    print("演示场景3：高级查询功能")
    print("="*60 + "\n")
    
    manager, event, person, location, emotion = (
        await demo_scenario_2_create_relationships()
    )
    
    try:
        # 查询邻域
        print("1. 获取实体的关系邻域\n")
        
        neighbors = await manager.get_entity_neighbors(
            entity_id=event.id,
            max_depth=2
        )
        print(f"   事件 '{event.name}' 的关系邻域:")
        print(json.dumps(neighbors, indent=2, ensure_ascii=False))
        
        # 获取统计信息
        print("\n2. 获取图数据库统计信息\n")
        
        stats = await manager.get_graph_statistics()
        print(f"   数据库统计:")
        print(f"   - 总节点数: {stats.get('total_nodes', 'N/A')}")
        print(f"   - 总关系数: {stats.get('total_relationships', 'N/A')}")
        
        # 获取按类型统计
        entity_stats = await manager.query_entities_by_type("Event")
        print(f"   - Event类型节点: {len(entity_stats)} 个")
        
        person_stats = await manager.query_entities_by_type("Person")
        print(f"   - Person类型节点: {len(person_stats)} 个")
        
        location_stats = await manager.query_entities_by_type("Location")
        print(f"   - Location类型节点: {len(location_stats)} 个")
        
        # 检测模式
        print("\n3. 检测访谈中的模式\n")
        
        patterns = await manager.detect_patterns(
            interview_id="interview_20260403_elder001"
        )
        
        print(f"   发现 {len(patterns)} 个模式:")
        for pattern in patterns:
            print(f"   - {pattern.get('type')}: {pattern.get('entity_name')}")
        
        # 时间线
        print("\n4. 生成事件时间线\n")
        
        timeline = await manager.get_timeline(
            interview_id="interview_20260403_elder001"
        )
        
        print(f"   时间线 (共 {len(timeline)} 个事件):")
        for evt in timeline:
            print(f"   - [{evt.get('time_frame')}] {evt.get('name')}")
        
    except Exception as e:
        print(f"✗ 错误：{e}")
        raise
    finally:
        await manager.close()


async def demo_scenario_4_conflict_and_verification():
    """演示场景4：冲突检测和验证"""
    
    print("\n" + "="*60)
    print("演示场景4：冲突检测和验证")
    print("="*60 + "\n")
    
    manager = EnhancedGraphMemoryManager(
        neo4j_uri="bolt://localhost:7687",
        neo4j_user="neo4j",
        neo4j_password="capstone2024"
    )
    
    try:
        await manager.initialize()
        
        print("1. 创建可能存在冲突的事件\n")
        
        # 事件1：一个版本
        event1 = await manager.create_event_node(
            name="去北京的决定",
            description="我决定去北京追求工程师梦想",
            time_frame="1965",
            time_precision="exact",
            significance_level="high",
            interview_id="interview_001",
            turn=8
        )
        print(f"   ✓ 事件1: {event1.name} (1965年)")
        
        # 事件2：矛盾的版本
        event2 = await manager.create_event_node(
            name="去北京的决定",
            description="被工厂分配到北京",
            time_frame="1967",
            time_precision="approximate",
            significance_level="high",
            interview_id="interview_001",
            turn=23
        )
        print(f"   ✓ 事件2: {event2.name} (1967年)\n")
        
        print("2. 标记冲突关系\n")
        
        await manager.flag_conflict(
            node_id=event1.id,
            conflicting_node_id=event2.id,
            conflict_description="关于去北京的时间有矛盾（1965 vs 1967）"
        )
        print(f"   ✓ 已标记冲突")
        
        print("\n3. 标记节点为已验证\n")
        
        await manager.mark_as_verified(
            node_id=event1.id,
            verification_notes="访谈对象在第二次访谈中确认了这个日期"
        )
        print(f"   ✓ 事件1已验证")
        
    except Exception as e:
        print(f"✗ 错误：{e}")
        raise
    finally:
        await manager.close()


async def main():
    """主演示函数"""
    
    print("\n" + "🎯 Graph RAG 记忆系统完整演示")
    print("================================================\n")
    
    print("本演示展示以下功能：")
    print("1. 创建包含丰富细节的节点")
    print("2. 建立节点间的多维关系")
    print("3. 执行高级查询和模式检测")
    print("4. 处理冲突和验证\n")
    
    print("先决条件: Neo4j必须在http://localhost:7687 运行")
    print("启动命令: docker run -d -p 7474:7474 -p 7687:7687 \\")
    print("          -e NEO4J_AUTH=neo4j/capstone2024 neo4j:latest\n")
    
    try:
        # 运行演示
        print("启动演示...\n")
        
        # 场景1：创建节点
        print("■ 演示场景1：创建包含丰富细节的节点")
        await demo_scenario_1_create_rich_nodes()
        
        # 场景2：创建关系
        print("\n■ 演示场景2：创建和查询关系")
        await demo_scenario_2_create_relationships()
        
        # 场景3：高级查询
        print("\n■ 演示场景3：高级查询功能")
        await demo_scenario_3_advanced_queries()
        
        # 场景4：冲突和验证
        print("\n■ 演示场景4：冲突检测和验证")
        await demo_scenario_4_conflict_and_verification()
        
        print("\n" + "="*60)
        print("✓ 所有演示场景完成！")
        print("="*60 + "\n")
        
        print("总结：")
        print("✓ 成功创建了包含丰富属性的实体节点")
        print("✓ 建立了多维关系")
        print("✓ 执行了复杂查询和模式检测")
        print("✓ 处理了冲突和验证")
        print("\n接下来的步骤：")
        print("1. 将内存工具集成到Agent中")
        print("2. 自动化记忆抽取和存储")
        print("3. 在访谈系统中持续改进")
        
    except Exception as e:
        print(f"\n✗ 演示失败：{e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
