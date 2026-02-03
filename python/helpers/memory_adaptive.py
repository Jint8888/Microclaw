"""Adaptive Vector Store with automatic backend switching.

This module provides an AdaptiveVectorStore class that:
- Uses sqlite-vec by default for small datasets
- Automatically switches to FAISS when document count exceeds threshold
- Supports fallback to FAISS if sqlite-vec is unavailable
- Handles data migration between backends transparently

Configuration via environment variables:
- MEMORY_VECTOR_BACKEND: "auto" | "sqlite-vec" | "faiss" (default: "auto")
- MEMORY_VECTOR_THRESHOLD: threshold for auto-switching (default: 10000)
"""

import os
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Try pysqlite3 first for extension loading support
try:
    import pysqlite3 as sqlite3
except ImportError:
    import sqlite3

logger = logging.getLogger(__name__)


@dataclass
class AdaptiveVectorConfig:
    """Configuration for adaptive vector store."""
    backend: str = "auto"  # auto, sqlite-vec, faiss
    auto_switch_threshold: int = 10000
    db_dir: str = ""
    dimensions: int = 1536
    

class VectorBackend(ABC):
    """Abstract base class for vector backends."""
    
    @abstractmethod
    def add(self, doc_id: str, embedding: List[float], metadata: Dict[str, Any]) -> None:
        """Add a document with embedding."""
        pass
    
    @abstractmethod
    def search(self, query_embedding: List[float], k: int) -> List[Tuple[str, float, Dict[str, Any]]]:
        """Search for similar documents. Returns [(doc_id, score, metadata), ...]"""
        pass
    
    @abstractmethod
    def delete(self, doc_id: str) -> bool:
        """Delete a document by ID."""
        pass
    
    @abstractmethod
    def count(self) -> int:
        """Return total document count."""
        pass
    
    @abstractmethod
    def get_all(self) -> List[Tuple[str, List[float], Dict[str, Any]]]:
        """Get all documents for migration. Returns [(doc_id, embedding, metadata), ...]"""
        pass
    
    @abstractmethod
    def clear(self) -> None:
        """Clear all data."""
        pass


class SqliteVecBackend(VectorBackend):
    """sqlite-vec backend wrapper."""
    
    def __init__(self, db_path: str, dimensions: int):
        from python.helpers.memory_sqlite_vec import VectorStore, SQLITE_VEC_AVAILABLE
        
        if not SQLITE_VEC_AVAILABLE:
            raise RuntimeError("sqlite-vec not available")
        
        self.db_path = db_path
        self.dimensions = dimensions
        
        # Create connection
        conn = sqlite3.connect(db_path, check_same_thread=False)
        self.store = VectorStore(conn, dimensions=dimensions, table_name="adaptive_vec")
        self.store.create_index()
        
        # Metadata storage (includes embeddings for migration)
        self._init_metadata_table(conn)
        self._conn = conn
        self._next_rowid = self._get_max_rowid() + 1
    
    def _init_metadata_table(self, conn):
        """Initialize metadata storage table."""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS adaptive_metadata (
                doc_id TEXT PRIMARY KEY,
                rowid INTEGER,
                metadata TEXT,
                embedding BLOB,
                created_at TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_adaptive_rowid ON adaptive_metadata(rowid)")
        conn.commit()
    
    def _get_max_rowid(self) -> int:
        """Get the maximum rowid used."""
        cursor = self._conn.execute("SELECT MAX(rowid) FROM adaptive_metadata")
        result = cursor.fetchone()[0]
        return result if result else 0
    
    def add(self, doc_id: str, embedding: List[float], metadata: Dict[str, Any]) -> None:
        import json
        import numpy as np
        
        # Assign rowid
        rowid = self._next_rowid
        self._next_rowid += 1
        
        # Insert into vector store
        self.store.insert(rowid, embedding)
        
        # Store metadata with embedding for migration
        emb_blob = np.array(embedding, dtype=np.float32).tobytes()
        self._conn.execute(
            "INSERT OR REPLACE INTO adaptive_metadata (doc_id, rowid, metadata, embedding, created_at) VALUES (?, ?, ?, ?, ?)",
            (doc_id, rowid, json.dumps(metadata), emb_blob, datetime.now().isoformat())
        )
        self._conn.commit()
    
    def search(self, query_embedding: List[float], k: int) -> List[Tuple[str, float, Dict[str, Any]]]:
        import json
        # VectorStore.search returns list of dicts with 'rowid' and 'distance'
        results = self.store.search(query_embedding, k)
        
        output = []
        for result in results:
            rowid = result['rowid']
            distance = result['distance']
            # Convert distance to similarity score (1 - distance for cosine)
            score = 1.0 - distance if distance <= 1.0 else 0.0
            
            # Look up doc_id from rowid
            cursor = self._conn.execute(
                "SELECT doc_id, metadata FROM adaptive_metadata WHERE rowid = ?", (rowid,)
            )
            row = cursor.fetchone()
            if row:
                doc_id = row[0]
                metadata = json.loads(row[1]) if row[1] else {}
                output.append((doc_id, score, metadata))
        
        return output
    
    def delete(self, doc_id: str) -> bool:
        # Get rowid first
        cursor = self._conn.execute("SELECT rowid FROM adaptive_metadata WHERE doc_id = ?", (doc_id,))
        row = cursor.fetchone()
        if row:
            rowid = row[0]
            self.store.delete(rowid)
            self._conn.execute("DELETE FROM adaptive_metadata WHERE doc_id = ?", (doc_id,))
            self._conn.commit()
            return True
        return False
    
    def count(self) -> int:
        cursor = self._conn.execute("SELECT COUNT(*) FROM adaptive_metadata")
        return cursor.fetchone()[0]
    
    def get_all(self) -> List[Tuple[str, List[float], Dict[str, Any]]]:
        import json
        import numpy as np
        results = []
        cursor = self._conn.execute("""
            SELECT doc_id, metadata, embedding 
            FROM adaptive_metadata
        """)
        
        for row in cursor.fetchall():
            doc_id = row[0]
            metadata = json.loads(row[1]) if row[1] else {}
            emb_blob = row[2]
            if emb_blob:
                embedding = np.frombuffer(emb_blob, dtype=np.float32).tolist()
                results.append((doc_id, embedding, metadata))
        
        return results
    
    def clear(self) -> None:
        self.store.clear()
        self._conn.execute("DELETE FROM adaptive_metadata")
        self._conn.commit()


class FaissBackend(VectorBackend):
    """FAISS backend wrapper."""
    
    def __init__(self, index_path: str, dimensions: int):
        try:
            import faiss
            import numpy as np
        except ImportError:
            raise RuntimeError("faiss-cpu not available")
        
        self.index_path = Path(index_path)
        self.metadata_path = self.index_path.with_suffix(".meta.db")
        self.dimensions = dimensions
        
        # Initialize or load index
        if self.index_path.exists():
            self.index = faiss.read_index(str(self.index_path))
        else:
            self.index = faiss.IndexFlatIP(dimensions)  # Inner product (cosine similarity)
        
        # ID mapping (FAISS uses sequential IDs)
        self._id_to_idx: Dict[str, int] = {}
        self._idx_to_id: Dict[int, str] = {}
        self._next_idx = 0
        
        # Embeddings cache for retrieval
        self._embeddings: Dict[str, List[float]] = {}
        
        # Metadata storage
        self._init_metadata_db()
        self._load_mappings()
    
    def _init_metadata_db(self):
        """Initialize metadata database."""
        self._meta_conn = sqlite3.connect(str(self.metadata_path), check_same_thread=False)
        self._meta_conn.execute("""
            CREATE TABLE IF NOT EXISTS faiss_metadata (
                doc_id TEXT PRIMARY KEY,
                idx INTEGER,
                metadata TEXT,
                embedding BLOB
            )
        """)
        self._meta_conn.commit()
    
    def _load_mappings(self):
        """Load ID mappings from database."""
        import json
        cursor = self._meta_conn.execute("SELECT doc_id, idx, embedding FROM faiss_metadata")
        for row in cursor.fetchall():
            doc_id, idx, emb_blob = row
            self._id_to_idx[doc_id] = idx
            self._idx_to_id[idx] = doc_id
            if emb_blob:
                import numpy as np
                self._embeddings[doc_id] = np.frombuffer(emb_blob, dtype=np.float32).tolist()
            if idx >= self._next_idx:
                self._next_idx = idx + 1
    
    def _save(self):
        """Save index to disk."""
        import faiss
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self.index, str(self.index_path))
    
    def add(self, doc_id: str, embedding: List[float], metadata: Dict[str, Any]) -> None:
        import json
        import numpy as np
        
        # Normalize for cosine similarity
        emb_array = np.array([embedding], dtype=np.float32)
        faiss_module = __import__('faiss')
        faiss_module.normalize_L2(emb_array)
        
        # Add to index
        self.index.add(emb_array)
        idx = self._next_idx
        self._next_idx += 1
        
        # Update mappings
        self._id_to_idx[doc_id] = idx
        self._idx_to_id[idx] = doc_id
        self._embeddings[doc_id] = embedding
        
        # Save metadata
        emb_blob = np.array(embedding, dtype=np.float32).tobytes()
        self._meta_conn.execute(
            "INSERT OR REPLACE INTO faiss_metadata (doc_id, idx, metadata, embedding) VALUES (?, ?, ?, ?)",
            (doc_id, idx, json.dumps(metadata), emb_blob)
        )
        self._meta_conn.commit()
        
        # Periodically save index
        if self._next_idx % 100 == 0:
            self._save()
    
    def search(self, query_embedding: List[float], k: int) -> List[Tuple[str, float, Dict[str, Any]]]:
        import json
        import numpy as np
        
        if self.index.ntotal == 0:
            return []
        
        # Normalize query
        query = np.array([query_embedding], dtype=np.float32)
        faiss_module = __import__('faiss')
        faiss_module.normalize_L2(query)
        
        # Search
        k = min(k, self.index.ntotal)
        scores, indices = self.index.search(query, k)
        
        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0:
                continue
            doc_id = self._idx_to_id.get(idx)
            if doc_id:
                cursor = self._meta_conn.execute(
                    "SELECT metadata FROM faiss_metadata WHERE doc_id = ?", (doc_id,)
                )
                row = cursor.fetchone()
                metadata = json.loads(row[0]) if row else {}
                results.append((doc_id, float(score), metadata))
        
        return results
    
    def delete(self, doc_id: str) -> bool:
        # FAISS doesn't support deletion well, mark as deleted in metadata
        if doc_id in self._id_to_idx:
            self._meta_conn.execute("DELETE FROM faiss_metadata WHERE doc_id = ?", (doc_id,))
            self._meta_conn.commit()
            del self._id_to_idx[doc_id]
            if doc_id in self._embeddings:
                del self._embeddings[doc_id]
            return True
        return False
    
    def count(self) -> int:
        return len(self._id_to_idx)
    
    def get_all(self) -> List[Tuple[str, List[float], Dict[str, Any]]]:
        import json
        results = []
        cursor = self._meta_conn.execute("SELECT doc_id, metadata, embedding FROM faiss_metadata")
        import numpy as np
        for row in cursor.fetchall():
            doc_id, meta_str, emb_blob = row
            metadata = json.loads(meta_str) if meta_str else {}
            embedding = np.frombuffer(emb_blob, dtype=np.float32).tolist() if emb_blob else []
            if embedding:
                results.append((doc_id, embedding, metadata))
        return results
    
    def clear(self) -> None:
        import faiss
        self.index = faiss.IndexFlatIP(self.dimensions)
        self._id_to_idx.clear()
        self._idx_to_id.clear()
        self._embeddings.clear()
        self._next_idx = 0
        self._meta_conn.execute("DELETE FROM faiss_metadata")
        self._meta_conn.commit()
        if self.index_path.exists():
            self.index_path.unlink()


class AdaptiveVectorStore:
    """Adaptive vector store with automatic backend switching.
    
    Uses sqlite-vec for small datasets (< threshold) and FAISS for larger ones.
    Automatically migrates data when threshold is exceeded.
    
    Example:
        >>> store = AdaptiveVectorStore(config)
        >>> store.add("doc1", embedding, {"text": "hello"})
        >>> results = store.search(query_embedding, k=5)
    """
    
    def __init__(self, config: AdaptiveVectorConfig):
        self.config = config
        self._backend: Optional[VectorBackend] = None
        self._current_type: str = ""
        self._initialize()
    
    def _initialize(self):
        """Initialize the appropriate backend."""
        from python.helpers.memory_sqlite_vec import SQLITE_VEC_AVAILABLE
        
        db_dir = Path(self.config.db_dir)
        db_dir.mkdir(parents=True, exist_ok=True)
        
        sqlite_path = str(db_dir / "adaptive_vectors.db")
        faiss_path = str(db_dir / "adaptive_vectors.faiss")
        
        if self.config.backend == "faiss":
            # Force FAISS
            self._backend = FaissBackend(faiss_path, self.config.dimensions)
            self._current_type = "faiss"
            logger.info("Using FAISS backend (forced)")
            
        elif self.config.backend == "sqlite-vec":
            # Force sqlite-vec
            if not SQLITE_VEC_AVAILABLE:
                raise RuntimeError("sqlite-vec requested but not available")
            self._backend = SqliteVecBackend(sqlite_path, self.config.dimensions)
            self._current_type = "sqlite-vec"
            logger.info("Using sqlite-vec backend (forced)")
            
        else:  # auto
            # Check if FAISS index already exists (previous migration)
            if Path(faiss_path).exists():
                try:
                    self._backend = FaissBackend(faiss_path, self.config.dimensions)
                    self._current_type = "faiss"
                    logger.info("Using existing FAISS backend")
                except Exception as e:
                    logger.warning(f"Failed to load FAISS index: {e}")
            
            if self._backend is None:
                # Try sqlite-vec first
                if SQLITE_VEC_AVAILABLE:
                    try:
                        self._backend = SqliteVecBackend(sqlite_path, self.config.dimensions)
                        self._current_type = "sqlite-vec"
                        logger.info("Using sqlite-vec backend")
                    except Exception as e:
                        logger.warning(f"sqlite-vec init failed: {e}")
                
                # Fallback to FAISS
                if self._backend is None:
                    self._backend = FaissBackend(faiss_path, self.config.dimensions)
                    self._current_type = "faiss"
                    logger.info("Falling back to FAISS backend")
    
    def _check_migration(self):
        """Check if migration to FAISS is needed."""
        if self._current_type != "sqlite-vec":
            return
        
        count = self._backend.count()
        if count >= self.config.auto_switch_threshold:
            logger.info(f"Document count ({count}) >= threshold ({self.config.auto_switch_threshold}), migrating to FAISS")
            self._migrate_to_faiss()
    
    def _migrate_to_faiss(self):
        """Migrate data from sqlite-vec to FAISS."""
        db_dir = Path(self.config.db_dir)
        faiss_path = str(db_dir / "adaptive_vectors.faiss")
        
        # Get all data from sqlite-vec
        all_data = self._backend.get_all()
        logger.info(f"Migrating {len(all_data)} documents to FAISS")
        
        # Create new FAISS backend
        new_backend = FaissBackend(faiss_path, self.config.dimensions)
        
        # Migrate data
        for doc_id, embedding, metadata in all_data:
            new_backend.add(doc_id, embedding, metadata)
        
        # Save FAISS index
        new_backend._save()
        
        # Switch backends
        self._backend = new_backend
        self._current_type = "faiss"
        logger.info("Migration to FAISS completed")
    
    def add(self, doc_id: str, embedding: List[float], metadata: Dict[str, Any] = None) -> None:
        """Add a document."""
        self._backend.add(doc_id, embedding, metadata or {})
        self._check_migration()
    
    def insert(self, rowid: int, embedding: List[float]) -> None:
        """Insert a vector by rowid (VectorStore API compatibility).
        
        This method provides compatibility with the VectorStore interface
        used by Memory class. The rowid is converted to a string doc_id.
        """
        doc_id = str(rowid)
        self._backend.add(doc_id, embedding, {"rowid": rowid})
        self._check_migration()

    
    def search(self, query_embedding: List[float], k: int = 10) -> List[Tuple[str, float, Dict[str, Any]]]:
        """Search for similar documents."""
        return self._backend.search(query_embedding, k)
    
    def delete(self, doc_id: str) -> bool:
        """Delete a document."""
        return self._backend.delete(doc_id)
    
    def count(self) -> int:
        """Get document count."""
        return self._backend.count()
    
    def clear(self) -> None:
        """Clear all data."""
        self._backend.clear()
    
    def status(self) -> Dict[str, Any]:
        """Get store status."""
        count = self._backend.count()
        return {
            "backend": self._current_type,
            "count": count,
            "threshold": self.config.auto_switch_threshold,
            "will_migrate": (
                self._current_type == "sqlite-vec" 
                and count >= self.config.auto_switch_threshold * 0.9
            )
        }
    
    @property
    def backend_type(self) -> str:
        """Current backend type."""
        return self._current_type


def get_adaptive_config() -> AdaptiveVectorConfig:
    """Get configuration from environment variables."""
    return AdaptiveVectorConfig(
        backend=os.getenv("MEMORY_VECTOR_BACKEND", "auto"),
        auto_switch_threshold=int(os.getenv("MEMORY_VECTOR_THRESHOLD", "10000")),
    )
