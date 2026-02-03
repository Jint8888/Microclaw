"""Enhanced Memory System Integration Module.

This module provides an EnhancedMemory class that extends the existing Memory class
with hybrid retrieval capabilities (FTS5 + vector search) and embedding caching.

Usage:
    # Use as drop-in replacement for Memory
    from python.helpers.memory_enhanced import EnhancedMemory
    
    memory = await EnhancedMemory.get(agent, enable_hybrid=True)
    results = await memory.hybrid_search(query, limit=10)
"""

import sqlite3
import os
from typing import Any, Dict, List, Optional
from langchain_core.documents import Document

from python.helpers import files
from python.helpers.memory import Memory, MyFaiss, get_agent_memory_subdir, abs_db_dir
from python.helpers.memory_cache import EmbeddingCache
from python.helpers.memory_fts import FTS5Manager
from python.helpers.memory_sqlite_vec import VectorStore, SQLITE_VEC_AVAILABLE
from python.helpers.memory_hybrid import HybridRetriever
from python.helpers.log import LogItem
from agent import Agent
import models


class EnhancedMemory(Memory):
    """Enhanced Memory with hybrid retrieval support.
    
    This class extends the base Memory class with:
    - FTS5 full-text search indexing
    - Hybrid search (vector + keyword with RRF fusion)
    - Embedding caching for performance
    - Optional sqlite-vec backend
    
    Attributes:
        fts_manager: FTS5Manager for full-text search
        hybrid_retriever: HybridRetriever for combined search
        embedding_cache: EmbeddingCache for performance
    """
    
    # Class-level cache for enhanced features
    _fts_index: Dict[str, FTS5Manager] = {}
    _hybrid_index: Dict[str, HybridRetriever] = {}
    _cache_index: Dict[str, EmbeddingCache] = {}
    
    def __init__(
        self,
        db: MyFaiss,
        memory_subdir: str,
        fts_manager: Optional[FTS5Manager] = None,
        hybrid_retriever: Optional[HybridRetriever] = None,
        embedding_cache: Optional[EmbeddingCache] = None,
    ):
        """Initialize EnhancedMemory.
        
        Args:
            db: FAISS database instance
            memory_subdir: Memory subdirectory path
            fts_manager: Optional FTS5Manager for full-text search
            hybrid_retriever: Optional HybridRetriever for hybrid search
            embedding_cache: Optional EmbeddingCache for caching
        """
        super().__init__(db, memory_subdir)
        self.fts_manager = fts_manager
        self.hybrid_retriever = hybrid_retriever
        self.embedding_cache = embedding_cache
    
    @staticmethod
    async def get(
        agent: Agent,
        enable_hybrid: bool = True,
        enable_cache: bool = True,
        cache_size: int = 1000,
    ) -> "EnhancedMemory":
        """Get or create an EnhancedMemory instance.
        
        Args:
            agent: Agent instance
            enable_hybrid: Whether to enable hybrid search (FTS5 + vector)
            enable_cache: Whether to enable embedding caching
            cache_size: Maximum embeddings to cache
            
        Returns:
            EnhancedMemory instance
        """
        memory_subdir = get_agent_memory_subdir(agent)
        
        # Get base memory using parent class
        base_memory = await Memory.get(agent)
        
        # Initialize enhanced features
        fts_manager = None
        hybrid_retriever = None
        embedding_cache = None
        
        if enable_hybrid:
            fts_manager = await EnhancedMemory._get_fts_manager(memory_subdir)
            
            # Create hybrid retriever if sqlite-vec is available
            if SQLITE_VEC_AVAILABLE and fts_manager:
                hybrid_retriever = await EnhancedMemory._get_hybrid_retriever(
                    memory_subdir, fts_manager, agent.config.embeddings_model
                )
        
        if enable_cache:
            embedding_cache = await EnhancedMemory._get_embedding_cache(
                memory_subdir, agent.config.embeddings_model, cache_size
            )
        
        return EnhancedMemory(
            db=base_memory.db,
            memory_subdir=memory_subdir,
            fts_manager=fts_manager,
            hybrid_retriever=hybrid_retriever,
            embedding_cache=embedding_cache,
        )
    
    @staticmethod
    async def _get_fts_manager(memory_subdir: str) -> Optional[FTS5Manager]:
        """Get or create FTS5Manager for the given memory subdir."""
        if memory_subdir in EnhancedMemory._fts_index:
            return EnhancedMemory._fts_index[memory_subdir]
        
        try:
            db_dir = abs_db_dir(memory_subdir)
            os.makedirs(db_dir, exist_ok=True)
            fts_db_path = os.path.join(db_dir, "fts.db")
            
            conn = sqlite3.connect(fts_db_path)
            fts_manager = FTS5Manager(conn, table_name="memory_fts")
            fts_manager.create_index()
            
            EnhancedMemory._fts_index[memory_subdir] = fts_manager
            return fts_manager
        except Exception as e:
            from python.helpers.print_style import PrintStyle
            PrintStyle.error(f"Failed to initialize FTS5: {e}")
            return None
    
    @staticmethod
    async def _get_hybrid_retriever(
        memory_subdir: str,
        fts_manager: FTS5Manager,
        model_config: models.ModelConfig,
    ) -> Optional[HybridRetriever]:
        """Get or create HybridRetriever for the given memory subdir."""
        if memory_subdir in EnhancedMemory._hybrid_index:
            return EnhancedMemory._hybrid_index[memory_subdir]
        
        if not SQLITE_VEC_AVAILABLE:
            return None
        
        try:
            db_dir = abs_db_dir(memory_subdir)
            vec_db_path = os.path.join(db_dir, "vec.db")
            
            conn = sqlite3.connect(vec_db_path)
            
            # Get embedding dimensions from model
            embeddings_model = models.get_embedding_model(
                model_config.provider,
                model_config.name,
                **model_config.build_kwargs(),
            )
            sample_embedding = embeddings_model.embed_query("test")
            dimensions = len(sample_embedding)
            
            vec_store = VectorStore(conn, dimensions=dimensions, table_name="memory_vec")
            vec_store.create_index()
            
            # Create embedding function wrapper
            def embed_fn(text: str) -> List[float]:
                return embeddings_model.embed_query(text)
            
            hybrid = HybridRetriever(fts_manager, vec_store, embed_fn=embed_fn)
            EnhancedMemory._hybrid_index[memory_subdir] = hybrid
            return hybrid
        except Exception as e:
            from python.helpers.print_style import PrintStyle
            PrintStyle.error(f"Failed to initialize HybridRetriever: {e}")
            return None
    
    @staticmethod
    async def _get_embedding_cache(
        memory_subdir: str,
        model_config: models.ModelConfig,
        cache_size: int,
    ) -> Optional[EmbeddingCache]:
        """Get or create EmbeddingCache for the given memory subdir."""
        if memory_subdir in EnhancedMemory._cache_index:
            return EnhancedMemory._cache_index[memory_subdir]
        
        try:
            embeddings_model = models.get_embedding_model(
                model_config.provider,
                model_config.name,
                **model_config.build_kwargs(),
            )
            
            def embed_fn(text: str) -> List[float]:
                return embeddings_model.embed_query(text)
            
            cache = EmbeddingCache(embed_fn, maxsize=cache_size)
            EnhancedMemory._cache_index[memory_subdir] = cache
            return cache
        except Exception as e:
            from python.helpers.print_style import PrintStyle
            PrintStyle.error(f"Failed to initialize EmbeddingCache: {e}")
            return None
    
    async def hybrid_search(
        self,
        query: str,
        limit: int = 10,
        fts_weight: float = 0.3,
        vec_weight: float = 0.7,
        fusion_method: str = "rrf",
        filter: str = "",
    ) -> List[Document]:
        """Perform hybrid search combining FTS5 and vector similarity.
        
        Args:
            query: Search query text
            limit: Maximum results to return
            fts_weight: Weight for FTS5 results (0-1)
            vec_weight: Weight for vector results (0-1)
            fusion_method: Fusion method ("weighted" or "rrf")
            filter: Optional filter expression
            
        Returns:
            List of matching Documents
        """
        if self.hybrid_retriever is None:
            # Fall back to standard vector search
            return await self.search_similarity_threshold(
                query, limit=limit, threshold=0.0, filter=filter
            )
        
        try:
            # Get embedding for query
            query_embedding = None
            if self.embedding_cache:
                query_embedding = self.embedding_cache.get_embedding(query)
            
            # Perform hybrid search
            results = self.hybrid_retriever.search(
                query=query,
                query_embedding=query_embedding,
                k=limit,
                fts_weight=fts_weight,
                vec_weight=vec_weight,
                fusion_method=fusion_method,
            )
            
            # Convert results to Documents
            documents = []
            for result in results:
                rowid = result.get("rowid")
                if rowid and self.hybrid_retriever:
                    doc_data = self.hybrid_retriever.get_content(rowid)
                    if doc_data:
                        doc = Document(
                            page_content=doc_data.get("content", ""),
                            metadata={
                                "id": str(rowid),
                                "score": result.get("score", 0),
                                "fts_score": result.get("fts_score", 0),
                                "vec_score": result.get("vec_score", 0),
                                "source": result.get("source", []),
                            }
                        )
                        documents.append(doc)
            
            return documents
        except Exception as e:
            from python.helpers.print_style import PrintStyle
            PrintStyle.error(f"Hybrid search failed, falling back to vector: {e}")
            return await self.search_similarity_threshold(
                query, limit=limit, threshold=0.0, filter=filter
            )
    
    async def fts_search(
        self,
        query: str,
        limit: int = 10,
    ) -> List[Document]:
        """Perform FTS5-only search.
        
        Args:
            query: Search query text
            limit: Maximum results to return
            
        Returns:
            List of matching Documents
        """
        if self.fts_manager is None:
            return []
        
        try:
            results = self.fts_manager.search(query, limit=limit)
            
            documents = []
            for result in results:
                doc = Document(
                    page_content=result.get("content", ""),
                    metadata={
                        "id": str(result.get("rowid")),
                        "rank": result.get("rank", 0),
                    }
                )
                documents.append(doc)
            
            return documents
        except Exception as e:
            from python.helpers.print_style import PrintStyle
            PrintStyle.error(f"FTS search failed: {e}")
            return []
    
    async def insert_documents(self, docs: List[Document]) -> List[str]:
        """Insert documents into both FAISS and FTS5/hybrid indexes.
        
        Args:
            docs: List of Documents to insert
            
        Returns:
            List of document IDs
        """
        # Insert into FAISS (parent method)
        ids = await super().insert_documents(docs)
        
        # Also insert into FTS5 if available
        if self.fts_manager or self.hybrid_retriever:
            try:
                for doc, doc_id in zip(docs, ids):
                    rowid = hash(doc_id) & 0x7FFFFFFF  # Convert to positive int
                    content = doc.page_content
                    metadata = str(doc.metadata)
                    
                    if self.hybrid_retriever:
                        # Get embedding
                        embedding = None
                        if self.embedding_cache:
                            embedding = self.embedding_cache.get_embedding(content)
                        
                        if embedding:
                            self.hybrid_retriever.insert(
                                rowid=rowid,
                                content=content,
                                embedding=embedding,
                                metadata=metadata,
                            )
                    elif self.fts_manager:
                        self.fts_manager.insert(content, metadata=metadata, rowid=rowid)
            except Exception as e:
                from python.helpers.print_style import PrintStyle
                PrintStyle.error(f"Failed to insert into FTS5/hybrid index: {e}")
        
        return ids
    
    async def delete_documents_by_ids(self, ids: List[str]) -> List[Document]:
        """Delete documents from both FAISS and FTS5/hybrid indexes.
        
        Args:
            ids: List of document IDs to delete
            
        Returns:
            List of deleted Documents
        """
        # Delete from FAISS (parent method)
        deleted = await super().delete_documents_by_ids(ids)
        
        # Also delete from FTS5/hybrid if available
        if self.hybrid_retriever:
            try:
                for doc_id in ids:
                    rowid = hash(doc_id) & 0x7FFFFFFF
                    self.hybrid_retriever.delete(rowid)
            except Exception as e:
                from python.helpers.print_style import PrintStyle
                PrintStyle.error(f"Failed to delete from hybrid index: {e}")
        elif self.fts_manager:
            try:
                for doc_id in ids:
                    rowid = hash(doc_id) & 0x7FFFFFFF
                    self.fts_manager.delete(rowid)
            except Exception as e:
                from python.helpers.print_style import PrintStyle
                PrintStyle.error(f"Failed to delete from FTS5 index: {e}")
        
        return deleted
    
    def get_cache_info(self) -> Optional[Dict[str, int]]:
        """Get embedding cache statistics.
        
        Returns:
            Cache info dict or None if caching disabled
        """
        if self.embedding_cache:
            return self.embedding_cache.cache_info()
        return None
    
    def clear_cache(self) -> None:
        """Clear the embedding cache."""
        if self.embedding_cache:
            self.embedding_cache.cache_clear()
    
    @property
    def is_hybrid_enabled(self) -> bool:
        """Check if hybrid search is enabled."""
        return self.hybrid_retriever is not None
    
    @property
    def is_fts_enabled(self) -> bool:
        """Check if FTS5 is enabled."""
        return self.fts_manager is not None
    
    @property
    def is_cache_enabled(self) -> bool:
        """Check if embedding caching is enabled."""
        return self.embedding_cache is not None


# Convenience function for migration
async def upgrade_to_enhanced(agent: Agent) -> EnhancedMemory:
    """Upgrade existing Memory to EnhancedMemory.
    
    This function helps migrate existing memory data to the enhanced system.
    
    Args:
        agent: Agent instance
        
    Returns:
        EnhancedMemory instance with migrated data
    """
    enhanced = await EnhancedMemory.get(agent, enable_hybrid=True, enable_cache=True)
    
    # If hybrid is enabled, sync existing documents to FTS5
    if enhanced.is_hybrid_enabled and enhanced.hybrid_retriever:
        from python.helpers.print_style import PrintStyle
        PrintStyle.standard("Syncing existing memories to FTS5 index...")
        
        # Get all existing documents
        all_docs = enhanced.db.get_all_docs()
        
        for doc_id, doc in all_docs.items():
            try:
                rowid = hash(doc_id) & 0x7FFFFFFF
                content = doc.page_content
                metadata = str(doc.metadata)
                
                # Get embedding
                embedding = None
                if enhanced.embedding_cache:
                    embedding = enhanced.embedding_cache.get_embedding(content)
                
                if embedding:
                    enhanced.hybrid_retriever.insert(
                        rowid=rowid,
                        content=content,
                        embedding=embedding,
                        metadata=metadata,
                    )
            except Exception as e:
                PrintStyle.error(f"Failed to sync document {doc_id}: {e}")
        
        PrintStyle.standard("FTS5 sync complete!")
    
    return enhanced
