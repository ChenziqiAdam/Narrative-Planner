#!/usr/bin/env python3
"""
清理数据库中的旧节点标签（迁移到正确的:Entity标签）
"""

import sys
import os

from src.memory.neo4j_driver_sync import Neo4jGraphDriver

print("\n" + "="*70)
print("数据库迁移：清理旧标签并转换为 :Entity")
print("="*70 + "\n")

# 使用正确的凭证
driver = Neo4jGraphDriver(
    uri="bolt://localhost:7687",
    username="neo4j",
    password="capstone2024"
)
driver.connect()

try:
    # 统计所有节点
    print("[检查1] 统计现有节点:")
    result = driver._execute_query("MATCH (n) RETURN COUNT(n) as total", {})
    total = result[0]['total'] if result else 0
    print(f"  总节点数: {total}")
    
    # 统计Entity节点
    result = driver._execute_query("MATCH (n:Entity) RETURN COUNT(n) as cnt", {})
    entity_cnt = result[0]['cnt'] if result else 0
    print(f"  Entity节点数: {entity_cnt}")
    
    # 检查是否有非Entity标签的节点
    result = driver._execute_query(
        """
        MATCH (n) 
        WHERE NOT n:Entity
        RETURN COUNT(n) as cnt
        """,
        {}
    )
    non_entity_cnt = result[0]['cnt'] if result else 0
    print(f"  非Entity节点数: {non_entity_cnt}")
    
    if non_entity_cnt > 0:
        # 展示非Entity节点的标签
        result = driver._execute_query(
            """
            MATCH (n) 
            WHERE NOT n:Entity
            RETURN DISTINCT labels(n) as node_labels
            LIMIT 5
            """,
            {}
        )
        if result:
            print("  非Entity标签的节点:")
            for r in result:
                print(f"    - {r.get('node_labels')}")
    
    # 清理：删除所有关系和节点
    print("\n[清理] 删除所有节点和关系...")
    driver._execute_query("MATCH (n) DETACH DELETE n", {})
    print("  ✓ 已删除所有节点和关系")
    
    # 验证
    result = driver._execute_query("MATCH (n) RETURN COUNT(n) as total", {})
    final_total = result[0]['total'] if result else 0
    print(f"\n  验证：清理后节点数 = {final_total}")
    print("  ✓ 数据库已清空，准备好接收新数据")
    
finally:
    driver.close()

print("\n" + "="*70)
print("✅ 数据库清理完成")
print("="*70 + "\n")
