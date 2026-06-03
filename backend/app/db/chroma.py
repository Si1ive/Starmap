"""
ChromaDB 向量数据库连接封装

提供集合管理、向量存储和相似度搜索功能。
支持文本嵌入和元数据过滤。
"""

import hashlib
from typing import Any, Dict, List, Optional

import chromadb
from chromadb.config import Settings as ChromaSettings
from chromadb.api.types import EmbeddingFunction

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class ChromaConnectionError(Exception):
    """ChromaDB连接异常"""
    pass


class ChromaClient:
    """
    ChromaDB 客户端封装
    
    封装了集合管理和向量操作，支持：
    - 异步风格API（内部使用同步客户端）
    - 集合自动创建
    - 向量存储与检索
    - 元数据过滤
    - 文档去重
    """
    
    # 集合名称
    COLLECTION_PERSONS = "persons"
    COLLECTION_RELATIONS = "relations"
    COLLECTION_KNOWLEDGE = "knowledge"
    
    def __init__(self):
        self._client: Optional[chromadb.Client] = None
        self._host = settings.CHROMA_HOST
        self._port = settings.CHROMA_PORT
        self._collections: Dict[str, Any] = {}
        
    def connect(self) -> None:
        """
        建立ChromaDB连接
        
        创建HTTP客户端连接到ChromaDB服务。
        """
        try:
            self._client = chromadb.HttpClient(
                host=self._host,
                port=self._port,
                settings=ChromaSettings(
                    anonymized_telemetry=False
                )
            )
            # 验证连接
            self._client.heartbeat()
            logger.info("ChromaDB连接成功", host=self._host, port=self._port)
            
            # 初始化集合
            self._init_collections()
            
        except Exception as e:
            logger.error("ChromaDB连接失败", error=str(e), host=self._host, port=self._port)
            raise ChromaConnectionError(f"无法连接到ChromaDB: {e}")
    
    def _init_collections(self) -> None:
        """初始化默认集合"""
        for name in [
            self.COLLECTION_PERSONS,
            self.COLLECTION_RELATIONS,
            self.COLLECTION_KNOWLEDGE
        ]:
            try:
                self._collections[name] = self._client.get_or_create_collection(
                    name=name,
                    metadata={"description": f"StarMap {name} collection"}
                )
                logger.debug("集合已初始化", collection=name)
            except Exception as e:
                logger.error("集合初始化失败", collection=name, error=str(e))
    
    def close(self) -> None:
        """关闭连接"""
        self._client = None
        self._collections.clear()
        logger.info("ChromaDB连接已关闭")
    
    def health_check(self) -> bool:
        """
        健康检查
        
        Returns:
            bool: 连接正常返回True
        """
        if not self._client:
            return False
        try:
            self._client.heartbeat()
            return True
        except Exception:
            return False
    
    def _get_collection(self, name: str):
        """获取集合（自动创建）"""
        if name not in self._collections:
            self._collections[name] = self._client.get_or_create_collection(name=name)
        return self._collections[name]
    
    def _generate_id(self, text: str) -> str:
        """基于文本生成唯一ID"""
        return hashlib.md5(text.encode("utf-8")).hexdigest()
    
    # ========== 向量操作 ==========
    
    def add_documents(
        self,
        documents: List[str],
        metadatas: Optional[List[Dict[str, Any]]] = None,
        ids: Optional[List[str]] = None,
        collection_name: str = COLLECTION_KNOWLEDGE
    ) -> List[str]:
        """
        添加文档到向量库
        
        Args:
            documents: 文档文本列表
            metadatas: 元数据列表
            ids: 自定义ID列表
            collection_name: 目标集合
            
        Returns:
            List[str]: 文档ID列表
        """
        if not ids:
            ids = [self._generate_id(doc) for doc in documents]
        
        if not metadatas:
            metadatas = [{} for _ in documents]
        
        collection = self._get_collection(collection_name)
        
        try:
            collection.add(
                documents=documents,
                metadatas=metadatas,
                ids=ids
            )
            logger.info(
                "文档已添加到向量库",
                count=len(documents),
                collection=collection_name
            )
            return ids
        except Exception as e:
            logger.error("添加文档失败", error=str(e), collection=collection_name)
            raise
    
    def search(
        self,
        query: str,
        n_results: int = 5,
        collection_name: str = COLLECTION_KNOWLEDGE,
        filter_metadata: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        向量相似度搜索
        
        Args:
            query: 查询文本
            n_results: 返回结果数量
            collection_name: 目标集合
            filter_metadata: 元数据过滤条件
            
        Returns:
            List[Dict]: 搜索结果列表，包含文档、元数据和距离
        """
        collection = self._get_collection(collection_name)
        
        try:
            results = collection.query(
                query_texts=[query],
                n_results=n_results,
                where=filter_metadata
            )
            
            # 格式化结果
            formatted = []
            for i in range(len(results["ids"][0])):
                formatted.append({
                    "id": results["ids"][0][i],
                    "document": results["documents"][0][i],
                    "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                    "distance": results["distances"][0][i] if results["distances"] else None
                })
            
            return formatted
            
        except Exception as e:
            logger.error("向量搜索失败", error=str(e), query=query)
            return []
    
    def delete_documents(
        self,
        ids: List[str],
        collection_name: str = COLLECTION_KNOWLEDGE
    ) -> bool:
        """
        删除文档
        
        Args:
            ids: 文档ID列表
            collection_name: 目标集合
            
        Returns:
            bool: 删除成功返回True
        """
        collection = self._get_collection(collection_name)
        
        try:
            collection.delete(ids=ids)
            logger.info("文档已删除", count=len(ids), collection=collection_name)
            return True
        except Exception as e:
            logger.error("删除文档失败", error=str(e))
            return False
    
    def get_document(
        self,
        doc_id: str,
        collection_name: str = COLLECTION_KNOWLEDGE
    ) -> Optional[Dict[str, Any]]:
        """
        获取指定文档
        
        Args:
            doc_id: 文档ID
            collection_name: 目标集合
            
        Returns:
            Dict: 文档信息
        """
        collection = self._get_collection(collection_name)
        
        try:
            result = collection.get(ids=[doc_id])
            if result["ids"]:
                return {
                    "id": result["ids"][0],
                    "document": result["documents"][0],
                    "metadata": result["metadatas"][0] if result["metadatas"] else {}
                }
        except Exception as e:
            logger.error("获取文档失败", error=str(e), doc_id=doc_id)
        
        return None
    
    def count(self, collection_name: str = COLLECTION_KNOWLEDGE) -> int:
        """
        获取集合文档数量
        
        Args:
            collection_name: 目标集合
            
        Returns:
            int: 文档数量
        """
        collection = self._get_collection(collection_name)
        return collection.count()
    
    # ========== 人物专用操作 ==========
    
    def add_person_embedding(
        self,
        person_id: str,
        name: str,
        description: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        添加人物向量嵌入
        
        Args:
            person_id: 人物ID
            name: 人物名称
            description: 人物描述
            metadata: 额外元数据
            
        Returns:
            str: 文档ID
        """
        doc_text = f"{name}。{description}"
        
        meta = {
            "person_id": person_id,
            "name": name,
            "type": "person"
        }
        if metadata:
            meta.update(metadata)
        
        return self.add_documents(
            documents=[doc_text],
            metadatas=[meta],
            ids=[person_id],
            collection_name=self.COLLECTION_PERSONS
        )[0]
    
    def search_similar_persons(
        self,
        query: str,
        n_results: int = 5,
        category: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        搜索相似人物
        
        Args:
            query: 查询文本
            n_results: 返回数量
            category: 分类过滤
            
        Returns:
            List[Dict]: 相似人物列表
        """
        filter_meta = {"type": "person"}
        if category:
            filter_meta["category"] = category
        
        return self.search(
            query=query,
            n_results=n_results,
            collection_name=self.COLLECTION_PERSONS,
            filter_metadata=filter_meta
        )
    
    # ========== 知识库操作 ==========
    
    def add_knowledge(
        self,
        content: str,
        source: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        添加知识到向量库
        
        Args:
            content: 知识内容
            source: 来源
            metadata: 元数据
            
        Returns:
            str: 文档ID
        """
        meta = {"source": source, "type": "knowledge"}
        if metadata:
            meta.update(metadata)
        
        doc_id = self._generate_id(f"{source}:{content[:100]}")
        
        return self.add_documents(
            documents=[content],
            metadatas=[meta],
            ids=[doc_id],
            collection_name=self.COLLECTION_KNOWLEDGE
        )[0]
    
    def search_knowledge(
        self,
        query: str,
        n_results: int = 3,
        source: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        搜索相关知识
        
        Args:
            query: 查询问题
            n_results: 返回数量
            source: 来源过滤
            
        Returns:
            List[Dict]: 相关知识列表
        """
        filter_meta = {"type": "knowledge"}
        if source:
            filter_meta["source"] = source
        
        return self.search(
            query=query,
            n_results=n_results,
            collection_name=self.COLLECTION_KNOWLEDGE,
            filter_metadata=filter_meta
        )


# 全局客户端实例
chroma_client = ChromaClient()


def get_chroma_client() -> ChromaClient:
    """
    获取ChromaDB客户端
    
    Returns:
        ChromaClient: 已连接的客户端实例
    """
    if not chroma_client._client:
        chroma_client.connect()
    return chroma_client
