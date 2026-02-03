"""Adaptive vector storage module with caching integration and configurable parameters.

This module provides an AdaptiveVectorStore class that wraps the low-level VectorStore
with embedding caching, automatic optimization, and a high-level unified interface
for vector operations.
"""

import sqlite3
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from python.helpers.memory_cache import EmbeddingCache
from python.helpers.memory_sqlite_vec import (
    VectorStore,
    VectorStoreError,
    ExtensionNotAvailableError,
    DatabaseNotInitializedError,
    SQLITE_VEC_AVAILABLE
)


class AdaptiveVectorStoreError(Exception):
    """Base exception for AdaptiveVectorStore errors."""
    pass


class AdaptiveVectorStore:
    """Adaptive vector storage with caching integration and configurable parameters.

    This class provides a high-level interface for vector storage operations,
    combining the VectorStore for persistence with EmbeddingCache for efficient
    embedding computation. It supports automatic embedding generation, batch
    operations, and configurable search parameters.

    Attributes:
        _vector_store: Underlying VectorStore for persistence.
        _cache: Optional EmbeddingCache for caching embeddings.
        _embed_fn: Function to generate embeddings from text.
        _default_k: Default number of results for search operations.
        _distance_threshold: Optional maximum distance for filtering results.

    Example:
        >>> import sqlite3
        >>> def embed_fn(text: str) -> List[float]:
        ...     return [0.1] * 384  # Simulated embedding
        >>> conn = sqlite3.connect(':memory:')
        >>> store = AdaptiveVectorStore(
        ...     conn=conn,
        ...     embed_fn=embed_fn,
        ...     dimensions=384,
        ...     cache_size=1000
        ... )
        >>> store.create_index()
        >>> store.add(1, "Hello world")
        >>> results = store.search_by_text("hello", k=5)
        >>> print(len(results))
        1
    """

    def __init__(
        self,
        conn: Optional[sqlite3.Connection] = None,
        db_path: str = ":memory:",
        table_name: str = "adaptive_vec",
        dimensions: int = 384,
        embed_fn: Optional[Callable[[str], List[float]]] = None,
        cache_size: int = 1000,
        enable_cache: bool = True,
        default_k: int = 10,
        distance_threshold: Optional[float] = None
    ):
        """Initialize the AdaptiveVectorStore.

        Args:
            conn: Existing SQLite connection. If None, creates a new connection.
            db_path: Path to SQLite database file. Used only if conn is None.
                    Defaults to ':memory:' for in-memory database.
            table_name: Name for the vec0 virtual table. Defaults to 'adaptive_vec'.
            dimensions: Number of dimensions for embedding vectors. Defaults to 384.
            embed_fn: Function that takes text and returns embedding vector.
                     Required for text-based operations.
            cache_size: Maximum number of embeddings to cache. Defaults to 1000.
            enable_cache: Whether to enable embedding caching. Defaults to True.
            default_k: Default number of results for search. Defaults to 10.
            distance_threshold: Optional maximum distance for filtering results.

        Raises:
            ExtensionNotAvailableError: If sqlite-vec is not installed.
            ValueError: If invalid parameters are provided.
        """
        if not SQLITE_VEC_AVAILABLE:
            raise ExtensionNotAvailableError(
                "sqlite-vec extension is not available. "
                "Install it with: pip install sqlite-vec"
            )

        if dimensions < 1:
            raise ValueError("dimensions must be at least 1")

        if cache_size < 1:
            raise ValueError("cache_size must be at least 1")

        if default_k < 1:
            raise ValueError("default_k must be at least 1")

        self._embed_fn = embed_fn
        self._default_k = default_k
        self._distance_threshold = distance_threshold
        self._dimensions = dimensions

        # Initialize the underlying VectorStore
        self._vector_store = VectorStore(
            conn=conn,
            db_path=db_path,
            table_name=table_name,
            dimensions=dimensions
        )

        # Initialize embedding cache if enabled and embed_fn provided
        if enable_cache and embed_fn is not None:
            self._cache = EmbeddingCache(embed_fn, maxsize=cache_size)
        else:
            self._cache = None

        # Track metadata (text -> rowid mapping for reverse lookup)
        self._text_index: Dict[int, str] = {}

    def create_index(self) -> None:
        """Create the vec0 virtual table for vector storage.

        This method is idempotent - calling it multiple times is safe.

        Raises:
            DatabaseNotInitializedError: If the extension is not loaded.
        """
        self._vector_store.create_index()

    def add(
        self,
        rowid: int,
        text: str,
        embedding: Optional[List[float]] = None
    ) -> None:
        """Add content to the vector store.

        If embedding is not provided and embed_fn is configured, the embedding
        will be automatically generated (and cached if caching is enabled).

        Args:
            rowid: Integer row identifier. Must be unique.
            text: Text content (used for embedding generation if needed).
            embedding: Optional pre-computed embedding vector. If None,
                      generates using embed_fn.

        Raises:
            AdaptiveVectorStoreError: If no embedding provided and embed_fn not set.
            ValueError: If embedding dimensions don't match.
            sqlite3.Error: If insertion fails (e.g., duplicate rowid).
        """
        if embedding is None:
            embedding = self._get_or_compute_embedding(text)

        self._vector_store.insert(rowid, embedding)
        self._text_index[rowid] = text

    def add_batch(
        self,
        items: List[Tuple[int, str, Optional[List[float]]]]
    ) -> None:
        """Add multiple items to the vector store.

        Args:
            items: List of (rowid, text, optional_embedding) tuples.
                  If embedding is None, it will be auto-generated.

        Raises:
            AdaptiveVectorStoreError: If embed_fn not set and embeddings missing.
        """
        batch_items: List[Tuple[int, List[float]]] = []

        for rowid, text, embedding in items:
            if embedding is None:
                embedding = self._get_or_compute_embedding(text)
            batch_items.append((rowid, embedding))
            self._text_index[rowid] = text

        self._vector_store.insert_batch(batch_items)

    def search(
        self,
        query_embedding: List[float],
        k: Optional[int] = None,
        max_distance: Optional[float] = None
    ) -> List[Dict[str, Any]]:
        """Search for similar vectors by embedding.

        Args:
            query_embedding: The query vector to find similar vectors for.
            k: Number of results to return. Uses default_k if not specified.
            max_distance: Maximum distance threshold. Uses instance default if not specified.

        Returns:
            List of dictionaries containing:
                - rowid: The row identifier
                - distance: Euclidean distance from query vector
                - text: Original text (if available in index)
        """
        if k is None:
            k = self._default_k

        threshold = max_distance if max_distance is not None else self._distance_threshold

        if threshold is not None:
            results = self._vector_store.search_with_threshold(
                query_embedding, k=k, max_distance=threshold
            )
        else:
            results = self._vector_store.search(query_embedding, k=k)

        # Enrich results with text if available
        return self._enrich_results(results)

    def search_by_text(
        self,
        query: str,
        k: Optional[int] = None,
        max_distance: Optional[float] = None
    ) -> List[Dict[str, Any]]:
        """Search for similar vectors by text query.

        Automatically generates embedding for the query text using embed_fn
        (with caching if enabled).

        Args:
            query: Text query to search for.
            k: Number of results to return.
            max_distance: Maximum distance threshold.

        Returns:
            List of search results with rowid, distance, and text.

        Raises:
            AdaptiveVectorStoreError: If embed_fn is not configured.
        """
        if not query:
            return []

        query_embedding = self._get_or_compute_embedding(query)
        return self.search(query_embedding, k=k, max_distance=max_distance)

    def update(
        self,
        rowid: int,
        text: Optional[str] = None,
        embedding: Optional[List[float]] = None
    ) -> bool:
        """Update a vector in the store.

        Args:
            rowid: The rowid of the vector to update.
            text: New text content (will generate new embedding if embed_fn set).
            embedding: New embedding vector (takes precedence over text).

        Returns:
            True if the update succeeded, False if no row with that rowid exists.

        Raises:
            AdaptiveVectorStoreError: If neither text nor embedding provided.
        """
        if embedding is None and text is None:
            raise AdaptiveVectorStoreError(
                "Must provide either text or embedding for update"
            )

        if embedding is None and text is not None:
            embedding = self._get_or_compute_embedding(text)

        success = self._vector_store.update(rowid, embedding)

        if success and text is not None:
            self._text_index[rowid] = text

        return success

    def delete(self, rowid: int) -> bool:
        """Delete a vector by its rowid.

        Args:
            rowid: The rowid of the vector to delete.

        Returns:
            True if a row was deleted, False if no row with that rowid exists.
        """
        success = self._vector_store.delete(rowid)
        if success and rowid in self._text_index:
            del self._text_index[rowid]
        return success

    def exists(self, rowid: int) -> bool:
        """Check if a vector with the given rowid exists.

        Args:
            rowid: The rowid to check.

        Returns:
            True if a vector with that rowid exists, False otherwise.
        """
        return self._vector_store.exists(rowid)

    def get_text(self, rowid: int) -> Optional[str]:
        """Get the text associated with a rowid.

        Args:
            rowid: The rowid to look up.

        Returns:
            The text if found, None otherwise.
        """
        return self._text_index.get(rowid)

    def count(self) -> int:
        """Return the number of vectors in the store.

        Returns:
            The total number of stored vectors.
        """
        return self._vector_store.count()

    def clear(self) -> None:
        """Delete all vectors from the store.

        This removes all stored vectors but keeps the table structure intact.
        Also clears the text index and cache.
        """
        self._vector_store.clear()
        self._text_index.clear()
        if self._cache is not None:
            self._cache.cache_clear()

    def cache_info(self) -> Optional[Dict[str, int]]:
        """Return embedding cache statistics.

        Returns:
            Dictionary with cache stats if caching is enabled, None otherwise.
        """
        if self._cache is not None:
            return self._cache.cache_info()
        return None

    def cache_clear(self) -> None:
        """Clear the embedding cache."""
        if self._cache is not None:
            self._cache.cache_clear()

    def optimize(self) -> None:
        """Optimize the vector store for better query performance.

        Currently a no-op placeholder for future optimization strategies
        (e.g., rebuilding indexes, compacting storage).
        """
        # Future: Implement optimization strategies
        pass

    def _get_or_compute_embedding(self, text: str) -> List[float]:
        """Get embedding from cache or compute it.

        Args:
            text: The text to get embedding for.

        Returns:
            The embedding vector.

        Raises:
            AdaptiveVectorStoreError: If embed_fn is not configured.
        """
        if self._embed_fn is None:
            raise AdaptiveVectorStoreError(
                "Cannot generate embedding: embed_fn not configured. "
                "Either provide embeddings directly or set embed_fn during initialization."
            )

        if self._cache is not None:
            return self._cache.get_embedding(text)
        else:
            return self._embed_fn(text)

    def _enrich_results(
        self,
        results: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Enrich search results with text from the index.

        Args:
            results: Raw search results from VectorStore.

        Returns:
            Results with text field added where available.
        """
        enriched = []
        for r in results:
            result = dict(r)
            rowid = r["rowid"]
            result["text"] = self._text_index.get(rowid)
            enriched.append(result)
        return enriched

    def close(self) -> None:
        """Close the underlying database connection if owned by this instance."""
        self._vector_store.close()

    @property
    def vector_store(self) -> VectorStore:
        """Return the underlying VectorStore instance."""
        return self._vector_store

    @property
    def cache(self) -> Optional[EmbeddingCache]:
        """Return the EmbeddingCache instance if enabled."""
        return self._cache

    @property
    def table_name(self) -> str:
        """Return the vec0 table name."""
        return self._vector_store.table_name

    @property
    def dimensions(self) -> int:
        """Return the number of embedding dimensions."""
        return self._dimensions

    @property
    def default_k(self) -> int:
        """Return the default k value for search."""
        return self._default_k

    @default_k.setter
    def default_k(self, value: int) -> None:
        """Set the default k value for search."""
        if value < 1:
            raise ValueError("default_k must be at least 1")
        self._default_k = value

    @property
    def distance_threshold(self) -> Optional[float]:
        """Return the default distance threshold."""
        return self._distance_threshold

    @distance_threshold.setter
    def distance_threshold(self, value: Optional[float]) -> None:
        """Set the default distance threshold."""
        self._distance_threshold = value

    @property
    def has_embed_fn(self) -> bool:
        """Return whether an embedding function is configured."""
        return self._embed_fn is not None

    @property
    def is_caching_enabled(self) -> bool:
        """Return whether embedding caching is enabled."""
        return self._cache is not None

    def __len__(self) -> int:
        """Return the number of stored vectors."""
        return self.count()

    def __contains__(self, rowid: int) -> bool:
        """Check if a vector with the given rowid exists."""
        return self.exists(rowid)

    def __repr__(self) -> str:
        """Return a string representation of the AdaptiveVectorStore."""
        return (
            f"AdaptiveVectorStore("
            f"table='{self.table_name}', "
            f"dimensions={self._dimensions}, "
            f"cache={'enabled' if self._cache else 'disabled'}, "
            f"embed_fn={'set' if self._embed_fn else 'none'})"
        )

    def __enter__(self) -> "AdaptiveVectorStore":
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit - closes connection if owned."""
        self.close()
