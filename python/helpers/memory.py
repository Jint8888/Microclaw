"""Memory Module - Enhanced Memory System.

This module provides a unified memory system with:
- FTS5 full-text search
- sqlite-vec vector storage
- Hybrid search with RRF fusion
- Embedding caching

The Memory class is now an alias to EnhancedMemory.
Legacy FAISS-based code has been moved to memory_legacy.py.
"""

import os
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional
from langchain_core.documents import Document
from enum import Enum

from python.helpers import guids, files
from python.helpers.print_style import PrintStyle
from python.helpers import knowledge_import
from python.helpers.log import Log, LogItem
from agent import Agent, AgentContext
import models
import logging

# Import new memory modules
from python.helpers.memory_cache import EmbeddingCache
from python.helpers.memory_fts import FTS5Manager
from python.helpers.memory_sqlite_vec import VectorStore, SQLITE_VEC_AVAILABLE
from python.helpers.memory_hybrid import HybridRetriever

# Suppress verbose logging
logging.getLogger("langchain_core.vectorstores.base").setLevel(logging.ERROR)


class MemoryArea(Enum):
    """Memory area enumeration."""
    MAIN = "main"
    FRAGMENTS = "fragments"
    SOLUTIONS = "solutions"
    INSTRUMENTS = "instruments"


class Memory:
    """Enhanced Memory System.
    
    This class provides a unified interface for memory operations using:
    - FTS5 for full-text search
    - sqlite-vec for vector similarity search
    - Hybrid retrieval with RRF fusion
    - Embedding caching for performance
    
    All operations are performed on SQLite databases for simplicity and
    atomic consistency.
    """
    
    # Backward compatibility alias
    Area = MemoryArea
    
    # Class-level indexes
    _fts_index: Dict[str, FTS5Manager] = {}
    _vec_index: Dict[str, VectorStore] = {}
    _hybrid_index: Dict[str, HybridRetriever] = {}
    _cache_index: Dict[str, EmbeddingCache] = {}
    _embeddings_model_cache: Dict[str, Any] = {}
    
    def __init__(
        self,
        memory_subdir: str,
        fts_manager: Optional[FTS5Manager] = None,
        vector_store: Optional[VectorStore] = None,
        hybrid_retriever: Optional[HybridRetriever] = None,
        embedding_cache: Optional[EmbeddingCache] = None,
        embeddings_model: Optional[Any] = None,
    ):
        """Initialize Memory instance.
        
        Args:
            memory_subdir: Memory subdirectory path
            fts_manager: FTS5Manager for full-text search
            vector_store: VectorStore for vector similarity
            hybrid_retriever: HybridRetriever for combined search
            embedding_cache: EmbeddingCache for caching
            embeddings_model: Embedding model for generating vectors
        """
        self.memory_subdir = memory_subdir
        self.fts_manager = fts_manager
        self.vector_store = vector_store
        self.hybrid_retriever = hybrid_retriever
        self.embedding_cache = embedding_cache
        self._embeddings_model = embeddings_model
        self._doc_store: Dict[str, Document] = {}  # In-memory document store
        self._id_to_rowid: Dict[str, int] = {}  # Map doc_id to rowid
    
    @staticmethod
    async def get(agent: Agent) -> "Memory":
        """Get or create a Memory instance for the agent.
        
        Args:
            agent: Agent instance
            
        Returns:
            Memory instance
        """
        memory_subdir = get_agent_memory_subdir(agent)
        
        log_item = agent.context.log.log(
            type="util",
            heading=f"Initializing Memory in '/{memory_subdir}'",
        )
        
        memory = await Memory._initialize(
            memory_subdir=memory_subdir,
            model_config=agent.config.embeddings_model,
            log_item=log_item,
        )
        
        # Preload knowledge
        knowledge_subdirs = get_knowledge_subdirs_by_memory_subdir(
            memory_subdir, agent.config.knowledge_subdirs or []
        )
        if knowledge_subdirs:
            await memory.preload_knowledge(log_item, knowledge_subdirs, memory_subdir)
        
        return memory
    
    @staticmethod
    async def get_by_subdir(
        memory_subdir: str,
        log_item: Optional[LogItem] = None,
        preload_knowledge: bool = True,
    ) -> "Memory":
        """Get Memory by subdirectory path.
        
        Args:
            memory_subdir: Memory subdirectory path
            log_item: Optional log item for progress
            preload_knowledge: Whether to preload knowledge
            
        Returns:
            Memory instance
        """
        import initialize
        agent_config = initialize.initialize_agent()
        
        memory = await Memory._initialize(
            memory_subdir=memory_subdir,
            model_config=agent_config.embeddings_model,
            log_item=log_item,
        )
        
        if preload_knowledge:
            knowledge_subdirs = get_knowledge_subdirs_by_memory_subdir(
                memory_subdir, agent_config.knowledge_subdirs or []
            )
            if knowledge_subdirs:
                await memory.preload_knowledge(log_item, knowledge_subdirs, memory_subdir)
        
        return memory
    
    @staticmethod
    async def reload(agent: Agent) -> "Memory":
        """Reload memory for the agent, clearing cached state.
        
        Args:
            agent: Agent instance
            
        Returns:
            Fresh Memory instance
        """
        memory_subdir = get_agent_memory_subdir(agent)
        
        # Clear cached instances
        if memory_subdir in Memory._fts_index:
            del Memory._fts_index[memory_subdir]
        if memory_subdir in Memory._vec_index:
            del Memory._vec_index[memory_subdir]
        if memory_subdir in Memory._hybrid_index:
            del Memory._hybrid_index[memory_subdir]
        
        return await Memory.get(agent)
    
    @staticmethod
    async def _initialize(
        memory_subdir: str,
        model_config: models.ModelConfig,
        log_item: Optional[LogItem] = None,
    ) -> "Memory":
        """Initialize memory components.
        
        Args:
            memory_subdir: Memory subdirectory
            model_config: Embedding model configuration
            log_item: Optional log item for progress
            
        Returns:
            Initialized Memory instance
        """
        if log_item:
            log_item.stream(progress="\nInitializing Enhanced Memory System")
        
        db_dir = abs_db_dir(memory_subdir)
        os.makedirs(db_dir, exist_ok=True)
        
        # Initialize embeddings model
        embeddings_model = Memory._get_embeddings_model(model_config)
        
        # Get embedding dimensions
        sample_embedding = embeddings_model.embed_query("test")
        dimensions = len(sample_embedding)
        
        # Initialize FTS5
        fts_manager = Memory._get_fts_manager(memory_subdir, db_dir)
        
        # Initialize vector store
        vector_store = Memory._get_vector_store(memory_subdir, db_dir, dimensions)
        
        # Initialize hybrid retriever
        hybrid_retriever = None
        if fts_manager and vector_store:
            def embed_fn(text: str) -> List[float]:
                return embeddings_model.embed_query(text)
            
            hybrid_retriever = HybridRetriever(fts_manager, vector_store, embed_fn=embed_fn)
            Memory._hybrid_index[memory_subdir] = hybrid_retriever
        
        # Initialize embedding cache
        cache_enabled = os.getenv("MEMORY_CACHE_ENABLED", "true").lower() in ("true", "1", "yes")
        cache_size = int(os.getenv("MEMORY_CACHE_SIZE", "1000"))
        
        embedding_cache = None
        if cache_enabled:
            def embed_fn_cache(text: str) -> List[float]:
                return embeddings_model.embed_query(text)
            
            embedding_cache = EmbeddingCache(embed_fn_cache, maxsize=cache_size)
            Memory._cache_index[memory_subdir] = embedding_cache
        
        PrintStyle.standard("✓ Enhanced Memory System initialized (FTS5 + sqlite-vec)")
        
        return Memory(
            memory_subdir=memory_subdir,
            fts_manager=fts_manager,
            vector_store=vector_store,
            hybrid_retriever=hybrid_retriever,
            embedding_cache=embedding_cache,
            embeddings_model=embeddings_model,
        )
    
    @staticmethod
    def _get_embeddings_model(model_config: models.ModelConfig) -> Any:
        """Get or create embeddings model."""
        model_key = f"{model_config.provider}_{model_config.name}"
        if model_key not in Memory._embeddings_model_cache:
            Memory._embeddings_model_cache[model_key] = models.get_embedding_model(
                model_config.provider,
                model_config.name,
                **model_config.build_kwargs(),
            )
        return Memory._embeddings_model_cache[model_key]
    
    @staticmethod
    def _get_fts_manager(memory_subdir: str, db_dir: str) -> Optional[FTS5Manager]:
        """Get or create FTS5Manager."""
        if memory_subdir in Memory._fts_index:
            return Memory._fts_index[memory_subdir]
        
        try:
            fts_db_path = os.path.join(db_dir, "memory.db")
            conn = sqlite3.connect(fts_db_path, check_same_thread=False)
            fts_manager = FTS5Manager(conn, table_name="memory_fts")
            fts_manager.create_index()
            Memory._fts_index[memory_subdir] = fts_manager
            return fts_manager
        except Exception as e:
            PrintStyle.error(f"Failed to initialize FTS5: {e}")
            return None
    
    @staticmethod
    def _get_vector_store(memory_subdir: str, db_dir: str, dimensions: int) -> Optional[VectorStore]:
        """Get or create VectorStore."""
        if memory_subdir in Memory._vec_index:
            return Memory._vec_index[memory_subdir]
        
        if not SQLITE_VEC_AVAILABLE:
            PrintStyle.error("sqlite-vec not available, vector search disabled")
            return None
        
        try:
            vec_db_path = os.path.join(db_dir, "memory.db")
            conn = sqlite3.connect(vec_db_path, check_same_thread=False)
            vec_store = VectorStore(conn, dimensions=dimensions, table_name="memory_vec")
            vec_store.create_index()
            Memory._vec_index[memory_subdir] = vec_store
            return vec_store
        except Exception as e:
            PrintStyle.error(f"Failed to initialize VectorStore: {e}")
            return None
    
    # ========================================
    # Search Methods
    # ========================================
    
    async def search_similarity_threshold(
        self,
        query: str,
        limit: int,
        threshold: float,
        filter: str = ""
    ) -> List[Document]:
        """Search for similar documents using hybrid retrieval.
        
        Args:
            query: Search query text
            limit: Maximum results to return
            threshold: Minimum similarity threshold (0-1)
            filter: Optional filter expression
            
        Returns:
            List of matching Documents
        """
        if not query:
            return []
        
        # Generate embedding
        query_embedding = None
        if self.embedding_cache:
            query_embedding = self.embedding_cache.get_embedding(query)
        elif self._embeddings_model:
            query_embedding = self._embeddings_model.embed_query(query)
        
        # Use hybrid search if available
        if self.hybrid_retriever and query_embedding:
            results = self.hybrid_retriever.search(
                query=query,
                query_embedding=query_embedding,
                k=limit * 2,  # Get more for filtering
                fusion_method="rrf",
            )
            
            # Convert to Documents and filter by threshold
            documents = []
            for result in results:
                rowid = result.get("rowid")
                score = result.get("score", 0)
                
                # Score is 0-1 from RRF, higher is better
                if score >= threshold:
                    doc_id = self._rowid_to_id(rowid)
                    if doc_id and doc_id in self._doc_store:
                        doc = self._doc_store[doc_id]
                        # Apply filter if specified
                        if not filter or self._apply_filter(doc.metadata, filter):
                            documents.append(doc)
                
                if len(documents) >= limit:
                    break
            
            return documents
        
        # Fallback to FTS-only search
        if self.fts_manager:
            fts_results = self.fts_manager.search(query, limit=limit)
            documents = []
            for result in fts_results:
                rowid = result.get("rowid")
                doc_id = self._rowid_to_id(rowid)
                if doc_id and doc_id in self._doc_store:
                    doc = self._doc_store[doc_id]
                    if not filter or self._apply_filter(doc.metadata, filter):
                        documents.append(doc)
            return documents
        
        return []
    
    async def delete_documents_by_query(
        self,
        query: str,
        threshold: float,
        filter: str = ""
    ) -> List[Document]:
        """Delete documents matching a query.
        
        Args:
            query: Search query
            threshold: Similarity threshold
            filter: Optional filter expression
            
        Returns:
            List of deleted Documents
        """
        docs = await self.search_similarity_threshold(query, limit=100, threshold=threshold, filter=filter)
        
        if docs:
            ids = [doc.metadata.get("id") for doc in docs if doc.metadata.get("id")]
            await self.delete_documents_by_ids(ids)
        
        return docs
    
    async def delete_documents_by_ids(self, ids: List[str]) -> List[Document]:
        """Delete documents by their IDs.
        
        Args:
            ids: List of document IDs to delete
            
        Returns:
            List of deleted Documents
        """
        deleted = []
        
        for doc_id in ids:
            if doc_id in self._doc_store:
                doc = self._doc_store[doc_id]
                deleted.append(doc)
                
                # Delete from indexes
                rowid = self._id_to_rowid.get(doc_id)
                if rowid:
                    if self.hybrid_retriever:
                        self.hybrid_retriever.delete(rowid)
                    elif self.fts_manager:
                        self.fts_manager.delete(rowid)
                    if self.vector_store:
                        self.vector_store.delete(rowid)
                    del self._id_to_rowid[doc_id]
                
                del self._doc_store[doc_id]
        
        return deleted
    
    async def insert_text(self, text: str, metadata: Dict = {}) -> str:
        """Insert text as a document.
        
        Args:
            text: Text content
            metadata: Optional metadata
            
        Returns:
            Document ID
        """
        doc = Document(page_content=text, metadata=metadata)
        ids = await self.insert_documents([doc])
        return ids[0]
    
    async def insert_documents(self, docs: List[Document]) -> List[str]:
        """Insert documents into memory.
        
        Args:
            docs: List of Documents to insert
            
        Returns:
            List of document IDs
        """
        ids = []
        timestamp = self.get_timestamp()
        
        for doc in docs:
            doc_id = self._generate_doc_id()
            rowid = hash(doc_id) & 0x7FFFFFFF  # Positive int
            
            # Set metadata
            doc.metadata["id"] = doc_id
            doc.metadata["timestamp"] = timestamp
            if not doc.metadata.get("area"):
                doc.metadata["area"] = MemoryArea.MAIN.value
            
            # Store document
            self._doc_store[doc_id] = doc
            self._id_to_rowid[doc_id] = rowid
            
            # Generate embedding
            embedding = None
            if self.embedding_cache:
                embedding = self.embedding_cache.get_embedding(doc.page_content)
            elif self._embeddings_model:
                embedding = self._embeddings_model.embed_query(doc.page_content)
            
            # Insert into indexes
            if self.hybrid_retriever and embedding:
                self.hybrid_retriever.insert(
                    rowid=rowid,
                    content=doc.page_content,
                    embedding=embedding,
                    metadata=str(doc.metadata),
                )
            else:
                if self.fts_manager:
                    self.fts_manager.insert(doc.page_content, metadata=str(doc.metadata), rowid=rowid)
                if self.vector_store and embedding:
                    self.vector_store.insert(rowid, embedding)
            
            ids.append(doc_id)
        
        return ids
    
    async def update_documents(self, docs: List[Document]) -> List[str]:
        """Update existing documents.
        
        Args:
            docs: List of Documents to update
            
        Returns:
            List of document IDs
        """
        ids = [doc.metadata.get("id") for doc in docs if doc.metadata.get("id")]
        await self.delete_documents_by_ids(ids)
        return await self.insert_documents(docs)
    
    def get_document_by_id(self, doc_id: str) -> Optional[Document]:
        """Get a document by its ID.
        
        Args:
            doc_id: Document ID
            
        Returns:
            Document if found, None otherwise
        """
        return self._doc_store.get(doc_id)
    
    def get_all_docs(self) -> Dict[str, Document]:
        """Get all stored documents.
        
        Returns:
            Dictionary of doc_id -> Document
        """
        return self._doc_store.copy()
    
    # ========================================
    # Knowledge Preloading
    # ========================================
    
    async def preload_knowledge(
        self,
        log_item: Optional[LogItem],
        kn_dirs: List[str],
        memory_subdir: str
    ) -> None:
        """Preload knowledge from directories.
        
        Args:
            log_item: Optional log item for progress
            kn_dirs: List of knowledge directories
            memory_subdir: Memory subdirectory
        """
        if log_item:
            log_item.update(heading="Preloading knowledge...")
        
        db_dir = abs_db_dir(memory_subdir)
        index_path = os.path.join(db_dir, "knowledge_import.json")
        
        # Load existing index
        import json
        index: Dict[str, knowledge_import.KnowledgeImport] = {}
        if os.path.exists(index_path):
            with open(index_path, "r") as f:
                index = json.load(f)
        
        # Load knowledge folders
        index = self._preload_knowledge_folders(log_item, kn_dirs, index)
        
        # Process changes
        for file in index:
            if index[file]["state"] in ["changed", "removed"] and index[file].get("ids", []):
                await self.delete_documents_by_ids(index[file]["ids"])
            if index[file]["state"] == "changed":
                index[file]["ids"] = await self.insert_documents(index[file]["documents"])
        
        # Clean up and save index
        index = {k: v for k, v in index.items() if v["state"] != "removed"}
        for file in index:
            if "documents" in index[file]:
                del index[file]["documents"]
            if "state" in index[file]:
                del index[file]["state"]
        
        with open(index_path, "w") as f:
            json.dump(index, f)
    
    def _preload_knowledge_folders(
        self,
        log_item: Optional[LogItem],
        kn_dirs: List[str],
        index: Dict[str, knowledge_import.KnowledgeImport],
    ) -> Dict[str, knowledge_import.KnowledgeImport]:
        """Load knowledge from folders."""
        for kn_dir in kn_dirs:
            # Root knowledge goes to main
            index = knowledge_import.load_knowledge(
                log_item,
                abs_knowledge_dir(kn_dir),
                index,
                {"area": MemoryArea.MAIN.value},
                filename_pattern="*",
                recursive=False,
            )
            # Subdirectories go to their areas
            for area in MemoryArea:
                index = knowledge_import.load_knowledge(
                    log_item,
                    abs_knowledge_dir(kn_dir, area.value),
                    index,
                    {"area": area.value},
                    recursive=True,
                )
        
        # Load instruments
        index = knowledge_import.load_knowledge(
            log_item,
            files.get_abs_path("instruments"),
            index,
            {"area": MemoryArea.INSTRUMENTS.value},
            filename_pattern="**/*.md",
            recursive=True,
        )
        
        return index
    
    # ========================================
    # Utility Methods
    # ========================================
    
    def _generate_doc_id(self) -> str:
        """Generate a unique document ID."""
        while True:
            doc_id = guids.generate_id(10)
            if doc_id not in self._doc_store:
                return doc_id
    
    def _rowid_to_id(self, rowid: int) -> Optional[str]:
        """Convert rowid back to document ID."""
        for doc_id, rid in self._id_to_rowid.items():
            if rid == rowid:
                return doc_id
        return None
    
    def _apply_filter(self, metadata: Dict, filter_expr: str) -> bool:
        """Apply filter expression to metadata."""
        if not filter_expr:
            return True
        try:
            from simpleeval import simple_eval
            return simple_eval(filter_expr, names=metadata)
        except Exception:
            return False
    
    @staticmethod
    def get_timestamp() -> str:
        """Get current timestamp string."""
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    @staticmethod
    def format_docs_plain(docs: List[Document]) -> List[str]:
        """Format documents as plain text."""
        result = []
        for doc in docs:
            text = ""
            for k, v in doc.metadata.items():
                text += f"{k}: {v}\n"
            text += f"Content: {doc.page_content}"
            result.append(text)
        return result
    
    def get_cache_info(self) -> Optional[Dict[str, int]]:
        """Get embedding cache statistics."""
        if self.embedding_cache:
            return self.embedding_cache.cache_info()
        return None
    
    def clear_cache(self) -> None:
        """Clear the embedding cache."""
        if self.embedding_cache:
            self.embedding_cache.cache_clear()


# ========================================
# Helper Functions (Backward Compatible)
# ========================================

def reload() -> None:
    """Clear all memory indexes."""
    Memory._fts_index = {}
    Memory._vec_index = {}
    Memory._hybrid_index = {}
    Memory._cache_index = {}


def abs_db_dir(memory_subdir: str) -> str:
    """Get absolute path to memory database directory."""
    if memory_subdir.startswith("projects/"):
        from python.helpers.projects import get_project_meta_folder
        return files.get_abs_path(get_project_meta_folder(memory_subdir[9:]), "memory")
    return files.get_abs_path("memory", memory_subdir)


def abs_knowledge_dir(knowledge_subdir: str, *sub_dirs: str) -> str:
    """Get absolute path to knowledge directory."""
    if knowledge_subdir.startswith("projects/"):
        from python.helpers.projects import get_project_meta_folder
        return files.get_abs_path(
            get_project_meta_folder(knowledge_subdir[9:]), "knowledge", *sub_dirs
        )
    return files.get_abs_path("knowledge", knowledge_subdir, *sub_dirs)


def get_memory_subdir_abs(agent: Agent) -> str:
    """Get absolute memory subdirectory path for agent."""
    subdir = get_agent_memory_subdir(agent)
    return abs_db_dir(subdir)


def get_agent_memory_subdir(agent: Agent) -> str:
    """Get memory subdirectory for agent."""
    return get_context_memory_subdir(agent.context)


def get_context_memory_subdir(context: AgentContext) -> str:
    """Get memory subdirectory for context."""
    from python.helpers.projects import get_context_memory_subdir as get_project_memory_subdir
    memory_subdir = get_project_memory_subdir(context)
    if memory_subdir:
        return memory_subdir
    return context.config.memory_subdir or "default"


def get_existing_memory_subdirs() -> List[str]:
    """Get list of existing memory subdirectories."""
    try:
        from python.helpers.projects import get_project_meta_folder, get_projects_parent_folder
        
        subdirs = files.get_subdirectories("memory", exclude="embeddings")
        
        project_subdirs = files.get_subdirectories(get_projects_parent_folder())
        for project_subdir in project_subdirs:
            if files.exists(get_project_meta_folder(project_subdir), "memory", "memory.db"):
                subdirs.append(f"projects/{project_subdir}")
        
        if "default" not in subdirs:
            subdirs.insert(0, "default")
        
        return subdirs
    except Exception as e:
        PrintStyle.error(f"Failed to get memory subdirectories: {str(e)}")
        return ["default"]


def get_knowledge_subdirs_by_memory_subdir(memory_subdir: str, default: List[str]) -> List[str]:
    """Get knowledge subdirectories for a memory subdirectory."""
    if memory_subdir.startswith("projects/"):
        from python.helpers.projects import get_project_meta_folder
        default.append(get_project_meta_folder(memory_subdir[9:], "knowledge"))
    return default


def get_custom_knowledge_subdir_abs(agent: Agent) -> str:
    """Get custom knowledge subdirectory path."""
    for dir in agent.config.knowledge_subdirs:
        if dir != "default":
            return files.get_abs_path("knowledge", dir)
    raise Exception("No custom knowledge subdir set")
