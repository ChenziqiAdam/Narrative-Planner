# Neo4j 图数据库驱动实现 - 同步版本
# 使用官方 neo4j 包的同步 API

import logging
from typing import Any, Dict, List, Optional
from datetime import datetime
import json

logger = logging.getLogger(__name__)


class Neo4jGraphDriver:
    """
    Neo4j 图数据库驱动实现（同步版本）
    
    特点：
    - 使用官方同步 API（neo4j 包）
    - 支持复杂的 Cypher 查询
    - 自动事务管理
    - 连接池
    - 简单直接，无事件循环问题
    """
    
    def __init__(
        self,
        uri: str = "bolt://localhost:7687",
        username: str = "neo4j",
        password: str = "password",
        database: str = "neo4j"
    ):
        """
        初始化 Neo4j 连接
        
        Args:
            uri: Neo4j 连接 URI (bolt://host:port)
            username: 用户名
            password: 密码
            database: 数据库名
        """
        self.uri = uri
        self.username = username
        self.password = password
        self.database = database
        self.driver = None
        self._connection_attempted = False
        
        print(f"[DRIVER] Initialized Neo4j driver config: {uri}")
    
    def connect(self):
        """建立同步连接"""
        try:
            from neo4j import GraphDatabase
            
            print(f"[CONNECTION] Connecting to Neo4j at {self.uri}...")
            self.driver = GraphDatabase.driver(
                self.uri,
                auth=(self.username, self.password),
                max_connection_pool_size=50
            )
            
            # 测试连接
            with self.driver.session(database=self.database) as session:
                result = session.run("RETURN 1")
                result.consume()
            
            print(f"[CONNECTION] ✓ Success! Connected to Neo4j at {self.uri}")
            
        except ImportError:
            print("[CONNECTION] neo4j package not installed. Run: pip install neo4j")
            raise
        except Exception as e:
            print(f"[CONNECTION] ✗ Failed to connect to Neo4j at {self.uri}: {e}")
            raise
    
    def close(self):
        """关闭连接"""
        if self.driver:
            self.driver.close()
            print("[CONNECTION] Neo4j connection closed")
    
    def _ensure_connected(self):
        """确保连接已建立，如果未建立则自动连接（仅尝试一次）"""
        if self.driver is None and not self._connection_attempted:
            self._connection_attempted = True
            try:
                print("[CONNECTION] Auto-connecting to Neo4j...")
                self.connect()
            except Exception as e:
                print(f"[CONNECTION] Auto-connect attempt failed: {e}")
                self._connection_attempted = False  # 允许重试
        elif self.driver is not None:
            print("[CONNECTION] Already connected to Neo4j")
    
    def _execute_query(self, query: str, params: Dict = None):
        """执行单个查询"""
        self._ensure_connected()
        
        if self.driver is None:
            print("[QUERY] Neo4j driver not initialized, cannot execute query")
            return None
        
        try:
            print(f"[QUERY] Executing Cypher query with params: {list(params.keys()) if params else []}")
            
            with self.driver.session(database=self.database) as session:
                result = session.run(query, params or {})
                # 转换为列表以便返回（消费结果）
                records = [dict(record) for record in result]
            
            print(f"[QUERY] ✓ Query executed successfully, returned {len(records)} records")
            return records
            
        except Exception as e:
            print(f"[QUERY] ✗ Query execution failed: {e}")
            print(f"Query: {query}")
            return None
    
    def insert_node(self, node_dict: Dict[str, Any]) -> bool:
        """插入或更新一个节点（使用多标签设计）"""
        
        node_id = node_dict.get("id", "")
        node_type = node_dict.get("type", "Entity")
        
        try:
            # 准备属性
            properties = {k: v for k, v in node_dict.items()}
            
            # 根据type设置不同标签
            type_label_map = {
                "Event": "Event",
                "Person": "Person",
                "Location": "Location",
                "Emotion": "Emotion",
                "Topic": "Topic",
                "Object": "Object",
                "Time_Period": "TimePeriod",
                "TimePeriod": "TimePeriod"
            }
            
            label = type_label_map.get(node_type, "Entity")
            
            # 使用动态标签创建查询
            query = f"""
            MERGE (n:{label} {{id: $id}})
            SET n += $properties
            RETURN n
            """
            
            params = {
                "id": node_id,
                "properties": properties
            }
            
            print(f"[STORAGE] Attempting to insert node: ID={node_id}, Type={node_type}, Label={label}")
            
            result = self._execute_query(query, params)
            
            if result:
                print(f"[STORAGE] ✓ Node inserted successfully: {node_id} (label: {label})")
                return True
            else:
                print(f"[STORAGE] ✗ Failed to insert node {node_id}")
                return False
                
        except Exception as e:
            print(f"[STORAGE] ✗ Error inserting node {node_id}: {e}")
            return False
    
    def node_exists(self, node_id: str) -> bool:
        """检查节点是否存在"""
        try:
            query = "MATCH (n {id: $id}) RETURN n LIMIT 1"
            result = self._execute_query(query, {"id": node_id})
            return bool(result)
        except Exception as e:
            print(f"[STORAGE] Error checking node existence: {e}")
            return False
    
    def insert_edge(
        self,
        source_id: str,
        target_id: str,
        relation_type: str,
        properties: Dict[str, Any] = None
    ) -> bool:
        """创建关系
        
        NOTE: 使用条件MATCH匹配任意节点，避免标签限制导致的匹配失败
        """
        
        try:
            # 先验证节点是否存在
            source_exists = self.node_exists(source_id)
            target_exists = self.node_exists(target_id)
            
            if not source_exists:
                print(f"[STORAGE] ✗ Source node not found: {source_id}")
                return False
            if not target_exists:
                print(f"[STORAGE] ✗ Target node not found: {target_id}")
                return False
            
            # 使用 WHERE 子句，而不是花括号语法，避免标签问题
            query = f"""
            MATCH (source) WHERE source.id = $source_id
            MATCH (target) WHERE target.id = $target_id
            MERGE (source)-[r:{relation_type}]->(target)
            SET r += $properties
            RETURN r, source.id as src_id, target.id as tgt_id
            """
            
            params = {
                "source_id": source_id,
                "target_id": target_id,
                "properties": properties or {}
            }
            
            print(f"[STORAGE] Creating edge: {source_id} -[{relation_type}]-> {target_id}")
            
            result = self._execute_query(query, params)
            
            if result:
                print(f"[STORAGE] ✓ Edge created successfully: {source_id} -[{relation_type}]-> {target_id}")
                return True
            else:
                print(f"[STORAGE] ✗ Failed to create edge: {source_id} -[{relation_type}]-> {target_id}")
                return False
            
        except Exception as e:
            print(f"[STORAGE] Error creating edge: {e}")
            print(f"[STORAGE] Failed to create: {source_id} -[{relation_type}]-> {target_id}")
            import traceback
            traceback.print_exc()
            return False
    
    def get_neighbors(
        self,
        node_id: str,
        max_depth: int = 1,
        relation_types: List[str] = None
    ) -> List[Dict[str, Any]]:
        """获取节点的邻域（相关节点）- 支持多标签"""
        
        try:
            # 构建关系过滤
            if relation_types:
                rel_pattern = "|".join(relation_types)
                rel_str = f"[:{rel_pattern}]*1..{max_depth}"
            else:
                rel_str = f"*1..{max_depth}"
            
            # 改进：支持多标签查询
            query = f"""
            MATCH (center {{id: $node_id}})
            MATCH (center)-[{rel_str}]-(neighbor)
            RETURN DISTINCT neighbor
            """
            
            params = {"node_id": node_id}
            
            result = self._execute_query(query, params)
            
            neighbors = []
            if result:
                for record in result:
                    if "neighbor" in record:
                        neighbors.append(dict(record["neighbor"]))
            
            print(f"[QUERY] Retrieved {len(neighbors)} neighbors for {node_id}")
            return neighbors
            
        except Exception as e:
            print(f"[QUERY] Error getting neighbors: {e}")
            return []
    
    def query_by_hop(
        self,
        node_id: str,
        hop_count: int = 1,
        interview_id: Optional[str] = None,
        max_nodes: int = 100
    ) -> Dict[str, Any]:
        """
        查询某个节点周围N跳范围内的所有节点和关系
        
        返回格式：
        {
            "center": {...},  # 中心节点
            "neighbors_by_hop": {
                1: [节点列表],
                2: [节点列表],
                ...
            },
            "relationships": [  # 所有关系
                {"source_id": "...", "relation_type": "...", "target_id": "..."},
                ...
            ]
        }
        """
        
        try:
            # 验证hop_count范围
            if hop_count < 1:
                hop_count = 1
            if hop_count > 5:
                hop_count = 5  # 限制最大5跳，防止查询过大
            
            result = {
                "center": None,
                "neighbors_by_hop": {},
                "relationships": [],
                "total_nodes": 0,
                "total_relations": 0
            }
            
            # 步骤1：获取中心节点（支持多标签）
            center_query = "MATCH (center {id: $node_id}) RETURN center"
            center_result = self._execute_query(center_query, {"node_id": node_id})
            
            if center_result and len(center_result) > 0:
                center_node = center_result[0].get("center")
                if center_node:
                    result["center"] = dict(center_node)
            else:
                print(f"[QUERY] Node {node_id} not found")
                return result
            
            # 步骤2：按hop获取邻域节点（支持多标签）
            for hop in range(1, hop_count + 1):
                # 查询距离中心节点恰好hop步的节点
                neighbor_query = f"""
                MATCH (center {{id: $node_id}})
                MATCH (center)-[*{hop}]-(neighbor)
                WHERE neighbor.id <> $node_id
                {f"AND neighbor.source_interview_id = $interview_id" if interview_id else ""}
                WITH DISTINCT neighbor
                LIMIT $max_nodes
                RETURN 
                    neighbor.id as id,
                    neighbor.type as type,
                    neighbor.name as name,
                    neighbor.description as description,
                    neighbor.confidence as confidence
                """
                
                params = {
                    "node_id": node_id,
                    "max_nodes": max_nodes
                }
                if interview_id:
                    params["interview_id"] = interview_id
                
                hop_result = self._execute_query(neighbor_query, params)
                
                if hop_result:
                    result["neighbors_by_hop"][hop] = hop_result
                    result["total_nodes"] += len(hop_result)
            
            # 步骤3：获取所有关系（在hop范围内，支持多标签）
            relation_query = f"""
            MATCH (center {{id: $node_id}})
            MATCH path = (center)-[*1..{hop_count}]-(neighbor)
            WHERE neighbor.id <> $node_id
            {f"AND neighbor.source_interview_id = $interview_id AND center.source_interview_id = $interview_id" if interview_id else ""}
            UNWIND relationships(path) as rel
            WITH DISTINCT 
                startNode(rel).id as source_id,
                type(rel) as relation_type,
                endNode(rel).id as target_id
            RETURN source_id, relation_type, target_id
            LIMIT 1000
            """
            
            params = {"node_id": node_id}
            if interview_id:
                params["interview_id"] = interview_id
            
            rel_result = self._execute_query(relation_query, params)
            
            if rel_result:
                result["relationships"] = rel_result
                result["total_relations"] = len(rel_result)
            
            print(f"[QUERY] Found {result['total_nodes']} nodes and {result['total_relations']} relationships within {hop_count} hops")
            return result
            
        except Exception as e:
            print(f"[QUERY] Error in hop-based query: {e}")
            return {
                "center": None,
                "neighbors_by_hop": {},
                "relationships": [],
                "error": str(e)
            }
    
    def query_relations(
        self,
        source_id: str,
        target_id: str = None,
        relation_type: str = None
    ) -> List[Dict[str, Any]]:
        """查询关系"""
        
        try:
            if target_id:
                # 查询两个特定节点之间的关系
                query = """
                MATCH (source {id: $source_id})-[r]->(target {id: $target_id})
                RETURN r as relation, target
                """
                params = {"source_id": source_id, "target_id": target_id}
            else:
                # 查询来自某个节点的所有关系
                query = """
                MATCH (source {id: $source_id})-[r]->(target)
                RETURN r as relation, target
                """
                params = {"source_id": source_id}
            
            result = self._execute_query(query, params)
            return result or []
            
        except Exception as e:
            print(f"[QUERY] Error querying relations: {e}")
            return []
    
    def get_graph_statistics(self, interview_id: Optional[str] = None) -> Dict[str, Any]:
        """获取图的统计信息（支持多标签）"""
        
        where_clause = ""
        params = {}
        
        if interview_id:
            where_clause = "WHERE n.source_interview_id = $interview_id"
            params["interview_id"] = interview_id
        
        # 改进：使用通用节点模式获取所有标签的统计
        query = f"""
        MATCH (n)
        {where_clause}
        RETURN 
            COUNT(n) as total_nodes,
            COUNT(DISTINCT n.type) as unique_types,
            AVG(n.confidence) as avg_confidence
        """
        
        try:
            result = self._execute_query(query, params)
            
            if result and len(result) > 0:
                stats = dict(result[0])
            else:
                stats = {"total_nodes": 0, "unique_types": 0, "avg_confidence": 0}
            
            # 按类型统计（支持多标签）
            query_by_type = f"""
            MATCH (n)
            {where_clause}
            RETURN n.type as type, COUNT(n) as count
            """
            
            type_result = self._execute_query(query_by_type, params)
            
            if type_result:
                stats["entities_by_type"] = {r["type"]: r["count"] for r in type_result}
            
            # 按关系统计（Neo4j 5.x 不需要GROUP BY）
            query_relations = """
            MATCH (source)-[r]-(target)
            RETURN type(r) as relation_type, COUNT(r) as count
            ORDER BY count DESC
            """
            
            try:
                rel_result = self._execute_query(query_relations, {})
                if rel_result:
                    stats["relations_by_type"] = {r["relation_type"]: r["count"] for r in rel_result}
            except:
                stats["relations_by_type"] = {}
            
            return stats
            
        except Exception as e:
            print(f"[QUERY] Error getting statistics: {e}")
            return {"error": str(e)}
    
    def query_by_text_similarity(
        self,
        text: str,
        entity_type: Optional[str] = None,
        max_results: int = 10,
        interview_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """按文本相似度查询（支持多标签）"""
        
        try:
            # 构建 WHERE 条件
            where_clauses = [
                "(toLower(n.name) CONTAINS toLower($text) OR toLower(n.description) CONTAINS toLower($text))"
            ]
            
            # 如果指定了实体类型，添加类型过滤
            if entity_type:
                where_clauses.append("n.type = $entity_type")
            
            # 如果指定了采访ID，添加采访过滤
            if interview_id:
                where_clauses.append("n.source_interview_id = $interview_id")
            
            where_str = " AND ".join(where_clauses)
            
            # 改进：使用通用节点模式支持多标签查询
            query = f"""
            MATCH (n)
            WHERE {where_str}
            RETURN 
                n.id as id,
                n.type as type,
                n.name as name,
                n.description as description,
                n.confidence as confidence
            LIMIT $max_results
            """
            
            params = {
                "text": text,
                "max_results": max_results
            }
            
            # 如果指定了类型，添加到参数
            if entity_type:
                params["entity_type"] = entity_type
            
            # 如果指定了采访ID，添加到参数
            if interview_id:
                params["interview_id"] = interview_id
            
            result = self._execute_query(query, params)
            return result or []
            
        except Exception as e:
            print(f"[QUERY] Error in text similarity search: {e}")
            return []
    
    def initialize_schema(self):
        """初始化数据库模式（创建约束和索引 - 支持多标签）"""
        
        try:
            with self.driver.session(database=self.database) as session:
                # 为每个标签创建约束和索引
                label_list = ["Event", "Person", "Location", "Emotion", "Topic", "Object", "TimePeriod"]
                
                for label in label_list:
                    try:
                        # 创建唯一性约束
                        session.run(f"CREATE CONSTRAINT unique_{label}_id IF NOT EXISTS FOR (e:{label}) REQUIRE e.id IS UNIQUE")
                        
                        # 创建索引
                        session.run(f"CREATE INDEX idx_{label}_type IF NOT EXISTS FOR (e:{label}) ON (e.type)")
                        session.run(f"CREATE INDEX idx_{label}_interview_id IF NOT EXISTS FOR (e:{label}) ON (e.source_interview_id)")
                        session.run(f"CREATE INDEX idx_{label}_name IF NOT EXISTS FOR (e:{label}) ON (e.name)")
                        
                        print(f"[DRIVER] Created schema for label :{label}")
                    except Exception as e:
                        # 约束或索引可能已存在
                        print(f"[DRIVER] Note: Could not create schema for :{label}: {e}")
                
                # 也保留通用Entity标签的约束（向后兼容）
                try:
                    session.run("CREATE CONSTRAINT unique_entity_id IF NOT EXISTS FOR (e:Entity) REQUIRE e.id IS UNIQUE")
                    session.run("CREATE INDEX idx_entity_type IF NOT EXISTS FOR (e:Entity) ON (e.type)")
                    session.run("CREATE INDEX idx_entity_interview IF NOT EXISTS FOR (e:Entity) ON (e.source_interview_id)")
                    session.run("CREATE INDEX idx_entity_name IF NOT EXISTS FOR (e:Entity) ON (e.name)")
                except:
                    pass
            
            print("[DRIVER] Schema initialized successfully")
            
        except Exception as e:
            print(f"[DRIVER] Warning: Could not initialize schema: {e}")
