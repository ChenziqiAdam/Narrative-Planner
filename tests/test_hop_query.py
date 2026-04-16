#!/usr/bin/env python3
"""
测试hop查询功能
"""

import sys
import os
from datetime import datetime


from src.memory.manager_sync import EnhancedGraphMemoryManager

print("\n" + "="*70)
print("测试：Hop查询功能")
print("="*70 + "\n")

manager = EnhancedGraphMemoryManager()
manager.initialize_sync()

interview_id = f"hop_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

print(f"创建测试采访: {interview_id}\n")

# 创建一个主事件
print("[创建数据]")
main_event = manager.create_event_node(
    name="祖父在天井教我认字",
    description="主要的记忆事件",
    participants=["祖父", "我", "奶奶"],
    locations=["天井", "书房"],
    emotional_tone=["温暖", "期待", "尊敬"],
    interview_id=interview_id
)
print()

# 查询不同hop的结果
print("="*70)
print("[Hop1查询 - 直接邻居]")
print("="*70)
result1 = manager.get_entity_by_hop(
    entity_id=main_event.id,
    hop_count=1,
    interview_id=interview_id
)

print(f"中心节点: {result1['center']['name']} ({result1['center']['type']})")
print(f"\n邻域节点:")
for node in result1['neighbors_by_hop'].get(1, []):
    print(f"  - {node['name']} ({node['type']})")

print(f"\n关系:")
for rel in result1['relationships'][:10]:
    print(f"  {rel['source_id']} --{rel['relation_type']}--> {rel['target_id']}")

print(f"\n统计: {result1['total_nodes']} 节点, {result1['total_relations']} 关系")

print("\n" + "="*70)
print("[Hop2查询 - 间接邻居]")
print("="*70)
result2 = manager.get_entity_by_hop(
    entity_id=main_event.id,
    hop_count=2,
    interview_id=interview_id
)

print(f"中心节点: {result2['center']['name']}")
for hop in sorted(result2['neighbors_by_hop'].keys()):
    nodes = result2['neighbors_by_hop'][hop]
    print(f"  {hop}跳: {len(nodes)} 个节点")
    for node in nodes[:5]:
        print(f"    - {node['name']} ({node['type']})")

print(f"\n统计: {result2['total_nodes']} 节点, {result2['total_relations']} 关系")

manager.close()

print("\n" + "="*70)
print("✅ 测试完成")
print("="*70 + "\n")

print("""
【Hop查询说明】

1. Hop查询返回的结构：
   {
       "center": 中心节点信息,
       "neighbors_by_hop": {
           1: [1跳邻居],
           2: [2跳邻居],
           ...
       },
       "relationships": [所有关系],
       "total_nodes": 总节点数,
       "total_relations": 总关系数
   }

2. 查询效果：
   - 1跳：直接与中心节点相连的节点（参与者、位置、情感等）
   - 2跳：与1跳节点相连的其他节点
   - N跳：距离中心节点N步的所有节点

3. 采访隔离：
   - Hop查询时可以指定interview_id
   - 确保只返回本采访内的节点和关系

4. 用途：
   - Agent查询某个事件的完整上下文
   - 理解记忆之间的关系网络
   - 发现隐藏的关联
""")
