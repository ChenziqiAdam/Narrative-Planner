#!/usr/bin/env python3
"""
验证关系创建
"""

import sys
import os
from datetime import datetime

from src.memory.manager_sync import EnhancedGraphMemoryManager
from src.memory.neo4j_driver_sync import Neo4jGraphDriver

print("\n" + "="*70)
print("验证关系创建")
print("="*70 + "\n")

manager = EnhancedGraphMemoryManager()
manager.initialize_sync()

interview_id = f"relation_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

print(f"创建测试采访: {interview_id}\n")

# 创建一个事件，带有参与者、位置、情感
event = manager.create_event_node(
    name="祖父教我读书",
    description="祖父在书房教我认字",
    category="education",
    participants=["祖父", "我"],
    locations=["书房"],
    emotional_tone=["温暖", "期待"],
    interview_id=interview_id
)

print(f"\n✓ 事件创建完成: {event.id}\n")

# 现在查询关系
driver = manager.driver

print("[验证关系]")
result = driver._execute_query(
    "MATCH (n)-[r]-() RETURN COUNT(r) as rel_count",
    {}
)
rel_count = result[0]['rel_count'] if result else 0
print(f"总关系数: {rel_count}")

if rel_count > 0:
    print("\n关系详情:")
    result = driver._execute_query(
        """
        MATCH (source)-[r]->(target)
        RETURN source.id as source_id, type(r) as rel_type, target.id as target_id
        """,
        {}
    )
    if result:
        for r in result:
            print(f"  {r['source_id']} --{r['rel_type']}-> {r['target_id']}")
else:
    print("❌ 没有创建任何关系！")

# 验证采访隔离
print(f"\n[验证采访隔离 - 采访 {interview_id}]")
stats = manager.get_graph_statistics(interview_id=interview_id)
print(f"总节点数: {stats.get('total_nodes')}")
print(f"节点类型分布: {stats.get('entities_by_type')}")
print(f"关系类型: {stats.get('relations_by_type')}")

manager.close()

print("\n" + "="*70)
