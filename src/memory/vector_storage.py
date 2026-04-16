# 向量存储模块 - 支持多种后端
# 用于节点去重和相似度搜索

import os
import json
from abc import ABC, abstractmethod
from typing import List, Dict, Optional, Tuple
from datetime import datetime

class VectorStore(ABC):
    """向量存储接口 - 定义所有向量存储实现必须支持的方法"""
    
    @abstractmethod
    def add(self, node_id: str, text: str, metadata: Dict) -> None:
        """
        添加或更新向量
        
        Args:
            node_id: 节点唯一ID
            text: 用于生成向量的文本
            metadata: 元数据（包含节点类型、名称等）
        """
        pass
    
    @abstractmethod
    def search(self, query_text: str, top_k: int = 5, threshold: float = 0.7) -> List[Tuple]:
        """
        相似度搜索
        
        Args:
            query_text: 查询文本
            top_k: 返回的最多结果数
            threshold: 相似度阈值（0-1），低于此值的结果将被过滤
        
        Returns:
            List[Tuple]: [(node_id, similarity_score, metadata), ...]
        """
        pass
    
    @abstractmethod
    def delete(self, node_id: str) -> None:
        """删除向量"""
        pass
    
    @abstractmethod
    def update(self, node_id: str, text: str, metadata: Dict) -> None:
        """更新向量"""
        pass
    
    @abstractmethod
    def batch_add(self, items: List[Dict]) -> None:
        """
        批量添加向量
        
        Args:
            items: List[{node_id, text, metadata}]
        """
        pass
    
    @abstractmethod
    def clear(self) -> None:
        """清空所有向量"""
        pass
    
    @abstractmethod
    def health_check(self) -> bool:
        """检查存储是否可用"""
        pass


class ChromaVectorStore(VectorStore):
    """
    基于Chroma的轻量级向量存储实现
    
    特点：
    - 无需外部服务，内存或文件存储
    - 自动处理embedding
    - 简单易用，适合中等规模应用
    """
    
    def __init__(self, collection_name: str = "memories", persist_dir: Optional[str] = None):
        """
        初始化Chroma向量存储
        
        Args:
            collection_name: 集合名称
            persist_dir: 持久化目录（可选）
        """
        try:
            import chromadb
            from chromadb.config import Settings
            
            # 配置持久化
            if persist_dir:
                os.makedirs(persist_dir, exist_ok=True)
                settings = Settings(
                    chroma_db_impl="duckdb+parquet",
                    persist_directory=persist_dir,
                    anonymized_telemetry=False
                )
                self.client = chromadb.Client(settings)
            else:
                self.client = chromadb.Client()
            
            self.collection = self.client.get_or_create_collection(
                name=collection_name,
                metadata={"hnsw:space": "cosine"}
            )
            self.collection_name = collection_name
            
        except ImportError:
            raise ImportError(
                "Please install chromadb: pip install chromadb\n"
                "If you encounter issues, try: pip install chromadb --upgrade"
            )
        
        # 初始化embedding模型
        try:
            from sentence_transformers import SentenceTransformer
            self.embedder = SentenceTransformer(
                'paraphrase-multilingual-MiniLM-L12-v2',
                device='cpu'  # 使用CPU以兼容性
            )
            print("[VectorStore] ✓ SentenceTransformer已加载")
        except ImportError:
            raise ImportError(
                "Please install sentence-transformers: pip install sentence-transformers"
            )
    
    def embed_text(self, text: str) -> List[float]:
        """
        生成文本的embedding向量
        
        Args:
            text: 输入文本
        
        Returns:
            向量列表
        """
        if not text or not isinstance(text, str):
            text = str(text) if text else "empty"
        
        # 截断过长文本
        text = text[:1000]
        
        try:
            embedding = self.embedder.encode(text, convert_to_tensor=False)
            return embedding.tolist()
        except Exception as e:
            print(f"[VectorStore] ⚠️ embedding生成失败: {e}")
            # 返回零向量作为备选
            return [0.0] * 384
    
    def add(self, node_id: str, text: str, metadata: Dict) -> None:
        """添加节点向量"""
        try:
            if not node_id:
                print("[VectorStore] ⚠️ node_id为空，跳过")
                return
            
            embedding = self.embed_text(text)
            
            # 添加元数据字段
            enhanced_metadata = {
                **metadata,
                "added_at": datetime.now().isoformat(),
                "text_preview": text[:100] if text else ""
            }
            
            self.collection.add(
                ids=[node_id],
                embeddings=[embedding],
                metadatas=[enhanced_metadata],
                documents=[text[:500]]  # 存储文本预览
            )
            print(f"[VectorStore] ✓ 节点已添加: {node_id}")
            
        except Exception as e:
            print(f"[VectorStore] ✗ 添加失败 {node_id}: {e}")
    
    def search(self, query_text: str, top_k: int = 5, threshold: float = 0.7) -> List[Tuple]:
        """
        相似度搜索
        
        返回的相似度是基于cosine距离转换的（0-1范围）
        """
        try:
            if not query_text:
                return []
            
            embedding = self.embed_text(query_text)
            
            results = self.collection.query(
                query_embeddings=[embedding],
                n_results=top_k,
                include=['distances', 'metadatas', 'documents']
            )
            
            output = []
            if results['ids'] and results['ids'][0]:
                for i, node_id in enumerate(results['ids'][0]):
                    # Chroma返回距离距离，需要转换为相似度（0-1）
                    distance = results['distances'][0][i]
                    # cosine距离范围是0-2，转换为相似度
                    similarity = 1 - (distance / 2)
                    
                    if similarity >= threshold:
                        metadata = results['metadatas'][0][i] if results['metadatas'] else {}
                        output.append((node_id, similarity, metadata))
            
            print(f"[VectorStore] ✓ 搜索完成: 查询={query_text[:50]} 结果={len(output)}")
            return output
            
        except Exception as e:
            print(f"[VectorStore] ✗ 搜索失败: {e}")
            return []
    
    def update(self, node_id: str, text: str, metadata: Dict) -> None:
        """更新向量 - 先删除后添加"""
        try:
            self.delete(node_id)
            self.add(node_id, text, metadata)
            print(f"[VectorStore] ✓ 节点已更新: {node_id}")
        except Exception as e:
            print(f"[VectorStore] ✗ 更新失败 {node_id}: {e}")
    
    def delete(self, node_id: str) -> None:
        """删除向量"""
        try:
            self.collection.delete(ids=[node_id])
            print(f"[VectorStore] ✓ 节点已删除: {node_id}")
        except Exception as e:
            print(f"[VectorStore] ⚠️ 删除失败 {node_id}: {e}")
    
    def batch_add(self, items: List[Dict]) -> None:
        """批量添加向量"""
        if not items:
            return
        
        try:
            ids = []
            embeddings = []
            metadatas = []
            documents = []
            
            for item in items:
                node_id = item.get('node_id') or item.get('id')
                text = item.get('text', '')
                metadata = item.get('metadata', {})
                
                if node_id:
                    ids.append(node_id)
                    embeddings.append(self.embed_text(text))
                    metadatas.append({**metadata, "added_at": datetime.now().isoformat()})
                    documents.append(text[:500])
            
            if ids:
                self.collection.add(
                    ids=ids,
                    embeddings=embeddings,
                    metadatas=metadatas,
                    documents=documents
                )
                print(f"[VectorStore] ✓ 批量添加完成: {len(ids)}个节点")
        
        except Exception as e:
            print(f"[VectorStore] ✗ 批量添加失败: {e}")
    
    def clear(self) -> None:
        """清空所有向量"""
        try:
            # Chroma没有直接的clear方法，需要删除整个collection再重建
            self.client.delete_collection(name=self.collection_name)
            self.collection = self.client.get_or_create_collection(
                name=self.collection_name,
                metadata={"hnsw:space": "cosine"}
            )
            print("[VectorStore] ✓ 已清空所有向量")
        except Exception as e:
            print(f"[VectorStore] ✗ 清空失败: {e}")
    
    def health_check(self) -> bool:
        """检查Chroma是否可用"""
        try:
            # 简单的测试操作
            self.collection.count()
            print("[VectorStore] ✓ 健康检查通过")
            return True
        except Exception as e:
            print(f"[VectorStore] ✗ 健康检查失败: {e}")
            return False
    
    def get_stats(self) -> Dict:
        """获取向量存储统计信息"""
        try:
            count = self.collection.count()
            return {
                "collection_name": self.collection_name,
                "total_vectors": count,
                "status": "healthy"
            }
        except Exception as e:
            return {
                "collection_name": self.collection_name,
                "total_vectors": 0,
                "status": "error",
                "error": str(e)
            }


class FAISSVectorStore(VectorStore):
    """
    基于FAISS的高性能向量存储实现
    
    特点：
    - 超快速相似度搜索（10-100倍快于Chroma）
    - 支持大规模数据（百万级向量）
    - 内存或磁盘存储
    - 专为生产环境优化
    """
    
    def __init__(self, dimension: int = 384, persist_path: Optional[str] = None):
        """
        初始化FAISS向量存储
        
        Args:
            dimension: 向量维度（默认384，对应SentenceTransformer）
            persist_path: 持久化路径（可选）
        """
        try:
            import faiss
            self.faiss = faiss
        except ImportError:
            raise ImportError(
                "Please install faiss-cpu: pip install faiss-cpu\n"
                "Or for GPU support: pip install faiss-gpu"
            )
        
        import numpy as np
        self.np = np
        
        # 初始化embedding模型
        try:
            from sentence_transformers import SentenceTransformer
            self.embedder = SentenceTransformer(
                'paraphrase-multilingual-MiniLM-L12-v2',
                device='cpu'
            )
            print("[VectorStore] ✓ SentenceTransformer已加载")
        except ImportError:
            raise ImportError(
                "Please install sentence-transformers: pip install sentence-transformers"
            )
        
        self.dimension = dimension
        self.persist_path = persist_path
        
        # 创建FAISS索引（使用L2距离）
        self.index = self.faiss.IndexFlatL2(dimension)
        
        # 维护ID映射和元数据
        self.id_to_node: Dict[int, str] = {}  # FAISS内部ID -> node_id
        self.node_to_id: Dict[str, int] = {}  # node_id -> FAISS内部ID
        self.metadatas: Dict[str, Dict] = {}
        self.next_internal_id = 0
        
        print("[VectorStore] ✓ FAISS向量存储已初始化")
    
    def embed_text(self, text: str) -> List[float]:
        """生成文本的embedding向量"""
        if not text or not isinstance(text, str):
            text = str(text) if text else "empty"
        
        text = text[:1000]
        
        try:
            embedding = self.embedder.encode(text, convert_to_tensor=False)
            return embedding.tolist()
        except Exception as e:
            print(f"[VectorStore] ⚠️ embedding生成失败: {e}")
            return [0.0] * self.dimension
    
    def add(self, node_id: str, text: str, metadata: Dict) -> None:
        """添加节点向量"""
        try:
            if not node_id:
                print("[VectorStore] ⚠️ node_id为空，跳过")
                return
            
            # 如果node_id已存在，先删除
            if node_id in self.node_to_id:
                self.delete(node_id)
            
            embedding = self.embed_text(text)
            embedding_array = self.np.array([embedding], dtype=self.np.float32)
            
            # 添加到FAISS索引
            internal_id = self.next_internal_id
            self.index.add(embedding_array)
            
            # 维护映射关系
            self.id_to_node[internal_id] = node_id
            self.node_to_id[node_id] = internal_id
            self.metadatas[node_id] = {
                **metadata,
                "added_at": datetime.now().isoformat(),
                "text_preview": text[:100] if text else ""
            }
            
            self.next_internal_id += 1
            print(f"[VectorStore] ✓ 节点已添加: {node_id}")
            
        except Exception as e:
            print(f"[VectorStore] ✗ 添加失败 {node_id}: {e}")
    
    def search(self, query_text: str, top_k: int = 5, threshold: float = 0.7) -> List[Tuple]:
        """
        相似度搜索
        
        返回的相似度是基于L2距离转换的（0-1范围）
        距离小 = 相似度高
        """
        try:
            if not query_text or self.index.ntotal == 0:
                return []
            
            embedding = self.embed_text(query_text)
            embedding_array = self.np.array([embedding], dtype=self.np.float32)
            
            # 搜索最近邻
            k = min(top_k, self.index.ntotal)
            distances, indices = self.index.search(embedding_array, k)
            
            output = []
            for i, internal_id in enumerate(indices[0]):
                if internal_id < 0:  # -1表示无效结果
                    continue
                
                distance = distances[0][i]
                # 将L2距离转换为相似度（0-1）
                # L2距离越小，相似度越高
                # 假设最大距离为2.0（标准化向量），转换公式：
                similarity = 1 - min(distance / 2.0, 1.0)
                
                if similarity >= threshold:
                    node_id = self.id_to_node[internal_id]
                    metadata = self.metadatas.get(node_id, {})
                    output.append((node_id, similarity, metadata))
            
            print(f"[VectorStore] ✓ 搜索完成: 查询={query_text[:50]} 结果={len(output)}")
            return output
            
        except Exception as e:
            print(f"[VectorStore] ✗ 搜索失败: {e}")
            return []
    
    def update(self, node_id: str, text: str, metadata: Dict) -> None:
        """更新向量"""
        try:
            self.delete(node_id)
            self.add(node_id, text, metadata)
            print(f"[VectorStore] ✓ 节点已更新: {node_id}")
        except Exception as e:
            print(f"[VectorStore] ✗ 更新失败 {node_id}: {e}")
    
    def delete(self, node_id: str) -> None:
        """删除向量"""
        try:
            if node_id not in self.node_to_id:
                print(f"[VectorStore] ⚠️ 节点不存在: {node_id}")
                return
            
            # FAISS不支持直接删除单个向量
            # 需要重建索引（排除该节点）
            internal_id = self.node_to_id[node_id]
            
            # 获取所有向量
            all_vectors = self.index.reconstruct_n(0, self.index.ntotal)
            
            # 重建索引（不包含要删除的向量）
            new_index = self.faiss.IndexFlatL2(self.dimension)
            new_id_to_node = {}
            new_node_to_id = {}
            new_next_id = 0
            
            for i in range(self.index.ntotal):
                if i != internal_id:
                    old_node_id = self.id_to_node[i]
                    new_index.add(self.np.array([all_vectors[i]], dtype=self.np.float32))
                    new_id_to_node[new_next_id] = old_node_id
                    new_node_to_id[old_node_id] = new_next_id
                    new_next_id += 1
            
            # 更新索引和映射
            self.index = new_index
            self.id_to_node = new_id_to_node
            self.node_to_id = new_node_to_id
            self.next_internal_id = new_next_id
            self.metadatas.pop(node_id, None)
            
            print(f"[VectorStore] ✓ 节点已删除: {node_id}")
            
        except Exception as e:
            print(f"[VectorStore] ✗ 删除失败 {node_id}: {e}")
    
    def batch_add(self, items: List[Dict]) -> None:
        """批量添加向量"""
        if not items:
            return
        
        try:
            embeddings = []
            ids = []
            
            for item in items:
                node_id = item.get('node_id') or item.get('id')
                text = item.get('text', '')
                metadata = item.get('metadata', {})
                
                if node_id:
                    embedding = self.embed_text(text)
                    embeddings.append(embedding)
                    ids.append((node_id, metadata, text))
            
            if embeddings:
                embedding_array = self.np.array(embeddings, dtype=self.np.float32)
                self.index.add(embedding_array)
                
                # 更新映射
                for node_id, metadata, text in ids:
                    if node_id not in self.node_to_id:
                        internal_id = self.next_internal_id
                        self.id_to_node[internal_id] = node_id
                        self.node_to_id[node_id] = internal_id
                        self.metadatas[node_id] = {
                            **metadata,
                            "added_at": datetime.now().isoformat(),
                            "text_preview": text[:100] if text else ""
                        }
                        self.next_internal_id += 1
                
                print(f"[VectorStore] ✓ 批量添加完成: {len(ids)}个节点")
        
        except Exception as e:
            print(f"[VectorStore] ✗ 批量添加失败: {e}")
    
    def clear(self) -> None:
        """清空所有向量"""
        try:
            self.index = self.faiss.IndexFlatL2(self.dimension)
            self.id_to_node.clear()
            self.node_to_id.clear()
            self.metadatas.clear()
            self.next_internal_id = 0
            print("[VectorStore] ✓ 已清空所有向量")
        except Exception as e:
            print(f"[VectorStore] ✗ 清空失败: {e}")
    
    def health_check(self) -> bool:
        """检查FAISS是否可用"""
        try:
            # 测试基本操作
            test_vec = self.np.array([[0.0] * self.dimension], dtype=self.np.float32)
            self.index.add(test_vec)
            _, indices = self.index.search(test_vec, 1)
            # 回滚测试
            self.index = self.faiss.IndexFlatL2(self.dimension)
            print("[VectorStore] ✓ FAISS健康检查通过")
            return True
        except Exception as e:
            print(f"[VectorStore] ✗ FAISS健康检查失败: {e}")
            return False
    
    def save(self, path: str) -> None:
        """保存索引到磁盘"""
        try:
            self.faiss.write_index(self.index, path)
            # 也保存映射和元数据
            import json
            metadata_path = path + ".metadata"
            with open(metadata_path, 'w') as f:
                json.dump({
                    "id_to_node": {str(k): v for k, v in self.id_to_node.items()},
                    "node_to_id": self.node_to_id,
                    "metadatas": self.metadatas,
                    "next_internal_id": self.next_internal_id
                }, f)
            print(f"[VectorStore] ✓ 索引已保存: {path}")
        except Exception as e:
            print(f"[VectorStore] ✗ 保存失败: {e}")
    
    def load(self, path: str) -> None:
        """从磁盘加载索引"""
        try:
            self.index = self.faiss.read_index(path)
            # 也加载映射和元数据
            import json
            metadata_path = path + ".metadata"
            if os.path.exists(metadata_path):
                with open(metadata_path, 'r') as f:
                    data = json.load(f)
                    self.id_to_node = {int(k): v for k, v in data["id_to_node"].items()}
                    self.node_to_id = data["node_to_id"]
                    self.metadatas = data["metadatas"]
                    self.next_internal_id = data["next_internal_id"]
            print(f"[VectorStore] ✓ 索引已加载: {path}")
        except Exception as e:
            print(f"[VectorStore] ✗ 加载失败: {e}")


class InMemoryVectorStore(VectorStore):
    """
    纯内存向量存储 - 用于测试和轻量级场景
    
    特点：
    - 无依赖，仅使用标准库
    - 简单的向量相似度计算
    - 进程重启后数据丢失
    """
    
    def __init__(self):
        """初始化内存存储"""
        self.vectors: Dict[str, List[float]] = {}
        self.metadatas: Dict[str, Dict] = {}
        print("[VectorStore] ✓ 步内存向量存储已初始化（测试用）")
    
    def _simple_embed(self, text: str) -> List[float]:
        """简单的embedding - 仅用于测试"""
        # 非常简单的hash-based embedding
        import hashlib
        text = (text or "").lower()
        hash_val = int(hashlib.md5(text.encode()).hexdigest(), 16)
        # 生成固定长度的"伪向量"
        vector = []
        for i in range(384):
            vector.append(((hash_val >> i) & 1) * 2 - 1)
        return vector
    
    @staticmethod
    def _cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
        """计算两个向量的余弦相似度"""
        if not vec1 or not vec2:
            return 0.0
        
        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        magnitude1 = sum(a ** 2 for a in vec1) ** 0.5
        magnitude2 = sum(b ** 2 for b in vec2) ** 0.5
        
        if magnitude1 == 0 or magnitude2 == 0:
            return 0.0
        
        return dot_product / (magnitude1 * magnitude2)
    
    def add(self, node_id: str, text: str, metadata: Dict) -> None:
        """添加节点向量"""
        self.vectors[node_id] = self._simple_embed(text)
        self.metadatas[node_id] = metadata
        print(f"[VectorStore] ✓ 【内存】节点已添加: {node_id}")
    
    def search(self, query_text: str, top_k: int = 5, threshold: float = 0.7) -> List[Tuple]:
        """相似度搜索"""
        query_vec = self._simple_embed(query_text)
        
        scores = []
        for node_id, stored_vec in self.vectors.items():
            sim = self._cosine_similarity(query_vec, stored_vec)
            if sim >= threshold:
                scores.append((node_id, sim, self.metadatas[node_id]))
        
        # 按相似度排序，返回top_k
        scores.sort(key=lambda x: x[1], reverse=True)
        result = scores[:top_k]
        
        print(f"[VectorStore] ✓ 【内存】搜索完成: 结果={len(result)}")
        return result
    
    def delete(self, node_id: str) -> None:
        """删除向量"""
        self.vectors.pop(node_id, None)
        self.metadatas.pop(node_id, None)
        print(f"[VectorStore] ✓ 【内存】节点已删除: {node_id}")
    
    def update(self, node_id: str, text: str, metadata: Dict) -> None:
        """更新向量"""
        self.delete(node_id)
        self.add(node_id, text, metadata)
    
    def batch_add(self, items: List[Dict]) -> None:
        """批量添加"""
        for item in items:
            self.add(item['node_id'], item['text'], item['metadata'])
    
    def clear(self) -> None:
        """清空所有向量"""
        self.vectors.clear()
        self.metadatas.clear()
        print("[VectorStore] ✓ 【内存】已清空所有向量")
    
    def health_check(self) -> bool:
        """检查状态"""
        return True


def create_vector_store(store_type: str = "auto", **kwargs) -> VectorStore:
    """
    工厂函数 - 创建合适的向量存储
    
    Args:
        store_type: "faiss" | "chroma" | "memory" | "auto"（自动选择）
                   推荐: faiss（最快）> chroma（平衡） > memory（测试）
        **kwargs: 传递给存储类的参数
    
    Returns:
        VectorStore 实例
    """
    if store_type == "auto":
        # 自动选择优先级: FAISS > Chroma > InMemory
        try:
            store = FAISSVectorStore(**kwargs)
            if store.health_check():
                print("[VectorStore]  Auto选择: FAISS（高性能后端）")
                return store
        except ImportError:
            print("[VectorStore] ℹFAISS不可用，尝试Chroma...")
        except Exception as e:
            print(f"[VectorStore] FAISS初始化失败: {e}，尝试Chroma...")
        
        try:
            store = ChromaVectorStore(**kwargs)
            if store.health_check():
                print("[VectorStore]  Auto选择: Chroma（平衡后端）")
                return store
        except ImportError:
            print("[VectorStore] ℹ Chroma不可用，使用内存存储")
        
        print("[VectorStore]  Auto选择: InMemory（测试用）")
        return InMemoryVectorStore()
    
    elif store_type == "faiss":
        print("[VectorStore] 创建FAISS向量存储...")
        return FAISSVectorStore(**kwargs)
    
    elif store_type == "chroma":
        print("[VectorStore] 创建Chroma向量存储...")
        return ChromaVectorStore(**kwargs)
    
    elif store_type == "memory":
        print("[VectorStore] 创建InMemory向量存储...")
        return InMemoryVectorStore()
    
    else:
        raise ValueError(f"不支持的向量存储类型: {store_type}。有效选项: faiss, chroma, memory, auto")
