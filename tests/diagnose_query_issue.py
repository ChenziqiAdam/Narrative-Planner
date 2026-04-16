#!/usr/bin/env python3
"""
诊断脚本：检查节点创建和查询问题
"""

import sys
import os
from datetime import datetime

from src.memory.neo4j_driver_sync import Neo4jGraphDriver

print("\n" + "="*70)
print("诊断：节点创建和查询问题")
print("="*70 + "\n")

driver = Neo4jGraphDriver(
    uri="bolt://localhost:7687",
    username="neo4j",
    password="capstone2024"
)
driver.connect()

try:
    # 步骤1：创建一个测试节点
    print("[步骤1] 创建一个测试节点")
    test_node = {
        "id": "test_evt_001",
        "type": "Event",
        "name": "测试事件",
        "description": "这是一个测试事件，用于诊断",
        "source_interview_id": "test_interview_001",
        "confidence": 0.95
    }
    
    success = driver.insert_node(test_node)
    print(f"  创建结果: {success}\n")
    
    # 步骤2：直接查询该节点
    print("[步骤2] 直接查询测试节点 (多种方式)")
    
    # 方式A: 按ID查询
    print("  A) 按ID查询:")
    result = driver._execute_query(
        "MATCH (n:Entity {id: $id}) RETURN n",
        {"id": "test_evt_001"}
    )
    print(f"     找到 {len(result)} 个节点")
    if result:
        for r in result:
            print(f"     - {r}")
    
    # 方式B: 查询所有Event类型
    print("\n  B) 查询所有Event类型:")
    result = driver._execute_query(
        "MATCH (n:Entity) WHERE n.type = 'Event' RETURN n",
        {}
    )
    print(f"     找到 {len(result)} 个Event节点")
    if result:
        for r in result:
            node = r.get('n')
            print(f"     - ID: {node.get('id') if hasattr(node, 'get') else node['id']}")
    
    # 方式C: 按文本搜索
    print("\n  C) 按文本搜索 '测试':")
    result = driver.query_by_text_similarity(
        text="测试",
        interview_id="test_interview_001",
        max_results=10
    )
    print(f"     找到 {len(result)} 个结果")
    if result:
        for r in result:
            print(f"     - {r}")
    
    # 方式D: 检查interview_id条件
    print("\n  D) 查询该采访的所有节点:")
    result = driver._execute_query(
        "MATCH (n:Entity) WHERE n.source_interview_id = $iid RETURN n",
        {"iid": "test_interview_001"}
    )
    print(f"     找到 {len(result)} 个节点")
    if result:
        for r in result:
            node = r.get('n')
            print(f"     - ID: {node.get('id') if hasattr(node, 'get') else node['id']}")
    
    # 步骤3：检查节点属性
    print("\n[步骤3] 检查节点属性类型")
    result = driver._execute_query(
        "MATCH (n:Entity {id: $id}) RETURN apoc.node.labels(n) as labels, keys(n) as properties",
        {"id": "test_evt_001"}
    )
    if result:
        print(f"  标签: {result[0].get('labels')}")
        print(f"  属性名: {result[0].get('properties')}")
    
    # 步骤4：检查关系
    print("\n[步骤4] 检查是否有任何关系被创建")
    result = driver._execute_query(
        "MATCH (n)-[r]-() RETURN COUNT(r) as rel_count",
        {}
    )
    rel_count = result[0]['rel_count'] if result else 0
    print(f"  关系总数: {rel_count}")
    
    if rel_count == 0:
        print("  ⚠️  警告：没有创建任何关系")
        print("  可能的原因：")
        print("    1. manager_sync.py 未调用 driver.insert_edge()")
        print("    2. create_event_node() 等方法未创建关系")
        print("    3. 需要在节点之间手动创建关系")
    
    # 步骤5：验证存储逻辑
    print("\n[步骤5] 验证节点属性是否正确存储")
    result = driver._execute_query(
        "MATCH (n:Entity {id: $id}) RETURN n.type, n.name, n.description, n.source_interview_id",
        {"id": "test_evt_001"}
    )
    if result:
        r = result[0]
        print(f"  type: {r.get('n.type')}")
        print(f"  name: {r.get('n.name')}")
        print(f"  description: {r.get('n.description')}")
        print(f"  source_interview_id: {r.get('n.source_interview_id')}")
    
finally:
    driver.close()

print("\n" + "="*70)
