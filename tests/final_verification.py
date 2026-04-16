#!/usr/bin/env python3
"""
最终验证：多采访隔离和关系完整性
"""

import sys
import os
from datetime import datetime

from src.memory.manager_sync import EnhancedGraphMemoryManager

print("\n" + "="*70)
print("最终验证：多采访隔离和关系完整性")
print("="*70 + "\n")

manager = EnhancedGraphMemoryManager()
manager.initialize_sync()

# 创建两个不同的采访
interview_1 = f"final_test_1_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
interview_2 = f"final_test_2_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

print(f"[采访1] {interview_1}")
event1 = manager.create_event_node(
    name="采访1的事件",
    description="发生在采访1中",
    participants=["采访1的人物A"],
    locations=["采访1的地点A"],
    emotional_tone=["采访1的情感"],
    interview_id=interview_1
)
print()

print(f"[采访2] {interview_2}")
event2 = manager.create_event_node(
    name="采访2的事件",
    description="发生在采访2中",
    participants=["采访2的人物B"],
    locations=["采访2的地点B"],
    emotional_tone=["采访2的情感"],
    interview_id=interview_2
)
print()

# 验证隔离
print("="*70)
print("验证：多采访隔离")
print("="*70 + "\n")

stats_1 = manager.get_graph_statistics(interview_id=interview_1)
stats_2 = manager.get_graph_statistics(interview_id=interview_2)

print(f"[采访1统计]")
print(f"  总节点数: {stats_1.get('total_nodes')}")
print(f"  节点类型: {stats_1.get('entities_by_type')}")
print(f"  关系数: {sum(stats_1.get('relations_by_type', {}).values())}")

print(f"\n[采访2统计]")
print(f"  总节点数: {stats_2.get('total_nodes')}")
print(f"  节点类型: {stats_2.get('entities_by_type')}")
print(f"  关系数: {sum(stats_2.get('relations_by_type', {}).values())}")

# 验证隔离：在采访1中查询采访2的关键词
print(f"\n[采访隔离验证]")
results = manager.query_by_text_similarity(
    text="采访2",
    interview_id=interview_1,
    top_k=10
)
print(f"  采访1中搜索'采访2': {len(results)}个结果（应该是0）")

# 验证可以找到本采访的数据
results = manager.query_by_text_similarity(
    text="采访1",
    interview_id=interview_1,
    top_k=10
)
print(f"  采访1中搜索'采访1': {len(results)}个结果（应该>0）")

# 验证关系
print(f"\n[关系验证]")
driver = manager.driver
result = driver._execute_query(
    "MATCH (n)-[r]-() RETURN COUNT(r) as rel_count",
    {}
)
rel_count = result[0]['rel_count'] if result else 0
print(f"  全局关系总数: {rel_count}")

if rel_count > 0:
    result = driver._execute_query(
        """
        MATCH (source)-[r]->(target)
        RETURN DISTINCT type(r) as rel_type, COUNT(r) as cnt
        ORDER BY cnt DESC
        """,
        {}
    )
    print(f"  关系类型分布:")
    for r in result:
        print(f"    - {r['rel_type']}: {r['cnt']} 个")
else:
    print(f"  ❌ 没有创建任何关系！")

manager.close()

print("\n" + "="*70)
print("✅ 验证完成")
print("="*70 + "\n")
